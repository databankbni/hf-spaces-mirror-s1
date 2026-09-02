from langchain_core.tools import tool
import os
import subprocess
import threading
from collections import deque
import datetime
import signal
import uuid
import base64
import mimetypes
from pathlib import Path
from typing import TypedDict, Literal
from pydantic import BaseModel, Field, model_validator
from langchain.tools import ToolRuntime
from langchain.messages import ToolMessage, HumanMessage
from langgraph.types import Command
from langchain_community.tools import DuckDuckGoSearchResults, ReadFileTool, WriteFileTool

WORKSPACE = os.environ.get("AGENT_WORKSPACE", "/workspace")
MAX_TAIL_BYTES = 15_000     # max number of bytes pass to LLM
MAX_FILE_BYTES = 50 * 1024 * 1024   # max file size of file saves output
CHUNK_SIZE = 8192           # avoid massive single line

class PlanStep(BaseModel):
    step: str = Field(description="Short imperative description of the step")
    status: Literal["pending", "in_progress", "completed"] = Field(
        default="pending",
        description="pending: not started; in_progress: currently active; completed: finished"
    )

class UpdatePlanInput(BaseModel):
    plan: list[PlanStep] = Field(
        description="Complete ordered checklist; replaces any previous plan entirely."
    )

    @model_validator(mode="after")
    def only_one_active(self):
        active = [s for s in self.plan if s.status == "in_progress"]
        if len(active) > 1:
            raise ValueError(
                "At most one step may be in_progress: "
                + ", ".join(s.step for s in active)
            )
        return self

def generate_timestamp_filename(prefix="output", ext="txt"):
    now_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    pid = os.getpid()
    return f"{prefix}_{now_str}_p{pid}_{uuid.uuid4().hex[:8]}.{ext}"

def _drain(pipe, out_path, cap, state):
    '''stream read from pipe in chunks'''
    buf = bytearray()       # output buffer in memory
    tail_chunks = deque()   # shown output
    tail_bytes = 0          # size of shown output
    f = None
    total = 0
    state.update({"truncated": False, "save_failed": False,
                  "tail": "", "total": 0, "capped": False})

    while True:
        chunk = pipe.read(CHUNK_SIZE)
        if not chunk:
            break
        total += len(chunk)
        if not state["truncated"]:
            buf += chunk
            if len(buf) <= MAX_TAIL_BYTES:
                continue

            state["truncated"] = True
            tail_chunks.append(buf[-MAX_TAIL_BYTES:])
            tail_bytes = len(tail_chunks[-1])
            try:
                f = open(out_path, "wb")
                f.write(buf)
            except Exception as e:
                f = None
                state["save_failed"] = True
                state["save_error"] = str(e)
            buf = None
        else:
            if f is not None:
                try:
                    if total <= cap:
                        f.write(chunk)
                except Exception as e:
                    f = None
                    state["save_failed"] = True
                    state["save_error"] = str(e)
        
            tail_chunks.append(chunk)
            tail_bytes += len(chunk)
            while tail_bytes > MAX_TAIL_BYTES:
                old = tail_chunks.popleft()
                tail_bytes -= len(old)

    if f is not None:
        try:
            f.close()
        except Exception:
            pass

    try:
        pipe.close()
    except Exception:
        pass

    if not state["truncated"]:
        state["tail"] = buf.decode("utf-8", errors="replace")
    else:
        state["tail"] = b"".join(tail_chunks).decode("utf-8", errors="replace")
    state["total"] = total
    state["capped"] = total > cap

@tool
def bashtool(command: str, timeouts: int = 60, workdir: str = WORKSPACE) -> str:
    '''Run a bash command and return its stdout/stderr.
    Each call runs in a fresh bash process: no state(cwd, variables, functions) persists between calls — pass `workdir` instead of using `cd`.
    Non-zero exits are reported as `[exit code: N]`.
    Long output is truncated to its tail; the full output is saved to file whose path is reported when available.

    Args:
        command: The bash command to run (e.g. `ls -la /workspace`)
        timeouts: Timeout in seconds. The executor applies its configured default and cap, and kills the command on expiry.
        workdir: Working directory for this command. Defaults to the session workspace. Always use absolute paths.
    '''
    try:
        command = command.strip()
        # basic filter
        if command.startswith("cd ") and "&&" not in command and ";" not in command:
            return "[bash] bare `cd` has no effect between calls. Use absolute paths or `cd DIR && cmd`."

        # get path of the file that will save full output
        out_dir = os.path.join(WORKSPACE, ".output")
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, generate_timestamp_filename(prefix="bash"))

        os.makedirs(workdir, exist_ok=True)
        # create a bash process (group)
        proc = subprocess.Popen(
            command, shell=True, executable="/bin/bash",
            cwd=workdir, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            start_new_session=True
        )

        # create a thread to read from bash stdout/stderr
        state = {}
        reader_thread = threading.Thread(
            target=_drain,
            args=(proc.stdout, out_path, MAX_FILE_BYTES, state),
            daemon=True
        )
        reader_thread.start()

        timed_out = False

        try:
            returncode = proc.wait(timeout=timeouts)
        except subprocess.TimeoutExpired:
            timed_out = True
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except Exception:
                proc.kill()

            returncode = proc.wait()

        reader_thread.join(10.0)

        notes = []

        if reader_thread.is_alive():
            notes.append("WARNING: output may be incomplete (pipe not fully drained)")

        tail = state.get("tail", "")
        total = state.get("total", 0)
        saved = min(total, MAX_FILE_BYTES)
        truncated = state.get("truncated", False)

        shown = tail.strip() or "(no output)"

        if timed_out:
            notes.append(f"time out after {timeouts}s, process killed")
        notes.append(f"exit code: {returncode}")

        if truncated:
            if state.get("save_failed"):
                notes.append(f"TRUNCATED: only last {len(tail)} chars shown;"
                            f"saving full output FAILED ({state.get('save_error', 'unknown')})")
            else:
                notes.append(f"TRUNCATED: showing last {len(tail)} chars of {saved} bytes")
                notes.append(f"full output: {out_path}")

                if state.get("capped"):
                    notes.append(f"output file capped at {MAX_FILE_BYTES} bytes, earlier output discarded")

        return f"{shown}\n\n[" + "; ".join(notes) + "]"
    except Exception as e:
        return f"[bash] failed while executing. Error: {str(e)}"

def _sniff_image_mime(path: str) -> str | None:
    """Detect image MIME from magic bytes"""

    with open(path, "rb") as f:
        header = f.read(12)

    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if header.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if header.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if header.startswith(b"RIFF") and header[8:12] == b"WEBP":
        return "image/webp"
    if header.startswith(b"BM"):
        return "image/bmp"

    ext_mime = mimetypes.guess_type(path)[0] or ""
    return ext_mime if ext_mime.startswith("image/") else None

@tool
def attachImage(file: str, runtime: ToolRuntime) -> Command:
    """View an image so its contents appear directly in your context.
    Use this whenever you need to perceive a media file rather than process it programmatically.
    
    Args:
        file: absolute path of the image
    """

    # check file existence
    if not os.path.isfile(file):
        return Command(update={
            "messages": [ToolMessage(
                f"Could not load {file}: file does not exist.",
                tool_call_id=runtime.tool_call_id
            )]
        })

    # check file size
    size = os.path.getsize(file)
    if size > 50 * 1024 * 1024:
        return Command(update={
            "messages": [ToolMessage(
                f"Could not load {file}: only file with size less than 50MB can be injected into the context.",
                tool_call_id=runtime.tool_call_id
            )]
        })

    # check file type
    mime = _sniff_image_mime(file)
    if mime is None:
        return Command(update={
            "messages": [ToolMessage(
                f"Could not load {file}: not a recognized image format "
                f"(checked magic bytes and file extension)",
                tool_call_id=runtime.tool_call_id
            )]
        })
    data = base64.b64encode(Path(file).read_bytes()).decode()

    if mime.startswith("image/"):
        block = {"type": "image_url",
                 "image_url": {"url": f"data:{mime};base64,{data}"}}
    else:
        return Command(update={
            "messages": [ToolMessage(
                f"Could not load {file}: not an image",
                tool_call_id=runtime.tool_call_id
            )]
        })

    return Command(update={
        "messages": [
            ToolMessage(
                f"{file} ({size} bytes) attached in the following message.",
                tool_call_id=runtime.tool_call_id
            ),
            HumanMessage(content=[
                {"type": "text", "text": f"[attached by attachImage: {file}]"},
                block
            ])
        ]
    })

def _sniff_video_mime(path: str) -> str | None:
    """Detect video MIME from magic bytes"""

    with open(path, "rb") as f:
        header = f.read(12)

    if header[4:8] == b"ftyp":
        brand = header[8:12]
        if brand.startswith((b"qt", b"moov")):
            return "video/quicktime"
        return "video/mp4"
    if header.startswith(b"\x1a\x45\xdf\xa3"):
        ext = Path(path).suffix.lower()
        return "video/webm" if ext == ".webm" else "video/x-matroska"
    if header.startswith(b"0&\xb2u\x8e\xcf\x11\xa5"):
        return "video/x-ms-wmv"
    if header.startswith(b"RIFF") and header[8:12] == b"AVI":
        return "video/x-msvideo"

    ext_mime = mimetypes.guess_type(path)[0] or ""
    return ext_mime if ext_mime.startswith("video/") else None

@tool
def attachVideo(file: str, runtime: ToolRuntime) -> Command:
    """View a video so its contents appear directly in your context.
    Use this whenever you need to perceive a media file rather than process it programmatically.
    
    Args:
        file: absolute path of the video
    """

    # check file existence
    if not os.path.isfile(file):
        return Command(update={
            "messages": [ToolMessage(
                f"Could not load {file}: file does not exist.",
                tool_call_id=runtime.tool_call_id
            )]
        })

    # check file size
    size = os.path.getsize(file)
    if size > 50 * 1024 * 1024:
        return Command(update={
            "messages": [ToolMessage(
                f"Could not load {file}: only file with size less than 50MB can be injected into the context.",
                tool_call_id=runtime.tool_call_id
            )]
        })

    # check file type
    mime = _sniff_video_mime(file)
    if mime is None:
        return Command(update={
            "messages": [ToolMessage(
                f"Could not load {file}: not a recognized image format "
                f"(checked magic bytes and file extension)",
                tool_call_id=runtime.tool_call_id
            )]
        })
    data = base64.b64encode(Path(file).read_bytes()).decode()

    if mime.startswith("video/"):
        block = {"type": "video_url",
                 "video_url": {"url": f"data:{mime};base64,{data}"},
                 "fps": 2}  # maybe add an argument to modify fps
    else:
        return Command(update={
            "messages": [ToolMessage(
                f"Could not load {file}: not an image",
                tool_call_id=runtime.tool_call_id
            )]
        })

    return Command(update={
        "messages": [
            ToolMessage(
                f"{file} ({size} bytes) attached in the following message.",
                tool_call_id=runtime.tool_call_id
            ),
            HumanMessage(content=[
                {"type": "text", "text": f"[attached by attachVideo: {file}]"},
                block
            ])
        ]
    })

def _sniff_audio_mime(path: str) -> str | None:
    """Detect audio MIME from magic bytes"""

    with open(path, "rb") as f:
        header = f.read(12)

    # MP3: ID3v2 tag or MPEG frame sync (0xFFEx)
    if header.startswith(b"ID3"):
        return "audio/mpeg"
    if header[0] == 0xFF and (header[1] & 0xE0) == 0xE0:
        return "audio/mpeg"
    # WAV/FLAC/OGG
    if header.startswith(b"RIFF") and header[8:12] == b"WAVE":
        return "audio/wav"
    if header.startswith(b"fLaC"):
        return "audio/flac"
    if header.startswith(b"OggS"):
        return "audio/ogg"
    # M4A: ISO base media with ftyp brand M4A
    if header[4:8] == b"ftyp" and header[8:10] == b"M4":
        return "audio/mp4"

    ext_mime = mimetypes.guess_type(path)[0] or ""
    return ext_mime if ext_mime.startswith("audio/") else None

@tool
def attachAudio(file: str, runtime: ToolRuntime) -> Command:
    """Listen to an audio file so its contents appear directly in your context.
    Use this whenever you need to perceive a media file rather than process it programmatically.

    Args:
        file: absolute path of the audio file
    """

    # check file existence
    if not os.path.isfile(file):
        return Command(update={
            "messages": [ToolMessage(
                f"Could not load {file}: file does not exist.",
                tool_call_id=runtime.tool_call_id
            )]
        })

    # check file size
    size = os.path.getsize(file)
    if size > 50 * 1024 * 1024:
        return Command(update={
            "messages": [ToolMessage(
                f"Could not load {file}: only file with size less than 50MB can be injected into the context.",
                tool_call_id=runtime.tool_call_id
            )]
        })

    # check file type
    mime = _sniff_audio_mime(file)
    if mime is None:
        return Command(update={
            "messages": [ToolMessage(
                f"Could not load {file}: not a recognized audio format "
                f"(checked magic bytes and file extension)",
                tool_call_id=runtime.tool_call_id
            )]
        })
    data = base64.b64encode(Path(file).read_bytes()).decode()

    if mime.startswith("audio/"):
        block = {"type": "input_audio",
                 "input_audio": {
                     "data": f"data:{mime};base64,{data}"
                 }}
    else:
        return Command(update={
            "messages": [ToolMessage(
                f"Could not load {file}: not an audio",
                tool_call_id=runtime.tool_call_id
            )]
        })

    return Command(update={
        "messages": [
            ToolMessage(
                f"{file} ({size} bytes) attached in the following message.",
                tool_call_id=runtime.tool_call_id
            ),
            HumanMessage(content=[
                {"type": "text", "text": f"[attached by attachAudio: {file}]"},
                block
            ])
        ]
    })

@tool("updatePlan", args_schema=UpdatePlanInput)
def updatePlan(plan: list[PlanStep], runtime: ToolRuntime) -> Command:
    """Replace the current task with an updated ordered checklist.

    Args:
        plan: the new plan.
    """
    return Command(update={
        "messages": [
            ToolMessage(
                f"Plan updated ({len(plan)} steps).",
                tool_call_id=runtime.tool_call_id
            )
        ],
        "plan": plan
    })

websearch = DuckDuckGoSearchResults()
readfile = ReadFileTool()
writefile = WriteFileTool()
