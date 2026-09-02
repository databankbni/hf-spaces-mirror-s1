"""Internal value types for content-based topic generation."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TopicBucket:
    """A topic/sub-topic unit with the surveyor observations routed to it."""

    topic_id: str
    subtopic_id: str
    topic_label: str
    subtopic_label: str
    observations: list[str] = field(default_factory=list)
    rating_value: str | None = None

    @property
    def code(self) -> str:
        """Stable per-report key (sub-topic id; unique across topics)."""
        return self.subtopic_id or self.topic_id
