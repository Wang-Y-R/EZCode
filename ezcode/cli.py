"""终端交互：prompt_toolkit 提供输入历史，输出按追加方式逐条打印（像聊天记录一样），不用 Live 原地重绘。"""

import asyncio
import os

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from rich.console import Console
from rich.markup import escape
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
    """把 agent 的过程事件直接追加打印到终端，每段只渲染一次，滚动时不会重叠。"""

    def __init__(self, agent: Agent):
        self.agent = agent
        self._last_tool: str | None = None
        self._text_open = False
        self._thinking_open = False
        agent.on_text = self._on_text
        agent.on_tool = self._on_tool
        agent.on_tool_result = self._on_tool_result
        agent.on_abort = self._on_abort
        agent.on_sub = self._on_sub
        agent.on_status = self._on_status
        agent.on_thinking = self._on_thinking

    def _end_text(self) -> None:
        if self._text_open:
            console.print("")
            self._text_open = False

    def _end_thinking(self) -> None:
        if self._thinking_open:
            console.print("")
            self._thinking_open = False

    def _close_streams(self) -> None:
        self._end_thinking()
        self._end_text()

    def _on_text(self, delta: str) -> None:
        self._end_thinking()
        console.print(delta, end="", markup=False, highlight=False)
        console.file.flush()
        self._text_open = not delta.endswith("\n")

    def _on_thinking(self, delta: str) -> None:
        self._end_text()
        if not self._thinking_open:
            console.print("\n[dim]思考 [/dim]", end="")
            self._thinking_open = True
        console.print(delta, end="", markup=False, highlight=False, style="dim")
        console.file.flush()

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
        self._close_streams()
        self._last_tool = name
        if name == "bash":
            cmd = args.get("command", "")
            if len(cmd) > 200:
                cmd = cmd[:200] + "…"
            console.print(f"\n$ {cmd}\n", markup=False, highlight=False, style="cyan")
        elif name == "todo_write":
            console.print("\n任务计划\n", style="bold")
        else:
            console.print(f"· {name} {self._summarize(args)}", markup=False, style="dim")

    def _on_tool_result(self, output: str) -> None:
        if self._last_tool == "todo_write":
            console.print(self._render_todos(output), markup=False)
            return
        if self._last_tool != "bash":
            # 只展示 bash 的结果（用户要看 pytest 运行），其余工具结果省略
            return
        lines = output.splitlines()
        preview = "\n".join(lines[:5])
        truncated = len(lines) > 5 or len(preview) > 300
        if len(preview) > 300:
            preview = preview[:300] + "…"
        if truncated:
            preview += f"\n…（已截断：共 {len(lines)} 行 / {len(output)} 字符）"
        console.print(preview, markup=False, highlight=False)
        console.print()

    @staticmethod
    def _render_todos(output: str) -> str:
        lines = []
        for line in output.splitlines():
            line = line.strip()
            if line.startswith("[x]"):
                lines.append(f"✓ {line[3:]}")
            elif line.startswith("[>]"):
                lines.append(f"▶ {line[3:]}")
            elif line.startswith("[ ]"):
                lines.append(f"· {line[3:]}")
            elif line:
                lines.append(line)
        return "\n" + "\n".join(lines) + "\n"

    def _on_abort(self, reason: str) -> None:
        self._close_streams()
        console.print(f"\n[已取消] 用户拒绝了该操作：{reason}\n", markup=False, style="red")

    def _on_sub(self, line: str) -> None:
        self._close_streams()
        console.print(f"> {line}", markup=False, style="dim")

    def _on_status(self, line: str) -> None:
        self._close_streams()
        console.print(f"> {line}", markup=False, style="dim")

    @staticmethod
    def _make_permission_handler():
        def handler(name: str, args: dict, reason: str) -> str:
            summary = ", ".join(f"{k}={str(v)[:60]}" for k, v in args.items())
            console.print(Panel(
                f"[bold yellow]权限请求[/bold yellow]\n原因：{escape(reason)}\n工具：{name}({escape(summary)})",
                border_style="yellow",
            ))
            try:
                ans = console.input("是否允许执行？[y/N] ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                ans = ""
            return "allow" if ans in ("y", "yes") else "deny"
        return handler

    async def run(self, task: str) -> None:
        self._text_open = False
        self._thinking_open = False
        self.agent.on_permission = self._make_permission_handler()
        try:
            await self.agent.run(task)
        except Exception as exc:
            self._close_streams()
            console.print(f"\n[错误] {exc}\n", markup=False, style="red")
        finally:
            self._close_streams()
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
