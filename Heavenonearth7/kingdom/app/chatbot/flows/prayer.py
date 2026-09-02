"""
Heaven on Earth CMS Backend — Prayer Request Flow

Defines the ordered slot list for collecting prayer request information.
The ``name`` slot is conditionally required based on the ``is_anonymous``
answer; the ``action_flow_node`` handles that conditional logic at runtime.

References
----------
- Req §10 (PrayerFlow Field Definitions), acceptance criteria 10.1–10.3
- Design § "Conversational Action Flows" → "Prayer Request Flow"
"""

from __future__ import annotations

from app.chatbot.flows.base import BaseFlow, Slot

# Values that indicate the user chose to remain anonymous
_ANONYMOUS_VALUES: frozenset[str] = frozenset({"yes", "true", "1", "አዎ", "አዎ።"})


def _is_anonymous_validator(v: str) -> bool:
    """Accept 'yes'/'no' (and Amharic equivalents) for the anonymous field."""
    normalised = v.strip().lower()
    return normalised in _ANONYMOUS_VALUES or normalised in {
        "no", "false", "0", "አይ", "አይ።"
    }


class PrayerFlow(BaseFlow):
    """
    Slot-filling flow for prayer request submission.

    Slots are returned in collection order:
    is_anonymous → name → request → email → phone.

    The ``name`` slot is marked ``required=False`` here; the
    ``action_flow_node`` promotes it to required when ``is_anonymous``
    is *not* set to a truthy value (yes/true/1/አዎ).
    """

    def get_slots(self) -> list[Slot]:
        return [
            Slot(
                name="is_anonymous",
                required=True,
                prompt_key="prayer_is_anonymous",
                validator=_is_anonymous_validator,
            ),
            # required=False here; action_flow_node promotes it dynamically
            # when is_anonymous is NOT truthy.
            Slot(
                name="name",
                required=False,
                prompt_key="prayer_name",
                validator=None,
            ),
            Slot(
                name="request",
                required=True,
                prompt_key="prayer_request",
                validator=lambda v: len(v.strip()) >= 10,
            ),
            Slot(
                name="email",
                required=False,
                prompt_key="prayer_email",
                validator=None,
            ),
            Slot(
                name="phone",
                required=False,
                prompt_key="prayer_phone",
                validator=None,
            ),
        ]
