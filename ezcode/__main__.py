"""入口：`python -m ezcode [task]` —— 无参数进入 REPL，带参数则单次执行。"""

import asyncio
import sys

from .agent import Agent
from .cli import REPL, TurnRenderer


async def run_once(task: str) -> None:
    agent = Agent()
    await TurnRenderer(agent).run(task)


def main() -> None:
    if len(sys.argv) > 1:
        asyncio.run(run_once(" ".join(sys.argv[1:])))
    else:
        asyncio.run(REPL().run())


if __name__ == "__main__":
    main()
