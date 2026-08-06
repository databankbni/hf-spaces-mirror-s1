"""Space entrypoint: run the viz server over the bucket mounted at /data."""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import viz  # noqa: E402  (copied in by sync.py --space)

viz.serve(Path(os.environ.get("RUNS_ROOT", "/data/runs")),
          int(os.environ.get("PORT", "7860")), open_browser=False)
