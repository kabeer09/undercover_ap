"""Work the queue with the UnderCover Agent: uv run -m agent [--cap N] [CLM-1001]"""

import sys
import uuid

from agent.main import run, run_queue


def main(args: list[str]) -> None:
    """Work one claim, or the queue, capped at a number of claims if asked."""
    if args and args[0] == "--cap":
        run_queue(int(args[1]))
    elif args:
        print(run(args[0], str(uuid.uuid4())))
    else:
        run_queue()


if __name__ == "__main__":
    main(sys.argv[1:])
