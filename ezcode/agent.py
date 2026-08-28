"""核心 agent 循环：流式调用模型 -> 触发 hook -> 执行工具 -> 回填结果，直到模型不再调用工具。"""

from . import config, permission
from .hooks import HookAbort, HookRegistry
from .tools import TOOLS, TOOL_HANDLERS


class Agent:
    """持有对话历史，run() 一轮任务；UI 通过 on_* 回调观察过程。"""

    def __init__(self, on_text=None, on_tool=None, on_tool_result=None, on_permission=None, on_abort=None):
        self.on_text = on_text
        self.on_tool = on_tool
        self.on_tool_result = on_tool_result
        self.on_permission = on_permission
        self.on_abort = on_abort
        self.messages = []
        self.hooks = HookRegistry()
        self.register_hook("PreToolUse", self._permission_hook)

    def register_hook(self, event: str, callback) -> None:
        """注册一个扩展 hook；循环只调用 trigger，扩展逻辑不侵入循环。"""
        self.hooks.register(event, callback)

    async def run(self, task: str) -> str:
        """执行一轮任务，返回模型的最终文本；历史保留，供后续轮次复用。"""
        self.hooks.trigger("UserPromptSubmit", task)
        self.messages.append({"role": "user", "content": task})
        return await self._loop()

    async def _loop(self) -> str:
        while True:
            response = await self._call()
            self.messages.append({"role": "assistant", "content": response.content})

            tool_calls = [b for b in response.content if b.type == "tool_use"]
            if not tool_calls:
                force = self.hooks.trigger("Stop", self.messages)
                if force:
                    self.messages.append({"role": "user", "content": force})
                    continue
                return "".join(b.text for b in response.content if b.type == "text")

            results, aborted_reason = self._run_tools(tool_calls)
            self.messages.append({"role": "user", "content": results})
            if aborted_reason is not None:
                if self.on_abort:
                    self.on_abort(aborted_reason)
                return f"已取消：用户拒绝了该操作（{aborted_reason}）"

    def _permission_hook(self, block) -> str | None:
        """PreToolUse：三道闸门（硬拒绝 → 规则 → 用户审批）。返回字符串表示拦下本条；用户拒绝时抛 HookAbort 中止本轮。"""
        name = block.name
        args = block.input or {}
        if name == "bash":
            reason = permission.check_deny_list(args.get("command", ""))
            if reason:
                return f"Blocked: {reason}"
        reason = permission.check_rules(name, args)
        if reason:
            if self.on_permission is None:
                return f"Permission required: {reason}"
            if self.on_permission(name, args, reason) != "allow":
                raise HookAbort(reason)
        return None

    def _run_tools(self, tool_calls) -> tuple[list, str | None]:
        """逐个触发 PreToolUse → 执行工具 → 触发 PostToolUse；用户拒绝时中止本轮并补齐占位结果。"""
        results = []
        for i, block in enumerate(tool_calls):
            if self.on_tool:
                self.on_tool(block.name, block.input)
            try:
                blocked = self.hooks.trigger("PreToolUse", block)
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
            output = str(blocked) if blocked is not None else self._execute(block)
            self.hooks.trigger("PostToolUse", block, output)
            if self.on_tool_result:
                self.on_tool_result(output)
            results.append({"type": "tool_result", "tool_use_id": block.id, "content": output})
        return results, None

    def _execute(self, block) -> str:
        handler = TOOL_HANDLERS.get(block.name)
        if handler is None:
            return f"Error: unknown tool {block.name!r}"
        try:
            return handler(**(block.input or {}))
        except Exception as exc:
            return f"Error: {exc}"

    async def _call(self):
        kwargs = dict(
            model=config.MODEL,
            system=config.SYSTEM,
            messages=self.messages,
            tools=TOOLS,
            max_tokens=8000,
        )
        try:
            async with config.client.messages.stream(**kwargs) as stream:
                async for text in stream.text_stream:
                    if self.on_text:
                        self.on_text(text)
                return await stream.get_final_message()
        except Exception:
            # 端点不支持流式时回退到一次性请求
            response = await config.client.messages.create(**kwargs)
            text = "".join(b.text for b in response.content if b.type == "text")
            if self.on_text and text:
                self.on_text(text)
            return response
