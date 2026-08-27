"""终端交互：prompt_toolkit 提供输入历史，rich 提供流式 Markdown 渲染。"""

import asyncio
import os

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel

from . import config
from .agent import Agent

console = Console()

HISTORY_FILE = os.path.join(config.WORKDIR, ".agent_history")

WELCOME = "EZCode —— 终端编程智能体\n输入任务后按 Enter 发送；空行或 q / exit 退出。"


def _make_session():
    """构造 prompt_toolkit 会话；在非原生控制台（如 Git Bash 的 mintty）会失败，返回 None 以便回退。"""
    try:
        return PromptSession(history=FileHistory(HISTORY_FILE))
    except Exception:
        return None


class TurnRenderer:
    """把 agent 的过程事件累积成 markdown 片段，在一个 rich Live 面板里逐帧渲染。"""

    def __init__(self, agent: Agent):
        self.agent = agent
        self.buffer: list[str] = []
        agent.on_text = self._on_text
        agent.on_tool = self._on_tool
        agent.on_tool_result = self._on_tool_result

    def _on_text(self, delta: str) -> None:
        self.buffer.append(delta)

    def _on_tool(self, name: str, args: dict) -> None:
        command = args.get("command", "") if isinstance(args, dict) else ""
        self.buffer.append(f"\n\n```bash\n$ {command}\n```\n\n")

    def _on_tool_result(self, output: str) -> None:
        preview = output[:600] + ("\n…（已截断）" if len(output) > 600 else "")
        self.buffer.append(f"```text\n{preview}\n```\n")

    async def run(self, task: str) -> None:
        self.buffer.clear()

        def panel(text: str) -> Panel:
            return Panel(Markdown(text or "_（无输出）_"), title="EZCode", border_style="cyan")

        with Live(panel("_思考中…_"), console=console, refresh_per_second=10) as live:
            async def render() -> None:
                last_len = -1
                while True:
                    n = len(self.buffer)
                    if n != last_len:
                        live.update(panel("".join(self.buffer)))
                        last_len = n
                    await asyncio.sleep(0.05)

            renderer = asyncio.create_task(render())
            try:
                await self.agent.run(task)
            except Exception as exc:
                self.buffer.append(f"\n\n**[错误]** {exc}\n")
            finally:
                renderer.cancel()
                try:
                    await renderer
                except asyncio.CancelledError:
                    pass
                live.update(panel("".join(self.buffer)))
        console.print()


class REPL:
    def __init__(self):
        self.agent = Agent()
        self.renderer = TurnRenderer(self.agent)
        self.session = _make_session()

    async def _prompt(self) -> str:
        if self.session is not None:
            return await self.session.prompt_async(">> ")
        return await asyncio.to_thread(input, ">> ")

    async def run(self) -> None:
        console.print(Panel(WELCOME, title="EZCode", border_style="cyan"))
        while True:
            try:
                task = await self._prompt()
            except (EOFError, KeyboardInterrupt):
                break
            task = task.strip()
            if not task or task.lower() in ("q", "exit", "quit"):
                break
            await self.renderer.run(task)
        console.print("\n[dim]再见。[/dim]")
