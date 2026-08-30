"""权限管线：硬拒绝 → 规则匹配 → 交给 UI 审批（闸门 3 由 agent 回调完成）。

权限模式 MODE（可用环境变量 EZCODE_PERMISSION_MODE 预设初值，REPL 里 /perm 运行时切换）：
- auto   —— 只在规则命中（破坏性命令 / 越界路径）时才询问
- ask    —— 额外对所有会改变状态的工具（bash / write / edit）一律询问
- bypass —— 跳过规则闸门（硬拒绝表 DENY_LIST 仍始终生效）
"""

import os
import re

from .tools import WORKDIR_PATH

# 闸门 1：硬拒绝表。任何模式都不放行
DENY_LIST = ("rm -rf /", "sudo", "shutdown", "reboot", "mkfs", "dd if=", "> /dev/sda")

VALID_MODES = ("auto", "ask", "bypass")

MODE = os.environ.get("EZCODE_PERMISSION_MODE", "auto").strip().lower()
if MODE not in VALID_MODES:
    MODE = "auto"

# ask 模式下无条件审批的工具：会改变工作区 / 系统状态
MUTATING_TOOLS = {"bash", "write_file", "edit_file"}
MUTATING_REASONS = {
    "bash": "执行命令",
    "write_file": "写入文件",
    "edit_file": "编辑文件",
}


def set_mode(mode: str) -> str:
    global MODE
    mode = (mode or "").strip().lower()
    if mode not in VALID_MODES:
        return f"未知模式 '{mode}'，可选：{', '.join(VALID_MODES)}"
    MODE = mode
    return f"权限模式已切换为 {mode}"


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
    """返回需要审批的原因；None 表示放行。覆盖所有带路径 / 命令的工具。"""
    if tool_name in ("read_file", "write_file", "edit_file", "grep"):
        path = args.get("path", "")
        if path and _outside_workspace(path):
            return "访问工作区之外的文件"
    elif tool_name == "bash":
        command = args.get("command", "")
        if contains_destructive_command(command):
            return "潜在的破坏性命令"
        if _touches_parent_dir(command):
            return "命令可能访问工作区之外"
    return None


def approval_reason(tool_name: str, args: dict) -> str | None:
    """根据当前模式返回是否需要审批及原因；None 表示放行。"""
    if MODE == "bypass":
        return None
    reason = check_rules(tool_name, args)
    if reason:
        return reason
    if MODE == "ask" and tool_name in MUTATING_TOOLS:
        return MUTATING_REASONS[tool_name]
    return None
