from app.config import settings
import httpx
import base64
import os


async def generate_image(prompt: str, output_path: str) -> str:
    async with httpx.AsyncClient() as client:
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
            timeout=120.0,
        )
        resp.raise_for_status()
        data = resp.json()

        content = data["choices"][0]["message"]["content"]
        if content.startswith("data:image"):
            b64_data = content.split(",")[1]
        else:
            b64_data = content

        img_bytes = base64.b64decode(b64_data)
        with open(output_path, "wb") as f:
            f.write(img_bytes)

    return output_path
