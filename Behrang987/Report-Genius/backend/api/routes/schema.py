"""Schema inspection and optional manual updates."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend.api.deps import get_current_tenant
from backend.domain import template_discoverer

router = APIRouter(prefix="/api", tags=["schema"])


class SchemaPatch(BaseModel):
    """Partial schema update (operator corrections)."""

    section_alias_map: dict[str, str] | None = None
    version: int | None = None


@router.get("/schema")
def get_schema(tenant_id: str = Depends(get_current_tenant)) -> dict:
    """Return the discovered template schema (sections, order, rating system)."""
    schema = template_discoverer.ensure_canonical_schema(tenant_id)
    return schema.model_dump()


@router.patch("/schema")
def patch_schema(
    patch: SchemaPatch,
    tenant_id: str = Depends(get_current_tenant),
) -> dict:
    """Apply operator corrections to the persisted schema (e.g. alias overrides)."""
    schema = template_discoverer.ensure_canonical_schema(tenant_id)
    if patch.section_alias_map is not None:
        schema.section_alias_map.update(patch.section_alias_map)
    if patch.version is not None:
        schema.version = patch.version
    template_discoverer.save_schema(tenant_id, schema)
    return schema.model_dump()
