"""Windows entry point; also supports the local project environment."""

import os
import subprocess
import sys
from pathlib import Path


def main() -> int:
    # The user's existing py launcher may still default to Python 3.10.
    # Re-exec the project environment for the documented `py main.py` command.
    root = Path(__file__).resolve().parent
    environment = root / ".venv"
    interpreter = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not getattr(sys, "frozen", False) and interpreter.exists() and Path(sys.prefix).resolve() != environment.resolve():
        return subprocess.call([str(interpreter), str(root / "main.py"), *sys.argv[1:]])
    if sys.version_info < (3, 11):  # noqa: UP036 - bootstrap runs on the user's older py launcher
        print("AvalancheView requires Python 3.11+. See README.md for setup.", file=sys.stderr)
        return 1
    from avalanche_view.app import main as application_main

    return application_main()


if __name__ == "__main__":
    raise SystemExit(main())
