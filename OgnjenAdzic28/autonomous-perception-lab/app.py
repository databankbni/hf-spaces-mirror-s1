from __future__ import annotations

import json
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Any

import gradio as gr

ASSET_DIR = Path(__file__).parent / "assets"
DEMO_VIDEO = ASSET_DIR / "demo.mp4"
DEMO_GIF = ASSET_DIR / "demo.gif"
THUMBNAIL = ASSET_DIR / "thumbnail.png"
OVERLAY_FRAME = ASSET_DIR / "overlay_frame0.png"
METRICS = ASSET_DIR / "metrics.json"
ANALYSIS = ASSET_DIR / "analysis.md"
DETECTIONS = ASSET_DIR / "detections.jsonl"
TRACKS = ASSET_DIR / "tracks.jsonl"
DEFAULT_MODEL = "yolo11n.pt"
MAX_OUTPUT_SIDE = 960
DEFAULT_MAX_FRAMES = 180
COCO_NAMES = {
    0: "person",
    1: "bicycle",
    2: "car",
    3: "motorcycle",
    5: "bus",
    7: "truck",
}


def _load_metrics() -> dict[str, Any]:
    return json.loads(METRICS.read_text(encoding="utf-8"))


def _load_analysis() -> str:
    return ANALYSIS.read_text(encoding="utf-8")


def _summary_markdown(metrics: dict[str, Any]) -> str:
    detection = metrics["detection"]
    quality = detection["quality_at_iou_0_50"]
    tracking = metrics["tracking"]
    depth = metrics["depth"]
    return f"""
## Autonomous Perception Lab

Perception MVP on a real KITTI driving sequence, combining learned object
detection, sparse LiDAR depth projection, multi-object tracking, BEV
visualization, and replay export.

**Benchmark scene:** KITTI tracking sequence `0000`, frames `000000`-`000011`.

| Metric | Value |
| --- | ---: |
| Evaluated frames | {detection["frame_count"]} |
| YOLO detections | {detection["detection_count"]} |
| Tracks produced | {tracking["track_count"]} |
| Detection precision @ IoU 0.50 | {quality["precision"]:.3f} |
| Detection recall @ IoU 0.50 | {quality["recall"]:.3f} |
| Detection F1 @ IoU 0.50 | {quality["f1"]:.3f} |
| Mean matched IoU | {quality["mean_matched_iou"]:.3f} |
| Sparse-depth pixel coverage | {depth["mean_valid_pixel_ratio"]:.2%} |

The replay below is generated from real KITTI camera frames, official
labels/calibration, projected Velodyne points, a COCO-pretrained Ultralytics
YOLO detector, and a lightweight tracking/BEV visualization stack.
"""


@lru_cache(maxsize=1)
def _load_model() -> Any:
    from ultralytics import YOLO

    return YOLO(DEFAULT_MODEL)


def _resize_for_demo(frame: Any, max_side: int = MAX_OUTPUT_SIDE) -> Any:
    import cv2

    height, width = frame.shape[:2]
    scale = min(1.0, max_side / max(height, width))
    if scale == 1.0:
        return frame
    return cv2.resize(
        frame,
        (int(width * scale), int(height * scale)),
        interpolation=cv2.INTER_AREA,
    )


def _empty_counts() -> dict[str, int]:
    return {label: 0 for label in COCO_NAMES.values()}


def _coerce_video_path(video: str | dict[str, Any] | None) -> str:
    if isinstance(video, str):
        return video
    if isinstance(video, dict):
        nested = video.get("video")
        if isinstance(nested, str):
            return nested
        if isinstance(nested, dict) and isinstance(nested.get("path"), str):
            return nested["path"]
        if isinstance(video.get("path"), str):
            return video["path"]
    raise gr.Error("Upload a video first.")


def process_uploaded_video(
    video_path: str | dict[str, Any] | None,
    confidence: float,
    frame_stride: int,
    max_frames: int,
) -> tuple[str | None, dict[str, Any], str]:
    import cv2

    input_path = _coerce_video_path(video_path)
    frame_stride = max(1, int(frame_stride))
    max_frames = max(1, int(max_frames))
    capture = cv2.VideoCapture(input_path)
    if not capture.isOpened():
        raise gr.Error("Could not read that video file.")

    fps = capture.get(cv2.CAP_PROP_FPS) or 24.0
    output_fps = max(1.0, fps / max(1, frame_stride))
    output_path = str(Path(tempfile.mkdtemp(prefix="apl_upload_")) / "annotated.mp4")
    writer: Any | None = None
    model = _load_model()

    processed_frames = 0
    source_frames_seen = 0
    total_detections = 0
    class_counts = _empty_counts()

    try:
        while processed_frames < max_frames:
            ok, frame = capture.read()
            if not ok:
                break

            if source_frames_seen % frame_stride != 0:
                source_frames_seen += 1
                continue

            frame = _resize_for_demo(frame)
            result = model.predict(frame, conf=confidence, imgsz=640, verbose=False)[0]
            annotated = result.plot()

            if writer is None:
                height, width = annotated.shape[:2]
                fourcc = cv2.VideoWriter_fourcc(*"mp4v")  # type: ignore[attr-defined]
                writer = cv2.VideoWriter(
                    output_path,
                    fourcc,
                    output_fps,
                    (width, height),
                )
                if not writer.isOpened():
                    raise gr.Error("Could not create the annotated output video.")

            writer.write(annotated)
            boxes = result.boxes
            if boxes is not None:
                class_ids = boxes.cls.cpu().numpy().astype(int).tolist()
                for class_id in class_ids:
                    label = COCO_NAMES.get(class_id)
                    if label is not None:
                        class_counts[label] += 1
                        total_detections += 1

            processed_frames += 1
            source_frames_seen += 1
    finally:
        capture.release()
        if writer is not None:
            writer.release()

    if processed_frames == 0:
        raise gr.Error("No frames were processed from that video.")

    summary = {
        "model": DEFAULT_MODEL,
        "confidence": confidence,
        "frame_stride": frame_stride,
        "processed_frames": processed_frames,
        "source_frames_seen": source_frames_seen,
        "total_vehicle_person_detections": total_detections,
        "class_counts": {label: count for label, count in class_counts.items() if count > 0},
        "limits": {
            "max_frames": max_frames,
            "max_output_side_px": MAX_OUTPUT_SIDE,
            "note": "CPU demo path; not calibrated KITTI depth or tracking.",
        },
    }
    note = (
        f"Processed {processed_frames} sampled frames with {total_detections} "
        "person/vehicle detections. Uploaded videos use 2D YOLO annotations only; "
        "the KITTI replay is the calibrated depth/tracking benchmark."
    )
    return output_path, summary, note


def build_app() -> gr.Blocks:
    metrics = _load_metrics()
    with gr.Blocks(title="Autonomous Perception Lab") as demo:
        gr.Markdown(_summary_markdown(metrics))
        with gr.Tab("Demo"):
            gr.Video(
                value=str(DEMO_VIDEO),
                label="Calibrated KITTI replay: YOLO, sparse LiDAR depth, tracking, and BEV",
            )
            gr.Image(value=str(OVERLAY_FRAME), label="Rendered frame preview")
        with gr.Tab("Upload Video"):
            gr.Markdown(
                "Upload a short driving clip to run 2D YOLO annotations on CPU. "
                "This path is for quick visual testing and does not include "
                "calibrated depth, BEV, or tracking."
            )
            upload = gr.Video(label="Short driving clip", sources=["upload"])
            with gr.Row():
                confidence = gr.Slider(
                    minimum=0.1,
                    maximum=0.9,
                    value=0.35,
                    step=0.05,
                    label="Confidence",
                )
                frame_stride = gr.Slider(
                    minimum=1,
                    maximum=5,
                    value=2,
                    step=1,
                    label="Frame stride",
                )
                max_frames = gr.Slider(
                    minimum=30,
                    maximum=300,
                    value=DEFAULT_MAX_FRAMES,
                    step=30,
                    label="Max sampled frames",
                )
            run_button = gr.Button("Run YOLO on uploaded clip", variant="primary")
            upload_note = gr.Markdown()
            upload_output = gr.Video(label="Annotated clip")
            upload_summary = gr.JSON(label="Detection summary JSON")
            run_button.click(
                process_uploaded_video,
                inputs=[upload, confidence, frame_stride, max_frames],
                outputs=[upload_output, upload_summary, upload_note],
            )
        with gr.Tab("Metrics"):
            gr.Markdown(_load_analysis())
            gr.JSON(value=metrics, label="metrics.json")
        with gr.Tab("Artifacts"):
            gr.File(value=str(DETECTIONS), label="detections.jsonl")
            gr.File(value=str(TRACKS), label="tracks.jsonl")
            gr.Image(value=str(THUMBNAIL), label="Thumbnail")
            gr.Image(value=str(DEMO_GIF), label="Short GIF")
    return demo


if __name__ == "__main__":
    build_app().launch()
