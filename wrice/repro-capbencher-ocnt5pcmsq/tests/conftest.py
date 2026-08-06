import sys
sys.dont_write_bytecode = True
from pathlib import Path

cap_dir = Path(__file__).parent.parent
if str(cap_dir) not in sys.path:
    sys.path.insert(0, str(cap_dir))
