"""权限管线：硬拒绝 → 规则匹配 → 交给 UI 审批（闸门 3 由 agent 回调完成）。"""

import re

from .tools import WORKDIR_PATH

# 闸门 1：硬拒绝表。简单字符串匹配
DENY_LIST = ("rm -rf /", "sudo", "shutdown", "reboot", "mkfs", "dd if=", "> /dev/sda")


def check_deny_list(command: str) -> str | None:
    for pattern in DENY_LIST:
        if pattern in command:
            return f"'{pattern}' 在拒绝列表中"
    return None


# 闸门 2：规则匹配
DESTRUCTIVE_COMMAND_WORD = re.compile(
    r"(?i)(?:^|[;&|()\n])\s*(?:rm|del)(?=\s|$|[;&|()])"
)
_ABSOLUTE_PATH = re.compile(r"(?:^|[\s'\"(])(?:[A-Za-z]:[\\/]|/[A-Za-z])")


def contains_destructive_command(command: str) -> bool:
    return bool(DESTRUCTIVE_COMMAND_WORD.search(command))


def _outside_workspace(path: str) -> bool:
    return not (WORKDIR_PATH / path).resolve().is_relative_to(WORKDIR_PATH)


def _touches_parent_dir(command: str) -> bool:
    # 启发式：出现父目录穿越，或引用绝对路径，可能访问工作区之外
    return ".." in command or bool(_ABSOLUTE_PATH.search(command))


def check_rules(tool_name: str, args: dict) -> str | None:
    """返回需要审批的原因；None 表示直接放行。"""
    if tool_name in ("read_file", "write_file", "edit_file"):
        if _outside_workspace(args.get("path", "")):
            return "访问工作区之外的文件"
    elif tool_name == "bash":
        command = args.get("command", "")
        if contains_destructive_command(command):
            return "潜在的破坏性命令"
        if _touches_parent_dir(command):
            return "命令可能访问工作区之外"
    return None
