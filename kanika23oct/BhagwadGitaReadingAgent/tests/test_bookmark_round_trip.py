# ---------------------------------------------------------------------------
# tests/test_bookmark_round_trip.py
#
# Verifies bookmark + profile persistence against a temp SQLite database.
# No network, no audio.
# ---------------------------------------------------------------------------

from users.bookmarks import BookmarkStore
from users.profile_store import ProfileStore


def test_new_user_gets_default_verse(tmp_path):
    db = tmp_path / "t.sqlite"
    store = BookmarkStore(db_path=db, default_verse_id="BG1.1")
    assert store.load_position("new@example.com") == "BG1.1"


def test_save_and_load_position(tmp_path):
    db = tmp_path / "t.sqlite"
    store = BookmarkStore(db_path=db, default_verse_id="BG1.1")
    store.save_position("user@example.com", "BG2.47")
    assert store.load_position("user@example.com") == "BG2.47"
    # Email is normalized to lowercase.
    assert store.load_position("USER@example.com") == "BG2.47"


def test_profile_defaults_and_update(tmp_path):
    db = tmp_path / "t.sqlite"
    profiles = ProfileStore(db_path=db)
    p = profiles.get_or_create("a@b.com")
    assert p.max_minutes == 10
    assert p.reminder_opt_in is False

    updated = profiles.update_settings(
        "a@b.com", max_minutes=30, reminder_opt_in=True, reminder_time_local="07:30"
    )
    assert updated.max_minutes == 30
    assert updated.reminder_opt_in is True
    assert updated.reminder_time_local == "07:30"

    subs = profiles.list_subscribers()
    assert len(subs) == 1
    assert subs[0].email == "a@b.com"


def test_max_minutes_clamped(tmp_path):
    db = tmp_path / "t.sqlite"
    profiles = ProfileStore(db_path=db)
    p = profiles.update_settings("c@d.com", max_minutes=5)   # below min 10
    assert p.max_minutes == 10
    p = profiles.update_settings("c@d.com", max_minutes=999)  # above max 60
    assert p.max_minutes == 60
