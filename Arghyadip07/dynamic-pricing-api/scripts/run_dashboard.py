import subprocess
import sys

from src.core.settings import settings


if __name__ == "__main__":
    subprocess.run(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            "apps/dashboard/streamlit_app.py",
            "--server.port",
            str(settings.dashboard_port),
            "--server.headless",
            str(settings.dashboard_headless).lower(),
        ],
        check=True,
    )
