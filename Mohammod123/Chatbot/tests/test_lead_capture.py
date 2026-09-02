from __future__ import annotations

import unittest

from src.lead_capture import LeadCaptureManager


class FakeSender:
    def browser_payload(self, lead):
        return {
            "public_key": "public",
            "service_id": "service",
            "template_id": "template",
            "template_params": {"message": "sent", "request_type": lead.request_type},
        }

    def send(self, lead) -> None:
        return None


class LeadCaptureManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = LeadCaptureManager(sender=FakeSender())

    def test_meeting_request_collects_schedule_details(self) -> None:
        session_id = "meeting-session"

        turn = self.manager.handle_message(session_id, "I want to schedule a meeting")
        self.assertIsNotNone(turn)
        self.assertEqual(turn.lead["request_type"], "meeting")
        self.assertIn("What would you like to discuss", turn.answer)

        self.manager.handle_message(session_id, "I want to discuss a new AI chatbot project")
        self.manager.handle_message(session_id, "Tomorrow")
        self.manager.handle_message(session_id, "3pm")
        self.manager.handle_message(session_id, "Dhaka time")
        self.manager.handle_message(session_id, "My name is Sarah")
        self.manager.handle_message(session_id, "sarah@example.com")
        self.manager.handle_message(session_id, "+8801712345678")
        turn = self.manager.handle_message(session_id, "WhatsApp")

        self.assertIsNotNone(turn)
        self.assertTrue(turn.lead["confirmation_required"])
        self.assertEqual(turn.lead["preferred_date"], "Tomorrow")
        self.assertEqual(turn.lead["preferred_time"], "3pm")
        self.assertEqual(turn.lead["timezone_or_location"], "Dhaka time")
        self.assertIn("Meeting Request", turn.answer)
        self.assertEqual(turn.emailjs["template_params"]["request_type"], "meeting")

    def test_service_request_still_collects_project_details(self) -> None:
        session_id = "service-session"

        self.manager.handle_message(session_id, "I need a website")
        self.manager.handle_message(session_id, "A landing page for my agency")
        self.manager.handle_message(session_id, "My name is Karim")
        self.manager.handle_message(session_id, "karim@example.com")
        self.manager.handle_message(session_id, "$1000 to $1500")
        self.manager.handle_message(session_id, "within 1 month")
        turn = self.manager.handle_message(session_id, "Email")

        self.assertIsNotNone(turn)
        self.assertTrue(turn.lead["confirmation_required"])
        self.assertEqual(turn.lead["request_type"], "service")
        self.assertEqual(turn.lead["service"], "Website / web development")
        self.assertIn("Service Request", turn.answer)

    def test_side_question_during_collection_can_fall_back_to_rag(self) -> None:
        session_id = "side-question-session"

        self.manager.handle_message(session_id, "How can I order a custom RAG chatbot?")
        turn = self.manager.handle_message(session_id, "What does RAG mean?")

        self.assertIsNone(turn)
        state = self.manager.get_state(session_id)
        self.assertIsNotNone(state)
        self.assertEqual(state["request_type"], "service")

    def test_service_request_accepts_phone_as_contact_detail(self) -> None:
        session_id = "phone-contact-session"

        self.manager.handle_message(session_id, "I need a website")
        self.manager.handle_message(session_id, "A landing page for my agency")
        self.manager.handle_message(session_id, "My name is Karim")
        self.manager.handle_message(session_id, "$1000 to $1500")
        self.manager.handle_message(session_id, "within 1 month")
        self.manager.handle_message(session_id, "WhatsApp")
        turn = self.manager.handle_message(session_id, "+8801712345678")

        self.assertIsNotNone(turn)
        self.assertTrue(turn.lead["confirmation_required"])
        self.assertEqual(turn.lead["phone"], "+8801712345678")

    def test_uncertain_budget_and_timeline_do_not_trap_user(self) -> None:
        session_id = "uncertain-session"

        self.manager.handle_message(session_id, "I need a mobile app")
        self.manager.handle_message(session_id, "An ordering app for my restaurant")
        self.manager.handle_message(session_id, "My name is Rafi")
        self.manager.handle_message(session_id, "not sure")
        self.manager.handle_message(session_id, "flexible")
        self.manager.handle_message(session_id, "Email")
        turn = self.manager.handle_message(session_id, "rafi@example.com")

        self.assertIsNotNone(turn)
        self.assertTrue(turn.lead["confirmation_required"])
        self.assertEqual(turn.lead["budget"], "To discuss with AllOfTech")
        self.assertEqual(turn.lead["timeline"], "Flexible / to discuss")

    def test_explicit_updates_change_existing_fields(self) -> None:
        session_id = "update-session"

        self.manager.handle_message(session_id, "I need a website")
        turn = self.manager.handle_message(session_id, "change service to mobile app")

        self.assertIsNotNone(turn)
        self.assertEqual(turn.lead["service"], "Mobile app development")
        self.assertIn("Mobile app development", turn.answer)

    def test_user_can_pause_lead_collection_mid_flow(self) -> None:
        session_id = "pause-session"

        self.manager.handle_message(session_id, "How can I order a custom RAG chatbot?")
        turn = self.manager.handle_message(session_id, "nope not right now")

        self.assertIsNotNone(turn)
        self.assertIn("won't collect or send a request", turn.answer)
        self.assertFalse(turn.lead["confirmation_required"])
        self.assertIsNone(self.manager.get_state(session_id))

        next_turn = self.manager.handle_message(session_id, "nope not right now")
        self.assertIsNone(next_turn)

    def test_support_request_collects_urgency_and_contact_method(self) -> None:
        session_id = "support-session"

        self.manager.handle_message(session_id, "I need support, my website is broken")
        self.manager.handle_message(session_id, "Critical, users cannot submit forms")
        self.manager.handle_message(session_id, "My name is Nadia")
        self.manager.handle_message(session_id, "nadia@example.com")
        turn = self.manager.handle_message(session_id, "Google Meet")

        self.assertIsNotNone(turn)
        self.assertTrue(turn.lead["confirmation_required"])
        self.assertEqual(turn.lead["request_type"], "support")
        self.assertIn("Support Request", turn.answer)


if __name__ == "__main__":
    unittest.main()
