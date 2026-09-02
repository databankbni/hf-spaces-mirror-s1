"""
Heaven on Earth CMS Backend — Testimony Submission Flow

Defines the ordered slot list for collecting testimony information from a
user before submitting to ``POST /api/v1/testimonials``.

References
----------
- Req §9 (TestimonyFlow Field Definitions), acceptance criteria 9.1–9.4
- Design § "Conversational Action Flows" → "Testimony Submission Flow"
"""

from __future__ import annotations

from app.chatbot.flows.base import BaseFlow, Slot

_VALID_CATEGORIES = {"healing", "salvation", "provision", "deliverance", "general"}


class TestimonyFlow(BaseFlow):
    """
    Slot-filling flow for testimony submission.

    Slots are returned in the order the chatbot should collect them:
    name → title → content → category → email → phone → location.

    Required slots: ``name``, ``content``, ``category``.
    Optional slots: ``title``, ``email``, ``phone``, ``location``.
    """

    def get_slots(self) -> list[Slot]:
        return [
            Slot(
                name="name",
                required=True,
                prompt_key="testimony_name",
                validator=lambda v: len(v.strip()) >= 2,
            ),
            Slot(
                name="title",
                required=False,
                prompt_key="testimony_title",
                validator=None,
            ),
            Slot(
                name="content",
                required=True,
                prompt_key="testimony_content",
                validator=lambda v: len(v.strip()) >= 5,
            ),
            Slot(
                name="category",
                required=True,
                prompt_key="testimony_category",
                validator=lambda v: v.strip().lower() in _VALID_CATEGORIES,
            ),
            Slot(
                name="email",
                required=False,
                prompt_key="testimony_email",
                validator=None,
            ),
            Slot(
                name="phone",
                required=False,
                prompt_key="testimony_phone",
                validator=None,
            ),
            Slot(
                name="location",
                required=False,
                prompt_key="testimony_location",
                validator=None,
            ),
        ]
