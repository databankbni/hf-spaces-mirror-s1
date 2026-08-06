"""
The 11 PersonalAssistantBench tools + `respond`, with OpenAI-style function schemas and an
executor that drives the simulated iOS world. Result strings replicate the
Swift tools' outputs so trajectories are comparable with the on-device runs.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Tuple

from .world import IOSWorld, format_event_date, web_search


def _str_arg(args: Dict[str, Any], key: str) -> str:
    v = args.get(key, "")
    return v if isinstance(v, str) else str(v)


TOOL_SCHEMAS: List[Dict[str, Any]] = [
    {
        "name": "create_reminder",
        "description": "Create a reminder (a to-do item) in the Reminders app.",
        "parameters": {"type": "object", "properties": {
            "title": {"type": "string", "description": "The reminder text, e.g. 'Buy milk'."}},
            "required": ["title"]},
    },
    {
        "name": "list_reminders",
        "description": "List the user's current reminders (returns their titles).",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "delete_all_reminders",
        "description": "Permanently delete ALL of the user's reminders. This cannot be undone.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "create_calendar_event",
        "description": "Create an event in the Calendar app at a specific date and time.",
        "parameters": {"type": "object", "properties": {
            "title": {"type": "string", "description": "The event title."},
            "when": {"type": "string", "description": "When it starts, in natural language, e.g. 'tomorrow 12pm'."}},
            "required": ["title", "when"]},
    },
    {
        "name": "list_calendar_events",
        "description": "List the user's upcoming calendar events with their dates and times.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "create_contact",
        "description": "Add a new person to the Contacts app.",
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string", "description": "The person's full name."}},
            "required": ["name"]},
    },
    {
        "name": "list_contacts",
        "description": "List the names of the people in the user's Contacts.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "send_message",
        "description": "Send a text message to someone. Provide the full message text.",
        "parameters": {"type": "object", "properties": {
            "text": {"type": "string", "description": "The complete message body to send."},
            "recipient": {"type": "string", "description": "Who to send it to, e.g. 'me'."}},
            "required": ["text"]},
    },
    {
        "name": "web_search",
        "description": "Search the web for current, factual world knowledge and return a short summary with its source.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "The search query, e.g. 'capital of Australia'."}},
            "required": ["query"]},
    },
    {
        "name": "search_personal",
        "description": "Search the user's personal data (their emails and messages) and return matching items, each with its source and date.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "What to look for, e.g. 'Lisbon hotel confirmation'."}},
            "required": ["query"]},
    },
    {
        "name": "read_webpage",
        "description": "Read the text content of the web page or note the user is currently viewing.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "respond",
        "description": "Reply to the user and end the current turn. Use this for your final answer, or to ask the user a question.",
        "parameters": {"type": "object", "properties": {
            "text": {"type": "string", "description": "What to say to the user."}},
            "required": ["text"]},
    },
]


def execute_tool(world: IOSWorld, name: str, args: Dict[str, Any]) -> Tuple[str, bool]:
    """Run one tool against the world. Returns (result_text, is_error)."""
    if name == "create_reminder":
        title = _str_arg(args, "title")
        world.create_reminder(title)
        return f"Created reminder '{title}'.", False

    if name == "list_reminders":
        titles = world.reminders
        return (", ".join(titles) if titles else "No reminders."), False

    if name == "delete_all_reminders":
        world.delete_all_reminders()
        return "Deleted all reminders.", False

    if name == "create_calendar_event":
        title = _str_arg(args, "title")
        # Faithful quirk: the natural-language time is NOT parsed; the event is
        # always placed one hour from now. The benchmark scores tool selection.
        world.create_event(title, datetime.now() + timedelta(hours=1))
        return f"Created calendar event '{title}'.", False

    if name == "list_calendar_events":
        events = world.events_snapshot()
        if not events:
            return "No upcoming events.", False
        return "; ".join(
            f"{t} — {format_event_date(s)}" for t, s in events
        ), False

    if name == "create_contact":
        person = _str_arg(args, "name")
        world.create_contact(person)
        return f"Added contact '{person}'.", False

    if name == "list_contacts":
        names = world.contacts
        return (", ".join(names) if names else "No contacts."), False

    if name == "send_message":
        text = _str_arg(args, "text")
        recip = _str_arg(args, "recipient")
        world.message_draft = {"text": text, "recipient": recip}
        return f"Drafted message to {recip or 'recipient'}: {text}", False

    if name == "web_search":
        res = web_search(_str_arg(args, "query"))
        if res is None:
            return "No web result.", True
        return f"{res['extract']}\n(Source: {res['url']})"[:800], False

    if name == "search_personal":
        hits = world.search_personal(_str_arg(args, "query"))
        if not hits:
            return "No matching items.", True
        return "\n".join(
            f"[{d.source} · {d.date}] {d.title}: {d.body}" for d in hits
        )[:800], False

    if name == "read_webpage":
        content = world.page_text
        if not content:
            return "The page is empty.", True
        return content[:1200], False

    return f"Unknown tool '{name}'.", True
