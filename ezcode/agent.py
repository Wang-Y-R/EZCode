"""核心 agent 循环：流式调用模型 -> 执行工具 -> 回填结果，直到模型不再调用工具。"""

from . import config
from .tools import TOOLS, TOOL_HANDLERS


class Agent:
    """持有对话历史，run() 一轮任务；UI 通过 on_* 回调观察过程。"""

    def __init__(self, on_text=None, on_tool=None, on_tool_result=None):
        self.on_text = on_text
        self.on_tool = on_tool
        self.on_tool_result = on_tool_result
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

            results = []
            for block in tool_calls:
                if self.on_tool:
                    self.on_tool(block.name, block.input)
                output = self._execute(block)
                if self.on_tool_result:
                    self.on_tool_result(output)
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": output,
                })
            self.messages.append({"role": "user", "content": results})

    def _execute(self, block) -> str:
        handler = TOOL_HANDLERS.get(block.name)
        if handler is None:
            return f"Error: unknown tool {block.name!r}"
        try:
            return handler(block.input or {})
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
