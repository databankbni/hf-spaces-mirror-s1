import importlib
import sys
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    checks = []
    checks.append(("Python >= 3.10", sys.version_info >= (3, 10)))
    checks.append(("app.py exists", (root / "app.py").exists()))
    checks.append(("README.md exists", (root / "README.md").exists()))
    checks.append(("sample data exists", (root / "public_demo" / "sample_data.py").exists()))
    for name in ("gradio",):
        try:
            importlib.import_module(name)
            ok = True
        except Exception:
            ok = False
        checks.append((f"dependency: {name}", ok))
    for label, ok in checks:
        print(f"[{'PASS' if ok else 'FAIL'}] {label}")
    if not all(ok for _, ok in checks):
        raise SystemExit(1)
    print("\nPRE-FLIGHT PASSED")


if __name__ == "__main__":
    main()
