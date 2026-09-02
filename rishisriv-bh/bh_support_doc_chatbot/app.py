import boto3
import gradio as gr
import requests
from huggingface_hub import InferenceClient
import uuid
from datetime import datetime
from urllib.parse import urlparse, parse_qs
import os

# Initialize DeepSeek via HuggingFace
hf_token = os.environ.get("HF_TOKEN", "")
client = InferenceClient(model="deepseek-ai/DeepSeek-V3", token=hf_token)

# Initialize AWS SES
ses = boto3.client("ses",
                   aws_access_key_id=os.environ.get("access_key"),
                   aws_secret_access_key=os.environ.get("secret_access_key"),
                   region_name="us-east-1")


def get_username_from_request(request: gr.Request):
    if request and request.url:
        parsed = urlparse(str(request.url))
        params = parse_qs(parsed.query)
        username = params.get("userName", ["UnknownUser"])[0]
        email = params.get("userEmail", ["UnknownUser"])[0]
        return username, email
    return "UnknownUser", "unknown@email.com"


def fetch_google_doc_text(doc_id: str):
    """Fetch documentation from Google Docs.

    Returns the document text, or None if it could not be fetched. Returning
    None (rather than an error string) matters: the return value becomes the
    chatbot's entire knowledge base, so an error string would silently turn
    every answer into "I don't have information about that" and fire an
    unanswered-question email to support on every single message.

    A Doc that is not shared as "anyone with the link can view" answers the
    unauthenticated export request with an HTML sign-in page, so the body is
    validated and not just the status code.
    """
    export_url = f"https://docs.google.com/document/d/{doc_id}/export?format=txt"
    try:
        response = requests.get(export_url, timeout=10)
    except Exception as e:
        print(f"[kb] Google Doc fetch failed for {doc_id}: {e}")
        return None

    if response.status_code != 200:
        print(f"[kb] Google Doc {doc_id} returned HTTP {response.status_code} "
              f"(is it shared as 'anyone with the link'?)")
        return None

    text = response.text.strip()
    if text.lstrip().lower().startswith("<!doctype html") or "<html" in text[:200].lower():
        print(f"[kb] Google Doc {doc_id} returned an HTML page, not document text "
              f"(is it shared as 'anyone with the link'?)")
        return None
    if len(text) < 2000:
        print(f"[kb] Google Doc {doc_id} returned only {len(text)} chars — treating as a bad fetch")
        return None

    return text


def load_bundled_knowledge_base():
    """Read the knowledge base snapshot committed alongside this Space."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "knowledge_base.md")
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read().strip()
    except Exception as e:
        print(f"[kb] Could not read bundled knowledge_base.md: {e}")
        return ""


# knowledge_base.md in this repo is the source of truth. It is written against the
# code that is actually deployed to production, and it is versioned with the app.
#
# A Google Doc can OVERRIDE it, so support can edit answers without a code change:
# set the Space secret/variable KB_GOOGLE_DOC_ID to the Doc's id and restart. The
# Doc must be shared as "anyone with the link can view", because it is fetched
# unauthenticated.
#
# The override is opt-in rather than hard-coded on purpose. Pointing at a Doc that
# has drifted behind this file silently downgrades every answer the bot gives, and
# a stale Doc is indistinguishable from a fresh one at runtime — so switching the
# override on should be a deliberate act, not the default.
GOOGLE_DOC_ID = os.environ.get("KB_GOOGLE_DOC_ID", "").strip()

if GOOGLE_DOC_ID:
    doc_context = fetch_google_doc_text(GOOGLE_DOC_ID)
    if doc_context:
        print(f"[kb] Loaded knowledge base from Google Doc {GOOGLE_DOC_ID} "
              f"({len(doc_context)} chars)")
    else:
        doc_context = load_bundled_knowledge_base()
        print(f"[kb] Google Doc override failed — using bundled knowledge_base.md "
              f"({len(doc_context)} chars)")
else:
    doc_context = load_bundled_knowledge_base()
    print(f"[kb] Loaded bundled knowledge_base.md ({len(doc_context)} chars). "
          f"Set KB_GOOGLE_DOC_ID to override from a Google Doc.")

# Where a reader can actually open the documentation, if anywhere.
#
# Citing "see §22.2" to a customer who has no way to open the document is worse
# than citing nothing — it points at a shelf they cannot reach. So the citation
# rule below is derived from whether a reachable URL exists:
#   * KB_DOC_URL set            -> cite the section AND give the link
#   * KB_GOOGLE_DOC_ID set      -> same, using that Doc's URL (it must be shared
#                                  as "anyone with the link" for the bot to have
#                                  read it in the first place)
#   * neither                   -> do not cite sections at all
KB_DOC_URL = os.environ.get("KB_DOC_URL", "").strip()
if not KB_DOC_URL and GOOGLE_DOC_ID:
    KB_DOC_URL = f"https://docs.google.com/document/d/{GOOGLE_DOC_ID}/edit"

if KB_DOC_URL:
    CITATION_RULE = (
        "   - When you reference a section of the documentation, give the reader the link so they "
        f"can open it: {KB_DOC_URL}\n"
        "   - Write it as a full sentence they can act on, e.g. \"See the Vendor COI compliance "
        f"section of the documentation: {KB_DOC_URL}\". Name the section rather than only its "
        "number, because numbers shift as the document is edited."
    )
else:
    CITATION_RULE = (
        "   - Do NOT cite section numbers or say \"see section X of the documentation\". The reader "
        "has no way to open that document, so a reference to it is a dead end that makes the answer "
        "look incomplete. Give them the answer itself instead, and point to "
        "support@beiinghuman.com when something genuinely falls outside what you know."
    )

print(f"[kb] Documentation link for citations: {KB_DOC_URL or '(none — section citations disabled)'}")

# Store chat history for email logging
chat_history = []


def send_email_if_needed(username, message, bot_response, email):
    """Send email notification when bot cannot answer"""
    trigger_phrases = [
        "I don't have information",
        "not found in the documentation"
    ]

    should_send = (
            any(phrase.lower() in bot_response.lower() for phrase in trigger_phrases) or
            len(bot_response) < 50
    )

    if should_send:
        sender_email = "process@documents.beiinghuman.com"
        recipient_emails = ["rishi@beiinghuman.com", "support@beiinghuman.com", "ubaid@beiinghuman.com"]

        session_id = str(uuid.uuid4())
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        log = (
            f"UNANSWERED QUESTION ALERT\n"
            f"{'=' * 60}\n"
            f"Session ID: {session_id}\n"
            f"Timestamp: {timestamp}\n"
            f"User: {username}\n"
            f"Email: {email}\n"
            f"{'=' * 60}\n\n"
            f"CONVERSATION HISTORY:\n"
            f"{'-' * 60}\n"
        )

        for i, (user_msg, bot_msg) in enumerate(chat_history, 1):
            log += f"\n[{i}] {user_msg}\n"
            log += f"Bot: {bot_msg}\n"
            log += f"{'-' * 60}\n"

        log += (
            f"\n\nACTION REQUIRED:\n"
            f"Please review this conversation and update the documentation.\n"
        )

        try:
            ses.send_email(
                Source=sender_email,
                Destination={'ToAddresses': recipient_emails},
                Message={
                    'Subject': {'Data': f"Unanswered FAQ - {username}"},
                    'Body': {'Text': {'Data': log}}
                }
            )
            print(f"Email notification sent to {recipient_email}")
        except Exception as e:
            print(f"Error sending email: {e}")
        finally:
            chat_history.clear()


def respond(message, history, system_message, max_tokens, temperature, top_p, request: gr.Request):
    """Main chatbot response function using DeepSeek"""
    try:
        username, email = get_username_from_request(request)

        # Enhanced system prompt with better instructions
        system_prompt = f"""You are a knowledgeable support assistant for Beiing Human, an invoice processing and approval platform.
ROLE: Answer user questions accurately using ONLY the documentation provided below.
RESPONSE GUIDELINES:
1. ACCURACY — this is the rule that matters most. Every factual statement you make must be traceable
   to a specific sentence in the documentation below. In particular:
   - Do NOT add prerequisites, requirements, dependencies or settings that the documentation does not
     state. If the documentation lists three conditions, list those three — never a fourth that seems
     plausible.
   - Do NOT carry a setting over from one feature to another because it sounds related.
   - If you are unsure whether a detail is in the documentation, leave it out. A short answer that is
     entirely correct is far better than a complete-looking answer containing one invented step.
   - The user is an accounting professional acting on your answer against real invoices. An invented
     step costs them real time and trust.
2. EXACT FEATURE NAMES: If the user names a specific feature and that exact capability is not in the
   documentation, say so directly. Do NOT answer about a different, similarly-named feature as if it
   were the same thing — check the "Names that sound like features but are not available" section
   first. Answering about PO matching when the user asked about PO *receipt* matching is a wrong
   answer, not a helpful approximation.
3. CLARITY: 
   - Write in clear, professional language
   - Use numbered steps for procedures
   - Break complex topics into digestible sections
   - Use bullet points for lists of features or options
4. RECOGNITION:
   - Understand user intent even with different wording (e.g., "recall" = "pull back", "remove" = "delete")
   - Match questions to relevant documentation sections
   - Recognize abbreviated terms (PO = Purchase Order, DT = Delivery Ticket, HIL = Human-in-the-Loop)
5. STRUCTURE:
   - Start with a direct answer
   - Follow with step-by-step instructions if applicable
   - Add relevant context or tips at the end
   - Keep responses concise but complete
6. WHEN INFORMATION IS MISSING:
   If the documentation doesn't contain the answer, respond with:
   "I don't have information about that in the current documentation. Please contact support@beiinghuman.com for assistance with this specific question."
7. FORMATTING:
   - Use **bold** for important terms or actions
   - Use numbered lists (1. 2. 3.) for sequential steps
   - Use bullet points (•) for non-sequential items
{CITATION_RULE}
DOCUMENTATION:
---
{doc_context}
---
Remember: Your goal is to help users quickly find accurate information. Be helpful, precise, and professional."""

        # Build messages
        messages = [
            {"role": "system", "content": system_prompt}
        ]

        # Add conversation history
        for user_msg, assistant_msg in history:
            messages.append({"role": "user", "content": user_msg})
            messages.append({"role": "assistant", "content": assistant_msg})

        # Add current message
        messages.append({"role": "user", "content": message})

        # Stream response from DeepSeek
        response = ""
        try:
            for chunk in client.chat_completion(
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    top_p=top_p,
                    stream=True
            ):
                # Safe access with multiple checks
                if hasattr(chunk, 'choices') and len(chunk.choices) > 0:
                    choice = chunk.choices[0]
                    if hasattr(choice, 'delta'):
                        delta = choice.delta
                        if hasattr(delta, 'content') and delta.content is not None:
                            token = delta.content
                            response += token
                            yield response
        except IndexError as e:
            print(f"IndexError in streaming: {e}")
            if not response:
                response = "I apologize, but I encountered an error processing your request. Please try again."
                yield response
        except Exception as stream_error:
            print(f"Streaming error: {stream_error}")
            if not response:
                response = "I apologize, but I encountered an error processing your request. Please try again."
                yield response

        # Save to history and check if email notification needed
        if response:  # Only save if we got a response
            chat_history.append((f"{username}: {message}", response))
            send_email_if_needed(username, message, response, email)

    except Exception as e:
        print(f"Error in respond function: {str(e)}")
        error_message = f"Error: {str(e)}\n\nPlease try again or contact support if the issue persists."
        yield error_message


# Gradio UI Setup
demo = gr.ChatInterface(
    respond,
    additional_inputs=[
        gr.Textbox(value="", label="System message", visible=False),
        gr.Slider(minimum=64, maximum=32000, value=2000, step=64, label="Max tokens", visible=False),
        gr.Slider(minimum=0.0, maximum=1.5, value=0.3, step=0.1, label="Temperature", visible=False),
        gr.Slider(minimum=0.0, maximum=1.0, value=0.95, step=0.05, label="Top-p", visible=False),
    ],
    title="💬 Beiing Human FAQ Chatbot",
    description=(
        "Ask questions on how to use Beiing Human App.\n\n"
        "I can help you with:\n"
        "• Document submission and processing\n"
        "• Invoice matching and approval workflows\n"
        "• User management and ERP integration\n"
        "• Reports and advanced features\n"
        "• Troubleshooting common issues\n\n"
    ),
    examples=[
        ["How do I upload invoices?"],
        ["What does the INYA report show?"],
        ["How do I match an invoice to a PO?"],
        ["How can I invite new users?"],
        ["What are the different document statuses?"],
        ["How does the Q&A feature work?"],
        ["How do I use the pull back feature?"],
        ["What is a Sub Admin and what can they do?"],
        ["How do I integrate with Foundation ERP?"],
        ["What's the difference between Approved and Verified statuses?"],
        ["How do I attach a delivery ticket to an invoice?"],
    ],
    css="""
    /* Override Gradio's CSS variables to force dark theme */
    :root {
        --background-fill-primary: #141414 !important;
        --background-fill-secondary: #1e1e1e !important;
        --body-text-color: #ffffff !important;
        --body-text-color-subdued: #cccccc !important;
        --color-accent: #ffffff !important;
        --color-accent-soft: #333333 !important;
        --border-color-primary: #444444 !important;
        --border-color-accent: #555555 !important;
        --neutral-100: #141414 !important;
        --neutral-200: #1e1e1e !important;
        --neutral-300: #333333 !important;
        --neutral-400: #444444 !important;
        --neutral-500: #555555 !important;
        --neutral-600: #666666 !important;
        --neutral-700: #777777 !important;
        --neutral-800: #888888 !important;
        --neutral-900: #999999 !important;
    }
    /* Force dark mode styles */
    body, html, .app, .gradio-container {
        background-color: #141414 !important;
        color: #ffffff !important;
    }
    textarea,
    input,
    .message,
    .chatbot {
        background-color: unset !important;
    }
    /* Only force text color on specific elements, not everything */
    body, html, .gradio-container, 
    .chatbot, .message, 
    textarea, input, 
    label, p, span, div.block,
    h1, h2, h3, h4, h5, h6 {
        color: #ffffff !important;
    }
    /* Input styling */
    textarea, input {
        background-color: #1e1e1e !important;
        color: #ffffff !important;
        border: 1px solid #444444 !important;
    }
    """
)

if __name__ == "__main__":
    demo.launch()