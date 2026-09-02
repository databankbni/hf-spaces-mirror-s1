"""
MOK native autonomous real-media production decision authority.

The public surface supplies intent and assets only.
MOK derives the executable production request autonomously.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple
from uuid import uuid4


class MOKNativeProductionDecision:
    """Derive authoritative real-media production requests from MOK intent."""

    authority = "MOK_NATIVE_PRODUCTION_DECISION"

    IMAGE_EXTENSIONS = {
        ".jpg",
        ".jpeg",
        ".png",
        ".webp",
        ".bmp",
    }

    VIDEO_EXTENSIONS = {
        ".mp4",
        ".mov",
        ".m4v",
        ".avi",
        ".mkv",
        ".webm",
    }

    AUDIO_EXTENSIONS = {
        ".mp3",
        ".wav",
        ".m4a",
        ".aac",
        ".flac",
        ".ogg",
    }

    def __init__(self, project_root: Optional[Path] = None) -> None:
        if project_root is None:
            project_root = Path(__file__).resolve().parents[6]

        self.project_root = Path(project_root).resolve()

    @staticmethod
    def _normalize_intent(execution_context: Mapping[str, Any]) -> str:
        for key in ("public_request", "request", "intent", "goal"):
            value = execution_context.get(key)

            if isinstance(value, str) and value.strip():
                return value.strip()

        decision_context = execution_context.get("decision_context")

        if isinstance(decision_context, Mapping):
            for key in ("public_request", "request", "intent", "goal"):
                value = decision_context.get(key)

                if isinstance(value, str) and value.strip():
                    return value.strip()

        return ""

    @staticmethod
    def _normalize_assets(
        execution_context: Mapping[str, Any],
    ) -> Tuple[str, ...]:
        raw_assets = execution_context.get("assets")

        if raw_assets is None:
            return tuple()

        if isinstance(raw_assets, (str, Path)):
            raw_assets = [raw_assets]

        if not isinstance(raw_assets, Sequence):
            return tuple()

        normalized = []
        seen = set()

        for item in raw_assets:
            if item is None:
                continue

            try:
                path = Path(str(item)).expanduser().resolve()
            except Exception:
                continue

            if not path.is_file():
                continue

            key = str(path).lower()

            if key in seen:
                continue

            seen.add(key)
            normalized.append(str(path))

        return tuple(normalized)

    def _output_path(self) -> Path:
        output_root = self.project_root / "output" / "mok_native_production"
        output_root.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")

        return output_root / (
            f"mok_autonomous_cinematic_{timestamp}_{uuid4().hex[:8]}.mp4"
        )

    @staticmethod
    def _supports_video_production(intent: str) -> bool:
        if not isinstance(intent, str) or not intent.strip():
            return False

        normalized = intent.lower()

        production_terms = (
            "video",
            "film",
            "movie",
            "cinematic",
            "story",
            "advertisement",
            "advert",
            "commercial",
            "wedding",
            "travel",
            "brand",
            "social media",
            "reel",
            "render",
        )

        return any(term in normalized for term in production_terms)

    def _classify_assets(
        self,
        assets: Sequence[str],
    ) -> Dict[str, list]:
        classified = {
            "images": [],
            "videos": [],
            "audio": [],
            "other": [],
        }

        for asset in assets:
            suffix = Path(asset).suffix.lower()

            if suffix in self.IMAGE_EXTENSIONS:
                classified["images"].append(asset)
            elif suffix in self.VIDEO_EXTENSIONS:
                classified["videos"].append(asset)
            elif suffix in self.AUDIO_EXTENSIONS:
                classified["audio"].append(asset)
            else:
                classified["other"].append(asset)

        return classified

    @staticmethod
    def _video_filter() -> str:
        return (
            "scale=1280:720:force_original_aspect_ratio=decrease,"
            "pad=1280:720:(ow-iw)/2:(oh-ih)/2,"
            "setsar=1,format=yuv420p"
        )

    @staticmethod
    def _native_motion_profiles() -> Tuple[Tuple[str, str], ...]:
        """Return MOK-owned native cinematic still-image motion profiles."""
        return (
            (
                "ZOOM_IN",
                "zoompan=z='min(zoom+0.0018,1.16)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=36:s=1280x720:fps=24",
            ),
            (
                "ZOOM_OUT",
                "zoompan=z='if(eq(on,1),1.16,max(1.0,zoom-0.0018))':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=36:s=1280x720:fps=24",
            ),
            (
                "PAN_LEFT_TO_RIGHT",
                "zoompan=z='1.14':x='(iw-iw/zoom)*on/35':y='ih/2-(ih/zoom/2)':d=36:s=1280x720:fps=24",
            ),
            (
                "PAN_RIGHT_TO_LEFT",
                "zoompan=z='1.14':x='(iw-iw/zoom)*(1-on/35)':y='ih/2-(ih/zoom/2)':d=36:s=1280x720:fps=24",
            ),
            (
                "PAN_TOP_TO_BOTTOM",
                "zoompan=z='1.14':x='iw/2-(iw/zoom/2)':y='(ih-ih/zoom)*on/35':d=36:s=1280x720:fps=24",
            ),
            (
                "PAN_BOTTOM_TO_TOP",
                "zoompan=z='1.14':x='iw/2-(iw/zoom/2)':y='(ih-ih/zoom)*(1-on/35)':d=36:s=1280x720:fps=24",
            ),
            (
                "DIAGONAL_DOWN_RIGHT",
                "zoompan=z='1.15':x='(iw-iw/zoom)*on/35':y='(ih-ih/zoom)*on/35':d=36:s=1280x720:fps=24",
            ),
            (
                "DIAGONAL_UP_LEFT",
                "zoompan=z='1.15':x='(iw-iw/zoom)*(1-on/35)':y='(ih-ih/zoom)*(1-on/35)':d=36:s=1280x720:fps=24",
            ),
            (
                "ORBIT_CLOCKWISE",
                "zoompan=z='1.16':x='(iw-iw/zoom)/2+((iw-iw/zoom)/2)*0.65*sin(2*PI*on/36)':y='(ih-ih/zoom)/2+((ih-ih/zoom)/2)*0.65*cos(2*PI*on/36)':d=36:s=1280x720:fps=24",
            ),
            (
                "ORBIT_COUNTERCLOCKWISE",
                "zoompan=z='1.16':x='(iw-iw/zoom)/2+((iw-iw/zoom)/2)*0.65*cos(2*PI*on/36)':y='(ih-ih/zoom)/2+((ih-ih/zoom)/2)*0.65*sin(2*PI*on/36)':d=36:s=1280x720:fps=24",
            ),
        )

    def _image_production_arguments(
        self,
        images: Sequence[str],
        audio: Sequence[str],
        output_path: Path,
    ) -> list:
        selected = list(images[:20])

        if not selected:
            raise ValueError("No image assets available for image production.")

        arguments = ["-y"]

        # One still frame enters zoompan; motion duration is owned by zoompan.
        for image in selected:
            arguments.extend([
                "-i",
                image,
            ])

        motion_profiles = self._native_motion_profiles()
        filter_parts = []

        for index in range(len(selected)):
            motion_name, motion_filter = motion_profiles[
                index % len(motion_profiles)
            ]

            # Normalize each still to a slightly oversized canvas.
            # The oversized source provides room for panning and orbit.
            filter_parts.append(
                f"[{index}:v]"
                "scale=1408:792:force_original_aspect_ratio=increase,"
                "crop=1408:792,"
                "setsar=1,"
                f"{motion_filter},"
                "format=yuv420p"
                f"[v{index}]"
            )

        concat_inputs = "".join(
            f"[v{index}]"
            for index in range(len(selected))
        )

        filter_parts.append(
            f"{concat_inputs}"
            f"concat=n={len(selected)}:v=1:a=0[vout]"
        )

        arguments.extend([
            "-filter_complex",
            ";".join(filter_parts),
            "-map",
            "[vout]",
        ])

        if audio:
            audio_index = len(selected)

            arguments.extend([
                "-stream_loop",
                "-1",
                "-i",
                audio[0],
                "-map",
                f"{audio_index}:a:0",
                "-shortest",
                "-c:a",
                "aac",
                "-b:a",
                "160k",
            ])

        arguments.extend([
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "22",
            "-pix_fmt",
            "yuv420p",
            "-r",
            "24",
            "-movflags",
            "+faststart",
            str(output_path),
        ])

        return arguments

    def _video_production_arguments(
        self,
        video: str,
        output_path: Path,
    ) -> list:
        return [
            "-y",
            "-i",
            video,
            "-vf",
            self._video_filter(),
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            "-movflags",
            "+faststart",
            str(output_path),
        ]

    def decide(
        self,
        execution_context: Mapping[str, Any],
    ) -> Dict[str, Any]:
        if not isinstance(execution_context, Mapping):
            raise TypeError("execution_context must be a mapping")

        intent = self._normalize_intent(execution_context)
        assets = self._normalize_assets(execution_context)

        if not intent:
            return {
                "authority": self.authority,
                "authorized": False,
                "status": "INTENT_REQUIRED",
                "reason": "No autonomous production intent supplied.",
                "production_request": None,
            }

        if not self._supports_video_production(intent):
            return {
                "authority": self.authority,
                "authorized": False,
                "status": "UNSUPPORTED_PRODUCTION_INTENT",
                "reason": "Intent is outside native video production capability.",
                "intent": intent,
                "production_request": None,
            }

        classified = self._classify_assets(assets)
        images = classified["images"]
        videos = classified["videos"]
        audio = classified["audio"]

        if not images and not videos:
            return {
                "authority": self.authority,
                "authorized": False,
                "status": "REAL_MEDIA_REQUIRED",
                "reason": (
                    "MOK requires at least one real image or video asset "
                    "for this production."
                ),
                "intent": intent,
                "assets": list(assets),
                "production_request": None,
            }

        output_path = self._output_path()

        if videos:
            strategy = "NATIVE_VIDEO_MASTER"
            arguments = self._video_production_arguments(
                videos[0],
                output_path,
            )
        else:
            strategy = "NATIVE_IMAGE_CINEMATIC"
            arguments = self._image_production_arguments(
                images,
                audio,
                output_path,
            )

        production_request = {
            "request_type": "MOK_NATIVE_AUTONOMOUS_VIDEO_PRODUCTION",
            "intent": intent,
            "input_files": list(assets),
            "output_path": str(output_path),
            "expected_artifacts": [str(output_path)],
            "executable": "ffmpeg",
            "arguments": arguments,
            "decision_authority": self.authority,
            "operation_class": "NATIVE_REAL_MEDIA_CINEMATIC_PRODUCTION",
            "production_source": "MOK_NATIVE_DECISION",
            "production_strategy": strategy,
            "image_count": len(images),
            "video_count": len(videos),
            "audio_count": len(audio),
            "execution_evidence_required": True,
        }

        return {
            "authority": self.authority,
            "authorized": True,
            "status": "REAL_MEDIA_PRODUCTION_DERIVED",
            "intent": intent,
            "strategy": strategy,
            "production_request": production_request,
        }
