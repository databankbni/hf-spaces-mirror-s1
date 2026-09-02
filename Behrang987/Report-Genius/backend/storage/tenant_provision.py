"""Copy operator bundle artifacts from the default tenant to a new tenant."""

from __future__ import annotations

import logging
import shutil

from backend.config import settings
from backend.rag.types import TIER_MASTER, TIER_REFERENCE
from backend.storage import tenant_store

logger = logging.getLogger(__name__)


def provision_tenant_from_default(tenant_id: str) -> bool:
    """Clone schema + FAISS indexes from default tenant when the new tenant is empty."""
    if tenant_id == settings.default_tenant_id:
        return False

    schema_dest = tenant_store.schema_path(tenant_id)
    if schema_dest.is_file():
        return False

    source = settings.default_tenant_id
    schema_src = tenant_store.schema_path(source)
    if not schema_src.is_file():
        from backend.domain import template_discoverer

        logger.warning(
            "Default tenant has no schema; seeding canonical RICS L3 for %s.",
            tenant_id,
        )
        template_discoverer.install_canonical_schema(tenant_id)
        return True

    shutil.copyfile(schema_src, schema_dest)
    prev = tenant_store.schema_prev_path(source)
    if prev.is_file():
        shutil.copyfile(prev, tenant_store.schema_prev_path(tenant_id))

    for tier in (TIER_MASTER, TIER_REFERENCE):
        src_dir = tenant_store.faiss_dir(source, tier)
        dest_dir = tenant_store.faiss_dir(tenant_id, tier)
        if dest_dir.exists():
            shutil.rmtree(dest_dir, ignore_errors=True)
        if src_dir.is_dir() and any(src_dir.iterdir()):
            shutil.copytree(src_dir, dest_dir)

    logger.info("Provisioned tenant %s from default operator bundle.", tenant_id)
    return True
