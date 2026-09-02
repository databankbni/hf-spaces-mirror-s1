import re
from uuid import uuid4
from slugify import slugify


def generate_slug(title: str) -> str:
    base = slugify(title or "truyen")
    suffix = str(uuid4()).split("-")[0]
    return f"{base}-{suffix}"