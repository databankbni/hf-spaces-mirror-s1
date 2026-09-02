"""
Heaven on Earth CMS Backend — Partnership Form Flow

Defines the ordered slot list for collecting partnership application
information.  Type-specific slots (volunteer_areas, financial_commitment,
material_items) are included in ``get_slots()`` with ``required=False``; the
``action_flow_node`` promotes the correct one to required once
``partnership_type`` is known.

References
----------
- Req §11 (PartnershipFlow Field Definitions), acceptance criteria 11.1–11.5
- Design § "Conversational Action Flows" → "Partnership Form Flow"
"""

from __future__ import annotations

from app.chatbot.flows.base import BaseFlow, Slot

_VALID_TYPES: frozenset[str] = frozenset({"financial", "volunteer", "material"})

# Maps partnership_type → the slot name that becomes required for that type
TYPE_SPECIFIC_SLOT: dict[str, str] = {
    "financial": "financial_commitment",
    "volunteer": "volunteer_areas",
    "material": "material_items",
}


class PartnershipFlow(BaseFlow):
    """
    Slot-filling flow for partnership form submission.

    Base slots (always collected):
        name → email → partnership_type → phone → message

    Type-specific slots (added dynamically by ``action_flow_node`` once
    ``partnership_type`` is known):
        financial  → financial_commitment
        volunteer  → volunteer_areas
        material   → material_items

    All type-specific slots are included in the return value of
    ``get_slots()`` as ``required=False``; the node promotes the relevant
    one to required at runtime.
    """

    def get_slots(self) -> list[Slot]:
        return [
            Slot(
                name="name",
                required=True,
                prompt_key="partnership_name",
                validator=lambda v: len(v.strip()) >= 2,
            ),
            Slot(
                name="email",
                required=True,
                prompt_key="partnership_email",
                validator=lambda v: "@" in v and len(v.strip()) >= 5,
            ),
            Slot(
                name="partnership_type",
                required=True,
                prompt_key="partnership_type",
                validator=lambda v: v.strip().lower() in _VALID_TYPES,
            ),
            Slot(
                name="phone",
                required=False,
                prompt_key="partnership_phone",
                validator=None,
            ),
            # Type-specific detail slots — required=False here; promoted by node
            Slot(
                name="volunteer_areas",
                required=False,
                prompt_key="partnership_volunteer_areas",
                validator=None,
            ),
            Slot(
                name="financial_commitment",
                required=False,
                prompt_key="partnership_financial_commitment",
                validator=None,
            ),
            Slot(
                name="material_items",
                required=False,
                prompt_key="partnership_material_items",
                validator=None,
            ),
            Slot(
                name="message",
                required=False,
                prompt_key="partnership_message",
                validator=None,
            ),
        ]
