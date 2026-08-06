"""
Data models for the SiriBench RL Environment.

Wraps SiriBench (an on-device iOS assistant benchmark: 14 tasks over the real
Reminders / Calendar / Contacts / Messages apps) as an OpenEnv environment.
The iOS system apps are replaced by a faithful simulated world; the agent is
handed the same 11 tools the on-device Apple Foundation Model was given, plus
`respond` to end a user turn. Rubrics are the benchmark's original
programmatic checks — no LLM judge.
"""

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

try:  # OpenEnv is present on the Space / platform; fall back for local dev.
    from openenv.core.env_server.types import Action, Observation, State
except Exception:  # pragma: no cover
    class Action(BaseModel):
        pass

    class Observation(BaseModel):
        pass

    class State(BaseModel):
        pass


class ToolName(str, Enum):
    CREATE_REMINDER = "create_reminder"
    LIST_REMINDERS = "list_reminders"
    DELETE_ALL_REMINDERS = "delete_all_reminders"
    CREATE_CALENDAR_EVENT = "create_calendar_event"
    LIST_CALENDAR_EVENTS = "list_calendar_events"
    CREATE_CONTACT = "create_contact"
    LIST_CONTACTS = "list_contacts"
    SEND_MESSAGE = "send_message"
    WEB_SEARCH = "web_search"
    SEARCH_PERSONAL = "search_personal"
    READ_WEBPAGE = "read_webpage"
    RESPOND = "respond"


class EpisodeStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    INVALID_ACTION = "invalid_action"
    STEP_LIMIT_REACHED = "step_limit_reached"


class Message(BaseModel):
    """One conversation entry shown to the agent."""

    role: str  # "system" | "user" | "assistant" | "tool"
    content: str = ""
    tool: Optional[str] = None


class TrajectoryEvent(BaseModel):
    """One recorded event, mirroring SiriBench's trajectory.jsonl vocabulary."""

    event: str  # reset | agent_start | function_call | tool_result | agent_done | verify_reminders
    fields: Dict[str, Any] = Field(default_factory=dict)


class SiriBenchAction(Action):
    """One agent decision: call a tool, or `respond` to end the user turn."""

    tool: ToolName
    arguments: Dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Tool arguments. create_reminder: {title}. create_calendar_event: "
            "{title, when}. create_contact: {name}. send_message: {text, "
            "recipient?}. web_search / search_personal: {query}. respond: "
            "{text} — the assistant's final answer (or question) for the "
            "current user turn. List/read tools take no arguments."
        ),
    )


class SiriBenchObservation(Observation):
    """Observation returned to the agent. Embeds reward + done per OpenEnv."""

    task_id: str = ""
    summary: str = ""
    instructions: str = ""
    conversation: List[Message] = Field(default_factory=list)
    available_tools: List[Dict[str, Any]] = Field(default_factory=list)
    step_count: int = 0
    max_steps: int = 16
    feedback: str = ""
    status: EpisodeStatus = EpisodeStatus.RUNNING
    reward: float = 0.0
    done: bool = False
    metadata: Dict[str, Any] = Field(default_factory=dict)


class SiriBenchState(State):
    """Internal env state."""

    task_id: str = ""
    prompt_index: int = 0
    conversation: List[Message] = Field(default_factory=list)
    events: List[TrajectoryEvent] = Field(default_factory=list)
    tools_called: List[str] = Field(default_factory=list)
    final_answers: List[str] = Field(default_factory=list)
    step_count: int = 0
    max_steps: int = 16
    status: EpisodeStatus = EpisodeStatus.RUNNING
    last_reward: float = 0.0
    episode_id: str = ""
