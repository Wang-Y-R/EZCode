"""终端交互：prompt_toolkit 提供输入历史，rich 提供流式 Markdown 渲染。"""

import asyncio
import os

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel

from . import config, permission
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
        self._last_tool: str | None = None
        agent.on_text = self._on_text
        agent.on_tool = self._on_tool
        agent.on_tool_result = self._on_tool_result
        agent.on_abort = self._on_abort
        agent.on_sub = self._on_sub
        agent.on_status = self._on_status

    def _on_text(self, delta: str) -> None:
        self.buffer.append(delta)

    @staticmethod
    def _summarize(args: dict) -> str:
        parts = []
        for k, v in args.items():
            s = str(v)
            if len(s) > 60:
                s = s[:60] + "…"
            parts.append(f"{k}={s!r}")
        return ", ".join(parts)

    def _on_tool(self, name: str, args: dict) -> None:
        args = args if isinstance(args, dict) else {}
        self._last_tool = name
        if name == "bash":
            self.buffer.append(f"\n\n```bash\n$ {args.get('command', '')}\n```\n\n")
        elif name == "todo_write":
            self.buffer.append("\n\n### 任务计划\n")
        else:
            self.buffer.append(f"\n\n```text\n{name}({self._summarize(args)})\n```\n\n")

    def _on_tool_result(self, output: str) -> None:
        if self._last_tool == "todo_write":
            # 专用渲染：把 `[ ]/[>]/[x]` 清单转成带图标的富文本，避免和普通工具输出混在一起
            self.buffer.append(self._render_todos(output))
            return
        preview = output[:600] + ("\n…（已截断）" if len(output) > 600 else "")
        self.buffer.append(f"```text\n{preview}\n```\n")

    @staticmethod
    def _render_todos(output: str) -> str:
        lines = []
        for line in output.splitlines():
            line = line.strip()
            if line.startswith("[x]"):
                lines.append(f"- ~~✓ {line[3:]}~~")
            elif line.startswith("[>]"):
                lines.append(f"- **▶ {line[3:]}**")
            elif line.startswith("[ ]"):
                lines.append(f"- · {line[3:]}")
            elif line:
                lines.append(line)
        return "\n" + "\n".join(lines) + "\n\n"

    def _on_abort(self, reason: str) -> None:
        self.buffer.append(f"\n\n**[已取消]** 用户拒绝了该操作：{reason}\n")

    def _on_sub(self, line: str) -> None:
        self.buffer.append(f"\n> {line}\n")

    def _on_status(self, line: str) -> None:
        self.buffer.append(f"\n> {line}\n")

    @staticmethod
    def _make_permission_handler(live):
        def handler(name: str, args: dict, reason: str) -> str:
            live.stop()
            try:
                summary = ", ".join(f"{k}={str(v)[:60]}" for k, v in args.items())
                console.print(Panel(
                    f"[bold yellow]权限请求[/bold yellow]\n原因：{reason}\n工具：{name}({summary})",
                    border_style="yellow",
                ))
                try:
                    ans = console.input("是否允许执行？[y/N] ").strip().lower()
                except (EOFError, KeyboardInterrupt):
                    ans = ""
                return "allow" if ans in ("y", "yes") else "deny"
            finally:
                live.start()
        return handler

    async def run(self, task: str) -> None:
        self.buffer.clear()

        def panel(text: str) -> Panel:
            return Panel(Markdown(text or "_思考中…_"), title="EZCode", border_style="cyan")

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
            self.agent.on_permission = self._make_permission_handler(live)
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
        welcome = WELCOME + f"\n权限模式：{permission.MODE}（输入 /perm auto|ask|bypass 切换）"
        console.print(Panel(welcome, title="EZCode", border_style="cyan"))
        while True:
            try:
                task = await self._prompt()
            except (EOFError, KeyboardInterrupt):
                break
            task = task.strip()
            if not task or task.lower() in ("q", "exit", "quit"):
                break
            if task.startswith("/perm"):
                arg = task[len("/perm"):].strip()
                console.print(permission.set_mode(arg) if arg else f"当前权限模式：{permission.MODE}")
                continue
            await self.renderer.run(task)
        console.print("\n[dim]再见。[/dim]")
