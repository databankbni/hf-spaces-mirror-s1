import os
import base64
import logging
from notebooklm import NotebookLMClient

logger = logging.getLogger(__name__)

SESSION_DIR = "/tmp/notebooklm"
SESSION_FILE = os.path.join(SESSION_DIR, "storage_state.json")
_client: NotebookLMClient | None = None


def init_session():
    """Write NBLM_SESSION env var (base64-encoded storage_state.json) to disk."""
    encoded = os.environ.get("NBLM_SESSION", "")
    if not encoded:
        logger.warning("NBLM_SESSION env var not set — NotebookLM integration disabled")
        return False
    os.makedirs(SESSION_DIR, exist_ok=True)
    try:
        data = base64.b64decode(encoded)
        with open(SESSION_FILE, "wb") as f:
            f.write(data)
        logger.info("NotebookLM session loaded from NBLM_SESSION env var")
        return True
    except Exception as e:
        logger.error(f"Failed to decode NBLM_SESSION: {e}")
        return False


def is_available() -> bool:
    return os.path.exists(SESSION_FILE)


async def get_client() -> NotebookLMClient:
    global _client
    if _client is None:
        _client = await NotebookLMClient.from_storage(SESSION_FILE).__aenter__()
    return _client


async def close_client():
    global _client
    if _client is not None:
        await _client.close(drain=False)
        _client = None


async def create_notebook(title: str) -> dict:
    client = await get_client()
    nb = await client.notebooks.create(title)
    return {"id": nb.id, "title": nb.title}


async def list_notebooks() -> list[dict]:
    client = await get_client()
    nbs = await client.notebooks.list()
    return [{"id": nb.id, "title": nb.title} for nb in nbs]


async def delete_notebook(notebook_id: str):
    client = await get_client()
    await client.notebooks.delete(notebook_id)


async def add_text_source(notebook_id: str, title: str, content: str) -> dict:
    client = await get_client()
    src = await client.sources.add_text(notebook_id, title, content, wait=True)
    return {"id": src.id, "title": src.title, "status": src.status}


async def add_url_source(notebook_id: str, url: str) -> dict:
    client = await get_client()
    src = await client.sources.add_url(notebook_id, url, wait=True)
    return {"id": src.id, "title": src.title, "status": src.status}


async def list_sources(notebook_id: str) -> list[dict]:
    client = await get_client()
    sources = await client.sources.list(notebook_id)
    return [{"id": s.id, "title": s.title, "status": s.status} for s in sources]


async def chat(notebook_id: str, question: str) -> dict:
    client = await get_client()
    result = await client.chat.ask(notebook_id, question)
    citations = []
    for ref in (result.citations or []):
        citations.append({"title": ref.title, "url": getattr(ref, "url", None)})
    return {"answer": result.answer, "citations": citations}


async def generate_audio(notebook_id: str, instructions: str = "") -> dict:
    client = await get_client()
    status = await client.artifacts.generate_audio(
        notebook_id, instructions=instructions or None
    )
    status = await client.artifacts.wait_for_completion(notebook_id, status.task_id)

    artifacts = await client.artifacts.list_audio(notebook_id)
    if not artifacts:
        return {"error": "No audio artifact found"}

    artifact = artifacts[-1]
    output_path = os.path.join(SESSION_DIR, f"audio_{notebook_id}.mp3")
    await client.artifacts.download_audio(notebook_id, output_path, artifact.id)
    return {"artifact_id": artifact.id, "file": output_path, "title": artifact.title}


async def generate_video(
    notebook_id: str, instructions: str = "", style: str = "classic"
) -> dict:
    from notebooklm import VideoStyle

    client = await get_client()
    vs = getattr(VideoStyle, style.upper(), VideoStyle.CLASSIC)
    status = await client.artifacts.generate_video(
        notebook_id, instructions=instructions or None, video_style=vs
    )
    status = await client.artifacts.wait_for_completion(notebook_id, status.task_id)

    artifacts = await client.artifacts.list_video(notebook_id)
    if not artifacts:
        return {"error": "No video artifact found"}

    artifact = artifacts[-1]
    output_path = os.path.join(SESSION_DIR, f"video_{notebook_id}.mp4")
    await client.artifacts.download_video(notebook_id, output_path, artifact.id)
    return {"artifact_id": artifact.id, "file": output_path, "title": artifact.title}


async def generate_quiz(notebook_id: str, difficulty: str = "medium") -> dict:
    from notebooklm import QuizDifficulty

    client = await get_client()
    qd = getattr(QuizDifficulty, difficulty.upper(), QuizDifficulty.MEDIUM)
    status = await client.artifacts.generate_quiz(notebook_id, difficulty=qd)
    status = await client.artifacts.wait_for_completion(notebook_id, status.task_id)

    artifacts = await client.artifacts.list_quizzes(notebook_id)
    if not artifacts:
        return {"error": "No quiz artifact found"}

    artifact = artifacts[-1]
    output_path = os.path.join(SESSION_DIR, f"quiz_{notebook_id}.json")
    await client.artifacts.download_quiz(
        notebook_id, output_path, artifact.id, output_format="json"
    )
    return {"artifact_id": artifact.id, "file": output_path, "title": artifact.title}


async def generate_report(notebook_id: str, custom_prompt: str = "") -> dict:
    client = await get_client()
    status = await client.artifacts.generate_report(
        notebook_id, custom_prompt=custom_prompt or None
    )
    status = await client.artifacts.wait_for_completion(notebook_id, status.task_id)

    artifacts = await client.artifacts.list_reports(notebook_id)
    if not artifacts:
        return {"error": "No report artifact found"}

    artifact = artifacts[-1]
    output_path = os.path.join(SESSION_DIR, f"report_{notebook_id}.md")
    await client.artifacts.download_report(notebook_id, output_path, artifact.id)
    return {"artifact_id": artifact.id, "file": output_path, "title": artifact.title}


async def generate_mind_map(notebook_id: str) -> dict:
    from notebooklm import MindMapKind

    client = await get_client()
    result = await client.mind_maps.generate(
        notebook_id, kind=MindMapKind.INTERACTIVE
    )
    return {"mind_map_id": result.id, "title": result.title}


async def generate_slide_deck(notebook_id: str, instructions: str = "") -> dict:
    client = await get_client()
    status = await client.artifacts.generate_slide_deck(
        notebook_id, instructions=instructions or None
    )
    status = await client.artifacts.wait_for_completion(notebook_id, status.task_id)

    artifacts = await client.artifacts.list_slide_decks(notebook_id)
    if not artifacts:
        return {"error": "No slide deck artifact found"}

    artifact = artifacts[-1]
    output_path = os.path.join(SESSION_DIR, f"slides_{notebook_id}.pdf")
    await client.artifacts.download_slide_deck(notebook_id, output_path, artifact.id)
    return {"artifact_id": artifact.id, "file": output_path, "title": artifact.title}


async def generate_infographic(
    notebook_id: str, instructions: str = "", orientation: str = "landscape"
) -> dict:
    from notebooklm import InfographicOrientation

    client = await get_client()
    orient = getattr(InfographicOrientation, orientation.upper(), InfographicOrientation.LANDSCAPE)
    status = await client.artifacts.generate_infographic(
        notebook_id, instructions=instructions or None, orientation=orient
    )
    status = await client.artifacts.wait_for_completion(notebook_id, status.task_id)

    artifacts = await client.artifacts.list_infographics(notebook_id)
    if not artifacts:
        return {"error": "No infographic artifact found"}

    artifact = artifacts[-1]
    output_path = os.path.join(SESSION_DIR, f"infographic_{notebook_id}.png")
    await client.artifacts.download_infographic(notebook_id, output_path, artifact.id)
    return {"artifact_id": artifact.id, "file": output_path, "title": artifact.title}
