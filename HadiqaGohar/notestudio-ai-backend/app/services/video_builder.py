import os
import uuid
import subprocess
import tempfile
from moviepy.editor import (
    ImageClip,
    AudioFileClip,
    CompositeVideoClip,
    concatenate_videoclips,
)
from PIL import Image

VIDEOS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "output")
os.makedirs(VIDEOS_DIR, exist_ok=True)


def _get_audio_duration(audio_path: str) -> float:
    """Get duration of an audio file using ffprobe."""
    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        audio_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return float(result.stdout.strip())


def _resize_image(image_path: str, target_width: int = 1920, target_height: int = 1080) -> str:
    """Resize and pad image to target dimensions, returning path to resized image."""
    img = Image.open(image_path)
    
    img_ratio = img.width / img.height
    target_ratio = target_width / target_height
    
    if img_ratio > target_ratio:
        new_width = target_width
        new_height = int(target_width / img_ratio)
    else:
        new_height = target_height
        new_width = int(target_height * img_ratio)
    
    img = img.resize((new_width, new_height), Image.LANCZOS)
    
    new_img = Image.new("RGB", (target_width, target_height), (0, 0, 0))
    offset = ((target_width - new_width) // 2, (target_height - new_height) // 2)
    new_img.paste(img, offset)
    
    resized_path = tempfile.mktemp(suffix=".png")
    new_img.save(resized_path, "PNG")
    return resized_path


def build_video(image_paths: list[str], audio_path: str, output_filename: str | None = None) -> str:
    """Combine images with audio into a slideshow-style mp4 video.
    
    Args:
        image_paths: List of image file paths to use as slides
        audio_path: Path to the audio file
        output_filename: Optional custom filename for output. If None, generates a UUID-based name.
    
    Returns:
        Path to the generated video file
    """
    if not output_filename:
        output_filename = f"{uuid.uuid4().hex}.mp4"
    
    output_path = os.path.join(VIDEOS_DIR, output_filename)
    
    audio_duration = _get_audio_duration(audio_path)
    
    num_images = len(image_paths)
    duration_per_image = audio_duration / num_images
    
    crossfade_duration = min(0.5, duration_per_image * 0.1)
    
    video_clips = []
    resized_paths = []
    
    for img_path in image_paths:
        resized_path = _resize_image(img_path)
        resized_paths.append(resized_path)
        
        clip = ImageClip(resized_path).set_duration(duration_per_image)
        video_clips.append(clip)
    
    if num_images > 1 and crossfade_duration > 0:
        for i, clip in enumerate(video_clips):
            if i > 0:
                clip = clip.crossfadein(crossfade_duration)
            video_clips[i] = clip
        
        final_video = concatenate_videoclips(video_clips, method="compose", padding=-crossfade_duration)
    else:
        final_video = concatenate_videoclips(video_clips, method="compose")
    
    audio_clip = AudioFileClip(audio_path)
    final_video = final_video.set_audio(audio_clip)
    
    final_video.write_videofile(
        output_path,
        fps=24,
        codec="libx264",
        audio_codec="aac",
        threads=4,
        logger=None,
    )
    
    final_video.close()
    audio_clip.close()
    
    for clip in video_clips:
        clip.close()
    
    for path in resized_paths:
        if os.path.exists(path):
            os.remove(path)
    
    return output_path
