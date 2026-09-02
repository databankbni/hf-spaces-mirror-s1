from pathlib import Path

import requests


def download_remote_video(video_url: str, destination_path: str) -> str:
    destination = Path(destination_path)
    destination.parent.mkdir(parents=True, exist_ok=True)

    with requests.get(video_url, stream=True, timeout=120) as response:
        response.raise_for_status()
        with destination.open("wb") as output_file:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    output_file.write(chunk)

    return str(destination.resolve())
