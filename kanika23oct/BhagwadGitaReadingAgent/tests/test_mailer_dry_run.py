# ---------------------------------------------------------------------------
# tests/test_mailer_dry_run.py
#
# Verifies the email MESSAGE FORMAT without sending anything over SMTP.
# ---------------------------------------------------------------------------

from reminders.mailer import build_message, build_reminder


def test_build_message_headers():
    msg = build_message(
        to_email="user@example.com",
        subject="Test subject",
        body="Hello body",
        from_addr="bot@example.com",
    )
    assert msg["To"] == "user@example.com"
    assert msg["From"] == "bot@example.com"
    assert msg["Subject"] == "Test subject"
    assert "Hello body" in msg.get_content()


def test_build_reminder_mentions_resume_point():
    subject, body = build_reminder(
        to_email="user@example.com",
        resume_ref="BG 2.47",
        space_url="https://example.com/space",
    )
    assert "Bhagavad Gita" in subject
    assert "BG 2.47" in body
    assert "https://example.com/space" in body
