"""核心 agent 循环：流式调用模型 -> 触发 hook -> 执行工具 -> 回填结果，直到模型不再调用工具。

task 工具会派生一个子 Agent：全新的 messages[]，只拥有基础五工具（不能再次委派），
最终文本作为一条 tool_result 返回给父 Agent。两个循环共享工作目录、hooks 与权限管线。
"""

import asyncio

from . import background, config, permission
from .compact import COMPACTOR
from .hooks import HookAbort, HookRegistry
from .memory import MEMORY_STORE
from .tools import TOOLS, TOOL_HANDLERS, SUB_TOOLS, SUB_HANDLERS

MAX_SUB_TURNS = 30
MAX_REACTIVE_RETRIES = 1


class Agent:
    """持有对话历史，run() 一轮任务；UI 通过 on_* 回调观察过程。"""

    def __init__(self, on_text=None, on_tool=None, on_tool_result=None, on_permission=None, on_abort=None, on_sub=None, on_status=None, on_thinking=None):
        self.on_text = on_text
        self.on_tool = on_tool
        self.on_tool_result = on_tool_result
        self.on_permission = on_permission
        self.on_abort = on_abort
        self.on_sub = on_sub
        self.on_status = on_status
        self.on_thinking = on_thinking
        self.messages = []
        self.hooks = HookRegistry()
        self.register_hook("PreToolUse", self._permission_hook)
        self.rounds_since_todo = 0
        self.active_request = ""
        self.compact_requested = False
        self.reactive_retries = 0
        self.system_prompt = config.SYSTEM
        COMPACTOR.notify = self._status
        MEMORY_STORE.notify = self._status
        background.BACKGROUND.notify = self._status

    def register_hook(self, event: str, callback) -> None:
        """注册一个扩展 hook；循环只调用 trigger，扩展逻辑不侵入循环。"""
        self.hooks.register(event, callback)

    async def run(self, task: str) -> str:
        """执行一轮任务，返回模型的最终文本；历史保留，供后续轮次复用。"""
        self.hooks.trigger("UserPromptSubmit", task)
        self.messages.append({"role": "user", "content": task})
        self.rounds_since_todo = 0
        self.active_request = task
        self.compact_requested = False
        self.reactive_retries = 0
        self.system_prompt = await MEMORY_STORE.build_system(config.SYSTEM, self.messages)
        return await self._loop()

    async def _loop(self) -> str:
        while True:
            background.inject_background_results(self.messages)
            self.messages = await COMPACTOR.prepare(self.messages, self.active_request)
            try:
                response = await self._call()
            except Exception as exc:
                if self._context_too_long(exc) and self.reactive_retries < MAX_REACTIVE_RETRIES:
                    self._status("[reactive compact]")
                    self.messages = await COMPACTOR.reactive_compact(self.messages, self.active_request)
                    self.reactive_retries += 1
                    continue
                raise
            self.reactive_retries = 0
            self.messages.append({"role": "assistant", "content": response.content})

            tool_calls = [b for b in response.content if b.type == "tool_use"]
            if not tool_calls:
                force = self.hooks.trigger("Stop", self.messages)
                if force:
                    self.messages.append({"role": "user", "content": force})
                    continue
                await MEMORY_STORE.extract_and_consolidate(self.messages)
                return "".join(b.text for b in response.content if b.type == "text")

            results, aborted_reason = await self._run_tools(tool_calls)

            if any(b.name == "todo_write" for b in tool_calls):
                self.rounds_since_todo = 0
            else:
                self.rounds_since_todo += 1
                if self.rounds_since_todo >= 3:
                    results.append({"type": "text", "text": "<reminder>Update your todos.</reminder>"})
                    self.rounds_since_todo = 0

            self.messages.append({"role": "user", "content": results})
            if aborted_reason is not None:
                if self.on_abort:
                    self.on_abort(aborted_reason)
                return f"已取消：用户拒绝了该操作（{aborted_reason}）"

            if self.compact_requested:
                self.compact_requested = False
                self.messages = await COMPACTOR.compact_history(self.messages, self.active_request)

    def _permission_hook(self, block) -> str | None:
        """PreToolUse：三道闸门（硬拒绝 → 规则 → 用户审批）。返回字符串表示拦下本条；用户拒绝时抛 HookAbort 中止本轮。"""
        name = block.name
        args = block.input or {}
        if name == "bash":
            reason = permission.check_deny_list(args.get("command", ""))
            if reason:
                return f"Blocked: {reason}"
        reason = permission.approval_reason(name, args)
        if reason:
            if self.on_permission is None:
                return f"Permission required: {reason}"
            if self.on_permission(name, args, reason) != "allow":
                raise HookAbort(reason)
        return None

    async def _run_tools(self, tool_calls) -> tuple[list, str | None]:
        """逐个触发 PreToolUse → 执行工具 → 触发 PostToolUse；用户拒绝时中止本轮并补齐占位结果。"""
        results = []
        for i, block in enumerate(tool_calls):
            if self.on_tool:
                self.on_tool(block.name, block.input)
            try:
                blocked = self.hooks.trigger("PreToolUse", block)
                output = str(blocked) if blocked is not None else await self._execute(block)
            except HookAbort as exc:
                output = f"Denied by user: {exc.reason}"
                if self.on_tool_result:
                    self.on_tool_result(output)
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": output})
                cancelled = "Cancelled: a previous request was denied by the user"
                for rest in tool_calls[i + 1:]:
                    if self.on_tool_result:
                        self.on_tool_result(cancelled)
                    results.append({"type": "tool_result", "tool_use_id": rest.id, "content": cancelled})
                return results, exc.reason
            self.hooks.trigger("PostToolUse", block, output)
            if self.on_tool_result:
                self.on_tool_result(output)
            results.append({"type": "tool_result", "tool_use_id": block.id, "content": output})
        return results, None

    async def _execute(self, block) -> str:
        """分派工具；task 走异步子 Agent 循环，compact 标记本轮后压缩，其余走同步 handler。"""
        if block.name == "task":
            return await self._run_subagent((block.input or {}).get("prompt", ""))
        if block.name == "compact":
            self.compact_requested = True
            return "Compaction requested after this tool batch."
        if background.should_run_background(block.name, block.input or {}):
            try:
                task_id = background.start_background_task(block)
                return f"[Background task {task_id} started] The result will be collected on a later turn."
            except Exception as exc:
                return f"Error: {exc}"
        return await asyncio.to_thread(self._dispatch, block, TOOL_HANDLERS)

    def _dispatch(self, block, handlers) -> str:
        handler = handlers.get(block.name)
        if handler is None:
            return f"Error: unknown tool {block.name!r}"
        try:
            return handler(**(block.input or {}))
        except Exception as exc:
            return f"Error: {exc}"

    async def _run_subagent(self, prompt: str) -> str:
        """用全新 messages[] 跑一个受限子循环，最终文本作为结果返回父 Agent。"""
        self._sub(f"[Subagent started] {prompt[:60]}")
        messages = [{"role": "user", "content": prompt}]
        for _ in range(MAX_SUB_TURNS):
            response = await self._call_sub(messages)
            messages.append({"role": "assistant", "content": response.content})
            tool_calls = [b for b in response.content if b.type == "tool_use"]
            if not tool_calls:
                force = self.hooks.trigger("Stop", messages)
                if force:
                    messages.append({"role": "user", "content": force})
                    continue
                self._sub("[Subagent done]")
                return self._extract_text(response.content) or "(no summary)"
            results = []
            for block in tool_calls:
                try:
                    blocked = self.hooks.trigger("PreToolUse", block)
                except HookAbort as exc:
                    blocked = f"Denied by user: {exc.reason}"
                if blocked is not None:
                    output = str(blocked)
                else:
                    output = await asyncio.to_thread(self._dispatch, block, SUB_HANDLERS)
                self.hooks.trigger("PostToolUse", block, output)
                self._sub(f"[sub] {block.name}: {output[:100]}")
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": output})
            messages.append({"role": "user", "content": results})
        self._sub("[Subagent stopped]")
        return "Subagent stopped after 30 turns without a final answer."

    async def _call_sub(self, messages):
        return await config.client.messages.create(
            model=config.MODEL,
            system=config.SUB_SYSTEM,
            messages=messages,
            tools=SUB_TOOLS,
            max_tokens=8000,
        )

    @staticmethod
    def _extract_text(content) -> str:
        if not isinstance(content, list):
            return str(content)
        return "\n".join(b.text for b in content if b.type == "text")

    def _sub(self, line: str) -> None:
        if self.on_sub:
            self.on_sub(line)

    def _status(self, line: str) -> None:
        if self.on_status:
            self.on_status(line)

    @staticmethod
    def _context_too_long(exc: Exception) -> bool:
        return any(t in str(exc).lower() for t in ("prompt_too_long", "too many tokens"))

    async def _call(self):
        kwargs = dict(
            model=config.MODEL,
            system=self.system_prompt,
            messages=self.messages,
            tools=TOOLS,
            max_tokens=8000,
        )
        if config.THINKING_BUDGET > 0:
            kwargs["thinking"] = {"type": "enabled", "budget_tokens": config.THINKING_BUDGET}
            kwargs["max_tokens"] = config.THINKING_BUDGET + 8000
        try:
            async with config.client.messages.stream(**kwargs) as stream:
                async for event in stream:
                    if event.type == "content_block_delta":
                        delta = event.delta
                        if delta.type == "text_delta":
                            if self.on_text:
                                self.on_text(delta.text)
                        elif delta.type == "thinking_delta":
                            if self.on_thinking:
                                self.on_thinking(delta.thinking)
                return await stream.get_final_message()
        except Exception:
            # 端点不支持流式时回退到一次性请求
            response = await config.client.messages.create(**kwargs)
            thinking = "\n".join(b.thinking for b in response.content if b.type == "thinking")
            if self.on_thinking and thinking:
                self.on_thinking(thinking)
            text = "".join(b.text for b in response.content if b.type == "text")
            if self.on_text and text:
                self.on_text(text)
            return response
