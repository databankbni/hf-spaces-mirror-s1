# ---------------------------------------------------------------------------
# reminders/calendar_invite.py
#
# Build a downloadable iCalendar (.ics) file containing a DAILY recurring
# event that reminds the user to read, with the app URL embedded in the
# event. Unlike SMTP reminders this needs no credentials and no running
# server at reminder time — the user's own calendar app does the nudging.
# ---------------------------------------------------------------------------

from datetime import datetime, timedelta, timezone
from pathlib import Path

from config import APP_URL, AUDIO_DIR


def _fold(line: str) -> str:
    """iCalendar lines longer than 75 octets must be folded. Good enough for
    our short content."""
    if len(line) <= 73:
        return line
    chunks = [line[i : i + 73] for i in range(0, len(line), 73)]
    return "\r\n ".join(chunks)


def _escape(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def _parse_hhmm(text: str | None) -> tuple[int, int]:
    try:
        hh, mm = (text or "08:00").strip().split(":")
        return int(hh), int(mm)
    except (ValueError, AttributeError):
        return 8, 0


def build_invite(
    email: str,
    reminder_time_local: str | None = None,
    app_url: str | None = None,
) -> str:
    """Return the .ics text for a daily reading reminder."""
    url = app_url or APP_URL
    hour, minute = _parse_hhmm(reminder_time_local)

    now = datetime.now(timezone.utc)
    # First occurrence: today at the chosen local-clock time (kept naive/
    # floating so the user's own timezone applies).
    start = datetime.now().replace(
        hour=hour, minute=minute, second=0, microsecond=0
    )
    if start < datetime.now():
        start += timedelta(days=1)
    end = start + timedelta(minutes=15)

    def _fmt_floating(dt: datetime) -> str:
        return dt.strftime("%Y%m%dT%H%M%S")

    uid = f"gita-{_escape(email)}-{now.strftime('%Y%m%d%H%M%S')}@bhagwadgita.app"
    summary = "Bhagavad Gita reading"
    description = (
        f"Time for today's Bhagavad Gita reading. "
        f"Continue where you left off: {url}"
    )

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Bhagwad Gita Reading Agent//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{now.strftime('%Y%m%dT%H%M%SZ')}",
        f"DTSTART:{_fmt_floating(start)}",
        f"DTEND:{_fmt_floating(end)}",
        "RRULE:FREQ=DAILY",
        _fold(f"SUMMARY:{_escape(summary)}"),
        _fold(f"DESCRIPTION:{_escape(description)}"),
        _fold(f"URL:{url}"),
        "BEGIN:VALARM",
        "ACTION:DISPLAY",
        "DESCRIPTION:Bhagavad Gita reading",
        "TRIGGER:-PT5M",
        "END:VALARM",
        "END:VEVENT",
        "END:VCALENDAR",
    ]
    return "\r\n".join(lines) + "\r\n"


def write_invite(
    email: str,
    reminder_time_local: str | None = None,
    app_url: str | None = None,
) -> Path:
    """Write the .ics to the audio cache dir (a Gradio-served folder) and
    return its path so a download button can offer it."""
    ics = build_invite(email, reminder_time_local, app_url)
    safe = "".join(c if c.isalnum() else "_" for c in email) or "reader"
    out = AUDIO_DIR / f"gita_reminder_{safe}.ics"
    out.write_text(ics, encoding="utf-8")
    return out
