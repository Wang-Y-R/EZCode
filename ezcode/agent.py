"""核心 agent 循环：流式调用模型 -> 执行工具 -> 回填结果，直到模型不再调用工具。"""

from . import config, permission
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

    async def run(self, task: str) -> str:
        """执行一轮任务，返回模型的最终文本；历史保留，供后续轮次复用。"""
        self.messages.append({"role": "user", "content": task})
        return await self._loop()

    async def _loop(self) -> str:
        while True:
            response = await self._call()
            self.messages.append({"role": "assistant", "content": response.content})

            tool_calls = [b for b in response.content if b.type == "tool_use"]
            if not tool_calls:
                return "".join(b.text for b in response.content if b.type == "text")

            results, aborted_reason = self._run_tools(tool_calls)
            self.messages.append({"role": "user", "content": results})
            if aborted_reason is not None:
                if self.on_abort:
                    self.on_abort(aborted_reason)
                return f"已取消：用户拒绝了该操作（{aborted_reason}）"

    def _gate(self, name: str, args: dict) -> tuple[bool, str, bool]:
        """三道闸门：硬拒绝 → 规则匹配 → 用户审批。返回 (是否放行, 拒绝原因, 是否由用户主动拒绝)。"""
        if name == "bash":
            reason = permission.check_deny_list(args.get("command", ""))
            if reason:
                return False, f"Blocked: {reason}", False
        reason = permission.check_rules(name, args)
        if reason:
            if self.on_permission is None:
                return False, f"Permission required: {reason}", False
            if self.on_permission(name, args, reason) != "allow":
                return False, reason, True
        return True, "", False

    def _run_tools(self, tool_calls) -> tuple[list, str | None]:
        """逐个执行工具；用户拒绝时中止本轮，并为剩余 tool_use 补齐占位结果，保证历史完整。"""
        results = []
        for i, block in enumerate(tool_calls):
            if self.on_tool:
                self.on_tool(block.name, block.input)
            allowed, deny_msg, user_denied = self._gate(block.name, block.input or {})
            if user_denied:
                output = f"Denied by user: {deny_msg}"
                if self.on_tool_result:
                    self.on_tool_result(output)
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": output})
                cancelled = "Cancelled: a previous request was denied by the user"
                for rest in tool_calls[i + 1:]:
                    if self.on_tool_result:
                        self.on_tool_result(cancelled)
                    results.append({"type": "tool_result", "tool_use_id": rest.id, "content": cancelled})
                return results, deny_msg
            output = self._execute(block) if allowed else deny_msg
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
