"""
Heaven on Earth CMS Backend — Action Flow Node

Implements the slot-filling state machine that drives testimony, prayer, and
partnership conversational flows.  The node:

1. Resolves the active flow from state.
2. Attempts to store the last user message into the "current" missing slot,
   running its validator.
3. Finds the next unfilled required slot (with flow-specific conditional
   logic for PrayerFlow / PartnershipFlow).
4. Either sets ``missing_fields`` and appends a bilingual prompt, or clears
   ``missing_fields`` so the graph routes to Confirmation.

References
----------
- Req §8 (Conversational Action Flows), acceptance criteria 8.1–8.7
- Req §9–§11 (flow-specific field definitions)
- Design § "Conversational Action Flows"
- Design § "Correctness Properties" → Properties 12, 16
"""

from __future__ import annotations

import structlog
from langchain_core.messages import AIMessage, HumanMessage

from app.chatbot.flows.base import BaseFlow, Slot
from app.chatbot.flows.partnership import PartnershipFlow, TYPE_SPECIFIC_SLOT
from app.chatbot.flows.prayer import PrayerFlow
from app.chatbot.flows.prompts import FIELD_PROMPTS
from app.chatbot.flows.testimony import TestimonyFlow
from app.chatbot.session import AgentState

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Flow dispatch map
# ---------------------------------------------------------------------------

FLOW_DEFINITIONS: dict[str, type[BaseFlow]] = {
    "testimony": TestimonyFlow,
    "prayer": PrayerFlow,
    "partnership": PartnershipFlow,
}

# Anonymous indicator values for PrayerFlow
_ANONYMOUS_VALUES: frozenset[str] = frozenset({"yes", "true", "1", "አዎ", "አዎ።"})

# Skip keywords — user wants to skip an optional field
_SKIP_KEYWORDS: frozenset[str] = frozenset({"skip", "ዝለል", "pass", "next"})


def _get_prompt(prompt_key: str, language: str) -> str:
    """Return the bilingual prompt string for *prompt_key* in *language*."""
    entry = FIELD_PROMPTS.get(prompt_key)
    if entry is None:
        fallback = FIELD_PROMPTS.get("generic_invalid", {})
        return fallback.get(language) or fallback.get("en", "Please try again.")
    return entry.get(language) or entry.get("en", "Please try again.")


def _last_human_message(state: AgentState) -> str | None:
    """Return the text of the most recent HumanMessage in the conversation."""
    for msg in reversed(state.get("messages", [])):
        if isinstance(msg, HumanMessage):
            return msg.content
    return None


def _is_skip(value: str) -> bool:
    return value.strip().lower() in _SKIP_KEYWORDS


def _effective_slots(
    flow_instance: BaseFlow,
    collected_fields: dict,
) -> list[Slot]:
    """
    Build the effective ordered slot list, applying flow-specific conditional
    logic:

    - **PrayerFlow**: if ``is_anonymous`` is a truthy value, mark the
      ``name`` slot as required=False (skip it).
    - **PartnershipFlow**: if ``partnership_type`` is filled, promote the
      type-specific slot (volunteer_areas / financial_commitment /
      material_items) to required=True.

    Returns a new list of :class:`Slot` objects (originals not mutated).
    """
    base_slots: list[Slot] = flow_instance.get_slots()

    if isinstance(flow_instance, PrayerFlow):
        is_anon_raw = collected_fields.get("is_anonymous", "")
        is_anon = is_anon_raw.strip().lower() in _ANONYMOUS_VALUES
        result: list[Slot] = []
        for slot in base_slots:
            if slot.name == "name" and is_anon:
                # User chose anonymous — skip the name slot entirely
                result.append(
                    Slot(
                        name=slot.name,
                        required=False,
                        prompt_key=slot.prompt_key,
                        validator=slot.validator,
                    )
                )
            else:
                result.append(slot)
        return result

    if isinstance(flow_instance, PartnershipFlow):
        ptype = collected_fields.get("partnership_type", "").strip().lower()
        type_specific_name = TYPE_SPECIFIC_SLOT.get(ptype)
        result = []
        for slot in base_slots:
            if slot.name == type_specific_name:
                # Promote to required now that we know the type
                result.append(
                    Slot(
                        name=slot.name,
                        required=True,
                        prompt_key=slot.prompt_key,
                        validator=slot.validator,
                    )
                )
            elif slot.name in TYPE_SPECIFIC_SLOT.values() and slot.name != type_specific_name:
                # Other type-specific slots stay optional (and will be skipped)
                result.append(slot)
            else:
                result.append(slot)
        return result

    return base_slots


async def action_flow_node(state: AgentState) -> AgentState:
    """
    Core slot-filling node.

    Parameters
    ----------
    state:
        Current LangGraph agent state.

    Returns
    -------
    AgentState
        Updated state with ``collected_fields``, ``missing_fields``, and
        ``messages`` (possibly with a new ``AIMessage`` prompt appended).
    """
    # ------------------------------------------------------------------
    # 0. If already awaiting confirmation, pass through unchanged so the
    #    graph routes to confirmation_node which will read the user's reply.
    # ------------------------------------------------------------------
    if state.get("flow_step") == "awaiting_confirm":
        logger.debug("action_flow_node: awaiting_confirm — passing through to confirmation")
        return state

    # ------------------------------------------------------------------
    # 1. Resolve the active flow
    # ------------------------------------------------------------------
    flow_name: str = state.get("flow") or "idle"
    intent: str | None = state.get("intent")

    # If a new intent arrives while flow is idle, activate that flow
    if flow_name == "idle" and intent in FLOW_DEFINITIONS:
        flow_name = intent

    if flow_name not in FLOW_DEFINITIONS:
        logger.debug("action_flow_node: unknown flow, passing through", flow=flow_name)
        return state

    language: str = state.get("language", "en")
    collected_fields: dict = dict(state.get("collected_fields") or {})
    missing_fields: list[str] = list(state.get("missing_fields") or [])
    messages = list(state.get("messages") or [])

    # ------------------------------------------------------------------
    # 2. Instantiate the flow and build effective slot list
    # ------------------------------------------------------------------
    flow_instance = FLOW_DEFINITIONS[flow_name]()
    effective_slots = _effective_slots(flow_instance, collected_fields)

    # ------------------------------------------------------------------
    # 3. Attempt to fill the *currently awaited* slot from the last user
    #    message (if we were waiting for one).
    # ------------------------------------------------------------------
    user_input = _last_human_message(state)

    if user_input is not None and missing_fields:
        awaited_slot_name = missing_fields[0]
        # Find the Slot object for the awaited slot
        awaited_slot: Slot | None = next(
            (s for s in effective_slots if s.name == awaited_slot_name), None
        )

        if awaited_slot is not None and awaited_slot_name not in collected_fields:
            value = user_input.strip()
            skip_requested = _is_skip(value)

            if skip_requested and not awaited_slot.required:
                # User skipped an optional field — move on without storing
                logger.debug(
                    "action_flow_node: optional slot skipped",
                    slot=awaited_slot_name,
                    flow=flow_name,
                )
            elif awaited_slot.validator is not None and not skip_requested:
                # Run validation
                try:
                    valid = awaited_slot.validator(value)
                except Exception:
                    valid = False

                if not valid:
                    # Validation failed — re-prompt with error message
                    error_key = f"{awaited_slot.prompt_key}_invalid"
                    if error_key not in FIELD_PROMPTS:
                        error_key = f"{awaited_slot.prompt_key}_too_short"
                    if error_key not in FIELD_PROMPTS:
                        error_key = "generic_invalid"

                    error_msg = _get_prompt(error_key, language)
                    messages.append(AIMessage(content=error_msg))

                    logger.debug(
                        "action_flow_node: validation failed",
                        slot=awaited_slot_name,
                        flow=flow_name,
                        value=value,
                    )

                    return {
                        **state,
                        "flow": flow_name,
                        "collected_fields": collected_fields,
                        "missing_fields": missing_fields,
                        "messages": messages,
                    }
                else:
                    # Valid — store the value
                    collected_fields[awaited_slot_name] = value
            else:
                # No validator or skip on required (skip on required not allowed here)
                if not skip_requested or not awaited_slot.required:
                    collected_fields[awaited_slot_name] = value

            # Rebuild effective slots now that collected_fields may have changed
            effective_slots = _effective_slots(flow_instance, collected_fields)

    # ------------------------------------------------------------------
    # 4. Find the first unfilled required slot
    # ------------------------------------------------------------------
    next_missing: Slot | None = None
    for slot in effective_slots:
        if slot.required and slot.name not in collected_fields:
            next_missing = slot
            break

    # ------------------------------------------------------------------
    # 5a. All required slots filled → clear missing_fields so router
    #     sends the graph to Confirmation
    # ------------------------------------------------------------------
    if next_missing is None:
        logger.debug(
            "action_flow_node: all required slots collected",
            flow=flow_name,
            collected=list(collected_fields.keys()),
        )
        return {
            **state,
            "flow": flow_name,
            "collected_fields": collected_fields,
            "missing_fields": [],
            "messages": messages,
        }

    # ------------------------------------------------------------------
    # 5b. Still have missing required slots → prompt for the next one
    # ------------------------------------------------------------------
    prompt_text = _get_prompt(next_missing.prompt_key, language)
    messages.append(AIMessage(content=prompt_text))

    logger.debug(
        "action_flow_node: prompting for slot",
        slot=next_missing.name,
        flow=flow_name,
    )

    return {
        **state,
        "flow": flow_name,
        "collected_fields": collected_fields,
        "missing_fields": [next_missing.name],
        "messages": messages,
    }
