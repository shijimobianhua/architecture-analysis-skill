"""Environment preflight for architecture-analysis scripts.

Checks the interpreter version and the Pillow dependency that every drawing
tool in this skill needs. Read-only: installs nothing, draws nothing, makes no
network calls. Run before the first use of layers.py / layout_check.py /
map_source.py / road_overlay.py / job_spec.py / migrate_spec.py.

Usage:
    python "${CODEBUDDY_SKILL_DIR}/scripts/preflight.py"
    python "${CODEBUDDY_SKILL_DIR}/scripts/preflight.py" --json
"""

import argparse
import json
import platform
import sys

MIN_PYTHON = (3, 10)
REQUIRED = ["Pillow"]
OPTIONAL = []  # standard library only beyond Pillow


def check_python():
    cur = sys.version_info[:2]
    ok = cur >= MIN_PYTHON
    return {
        "check": "python",
        "ok": ok,
        "detail": ".".join(str(p) for p in cur),
        "required": ">={}.{}".format(*MIN_PYTHON),
        "hint": None
        if ok
        else "Upgrade Python to {0}.{1} or newer before running this skill.".format(*MIN_PYTHON),
    }


def check_pillow():
    try:
        import PIL

        version = getattr(PIL, "__version__", "unknown")
        try:
            major = int(str(version).split(".")[0])
        except (ValueError, IndexError):
            major = 0
        ok = major >= 10
        return {
            "check": "Pillow",
            "ok": ok,
            "detail": version,
            "required": ">=10",
            "hint": None
            if ok
            else "Run: pip install -r \"${CODEBUDDY_SKILL_DIR}/requirements.txt\"",
        }
    except ImportError:
        return {
            "check": "Pillow",
            "ok": False,
            "detail": "not installed",
            "required": ">=10",
            "hint": "Run: pip install -r \"${CODEBUDDY_SKILL_DIR}/requirements.txt\"",
        }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()

    checks = [check_python(), check_pillow()]
    ok = all(c["ok"] for c in checks)
    result = {
        "status": "ready" if ok else "missing_dependencies",
        "platform": platform.platform(),
        "executable": sys.executable,
        "checks": checks,
    }

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("environment: {}".format("ready" if ok else "NOT ready"))
        print("platform   : {}".format(result["platform"]))
        print("interpreter: {}".format(sys.executable))
        for c in checks:
            mark = "OK  " if c["ok"] else "FAIL"
            print("  [{}] {:<8} {:<16} needs {}".format(mark, c["check"], c["detail"], c["required"]))
        if not ok:
            print("\nto fix:")
            for c in checks:
                if not c["ok"] and c["hint"]:
                    print("  - {}: {}".format(c["check"], c["hint"]))
            print("\nNote: on macOS/Linux use python3 in place of python.")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
