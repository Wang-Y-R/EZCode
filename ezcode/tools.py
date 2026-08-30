"""工具定义与本地执行：bash / read_file / write_file / edit_file / glob / grep / todo_write / task / load_skill。"""

import fnmatch
import glob as _glob
import re
import subprocess
from pathlib import Path

from . import config
from .skill import run_load_skill
from .tasks import (
    run_claim_task,
    run_complete_task,
    run_create_task,
    run_get_task,
    run_list_tasks,
    run_update_task,
)
from .todo import run_todo_write

WORKDIR_PATH = Path(config.WORKDIR).resolve()

DANGEROUS = ("rm -rf /", "sudo", "shutdown", "reboot", "> /dev/")


def safe_path(p: str) -> Path:
    """把路径约束在工作目录内，防止读写工作区之外的文件。"""
    path = (WORKDIR_PATH / p).resolve()
    if not path.is_relative_to(WORKDIR_PATH):
        raise ValueError(f"Path escapes workspace: {p}")
    return path


def run_bash(command: str, run_in_background: bool = False) -> str:
    """执行一条 shell 命令，返回 stdout+stderr（截断到合理长度）。

    run_in_background 由 Agent 循环在进入本 handler 前消费（见 background.should_run_background），
    这里保留该参数只为兼容 schema 传入，实际永远同步执行。
    """
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
        out = out[:50000] if out else "(no output)"
        if result.returncode != 0:
            return f"Error: command exited with status {result.returncode}\n{out}"
        return out
    except subprocess.TimeoutExpired:
        return "Error: command timed out (120s)"
    except (FileNotFoundError, OSError) as exc:
        return f"Error: {exc}"


def run_read(path: str, limit: int | None = None) -> str:
    try:
        lines = safe_path(path).read_text(encoding="utf-8").splitlines()
        if limit and limit < len(lines):
            lines = lines[:limit] + [f"... ({len(lines) - limit} more lines)"]
        return "\n".join(lines)
    except Exception as exc:
        return f"Error: {exc}"


def run_write(path: str, content: str) -> str:
    try:
        file_path = safe_path(path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        return f"Wrote {len(content)} bytes to {path}"
    except Exception as exc:
        return f"Error: {exc}"


def run_edit(path: str, old_text: str, new_text: str) -> str:
    try:
        if not old_text:
            return "Error: old_text must not be empty"
        file_path = safe_path(path)
        text = file_path.read_text(encoding="utf-8")
        count = text.count(old_text)
        if count == 0:
            return f"Error: text not found in {path}"
        if count > 1:
            return f"Error: old_text is not unique ({count} occurrences); provide more surrounding context to disambiguate"
        file_path.write_text(text.replace(old_text, new_text, 1), encoding="utf-8")
        return f"Edited {path}"
    except Exception as exc:
        return f"Error: {exc}"


def run_glob(pattern: str) -> str:
    try:
        matches = sorted({
            m for m in _glob.glob(pattern, root_dir=WORKDIR_PATH, recursive=True)
            if (WORKDIR_PATH / m).resolve().is_relative_to(WORKDIR_PATH)
        })
        shown = matches[:200]
        if len(matches) > 200:
            shown.append("... (more matches omitted; narrow the pattern)")
        return "\n".join(shown) if shown else "(no matches)"
    except Exception as exc:
        return f"Error: {exc}"


def run_grep(pattern: str, path: str = ".", glob: str | None = None) -> str:
    """按正则搜索 path（文件或目录）的文件内容，返回 file:line: text 匹配列表。"""
    try:
        regex = re.compile(pattern)
    except re.error as exc:
        return f"Error: invalid regex: {exc}"

    try:
        root = safe_path(path)
    except ValueError as exc:
        return f"Error: {exc}"

    if not root.exists():
        return f"Error: path not found: {path}"

    if root.is_file():
        files = [root]
    else:
        ignored = {
            ".git", "__pycache__", ".venv", "venv", "node_modules",
            ".memory", ".tasks", ".transcripts", ".task_outputs",
        }
        files = sorted(
            p for p in root.rglob("*")
            if p.is_file() and not (set(p.relative_to(root).parts) & ignored)
        )

    matches = []
    for file_path in files:
        if glob and not fnmatch.fnmatch(file_path.name, glob):
            continue
        try:
            text = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if regex.search(line):
                matches.append(f"{file_path.relative_to(WORKDIR_PATH)}:{lineno}: {line.strip()[:200]}")
                if len(matches) >= 200:
                    break
        if len(matches) >= 200:
            break

    if not matches:
        return "(no matches)"
    if len(matches) >= 200:
        matches.append("... (more matches omitted; narrow the pattern)")
    return "\n".join(matches)


TOOLS = [
    {
        "name": "bash",
        "description": "Run a shell command in the project directory and return its output.",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "The shell command to run."},
                "run_in_background": {
                    "type": "boolean",
                    "description": "Set true for independent long-running commands; the loop continues and the result arrives as a task_notification on a later turn.",
                },
            },
            "required": ["command"],
        },
    },
    {
        "name": "read_file",
        "description": "Read a file's contents, optionally limited to the first N lines.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the file, relative to the workspace."},
                "limit": {"type": "integer", "description": "Optional: only read the first N lines."},
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "Write text content to a file, creating parent directories as needed.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the file, relative to the workspace."},
                "content": {"type": "string", "description": "Full text content to write."},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "edit_file",
        "description": "Replace old_text with new_text in a file. old_text must match exactly once; "
        "if it appears multiple times, add more surrounding context to make it unique.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the file, relative to the workspace."},
                "old_text": {"type": "string", "description": "Exact text to find."},
                "new_text": {"type": "string", "description": "Replacement text."},
            },
            "required": ["path", "old_text", "new_text"],
        },
    },
    {
        "name": "glob",
        "description": "Find files matching a glob pattern; ** matches recursively.",
        "input_schema": {
            "type": "object",
            "properties": {"pattern": {"type": "string", "description": "Glob pattern, e.g. '**/*.py'."}},
            "required": ["pattern"],
        },
    },
    {
        "name": "grep",
        "description": "Search file contents for a regular expression and return file:line matches.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Regular expression to search for."},
                "path": {"type": "string", "description": "File or directory to search, relative to the workspace (default '.')."},
                "glob": {"type": "string", "description": "Optional filename filter, e.g. '*.py'."},
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "todo_write",
        "description": "Create and manage a task list to track progress on the current task. "
        "Use it before multi-step work: list steps as pending, mark the one you're working on "
        "in_progress (only one at a time), and completed when done. Each call replaces the whole list.",
        "input_schema": {
            "type": "object",
            "properties": {
                "todos": {
                    "type": "array",
                    "maxItems": 20,
                    "items": {
                        "type": "object",
                        "properties": {
                            "content": {"type": "string", "description": "The task description."},
                            "status": {"type": "string", "enum": ["pending", "in_progress", "completed"]},
                        },
                        "required": ["content", "status"],
                    },
                },
            },
            "required": ["todos"],
        },
    },
    {
        "name": "task",
        "description": "Run a subagent with fresh conversation context and return its final text. "
        "Use for focused exploration or a self-contained subtask; the subagent shares the "
        "workspace but only its final answer comes back.",
        "input_schema": {
            "type": "object",
            "properties": {"prompt": {"type": "string", "minLength": 1, "description": "The subtask for the subagent."}},
            "required": ["prompt"],
        },
    },
    {
        "name": "load_skill",
        "description": "Load the full SKILL.md content by skill name. Use when a listed skill applies "
        "to the current task; the catalog in the system prompt lists available skills.",
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string", "description": "Skill name to load."}},
            "required": ["name"],
        },
    },
    {
        "name": "compact",
        "description": "Summarize earlier conversation to free context space. Use after completing "
        "a distinct stage when the details that follow no longer matter.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "create_task",
        "description": "Create a persistent task and return its runtime-generated ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "subject": {"type": "string", "description": "Short task summary."},
                "description": {"type": "string", "description": "Optional details."},
            },
            "required": ["subject"],
        },
    },
    {
        "name": "update_task",
        "description": "Add dependencies to a task using IDs returned by create_task.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "pattern": "^task_[0-9a-f]{8}$"},
                "addBlockedBy": {
                    "type": "array",
                    "items": {"type": "string", "pattern": "^task_[0-9a-f]{8}$"},
                    "minItems": 1,
                },
            },
            "required": ["task_id", "addBlockedBy"],
        },
    },
    {
        "name": "list_tasks",
        "description": "List tasks with status, owner, and dependencies.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "get_task",
        "description": "Get a task's full JSON record by ID.",
        "input_schema": {
            "type": "object",
            "properties": {"task_id": {"type": "string"}},
            "required": ["task_id"],
        },
    },
    {
        "name": "claim_task",
        "description": "Claim a pending task whose dependencies are all completed.",
        "input_schema": {
            "type": "object",
            "properties": {"task_id": {"type": "string"}},
            "required": ["task_id"],
        },
    },
    {
        "name": "complete_task",
        "description": "Complete the task claimed by this agent, unlocking downstream tasks.",
        "input_schema": {
            "type": "object",
            "properties": {"task_id": {"type": "string"}},
            "required": ["task_id"],
        },
    },
]

# 注意：task 的 handler 是异步的（需要嵌套调用模型），定义在 agent.py 的 _run_subagent，
# 因此这里不放进 TOOL_HANDLERS，而是在 Agent._execute 中单独分派。
TOOL_HANDLERS = {
    "bash": run_bash,
    "read_file": run_read,
    "write_file": run_write,
    "edit_file": run_edit,
    "glob": run_glob,
    "grep": run_grep,
    "todo_write": run_todo_write,
    "load_skill": run_load_skill,
    "create_task": run_create_task,
    "update_task": run_update_task,
    "list_tasks": run_list_tasks,
    "get_task": run_get_task,
    "claim_task": run_claim_task,
    "complete_task": run_complete_task,
}

# 子 Agent 只保留基础五工具：不能委派（task）、不规划（todo_write）、不加载技能（load_skill）、
# 不压缩（compact），也不操作全局任务图（create/update/list/get/claim/complete_task）
SUB_EXCLUDED = {
    "task", "todo_write", "load_skill", "compact",
    "create_task", "update_task", "list_tasks", "get_task", "claim_task", "complete_task",
}
SUB_TOOLS = [t for t in TOOLS if t["name"] not in SUB_EXCLUDED]
SUB_HANDLERS = {k: v for k, v in TOOL_HANDLERS.items() if k not in SUB_EXCLUDED}
