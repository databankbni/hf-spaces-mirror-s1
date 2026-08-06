# ---------------------------------------------------------------------------
# reminders/scheduler.py — Phase C4.
#
# In-process daily reminder scheduler built on APScheduler. On startup it
# loads every opted-in user and schedules a daily job at their chosen local
# time that emails them a "continue reading" nudge.
#
# v1 LIMITATION (documented in PLAN.md): this runs inside the app process.
# On a free Hugging Face Space the container sleeps when idle, which stops
# the scheduler. A v2 upgrade moves scheduling to an external cron / GitHub
# Action that pings a webhook. For local use and paid/always-on Spaces this
# works as-is.
# ---------------------------------------------------------------------------

import os

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from reminders.mailer import build_reminder, send_email
from users.bookmarks import BookmarkStore
from users.profile_store import ProfileStore
from reader.verse_store import VerseStore


def _parse_hhmm(text: str) -> tuple[int, int]:
    hh, mm = text.strip().split(":")
    return int(hh), int(mm)


class ReminderScheduler:
    """Wraps a BackgroundScheduler with one daily job per subscriber."""

    def __init__(
        self,
        profiles: ProfileStore,
        bookmarks: BookmarkStore,
        verses: VerseStore,
        space_url: str | None = None,
    ):
        self._profiles = profiles
        self._bookmarks = bookmarks
        self._verses = verses
        self._space_url = space_url or os.environ.get(
            "SPACE_URL", "http://localhost:7860"
        )
        self._scheduler = BackgroundScheduler()

    def _job_id(self, email: str) -> str:
        return f"reminder::{email}"

    def _send_reminder(self, email: str) -> None:
        """The job body: look up where the user left off and email them."""
        resume_id = self._bookmarks.load_position(email)
        verse = self._verses.get_verse(resume_id)
        ref = verse.ref if verse else resume_id
        subject, body = build_reminder(email, ref, self._space_url)
        try:
            send_email(email, subject, body)
            print(f"[scheduler] reminder sent to {email}")
        except Exception as e:  # noqa: BLE001 — a failed send must not crash the scheduler
            print(f"[scheduler] failed to send reminder to {email}: {e}")

    def subscribe(self, email: str, time_local: str) -> None:
        """Add or replace a daily reminder job for one user."""
        hour, minute = _parse_hhmm(time_local)
        self._scheduler.add_job(
            self._send_reminder,
            trigger=CronTrigger(hour=hour, minute=minute),
            args=[email],
            id=self._job_id(email),
            replace_existing=True,
        )
        print(f"[scheduler] scheduled reminder for {email} at {time_local}")

    def unsubscribe(self, email: str) -> None:
        """Remove a user's reminder job if present."""
        job_id = self._job_id(email)
        if self._scheduler.get_job(job_id):
            self._scheduler.remove_job(job_id)
            print(f"[scheduler] unsubscribed {email}")

    def reschedule(self, email: str, time_local: str) -> None:
        """Convenience: re-point an existing reminder to a new time."""
        self.subscribe(email, time_local)

    def load_all(self) -> None:
        """Schedule jobs for every opted-in user. Called once at startup."""
        for profile in self._profiles.list_subscribers():
            self.subscribe(profile.email, profile.reminder_time_local)

    def start(self) -> None:
        if not self._scheduler.running:
            self._scheduler.start()
            print("[scheduler] started")

    def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
