"""工具定义与本地执行：bash / read_file / write_file / edit_file / glob / todo_write / task / load_skill。"""

import glob as _glob
import subprocess
from pathlib import Path

from . import config
from .skill import run_load_skill
from .todo import run_todo_write

WORKDIR_PATH = Path(config.WORKDIR).resolve()

DANGEROUS = ("rm -rf /", "sudo", "shutdown", "reboot", "> /dev/")


def safe_path(p: str) -> Path:
    """把路径约束在工作目录内，防止读写工作区之外的文件。"""
    path = (WORKDIR_PATH / p).resolve()
    if not path.is_relative_to(WORKDIR_PATH):
        raise ValueError(f"Path escapes workspace: {p}")
    return path


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
        file_path = safe_path(path)
        text = file_path.read_text(encoding="utf-8")
        if old_text not in text:
            return f"Error: text not found in {path}"
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


TOOLS = [
    {
        "name": "bash",
        "description": "Run a shell command in the project directory and return its output.",
        "input_schema": {
            "type": "object",
            "properties": {"command": {"type": "string", "description": "The shell command to run."}},
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
        "description": "Replace the first occurrence of old_text with new_text in a file.",
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
]

# 注意：task 的 handler 是异步的（需要嵌套调用模型），定义在 agent.py 的 _run_subagent，
# 因此这里不放进 TOOL_HANDLERS，而是在 Agent._execute 中单独分派。
TOOL_HANDLERS = {
    "bash": run_bash,
    "read_file": run_read,
    "write_file": run_write,
    "edit_file": run_edit,
    "glob": run_glob,
    "todo_write": run_todo_write,
    "load_skill": run_load_skill,
}

# 基础五工具：子 Agent 只拥有这些，不能再次委派（无 task）、不规划（无 todo_write）、不加载技能（无 load_skill）
SUB_TOOLS = [t for t in TOOLS if t["name"] not in ("task", "todo_write", "load_skill")]
SUB_HANDLERS = {k: v for k, v in TOOL_HANDLERS.items() if k not in ("todo_write", "load_skill")}
