"""Check the pinned runtime dependencies without importing GUI or capture modules."""
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
import sys


def main():
    missing = []
    requirements = Path(__file__).resolve().parents[1] / "requirements.txt"
    for line in requirements.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, expected = line.split("==", 1)
        try:
            installed = version(name)
        except PackageNotFoundError:
            installed = "missing"
        if installed != expected:
            missing.append(f"{name}: {installed}; required {expected}")
    if missing:
        print("\n".join(missing))
        return 1
    print("All pinned dependencies are installed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
