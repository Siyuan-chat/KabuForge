"""Check the extension tutorial in a built sdist, not in the source checkout.

Run with the candidate wheel installed non-editably in a clean virtualenv:
    /path/to/venv/bin/python tools/check_sdist_tutorial.py dist/kabuforge-*.tar.gz
CI's default ``python -m build`` builds that wheel from the same sdist.
Only use trusted project artifacts: the extracted tutorial and tests execute.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tarfile
import tempfile

REQUIRED_FILES = (
    "examples/extension_demo.py",
    "examples/README.md",
    "framework_v2/tests/test_extension_example.py",
)
INSTALL_PROBE = """
import json
from pathlib import Path
import sys
import sysconfig
import kabuforge
import framework_v2.application

if sys.prefix == sys.base_prefix:
    raise RuntimeError('use a clean virtualenv with the candidate wheel installed')
site = Path(sysconfig.get_paths()['purelib']).resolve()
origins = {}
for module in (kabuforge, framework_v2.application):
    origin = Path(module.__file__).resolve()
    if not origin.is_relative_to(site):
        raise RuntimeError('non-wheel import for ' + module.__name__ + ': ' + str(origin))
    origins[module.__name__] = str(origin)
print(json.dumps({'installed_modules': origins}))
"""


def extract_sdist(archive: Path, destination: Path) -> Path:
    """Require tutorial files and a single regular-file tree before extraction."""
    with tarfile.open(archive, "r:gz") as source:
        members = source.getmembers()
        roots: set[str] = set()
        seen: set[str] = set()
        files: set[str] = set()
        for member in members:
            path = PurePosixPath(member.name)
            if (path.is_absolute() or not path.parts or ".." in path.parts
                    or "\\" in member.name or ":" in member.name):
                raise ValueError("unsafe sdist path: " + member.name)
            if not (member.isdir() or member.isfile()):
                raise ValueError("sdist links/special files are not allowed: " + member.name)
            name = path.as_posix()
            if name in seen:
                raise ValueError("duplicate sdist path: " + name)
            seen.add(name)
            roots.add(path.parts[0])
            if member.isfile() and member.size > 0:
                files.add(name)
        if len(roots) != 1:
            raise ValueError("sdist must contain exactly one top-level directory")
        root = roots.pop()
        missing = [name for name in REQUIRED_FILES if f"{root}/{name}" not in files]
        if missing:
            raise ValueError("sdist missing required nonempty tutorial files: " + ", ".join(missing))
        source.extractall(destination, filter="data")
    return destination / root


def check_sdist(archive: Path) -> dict[str, object]:
    archive = Path(archive).resolve(strict=True)
    # Also protect the tutorial test's nested Python subprocess, which does
    # not use -I. Never let the checkout's PYTHONPATH satisfy missing files.
    env = {key: value for key, value in os.environ.items()
           if key not in {"PYTHONPATH", "PYTHONHOME"}}
    env["PYTHONNOUSERSITE"] = "1"
    with tempfile.TemporaryDirectory(prefix="kabuforge-sdist-tutorial-") as temp:
        root = extract_sdist(archive, Path(temp) / "source")
        python = [sys.executable, "-I"]
        subprocess.run(python + ["-c", INSTALL_PROBE], cwd=root, env=env,
                       check=True, timeout=60)
        demo = subprocess.run(
            python + [str(root / "examples/extension_demo.py"),
                      "--out", str(Path(temp) / "tutorial-output")],
            cwd=root, env=env, check=True, timeout=180,
            capture_output=True, text=True,
        )
        summary = json.loads(demo.stdout)
        if (summary.get("synthetic") is not True
                or summary.get("orders_submitted") is not False
                or summary.get("planned_order_count", 0) < 1):
            raise ValueError("unexpected synthetic tutorial result: " + demo.stdout)
        print(json.dumps({"tutorial_output": summary}), flush=True)
        subprocess.run(
            python + ["-m", "unittest", "discover", "-s", "framework_v2/tests",
                      "-p", "test_extension_example.py", "-v"],
            cwd=root, env=env, check=True, timeout=180,
        )
    return {"sdist": archive.name, "required_files": list(REQUIRED_FILES),
            "tutorial": "passed", "tutorial_tests": "passed"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sdist", type=Path, help="exactly one built .tar.gz artifact")
    args = parser.parse_args()
    try:
        result = check_sdist(args.sdist)
    except (OSError, ValueError, tarfile.TarError, subprocess.SubprocessError) as exc:
        print("sdist tutorial check failed: " + str(exc), file=sys.stderr)
        if isinstance(exc, subprocess.CalledProcessError):
            for output in (exc.stdout, exc.stderr):
                if output:
                    print(output, file=sys.stderr)
        raise SystemExit(1) from exc
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
