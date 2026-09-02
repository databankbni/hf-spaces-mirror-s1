"""
Heaven on Earth CMS Backend — API Submission Node

Validates the collected slot values against the appropriate Pydantic schema
and writes them directly to the database via the CRUD layer.  This avoids an
HTTP self-call (which is unreliable inside the same process) and instead
shares the application's async DB session factory.

References
----------
- Req §8 (Conversational Action Flows), acceptance criteria 8.4–8.7
- Design § "Correctness Properties" → Properties 11, 13
- Arch §5 "LangGraph Agent Design" → "Tool Definitions"
"""

from __future__ import annotations

import json

import structlog
from langchain_core.messages import AIMessage
from pydantic import ValidationError

from app.chatbot.session import AgentState
from app.crud.partnership import create_partnership
from app.crud.prayer import create_prayer_request
from app.crud.testimonial import create_testimonial
from app.database import async_session_maker
from app.schemas.partnership import PartnershipCreate
from app.schemas.prayer import PrayerRequestCreate
from app.schemas.testimonial import TestimonialCreate

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Bilingual success / error messages
# ---------------------------------------------------------------------------

_SUCCESS_MESSAGES: dict[str, dict[str, str]] = {
    "testimony": {
        "en": (
            "✉️ Your testimony has been submitted to Heaven on Earth Kingdom Family Ministries! "
            "It will be reviewed before publishing. God bless you!"
        ),
        "am": (
            "✉️ ምስክርነትዎ ለሰማይ ላይ ምድር መንግሥት ቤተሰብ አገልግሎቶች ተልኳል! "
            "ከመታተሙ በፊት ይገመገማል። እግዚአብሔር ይባርክዎ!"
        ),
    },
    "prayer": {
        "en": (
            "✉️ Your prayer request has been received and will be forwarded to our prayer team. "
            "They will lift your request up in prayer. God bless you!"
        ),
        "am": (
            "✉️ የጸሎት ጥያቄዎ ደርሷል እና ለጸሎት ቡድናችን ይተላለፋል። "
            "ቡድናችን ጥያቄዎን ያቀርባሉ። እግዚአብሔር ይባርክዎ!"
        ),
    },
    "partnership": {
        "en": (
            "✉️ Your partnership application has been submitted to Heaven on Earth Kingdom Family Ministries! "
            "Our team will be in touch soon. God bless you!"
        ),
        "am": (
            "✉️ የአጋርነት ማመልከቻዎ ለሰማይ ላይ ምድር መንግሥት ቤተሰብ አገልግሎቶች ተልኳል! "
            "ቡድናችን በቅርቡ ያናግርዎታል። እግዚአብሔር ይባርክዎ!"
        ),
    },
}

_VALIDATION_ERROR_MSG: dict[str, str] = {
    "en": (
        "Some of the information you provided doesn't look right. "
        "Please check your answers and try again."
    ),
    "am": (
        "ያቀረቡት አንዳንድ መረጃ ትክክል አይደለም። "
        "መልሶቻዎን ያረጋግጡ እና እንደገና ይሞክሩ።"
    ),
}

_DB_ERROR_MSG: dict[str, str] = {
    "en": (
        "😔 Something went wrong while submitting your request. "
        "Please try again later or contact us directly."
    ),
    "am": (
        "😔 ጥያቄዎን በሚልኩበት ጊዜ ችግር ተፈጥሯል። "
        "እባክዎ ቆይተው እንደገና ይሞክሩ ወይም በቀጥታ ያግኙን።"
    ),
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_list(value: str | list | None) -> list[str]:
    """
    Convert a comma-separated string or existing list to ``list[str]``.

    Used for ``volunteer_areas`` and ``material_items`` in PartnershipCreate.
    """
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [item.strip() for item in str(value).split(",") if item.strip()]


def _parse_financial_commitment(value: str | dict | None) -> dict | None:
    """
    Convert a plain string description to a dict for ``financial_commitment``.

    The Pydantic schema expects ``Optional[Dict[str, Any]]``.  We wrap a
    plain string in ``{"description": value}`` so it is always a dict.
    """
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    # Try JSON first
    try:
        parsed = json.loads(value)
        if isinstance(parsed, dict):
            return parsed
    except (json.JSONDecodeError, TypeError):
        pass
    # Fall back to wrapping the string
    return {"description": str(value)}


def _build_payload(flow: str, collected_fields: dict):
    """
    Build and validate the appropriate Pydantic schema from *collected_fields*.

    Returns the validated model instance.

    Raises
    ------
    ValidationError
        If the collected fields fail Pydantic validation.
    ValueError
        If *flow* is not a recognised flow name.
    """
    cf = {k: v for k, v in collected_fields.items()}

    if flow == "testimony":
        if "category" in cf:
            cf["category"] = cf["category"].strip().lower()
        cf["source"] = "chatbot"
        return TestimonialCreate(**cf)

    if flow == "prayer":
        is_anon_raw = cf.pop("is_anonymous", "no")
        cf["is_anonymous"] = is_anon_raw.strip().lower() in {
            "yes", "true", "1", "አዎ", "አዎ።"
        }
        cf["source"] = "chatbot"
        return PrayerRequestCreate(**cf)

    if flow == "partnership":
        if "partnership_type" in cf:
            cf["partnership_type"] = cf["partnership_type"].strip().lower()
        cf["volunteer_areas"] = _parse_list(cf.get("volunteer_areas"))
        cf["material_items"] = _parse_list(cf.get("material_items"))
        cf["financial_commitment"] = _parse_financial_commitment(
            cf.get("financial_commitment")
        )
        if not cf["volunteer_areas"]:
            cf["volunteer_areas"] = None
        if not cf["material_items"]:
            cf["material_items"] = None
        if cf["financial_commitment"] is None:
            del cf["financial_commitment"]
        cf["source"] = "chatbot"
        return PartnershipCreate(**cf)

    raise ValueError(f"Unknown flow: {flow!r}")


# ---------------------------------------------------------------------------
# submission_node
# ---------------------------------------------------------------------------


async def submission_node(state: AgentState) -> AgentState:
    """
    Validate collected fields and write them directly to the database via the
    CRUD layer (no HTTP self-call).

    On validation error: appends a bilingual error message and returns state
    unchanged.

    On success: appends a bilingual success message and resets flow state.

    On database error: logs the error and appends a user-facing error message.

    Parameters
    ----------
    state:
        Current LangGraph agent state.

    Returns
    -------
    AgentState
        Updated state.
    """
    flow: str = state.get("flow") or ""
    language: str = state.get("language", "en")
    collected_fields: dict = dict(state.get("collected_fields") or {})
    messages = list(state.get("messages") or [])

    _valid_flows = {"testimony", "prayer", "partnership"}
    if flow not in _valid_flows:
        logger.warning("submission_node: unknown flow", flow=flow)
        return state

    # ------------------------------------------------------------------
    # 1. Validate against Pydantic schema
    # ------------------------------------------------------------------
    try:
        payload = _build_payload(flow, collected_fields)
    except ValidationError as exc:
        logger.error(
            "submission_validation_error",
            flow=flow,
            errors=exc.errors(),
            collected_fields=list(collected_fields.keys()),
        )
        err_msg = _VALIDATION_ERROR_MSG.get(language, _VALIDATION_ERROR_MSG["en"])
        messages.append(AIMessage(content=err_msg))
        return {
            **state,
            "messages": messages,
            "error": str(exc),
        }

    # ------------------------------------------------------------------
    # 2. Write directly to the database via the CRUD layer
    # ------------------------------------------------------------------
    try:
        async with async_session_maker() as db:
            async with db.begin():
                if flow == "testimony":
                    record = await create_testimonial(db, testimonial_in=payload)
                elif flow == "prayer":
                    record = await create_prayer_request(db, prayer_in=payload)
                else:  # partnership
                    record = await create_partnership(db, partnership_in=payload)

        record_id = str(getattr(record, "id", ""))

    except Exception as exc:
        logger.error(
            "submission_db_error",
            flow=flow,
            error=str(exc),
        )
        err_msg = _DB_ERROR_MSG.get(language, _DB_ERROR_MSG["en"])
        messages.append(AIMessage(content=err_msg))
        return {
            **state,
            "flow": "idle",
            "flow_step": "",
            "collected_fields": {},
            "missing_fields": [],
            "messages": messages,
            "error": str(exc),
        }

    # ------------------------------------------------------------------
    # 3. Success
    # ------------------------------------------------------------------
    success_map = _SUCCESS_MESSAGES.get(flow, {})
    success_msg = success_map.get(language) or success_map.get("en", "Submitted!")
    messages.append(AIMessage(content=success_msg))

    logger.info(
        "submission_success",
        flow=flow,
        record_id=record_id,
    )

    return {
        **state,
        "flow": "idle",
        "flow_step": "",
        "collected_fields": {},
        "missing_fields": [],
        "messages": messages,
        "api_response": {"id": record_id},
        "error": None,
    }
