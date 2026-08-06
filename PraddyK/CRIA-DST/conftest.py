import os
import sys

# Ensure the repository root is importable so tests can `import app`, `utils`, `modules`
# regardless of how pytest is invoked (bare `pytest` vs `python -m pytest`).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
