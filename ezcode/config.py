"""配置：环境变量、模型端点、工作目录、系统提示词、shell 探测。"""

import os
import platform
import shutil

from anthropic import AsyncAnthropic
from dotenv import load_dotenv

load_dotenv(override=True)

# 兼容某些第三方网关：不设置 AUTH_TOKEN，避免与 API_KEY 冲突
if os.getenv("ANTHROPIC_BASE_URL"):
    os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)

WORKDIR = os.getcwd()

MODEL = os.getenv("MODEL_ID")
if not MODEL:
    raise SystemExit("请在 .env 中设置 MODEL_ID 和 ANTHROPIC_API_KEY")

BASE_URL = os.getenv("ANTHROPIC_BASE_URL")

client = AsyncAnthropic(base_url=BASE_URL)

SYSTEM = (
    f"You are a coding agent running on {platform.system()} in {WORKDIR}. "
    "Use the available tools to read and edit files, run commands, and solve the "
    "user's programming tasks. Destructive commands and access outside the workspace "
    "require user approval. Act, don't just explain."
)


def _find_shell() -> str | None:
    """Windows 上优先定位 Git Bash，让模型发出的 Unix 命令可执行；POSIX 返回 None 用系统默认 shell。"""
    if os.name != "nt":
        return None
    candidates = [
        r"C:\Program Files\Git\bin\bash.exe",
        r"C:\Program Files\Git\usr\bin\bash.exe",
        r"C:\Program Files (x86)\Git\bin\bash.exe",
        r"C:\Program Files (x86)\Git\usr\bin\bash.exe",
        os.path.expanduser(r"~\AppData\Local\Programs\Git\bin\bash.exe"),
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    # 从 git.exe 的位置反推 Git Bash，避免 shutil.which("bash") 误抓 System32 里的 WSL bash
    git = shutil.which("git")
    if git:
        root = os.path.dirname(os.path.dirname(os.path.abspath(git)))
        for b in (os.path.join(root, "bin", "bash.exe"),
                  os.path.join(root, "usr", "bin", "bash.exe")):
            if os.path.exists(b):
                return b
    return shutil.which("bash")


SHELL = _find_shell()
