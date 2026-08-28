"""TodoWrite：规划能力。TodoManager 维护内存中的任务列表并校验更新。"""

import ast
import json


class TodoManager:
    def __init__(self):
        self.items: list[dict] = []

    def update(self, todos: list | str) -> str:
        if isinstance(todos, str):
            try:
                todos = json.loads(todos)
            except json.JSONDecodeError:
                try:
                    todos = ast.literal_eval(todos)
                except (SyntaxError, ValueError) as exc:
                    raise ValueError("todos must be a JSON array or Python list") from exc

        if not isinstance(todos, list):
            raise ValueError("todos must be a list")
        if len(todos) > 20:
            raise ValueError("Max 20 todos allowed")

        validated = []
        in_progress = 0
        for i, todo in enumerate(todos):
            if not isinstance(todo, dict):
                raise ValueError(f"todos[{i}] must be an object")
            content = str(todo.get("content", "")).strip()
            status = str(todo.get("status", "pending")).lower()
            if not content:
                raise ValueError(f"todos[{i}] requires content")
            if status not in ("pending", "in_progress", "completed"):
                raise ValueError(f"todos[{i}] has invalid status '{status}'")
            if status == "in_progress":
                in_progress += 1
            validated.append({"content": content, "status": status})

        if in_progress > 1:
            raise ValueError("Only one todo can be in_progress at a time")

        self.items = validated
        return self.render()

    def render(self) -> str:
        if not self.items:
            return "No todos."
        markers = {"pending": "[ ]", "in_progress": "[>]", "completed": "[x]"}
        lines = [f"{markers[t['status']]} {t['content']}" for t in self.items]
        done = sum(1 for t in self.items if t["status"] == "completed")
        lines.append(f"\n({done}/{len(self.items)} completed)")
        return "\n".join(lines)


TODO = TodoManager()


def run_todo_write(todos: list | str) -> str:
    try:
        return TODO.update(todos)
    except ValueError as exc:
        return f"Error: {exc}"
