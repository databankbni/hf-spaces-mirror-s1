from __future__ import annotations
from .contracts import SectionSpec

BUILTIN_SECTIONS = (
    SectionSpec("blogger", "publishing", secret_names=(
        "BLOGGER_BLOG_ID", "BLOGGER_CLIENT_ID", "BLOGGER_CLIENT_SECRET", "BLOGGER_REFRESH_TOKEN"
    )),
    SectionSpec("news", "content", capabilities=("ingest", "process", "publish")),
    SectionSpec("sports", "content", capabilities=("ingest", "process", "publish")),
)

def register_builtins(registry):
    for spec in BUILTIN_SECTIONS:
        registry.register(spec)
    return registry
