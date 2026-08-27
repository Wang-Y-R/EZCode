"""工具定义与本地执行：目前只有 bash 一个工具。"""

import subprocess

from . import config

TOOLS = [
    {
        "name": "bash",
        "description": "Run a shell command in the project directory and return its output.",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "The shell command to run."},
            },
            "required": ["command"],
        },
    }
]

DANGEROUS = ("rm -rf /", "sudo", "shutdown", "reboot", "> /dev/")


def run_bash(command: str) -> str:
    """执行一条 shell 命令，返回 stdout+stderr（截断到合理长度）。"""
    if any(d in command for d in DANGEROUS):
        return "Error: dangerous command blocked"
    try:
        if config.SHELL:
            result = subprocess.run(
                [config.SHELL, "-c", command], cwd=config.WORKDIR,
                capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=120,
            )
        else:
            result = subprocess.run(
                command, shell=True, cwd=config.WORKDIR,
                capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=120,
            )
        out = (result.stdout + result.stderr).strip()
        return out[:50000] if out else "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: command timed out (120s)"
    except (FileNotFoundError, OSError) as exc:
        return f"Error: {exc}"


TOOL_HANDLERS = {
    "bash": lambda args: run_bash(args.get("command", "")),
}
