'''python
"""Utilities to ensure the Ollama Docker container is running.
Uses the local Docker CLI – assumes Docker is installed and the user has permission.
"""
import subprocess
import time
import os
from typing import Optional

DEFAULT_COMPOSE_FILE = os.path.join(os.path.dirname(__file__), "..", "docker-compose.yml")

def _run_cmd(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, check=False)

def is_container_running(name: str = "ollama") -> bool:
    result = _run_cmd(["docker", "ps", "--filter", f"name={name}", "--format", "{{.Names}}"])
    if result.returncode != 0:
        return False
    return name in result.stdout.splitlines()

def start_container(compose_file: Optional[str] = None) -> None:
    compose_file = compose_file or DEFAULT_COMPOSE_FILE
    if not os.path.exists(compose_file):
        raise FileNotFoundError(f"Compose file not found: {compose_file}")
    _run_cmd(["docker-compose", "-f", compose_file, "up", "-d", "ollama"])
    # wait a few seconds for Ollama to be ready
    for _ in range(10):
        if is_container_running("ollama"):
            break
        time.sleep(1)
    else:
        raise RuntimeError("Ollama container failed to start")

def stop_container(compose_file: Optional[str] = None) -> None:
    compose_file = compose_file or DEFAULT_COMPOSE_FILE
    _run_cmd(["docker-compose", "-f", compose_file, "down", "ollama"])

def ensure_running() -> None:
    """Public helper – start the container if it is not already running."""
    if not is_container_running("ollama"):
        start_container()

if __name__ == "__main__":
    ensure_running()
    print("Ollama container is up and running.")
'''
