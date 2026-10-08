"""Launch a frozen exe outside the source tree with Python removed from its search path."""

import argparse
import json
import os
import subprocess
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("exe", type=Path)
    parser.add_argument("--file", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    executable = args.exe.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    report = output / "report.json"
    environment = os.environ.copy()
    for name in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"):
        environment.pop(name, None)
    system = Path(environment.get("SystemRoot", "C:/Windows"))
    environment["PATH"] = os.pathsep.join([str(system / "System32"), str(system)])
    environment["AVALANCHEVIEW_DATA_DIR"] = str(output / "runtime")
    command = [str(executable), "--smoke-test", "--smoke-report", str(report)]
    if args.file:
        command.append(str(args.file.resolve()))
    else:
        command.append("--demo")
    result = subprocess.run(
        command, cwd=output, env=environment, timeout=150,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        capture_output=True, text=True,
    )
    if result.returncode:
        if report.is_file():
            print(report.read_text(encoding="utf-8"))
        raise RuntimeError(f"Frozen application exited with {result.returncode}: {result.stderr}")
    payload = json.loads(report.read_text(encoding="utf-8"))
    if payload.get("status") != "passed" or not payload.get("frozen"):
        raise AssertionError(payload)
    if not report.with_suffix(".map.png").is_file():
        raise AssertionError("Frozen map export was not created")
    print(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    main()
