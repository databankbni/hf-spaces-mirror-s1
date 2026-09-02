from pathlib import Path

from routes import crawl as crawl_routes


def test_cleanup_generated_video_files_removes_job_assets(tmp_path):
    base_dir = tmp_path / "static"
    (base_dir / "videos" / "audio").mkdir(parents=True, exist_ok=True)
    (base_dir / "videos" / "inputs").mkdir(parents=True, exist_ok=True)
    (base_dir / "videos").mkdir(parents=True, exist_ok=True)

    (base_dir / "videos" / "audio" / "job1_abc.mp3").write_text("audio")
    (base_dir / "videos" / "job1_def.mp4").write_text("video")
    (base_dir / "videos" / "inputs" / "job1_cover.jpg").write_text("image")
    (base_dir / "videos" / "audio" / "other.mp3").write_text("keep")

    crawl_routes._cleanup_generated_video_files("job1", base_dir)

    assert not (base_dir / "videos" / "audio" / "job1_abc.mp3").exists()
    assert not (base_dir / "videos" / "job1_def.mp4").exists()
    assert not (base_dir / "videos" / "inputs" / "job1_cover.jpg").exists()
    assert (base_dir / "videos" / "audio" / "other.mp3").exists()


def test_cleanup_uploaded_assets_only_runs_for_supabase_url(tmp_path):
    base_dir = tmp_path / "static"
    (base_dir / "videos").mkdir(parents=True)
    asset_path = base_dir / "videos" / "job2_output.mp4"
    asset_path.write_text("video")

    cleaned = crawl_routes._cleanup_uploaded_assets(
        "job2",
        "https://example.supabase.co/storage/v1/object/public/videos/job2_output.mp4",
        "http://localhost/static/videos/job2_output.mp4",
        base_dir,
    )

    assert cleaned is True
    assert not asset_path.exists()
