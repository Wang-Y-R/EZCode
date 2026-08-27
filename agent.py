#!/usr/bin/env python3
"""EZCode — S01: 最小 agent 循环。

一个工具（bash）+ 一个循环 = 一个 coding agent。

    while True:
        response = LLM(messages, tools)
        若无 tool_use -> 结束
        执行工具 -> 把结果追加回 messages -> 循环
"""

import os
import platform
import shutil
import subprocess
import sys

from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv(override=True)

if os.getenv("ANTHROPIC_BASE_URL"):
    os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)

WORKDIR = os.getcwd()
client = Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"))
MODEL = os.getenv("MODEL_ID")
if not MODEL:
    raise SystemExit("请在 .env 中设置 MODEL_ID 和 ANTHROPIC_API_KEY")

SYSTEM = (
    f"You are a coding agent on {platform.system()} at {WORKDIR}. "
    "Use the bash tool to solve tasks. Act, don't explain."
)

TOOLS = [
    {
        "name": "bash",
        "description": "Run a shell command and return its output.",
        "input_schema": {
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"],
        },
    }
]


def _find_shell() -> str | None:
    """Windows 上优先找 Git Bash，让模型发出的 Unix 命令能执行；POSIX 返回 None 用系统默认 shell。"""
    if os.name != "nt":
        return None
    for p in [
        r"C:\Program Files\Git\bin\bash.exe",
        r"C:\Program Files\Git\usr\bin\bash.exe",
        r"C:\Program Files (x86)\Git\bin\bash.exe",
        r"C:\Program Files (x86)\Git\usr\bin\bash.exe",
        os.path.expanduser(r"~\AppData\Local\Programs\Git\bin\bash.exe"),
    ]:
        if os.path.exists(p):
            return p
    # 从 git.exe 位置反推 Git Bash，避免 shutil.which("bash") 误抓到 System32 里的 WSL bash
    git = shutil.which("git")
    if git:
        root = os.path.dirname(os.path.dirname(os.path.abspath(git)))
        for b in (os.path.join(root, "bin", "bash.exe"),
                  os.path.join(root, "usr", "bin", "bash.exe")):
            if os.path.exists(b):
                return b
    return shutil.which("bash")


SHELL = _find_shell()


def run_bash(command: str) -> str:
    dangerous = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/"]
    if any(d in command for d in dangerous):
        return "Error: dangerous command blocked"
    try:
        if SHELL:
            r = subprocess.run(
                [SHELL, "-c", command], cwd=WORKDIR,
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
            )
        else:
            r = subprocess.run(
                command, shell=True, cwd=WORKDIR,
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
            )
        out = (r.stdout + r.stderr).strip()
        return out[:50000] if out else "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: command timed out (120s)"
    except (FileNotFoundError, OSError) as e:
        return f"Error: {e}"


def agent_loop(messages: list) -> str:
    """核心循环：调用模型 -> 执行工具 -> 回填结果，直到模型不再调用工具。"""
    while True:
        response = client.messages.create(
            model=MODEL, system=SYSTEM, messages=messages,
            tools=TOOLS, max_tokens=8000,
        )
        messages.append({"role": "assistant", "content": response.content})

        tool_calls = [b for b in response.content if b.type == "tool_use"]
        if not tool_calls:
            return "".join(b.text for b in response.content if b.type == "text")

        results = []
        for block in tool_calls:
            print(f"\033[33m$ {block.input['command']}\033[0m")
            output = run_bash(block.input["command"])
            print(output[:200])
            results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": output,
            })
        messages.append({"role": "user", "content": results})



def run_task(task: str) -> None:
    final = agent_loop([{"role": "user", "content": task}])
    if final:
        print(f"\n{final}")


def repl() -> None:
    print("EZCode — 最小 agent 循环 (S01)")
    print("输入任务按回车发送，输入 q 退出。\n")
    history = []
    while True:
        try:
            task = input("EZCode >> ")
        except (EOFError, KeyboardInterrupt):
            break
        if task.strip().lower() in ("q", "exit", ""):
            break
        history.append({"role": "user", "content": task})
        final = agent_loop(history)
        if final:
            print(f"\n{final}")
        print()


if __name__ == "__main__":
    if len(sys.argv) > 1:
        run_task(" ".join(sys.argv[1:]))
    else:
        repl()
