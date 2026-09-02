import asyncio

from routes import crawl


def test_get_video_progress_route_returns_progress_payload():
    crawl.VIDEO_PROGRESS["job-1"] = {
        "step": "generate_audio",
        "message": "Đang tạo audio",
        "detail": "voice=vi-VN-NamMinhNeural",
    }

    response = asyncio.run(crawl.get_video_progress_route("job-1"))

    assert response["success"] is True
    assert response["data"]["step"] == "generate_audio"
    assert response["data"]["message"] == "Đang tạo audio"


def test_get_video_progress_route_returns_idle_when_missing():
    crawl.VIDEO_PROGRESS.pop("missing-job", None)

    response = asyncio.run(crawl.get_video_progress_route("missing-job"))

    assert response["success"] is True
    assert response["data"]["step"] == "idle"
