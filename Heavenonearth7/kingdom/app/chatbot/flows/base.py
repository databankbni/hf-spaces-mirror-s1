"""
Heaven on Earth CMS Backend — Base Flow Definitions

Defines the ``Slot`` dataclass and ``BaseFlow`` abstract class used by all
conversational action flows (testimony, prayer, partnership).

References
----------
- Req §8 (Conversational Action Flows), acceptance criteria 8.1–8.7
- Req §9 (TestimonyFlow), §10 (PrayerFlow), §11 (PartnershipFlow)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Callable, Optional


@dataclass
class Slot:
    """
    Describes a single data field to be collected from the user.

    Attributes
    ----------
    name:
        Unique identifier for this slot (used as key in ``collected_fields``).
    required:
        Whether this slot must be filled before the form can be submitted.
    prompt_key:
        Key into ``FIELD_PROMPTS`` to retrieve the bilingual prompt text.
    validator:
        Optional callable that receives the user's input string and returns
        ``True`` if the value is acceptable, ``False`` otherwise.  When
        ``None``, any non-empty string is accepted.
    """

    name: str
    required: bool
    prompt_key: str
    validator: Optional[Callable[[str], bool]] = field(default=None)


class BaseFlow(ABC):
    """
    Abstract base class for all conversational action flows.

    Subclasses must implement :meth:`get_slots` to return an ordered list
    of :class:`Slot` objects defining the fields required/optional for the
    flow.
    """

    @abstractmethod
    def get_slots(self) -> list[Slot]:
        """
        Return an ordered list of :class:`Slot` objects for this flow.

        The order determines the sequence in which the chatbot prompts the
        user for missing information.
        """
        ...
