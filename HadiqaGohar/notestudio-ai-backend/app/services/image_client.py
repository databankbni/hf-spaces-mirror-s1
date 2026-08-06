import uuid
import os
import httpx
from urllib.parse import quote
from app.config import settings


IMAGES_DIR = os.path.join(settings.temp_dir, "images")
os.makedirs(IMAGES_DIR, exist_ok=True)


def _generate_filename() -> str:
    return f"{uuid.uuid4().hex}.png"


async def generate_image_pollinations(prompt: str) -> str:
    """Generate image using Pollinations.ai (free, no API key needed).
    Returns the filename of the saved image."""
    filename = _generate_filename()
    filepath = os.path.join(IMAGES_DIR, filename)

    encoded_prompt = quote(prompt)
    url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1024&height=1024&nologo=true"

    async with httpx.AsyncClient(follow_redirects=True, timeout=120.0) as client:
        resp = await client.get(url)
        resp.raise_for_status()

        with open(filepath, "wb") as f:
            f.write(resp.content)

    return filename


async def generate_image_openrouter(prompt: str) -> str:
    """Generate image using OpenRouter's image model.
    Returns the filename of the saved image."""
    filename = _generate_filename()
    filepath = os.path.join(IMAGES_DIR, filename)

    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            f"{settings.openrouter_base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.openrouter_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": settings.image_model,
                "messages": [{"role": "user", "content": prompt}],
            },
        )
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]

        import base64
        if content.startswith("data:image"):
            b64_data = content.split(",")[1]
        else:
            b64_data = content

        with open(filepath, "wb") as f:
            f.write(base64.b64decode(b64_data))

    return filename


async def generate_image(prompt: str) -> str:
    """Generate image, trying Pollinations first, then OpenRouter.
    Returns the filename of the saved image."""
    try:
        return await generate_image_pollinations(prompt)
    except Exception:
        pass

    if settings.openrouter_api_key:
        return await generate_image_openrouter(prompt)

    raise RuntimeError("No image generation provider available")
