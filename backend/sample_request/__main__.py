"""Entry point for `python -m backend.sample_request`."""
from __future__ import annotations

import sys


def main() -> int:
    try:
        from backend.sample_request.cli import main as cli_main
    except ImportError:
        # cli.py is implemented in Task 10; until then, fail loudly.
        print(
            "backend.sample_request.cli not implemented yet — see plan Task 10",
            file=sys.stderr,
        )
        return 2
    return cli_main()


if __name__ == "__main__":
    raise SystemExit(main())
