"""Hook 系统：事件注册表 + 触发。扩展点挂在循环之外，循环只调用 trigger。"""


class HookAbort(Exception):
    """PreToolUse hook 抛出以中止本轮；reason 供 UI 展示。"""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


EVENT_NAMES = ("UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop")


class HookRegistry:
    """事件名 -> 回调列表。trigger 按注册顺序执行，返回第一个非 None 的结果。"""

    def __init__(self):
        self._hooks = {name: [] for name in EVENT_NAMES}

    def register(self, event: str, callback) -> None:
        if event not in self._hooks:
            raise ValueError(f"Unknown hook event: {event!r}")
        self._hooks[event].append(callback)

    def trigger(self, event: str, *args):
        for callback in self._hooks[event]:
            result = callback(*args)
            if result is not None:
                return result
        return None
