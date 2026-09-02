"""Lead capture workflow for turning chat visitors into service requests."""

from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib.error
import urllib.request
from collections import OrderedDict
from dataclasses import asdict, dataclass, field
from threading import RLock
from typing import Any, Literal

logger = logging.getLogger(__name__)

LeadStatus = Literal["collecting", "awaiting_confirmation", "submitted"]
RequestType = Literal["service", "meeting", "support", "general_contact"]

_EMAILJS_ENDPOINT = "https://api.emailjs.com/api/v1.0/email/send"


@dataclass
class LeadDraft:
    """Information collected from a potential AllOfTech customer."""

    session_id: str
    status: LeadStatus = "collecting"
    request_type: RequestType | str = ""
    service: str = ""
    project_details: str = ""
    meeting_purpose: str = ""
    preferred_date: str = ""
    preferred_time: str = ""
    timezone_or_location: str = ""
    support_details: str = ""
    company_name: str = ""
    industry: str = ""
    website_url: str = ""
    main_goal: str = ""
    urgency: str = ""
    name: str = ""
    email: str = ""
    phone: str = ""
    budget: str = ""
    timeline: str = ""
    preferred_contact: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    submitted_at: float | None = None

    def public_state(self) -> dict[str, Any]:
        data = asdict(self)
        data["missing_fields"] = self.missing_fields()
        data["confirmation_required"] = self.status == "awaiting_confirmation"
        data.pop("created_at", None)
        data.pop("updated_at", None)
        return data

    def missing_fields(self) -> list[str]:
        required_by_type: dict[str, tuple[str, ...]] = {
            "service": (
                "service",
                "project_details",
                "name",
                "budget",
                "timeline",
                "preferred_contact",
            ),
            "meeting": (
                "meeting_purpose",
                "preferred_date",
                "preferred_time",
                "timezone_or_location",
                "name",
                "preferred_contact",
            ),
            "support": (
                "support_details",
                "urgency",
                "name",
                "preferred_contact",
            ),
            "general_contact": (
                "support_details",
                "name",
                "preferred_contact",
            ),
        }
        missing = [
            field_name
            for field_name in ("request_type",) + required_by_type.get(self.request_type, ())
            if not getattr(self, field_name)
        ]
        if self.request_type and not (self.email or self.phone):
            missing.append("contact_details")
        return missing


@dataclass
class LeadTurn:
    """A lead-capture response returned to the chat layer."""

    answer: str
    lead: dict[str, Any]
    emailjs: dict[str, Any] | None = None
    submitted: bool = False


class EmailJSLeadSender:
    """Send confirmed leads through EmailJS.

    The IDs below are public in EmailJS frontend integrations. They can be
    overridden in Hugging Face Space secrets or `.env` for production.
    """

    def __init__(self) -> None:
        self.public_key = os.getenv("EMAILJS_PUBLIC_KEY", "kgXIjzhce1SbUpve9")
        self.service_id = os.getenv("EMAILJS_SERVICE_ID", "service_lkha1el")
        self.template_id = os.getenv("EMAILJS_TEMPLATE_ID", "template_hat5kie")
        self.access_token = os.getenv("EMAILJS_ACCESS_TOKEN") or os.getenv("EMAILJS_PRIVATE_KEY")

    def browser_payload(self, lead: LeadDraft) -> dict[str, Any]:
        """Return the exact data the frontend needs for `emailjs.send(...)`."""
        return {
            "public_key": self.public_key,
            "service_id": self.service_id,
            "template_id": self.template_id,
            "template_params": build_emailjs_template_params(lead),
        }

    def send(self, lead: LeadDraft) -> None:
        payload = {
            "service_id": self.service_id,
            "template_id": self.template_id,
            "user_id": self.public_key,
            "template_params": build_emailjs_template_params(lead),
        }
        if self.access_token:
            payload["accessToken"] = self.access_token

        request = urllib.request.Request(
            _EMAILJS_ENDPOINT,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "User-Agent": "AllOfTech-RAG-Chatbot/1.0",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                if response.status >= 400:
                    raise RuntimeError(f"EmailJS returned HTTP {response.status}")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"EmailJS returned HTTP {exc.code}: {body}") from exc


class LeadCaptureManager:
    """Collect AllOfTech request details step-by-step and submit confirmed leads."""

    _EMAIL_RE = re.compile(r"[\w.\-+]+@[\w.\-]+\.\w+")
    _PHONE_RE = re.compile(r"(?:\+?\d[\d\s().-]{7,}\d)")
    _URL_RE = re.compile(r"https?://\S+|(?:www\.)?[\w-]+\.[a-z]{2,}(?:/\S*)?", re.I)
    _YES_RE = re.compile(r"\b(yes|yeah|yep|sure|confirm|confirmed|send it|submit|go ahead)\b", re.I)
    _NO_RE = re.compile(r"\b(no|nope|not yet|wait|edit|change|wrong|cancel)\b", re.I)
    _PAUSE_RE = re.compile(
        r"\b("
        r"nope\s+not\s+right\s+now|not\s+right\s+now|not\s+now|maybe\s+later|later|"
        r"stop|cancel|never\s+mind|nevermind|not\s+interested|don't\s+want|dont\s+want"
        r")\b",
        re.I,
    )
    _UNSURE_RE = re.compile(
        r"\b("
        r"not\s+sure|don't\s+know|dont\s+know|no\s+idea|unsure|flexible|to\s+discuss|"
        r"discuss\s+later|no\s+budget|not\s+decided|skip|prefer\s+not\s+to\s+say"
        r")\b",
        re.I,
    )
    _SIDE_QUESTION_RE = re.compile(
        r"^\s*(what|how|why|when|where|which|can|could|do|does|is|are|will|would)\b",
        re.I,
    )
    _INTENT_RE = re.compile(
        r"\b("
        r"i want|i need|i'm looking for|im looking for|build|create|make|order|buy|hire|"
        r"quote|pricing|proposal|consultation|consult|meeting|schedule|appointment|call|"
        r"talk to|speak with|contact|message your team|reach your team|"
        r"support|maintenance|bug|issue|problem|fix|help with|"
        r"website|web app|mobile app|app|chatbot|rag|ai bot|ai chatbot|automation|"
        r"ai/ml|machine learning|blockchain|branding|logo|ui/ux|ux/ui|animation|motion graphics"
        r")\b",
        re.I,
    )
    _MEETING_RE = re.compile(
        r"\b(meeting|schedule|appointment|consultation|consult|call|google meet|zoom|"
        r"talk to|talk with|speak to|speak with|book)\b",
        re.I,
    )
    _SUPPORT_RE = re.compile(
        r"\b(support|maintenance|bug|issue|problem|fix|broken|not working|error|"
        r"help with existing|after delivery)\b",
        re.I,
    )
    _CONTACT_RE = re.compile(
        r"\b(contact|message|reach|email your team|talk with your team|connect me|"
        r"send a message)\b",
        re.I,
    )
    _SERVICE_RE = re.compile(
        r"\b(build|create|make|order|buy|hire|quote|pricing|proposal|project|service|"
        r"website|web app|mobile app|app|chatbot|rag|ai bot|ai chatbot|automation|"
        r"ai/ml|machine learning|blockchain|branding|logo|ui/ux|ux/ui|animation|motion graphics)\b",
        re.I,
    )

    def __init__(self, sender: EmailJSLeadSender | None = None, max_sessions: int = 500) -> None:
        self.sender = sender or EmailJSLeadSender()
        self.max_sessions = max_sessions
        self.delivery_mode = os.getenv("EMAILJS_DELIVERY_MODE", "frontend").lower()
        self._lock = RLock()
        self._drafts: OrderedDict[str, LeadDraft] = OrderedDict()

    def handle_message(self, session_id: str, message: str) -> LeadTurn | None:
        """Return a lead-capture response for AllOfTech business request flows."""
        text = message.strip()
        if not text:
            return None

        with self._lock:
            draft = self._drafts.get(session_id)

            if draft is None and not self._looks_like_lead_intent(text):
                return None

            if draft is None:
                draft = LeadDraft(
                    session_id=session_id,
                    request_type=self._detect_request_type(text),
                )
                self._drafts[session_id] = draft

            self._drafts.move_to_end(session_id)

            if draft.status == "collecting" and self._looks_like_pause_or_cancel(text):
                self._drafts.pop(session_id, None)
                return LeadTurn(
                    answer=(
                        "No problem. I won't collect or send a request right now. "
                        "You can still ask me about AllOfTech services, pricing, meetings, or support anytime."
                    ),
                    lead=empty_lead_state(session_id),
                )

            if draft.status == "collecting" and self._looks_like_side_question(text):
                return None

            self._apply_message(draft, text)

            if draft.status == "awaiting_confirmation":
                if self._YES_RE.search(text):
                    return self._submit(draft)
                if self._NO_RE.search(text):
                    draft.status = "collecting"
                    draft.updated_at = time.time()
                    return LeadTurn(
                        answer=(
                            "No problem. Tell me what you want to change, and I'll update the request "
                            "before sending it to our team."
                        ),
                        lead=draft.public_state(),
                    )

            missing = draft.missing_fields()
            if missing:
                draft.status = "collecting"
                draft.updated_at = time.time()
                return LeadTurn(answer=self._next_question(draft, missing[0]), lead=draft.public_state())

            draft.status = "awaiting_confirmation"
            draft.updated_at = time.time()
            return LeadTurn(
                answer=build_lead_summary(draft, include_confirmation_question=True),
                lead=draft.public_state(),
                emailjs=self.sender.browser_payload(draft),
            )

    def get_state(self, session_id: str) -> dict[str, Any] | None:
        with self._lock:
            draft = self._drafts.get(session_id)
            return draft.public_state() if draft else None

    def confirm(self, session_id: str) -> LeadTurn:
        """Prepare a draft for the frontend confirmation button.

        In frontend delivery mode, this does not mark the lead as submitted.
        The browser must first call `emailjs.send(...)`, then call
        `mark_submitted()`.
        """
        with self._lock:
            draft = self._drafts.get(session_id)
            if draft is None:
                return LeadTurn(
                    answer="I don't have an AllOfTech request ready to send yet.",
                    lead=empty_lead_state(session_id),
                )

            missing = draft.missing_fields()
            if missing:
                draft.status = "collecting"
                return LeadTurn(
                    answer=self._next_question(draft, missing[0]),
                    lead=draft.public_state(),
                )

            draft.status = "awaiting_confirmation"
            if self.delivery_mode == "frontend":
                return LeadTurn(
                    answer="Ready to send. Please send this request through the website email service.",
                    lead=draft.public_state(),
                    emailjs=self.sender.browser_payload(draft),
                )
            return self._submit(draft)

    def mark_submitted(self, session_id: str) -> LeadTurn:
        """Mark the lead submitted after the browser EmailJS request succeeds."""
        with self._lock:
            draft = self._drafts.get(session_id)
            if draft is None:
                return LeadTurn(
                    answer="The request was sent, but I no longer have the draft in this session.",
                    lead=empty_lead_state(session_id),
                    submitted=True,
                )

            draft.status = "submitted"
            draft.submitted_at = time.time()
            draft.updated_at = draft.submitted_at
            return LeadTurn(
                answer=(
                    f"Perfect, your {request_type_label(draft).lower()} has been sent to the "
                    "AllOfTech team. We'll review it and contact you soon."
                ),
                lead=draft.public_state(),
                submitted=True,
            )

    def cancel(self, session_id: str) -> LeadTurn:
        """Cancel a draft after a frontend cancel/edit button click."""
        with self._lock:
            draft = self._drafts.pop(session_id, None)
            lead = (
                draft.public_state()
                if draft
                else empty_lead_state(session_id)
            )
            return LeadTurn(
                answer="No problem. I won't send this request. You can start again anytime.",
                lead=lead,
            )

    def clear(self, session_id: str) -> bool:
        with self._lock:
            return self._drafts.pop(session_id, None) is not None

    def _submit(self, draft: LeadDraft) -> LeadTurn:
        if self.delivery_mode == "frontend":
            return LeadTurn(
                answer=(
                    "Ready to send. Please send this request through the website email service."
                ),
                lead=draft.public_state(),
                emailjs=self.sender.browser_payload(draft),
            )

        try:
            self.sender.send(draft)
        except Exception:
            logger.exception("Failed to send lead email for session %s.", draft.session_id)
            return LeadTurn(
                answer=(
                    "I collected the details, but I couldn't send the email right now. "
                    "Please contact us directly at contact@alloftech.site, or try again in a moment."
                ),
                lead=draft.public_state(),
            )

        draft.status = "submitted"
        draft.submitted_at = time.time()
        draft.updated_at = draft.submitted_at
        return LeadTurn(
            answer=(
                f"Perfect, your {request_type_label(draft).lower()} has been sent to the "
                "AllOfTech team. We'll review it and contact you soon using the details you provided."
            ),
            lead=draft.public_state(),
            submitted=True,
        )

    def _looks_like_lead_intent(self, text: str) -> bool:
        return bool(self._INTENT_RE.search(text))

    def _detect_request_type(self, text: str) -> str:
        if self._looks_like_meeting_intent(text):
            return "meeting"
        if self._SUPPORT_RE.search(text):
            return "support"
        if self._SERVICE_RE.search(text) or extract_service(text):
            return "service"
        if self._CONTACT_RE.search(text):
            return "general_contact"
        return "general_contact"

    def _looks_like_meeting_intent(self, text: str) -> bool:
        return bool(self._MEETING_RE.search(text))

    def _looks_like_pause_or_cancel(self, text: str) -> bool:
        return bool(self._PAUSE_RE.search(text))

    def _looks_like_side_question(self, text: str) -> bool:
        if not (text.endswith("?") or self._SIDE_QUESTION_RE.search(text)):
            return False
        # Let direct data replies such as "email is..." or "my name is..." keep filling the form.
        if self._EMAIL_RE.search(text) or self._PHONE_RE.search(text):
            return False
        if extract_name(text) or extract_company_name(text):
            return False
        return True

    def _apply_message(self, draft: LeadDraft, text: str) -> None:
        if not draft.request_type:
            draft.request_type = self._detect_request_type(text)

        missing_before_update = draft.missing_fields()
        expected = missing_before_update[0] if missing_before_update else ""
        if self._apply_explicit_update(draft, text):
            return
        if self._apply_uncertain_answer(draft, expected, text):
            return

        email_match = self._EMAIL_RE.search(text)
        if email_match:
            draft.email = email_match.group(0)

        phone_match = self._PHONE_RE.search(text)
        if phone_match:
            draft.phone = phone_match.group(0).strip()

        lowered = text.lower()
        if "whatsapp" in lowered:
            draft.preferred_contact = "WhatsApp"
        elif "phone" in lowered or "call" in lowered:
            draft.preferred_contact = "Phone"
        elif "email" in lowered:
            draft.preferred_contact = "Email"

        service = extract_service(text)
        if service:
            draft.service = service

        name = extract_name(text)
        if name:
            draft.name = name

        company = extract_company_name(text)
        if company:
            draft.company_name = company

        url = self._URL_RE.search(text)
        if url:
            draft.website_url = url.group(0).strip(" .,)")

        industry = extract_industry(text)
        if industry:
            draft.industry = industry

        if _contains_urgency(text):
            draft.urgency = clean_user_value(text)

        if draft.request_type == "meeting":
            date_hint = extract_date_hint(text)
            time_hint = extract_time_hint(text)
            timezone_hint = extract_timezone_or_location(text)
            if date_hint:
                draft.preferred_date = date_hint
            if time_hint:
                draft.preferred_time = time_hint
            if timezone_hint:
                draft.timezone_or_location = timezone_hint

        cleaned = clean_user_value(text)

        if expected == "request_type":
            draft.request_type = self._detect_request_type(text)
        elif expected == "service" and not draft.service:
            draft.service = service or cleaned
        elif expected == "project_details" and not _looks_like_short_confirmation(text):
            draft.project_details = cleaned
        elif expected == "meeting_purpose" and not _looks_like_generic_meeting_start(text):
            draft.meeting_purpose = cleaned
        elif expected == "preferred_date":
            draft.preferred_date = extract_date_hint(text) or cleaned
        elif expected == "preferred_time":
            draft.preferred_time = extract_time_hint(text) or cleaned
        elif expected == "timezone_or_location":
            draft.timezone_or_location = extract_timezone_or_location(text) or cleaned
        elif expected == "support_details" and not _looks_like_short_confirmation(text):
            draft.support_details = cleaned
        elif expected == "name" and not draft.name:
            draft.name = cleaned
        elif expected == "email" and not draft.email:
            # Leave email empty if the visitor did not provide a valid email.
            pass
        elif expected == "phone" and not draft.phone:
            # Leave phone empty if the visitor did not provide a recognizable number.
            pass
        elif expected == "contact_details":
            # Leave contact empty unless a valid email or phone was extracted above.
            pass
        elif expected == "budget":
            draft.budget = cleaned
        elif expected == "timeline":
            draft.timeline = cleaned
        elif expected == "preferred_contact" and not draft.preferred_contact:
            draft.preferred_contact = normalize_contact_method(cleaned)
        elif expected == "urgency":
            draft.urgency = cleaned
        elif expected == "company_name":
            draft.company_name = cleaned
        elif expected == "industry":
            draft.industry = cleaned
        elif expected == "website_url":
            draft.website_url = cleaned
        elif expected == "main_goal":
            draft.main_goal = cleaned

        if expected not in ("email", "timeline") and _contains_budget(text):
            draft.budget = cleaned
        if expected not in ("email", "budget") and _contains_timeline(text):
            draft.timeline = cleaned
        if not draft.main_goal and _contains_goal(text):
            draft.main_goal = cleaned

    def _apply_explicit_update(self, draft: LeadDraft, text: str) -> bool:
        match = re.search(
            r"\b(?:change|update|set|make|use)\s+"
            r"(service|project|details|meeting|purpose|date|time|timezone|location|"
            r"support|message|name|email|phone|whatsapp|budget|timeline|contact|urgency)\s+"
            r"(?:to|as|is|:)\s+(.+)",
            text,
            re.I,
        )
        if not match:
            return False

        field_label = match.group(1).lower()
        value = clean_user_value(match.group(2))
        if not value:
            return False

        if field_label == "service":
            draft.service = extract_service(value) or value
        elif field_label in ("project", "details"):
            draft.project_details = value
        elif field_label in ("meeting", "purpose"):
            draft.meeting_purpose = value
        elif field_label == "date":
            draft.preferred_date = extract_date_hint(value) or value
        elif field_label == "time":
            draft.preferred_time = extract_time_hint(value) or value
        elif field_label in ("timezone", "location"):
            draft.timezone_or_location = extract_timezone_or_location(value) or value
        elif field_label in ("support", "message"):
            draft.support_details = value
        elif field_label == "name":
            draft.name = extract_name(f"my name is {value}") or value
        elif field_label == "email":
            email_match = self._EMAIL_RE.search(value)
            if email_match:
                draft.email = email_match.group(0)
        elif field_label in ("phone", "whatsapp"):
            phone_match = self._PHONE_RE.search(value)
            draft.phone = phone_match.group(0).strip() if phone_match else value
            if field_label == "whatsapp":
                draft.preferred_contact = "WhatsApp"
        elif field_label == "budget":
            draft.budget = value
        elif field_label == "timeline":
            draft.timeline = value
        elif field_label == "contact":
            draft.preferred_contact = normalize_contact_method(value)
        elif field_label == "urgency":
            draft.urgency = value
        return True

    def _apply_uncertain_answer(self, draft: LeadDraft, expected: str, text: str) -> bool:
        if not expected or not self._UNSURE_RE.search(text):
            return False

        flexible_value = "To discuss with AllOfTech"
        if expected == "budget":
            draft.budget = flexible_value
        elif expected == "timeline":
            draft.timeline = "Flexible / to discuss"
        elif expected == "preferred_contact":
            draft.preferred_contact = "Email or WhatsApp"
        elif expected == "phone":
            draft.phone = "Not provided"
        elif expected == "contact_details" and draft.phone:
            return True
        elif expected in ("preferred_date", "preferred_time", "timezone_or_location"):
            setattr(draft, expected, flexible_value)
        elif expected == "urgency":
            draft.urgency = "Flexible / not urgent"
        else:
            return False
        return True

    def _next_question(self, draft: LeadDraft, missing_field: str) -> str:
        if missing_field == "request_type":
            return (
                "Sure - should I prepare a service request, schedule a meeting, send a support "
                "request, or pass a general message to the AllOfTech team?"
            )
        if missing_field == "service":
            return (
                "Absolutely, we can help. Which service are you interested in: website, "
                "custom RAG chatbot, mobile app, AI/ML, blockchain, animation, UX/UI, or branding?"
            )
        if missing_field == "project_details":
            return (
                f"Great - for {draft.service}, tell me what you want to build and what problem "
                "you want it to solve."
            )
        if missing_field == "meeting_purpose":
            return "Of course. What would you like to discuss in the meeting with AllOfTech?"
        if missing_field == "preferred_date":
            return "What date works best for the meeting?"
        if missing_field == "preferred_time":
            return "What time works best for the meeting?"
        if missing_field == "timezone_or_location":
            return (
                "What timezone or location should we use for the meeting? "
                "For example: Dhaka/Bangladesh time, UTC+6, or your city."
            )
        if missing_field == "support_details":
            if draft.request_type == "support":
                return "Tell me what support you need, including the issue, product, or service involved."
            return "What message should I send to the AllOfTech team for you?"
        if missing_field == "name":
            return "Thanks. What name should our team use when contacting you?"
        if missing_field == "email":
            return "What email address should we use to reach you?"
        if missing_field == "phone":
            return "What phone or WhatsApp number should we use if the team needs to reach you quickly?"
        if missing_field == "contact_details":
            return "What email address or phone/WhatsApp number should our team use to reach you?"
        if missing_field == "budget":
            return "Do you have an estimated budget range for this project?"
        if missing_field == "timeline":
            return "What timeline are you aiming for? For example: urgent, 2 weeks, 1 month, or flexible."
        if missing_field == "preferred_contact":
            return "How would you prefer us to contact you: email, WhatsApp, phone, or Google Meet?"
        if missing_field == "urgency":
            return "How urgent is this request? For example: critical, this week, this month, or flexible."
        return "Tell me a little more so I can prepare the request for our team."


def build_lead_summary(draft: LeadDraft, include_confirmation_question: bool) -> str:
    request_label = request_type_label(draft)
    lines = [
        f"Perfect - here's the {request_label.lower()} I'll send to the AllOfTech team:",
        "",
        f"Request type: {request_label}",
    ]

    if draft.request_type == "meeting":
        lines.extend(
            [
                f"Meeting purpose: {draft.meeting_purpose}",
                f"Preferred date: {draft.preferred_date}",
                f"Preferred time: {draft.preferred_time}",
                f"Timezone/location: {draft.timezone_or_location}",
            ]
        )
    elif draft.request_type == "support":
        lines.extend(
            [
                f"Support details: {draft.support_details}",
                f"Urgency: {draft.urgency}",
            ]
        )
    elif draft.request_type == "general_contact":
        lines.append(f"Message: {draft.support_details}")
    else:
        lines.extend(
            [
                f"Service: {draft.service}",
                f"Project: {draft.project_details}",
                f"Budget: {draft.budget}",
                f"Timeline: {draft.timeline}",
            ]
        )

    optional_details = [
        ("Company/brand", draft.company_name),
        ("Industry", draft.industry),
        ("Website/app link", draft.website_url),
        ("Main goal", draft.main_goal),
    ]
    lines.extend(f"{label}: {value}" for label, value in optional_details if value)

    lines.extend(
        [
            f"Name: {draft.name}",
            f"Email: {draft.email}",
            f"Phone/WhatsApp: {draft.phone or 'Not provided'}",
            f"Preferred contact: {draft.preferred_contact or 'Email'}",
        ]
    )

    if include_confirmation_question:
        lines.extend(
            [
                "",
                "Please confirm: should I send this request to the AllOfTech team so they can contact you?",
                'Reply "yes, send it" to confirm, or tell me what you want to change.',
            ]
        )
    return "\n".join(lines)


def build_emailjs_template_params(lead: LeadDraft) -> dict[str, str]:
    """Build params for the existing EmailJS template used by the website."""
    return {
        # These match the existing website form fields/template variables.
        "name": lead.name,
        "email": lead.email,
        "subject": f"AllOfTech {request_type_label(lead)} from {lead.name or 'website visitor'}",
        "message": build_lead_summary(lead, include_confirmation_question=False),
        # Extra variables are useful if the EmailJS template is expanded later.
        "request_type": lead.request_type or "general_contact",
        "service": lead.service,
        "project_details": lead.project_details,
        "meeting_purpose": lead.meeting_purpose,
        "preferred_date": lead.preferred_date,
        "preferred_time": lead.preferred_time,
        "timezone_or_location": lead.timezone_or_location,
        "support_details": lead.support_details,
        "company_name": lead.company_name,
        "industry": lead.industry,
        "website_url": lead.website_url,
        "main_goal": lead.main_goal,
        "urgency": lead.urgency,
        "phone": lead.phone or "Not provided",
        "budget": lead.budget,
        "timeline": lead.timeline,
        "preferred_contact": lead.preferred_contact or "Email",
        "session_id": lead.session_id,
    }


def empty_lead_state(session_id: str) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "status": "collecting",
        "request_type": "",
        "service": "",
        "project_details": "",
        "meeting_purpose": "",
        "preferred_date": "",
        "preferred_time": "",
        "timezone_or_location": "",
        "support_details": "",
        "company_name": "",
        "industry": "",
        "website_url": "",
        "main_goal": "",
        "urgency": "",
        "name": "",
        "email": "",
        "phone": "",
        "budget": "",
        "timeline": "",
        "preferred_contact": "",
        "submitted_at": None,
        "missing_fields": [],
        "confirmation_required": False,
    }


def extract_service(text: str) -> str:
    lowered = text.lower()
    service_map = (
        (("rag", "chatbot", "ai bot", "ai chatbot"), "Custom RAG chatbot"),
        (("website", "web app", "web development", "landing page"), "Website / web development"),
        (("mobile app", "android", "ios", "app"), "Mobile app development"),
        (("ai/ml", "machine learning", "artificial intelligence", "automation"), "AI/ML solution"),
        (("blockchain", "web3", "crypto"), "Blockchain solution"),
        (("animation", "motion graphics", "3d product", "architectural walkthrough"), "Animation services"),
        (("ux/ui", "ui/ux", "ui design", "ux design"), "UX/UI design"),
        (("branding", "logo", "graphics", "graphic"), "Graphics & branding"),
    )
    for keywords, label in service_map:
        if any(keyword in lowered for keyword in keywords):
            return label
    return ""


def extract_name(text: str) -> str:
    match = re.search(r"\b(?:my name is|i am|i'm|im)\s+([A-Za-z][A-Za-z .'-]{1,40})", text, re.I)
    if not match:
        return ""
    name = match.group(1).strip(" .")
    stop_words = ("and", "from", "with", "looking", "want", "need")
    for stop_word in stop_words:
        marker = f" {stop_word} "
        if marker in name.lower():
            name = name[: name.lower().index(marker)].strip()
    return name.title()


def extract_company_name(text: str) -> str:
    match = re.search(
        r"\b(?:company|brand|business|agency|startup)\s*(?:name\s*)?(?:is|:)\s+([A-Za-z0-9][\w .&'-]{1,60})",
        text,
        re.I,
    )
    if not match:
        match = re.search(r"\bfrom\s+([A-Za-z0-9][\w .&'-]{1,60})", text, re.I)
    if not match:
        return ""
    company = match.group(1).strip(" .")
    stop_words = ("and", "with", "for", "looking", "want", "need")
    for stop_word in stop_words:
        marker = f" {stop_word} "
        if marker in company.lower():
            company = company[: company.lower().index(marker)].strip()
    return company


def extract_industry(text: str) -> str:
    match = re.search(
        r"\b(?:industry|sector|business type)\s*(?:is|:)?\s+([A-Za-z][A-Za-z /&-]{2,50})",
        text,
        re.I,
    )
    if not match:
        return ""
    industry = match.group(1).strip(" .")
    for stop_word in ("and", "with", "for"):
        marker = f" {stop_word} "
        if marker in industry.lower():
            industry = industry[: industry.lower().index(marker)].strip()
    return industry


def extract_date_hint(text: str) -> str:
    patterns = [
        r"\b(?:today|tomorrow|tonight)\b",
        r"\bnext\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
        r"\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
        r"\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b",
        r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\s+\d{1,2}(?:,\s*\d{4})?\b",
        r"\b\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*(?:\s+\d{4})?\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            return match.group(0).strip()
    return ""


def extract_time_hint(text: str) -> str:
    patterns = [
        r"\b\d{1,2}(?::\d{2})?\s*(?:am|pm)\b",
        r"\b\d{1,2}:\d{2}\b",
        r"\b(?:morning|afternoon|evening|night|noon)\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            return match.group(0).strip()
    return ""


def extract_timezone_or_location(text: str) -> str:
    patterns = [
        r"\b(?:utc|gmt)\s*[+-]?\s*\d{1,2}\b",
        r"\b(?:bangladesh|dhaka|bd|india|pakistan|usa|uk|canada|australia|uae|dubai)\s*(?:time)?\b",
        r"\b(?:timezone|time zone|location)\s*(?:is|:)?\s+([A-Za-z0-9 /+-]{2,50})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            value = match.group(1) if match.groups() else match.group(0)
            return value.strip(" .")
    return ""


def normalize_contact_method(text: str) -> str:
    lowered = text.lower()
    if "whatsapp" in lowered:
        return "WhatsApp"
    if "phone" in lowered or "call" in lowered:
        return "Phone"
    if "meet" in lowered or "video" in lowered:
        return "Google Meet"
    if "email" in lowered:
        return "Email"
    return text.strip(" .").title()


def clean_user_value(text: str) -> str:
    text = re.sub(
        r"^\s*(my\s+)?(name|email|budget|timeline|phone|date|time|timezone|location|urgency)\s*(is|:)?\s*",
        "",
        text,
        flags=re.I,
    )
    return text.strip(" .")


def request_type_label(draft: LeadDraft) -> str:
    labels = {
        "service": "Service Request",
        "meeting": "Meeting Request",
        "support": "Support Request",
        "general_contact": "General Contact Request",
    }
    return labels.get(draft.request_type, "AllOfTech Request")


def _contains_budget(text: str) -> bool:
    lowered = text.lower()
    return "budget" in lowered or "$" in text or "৳" in text or "tk" in lowered


def _contains_timeline(text: str) -> bool:
    lowered = text.lower()
    return any(word in lowered for word in ("timeline", "deadline", "urgent", "week", "month", "day"))


def _contains_urgency(text: str) -> bool:
    lowered = text.lower()
    return any(word in lowered for word in ("urgent", "critical", "asap", "this week", "priority", "soon"))


def _contains_goal(text: str) -> bool:
    lowered = text.lower()
    return any(word in lowered for word in ("goal", "objective", "want to", "need to", "trying to"))


def _looks_like_short_confirmation(text: str) -> bool:
    return bool(re.fullmatch(r"\s*(yes|yeah|no|ok|okay|sure|confirm|send it)\s*", text, re.I))


def _looks_like_generic_meeting_start(text: str) -> bool:
    return bool(
        re.fullmatch(
            r"\s*(i\s+)?(want|need|would like)?\s*(to\s+)?(book|schedule|have)?\s*"
            r"(a\s+)?(meeting|call|consultation|appointment)\s*",
            text,
            re.I,
        )
    )
