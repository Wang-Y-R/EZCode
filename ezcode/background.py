"""Background Tasks：把慢的 bash 命令丢到后台线程执行，主循环不阻塞。

bash 工具带上 run_in_background=true 时，start() 立即返回 bg_id（占位 tool_result），
命令在 daemon 线程里跑；后续轮次开始时 inject_background_results() 收集已完成结果，
以 <task_notification> 文本块注入对话。通知不复用原始 tool_use_id。

background 依赖 tools.run_bash（叶子方向：background -> tools -> config），
不 import agent，避免循环导入。
"""

import threading

from . import tools


class BackgroundManager:
    def __init__(self, notify=None):
        self.tasks: dict[str, dict] = {}
        self.results: dict[str, str] = {}
        self._ready: list[str] = []
        self._counter = 0
        self._lock = threading.Lock()
        self.notify = notify

    def _notify(self, line: str) -> None:
        if self.notify:
            self.notify(line)

    def start(self, block) -> str:
        if block.name != "bash":
            raise ValueError("Only Bash commands can run in the background")
        command = block.input.get("command")
        if not isinstance(command, str) or not command.strip():
            raise ValueError("Bash command cannot be empty")

        with self._lock:
            self._counter += 1
            task_id = f"bg_{self._counter:04d}"
            self.tasks[task_id] = {
                "tool_use_id": block.id,
                "command": command,
                "status": "running",
            }

        thread = threading.Thread(target=self._run, args=(task_id, command), daemon=True)
        try:
            thread.start()
        except Exception:
            with self._lock:
                self.tasks.pop(task_id, None)
            raise
        self._notify(f"[background] started {task_id}: {command[:60]}")
        return task_id

    def _run(self, task_id: str, command: str) -> None:
        try:
            output = tools.run_bash(command)
            status = "failed" if output.startswith("Error:") else "completed"
            result = output
        except Exception as error:
            result = f"Error: {type(error).__name__}: {error}"
            status = "failed"

        with self._lock:
            task = self.tasks.get(task_id)
            if task is None:
                return
            task["status"] = status
            self.results[task_id] = result
            self._ready.append(task_id)

    def collect(self) -> list[str]:
        with self._lock:
            ready = []
            for task_id in self._ready:
                task = self.tasks.pop(task_id, None)
                result = self.results.pop(task_id, "")
                if task is not None:
                    ready.append((task_id, task, result))
            self._ready.clear()

        notifications = []
        for task_id, task, result in ready:
            notifications.append(
                f"<task_notification>\n"
                f"  <task_id>{task_id}</task_id>\n"
                f"  <status>{task['status']}</status>\n"
                f"  <command>{task['command']}</command>\n"
                f"  <summary>{result[:500]}</summary>\n"
                f"</task_notification>"
            )
            self._notify(f"[background] collected {task_id}: {task['status']}")
        return notifications


BACKGROUND = BackgroundManager()


def should_run_background(tool_name: str, tool_input: dict) -> bool:
    return tool_name == "bash" and tool_input.get("run_in_background") is True


def start_background_task(block) -> str:
    return BACKGROUND.start(block)


def collect_background_results() -> list[str]:
    return BACKGROUND.collect()


def inject_background_results(messages: list) -> int:
    notifications = collect_background_results()
    if not notifications:
        return 0

    blocks = [{"type": "text", "text": item} for item in notifications]
    if messages and messages[-1].get("role") == "user":
        content = messages[-1].get("content", "")
        if isinstance(content, list):
            content.extend(blocks)
        else:
            messages[-1]["content"] = [
                {"type": "text", "text": str(content)},
                *blocks,
            ]
    else:
        messages.append({"role": "user", "content": blocks})
    return len(notifications)
