"""
Probe tests for the chatbot's knowledge base.

Runs real questions through app.respond() — the same code path the Space serves —
so the system prompt, the knowledge base and the answer are exactly what a user
would get. send_email_if_needed is stubbed out, so no unanswered-question mail is
sent to the support alias; instead, a probe FAILS when the real code path *would*
have sent one. That is the signal worth testing: every question the bot cannot
answer becomes an email to rishi@, support@ and ubaid@.

A probe WARNs when the bot answers but never mentions a term a correct answer has
to contain — that catches an answer about the wrong feature.

    pip install -r requirements.txt
    HF_TOKEN=... python test_knowledge_base.py

Exit code is non-zero if anything failed or warned.
"""
import os
import sys

REPO = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, REPO)

if not os.environ.get("HF_TOKEN"):
    env = os.path.join(REPO, ".env")
    if os.path.exists(env):
        with open(env) as handle:
            for line in handle:
                if line.startswith("HF_TOKEN"):
                    os.environ["HF_TOKEN"] = line.split("=", 1)[1].strip().strip('"').strip("'")
if not os.environ.get("HF_TOKEN"):
    sys.exit("HF_TOKEN not set (environment or .env)")

import app  # noqa: E402 — imported after HF_TOKEN so the client picks it up

# Never mail the support alias from a test run — but keep the REAL decision
# logic. send_email_if_needed runs after every answer and decides internally
# whether to send, so stubbing that function would record every question rather
# than every alert. Stub the SES client underneath it instead: what lands here
# is exactly what production would have mailed.
would_have_emailed = []


class _RecordingSES:
    def send_email(self, **kwargs):
        would_have_emailed.append(kwargs)


app.ses = _RecordingSES()

# (question, a substring a correct answer must contain)
PROBES = [
    # --- file types (KB 5.7) ---
    ("Can I email an iPhone photo of an invoice?", "yes"),
    ("Why was my HEIC photo rejected when I dragged it into the web app?", "email"),
    ("Can I send an invoice as an Excel file?", "pdf"),
    ("What file types can Beiing Human read?", "png"),

    # --- pay control (KB 6.2, 6.5) ---
    ("What is the Pay Control column?", "erp"),
    ("Why can't I see the Pay Control column?", "foundation"),
    ("How do I set the pay control on several invoices at once?", "assign"),
    ("Can I bulk assign pay control on Vista?", "foundation"),
    ("A pay control name is missing from the list. Why?", "sync"),

    # --- annotation (KB 7.8) ---
    ("How do I put a TAX EXEMPT stamp on an invoice?", "annotate"),
    ("What stamps can I use on a document?", "void"),
    ("Can I write a job number on the invoice image?", "note"),
    ("How do I remove a stamp I already saved?", "again"),

    # --- mobile ---
    ("Is there a mobile app?", "android"),
    ("Where do I download the Beiing Human app?", "play"),
    ("Why can't I log into the mobile app?", "accountant"),
    ("Can our AP admin use the phone app?", "owner"),
    ("How do I upload a receipt from my phone?", "upload file"),
    ("I don't see the Create PO button on my phone, why?", "sign"),
    ("Why is there no approve button on the To Review list in the app?", "details"),
    ("The app says fix 3 issues before approving. What do I do?", "validation"),
    ("Can I reject an invoice on mobile without leaving a comment?", "comment"),
    ("Does the mobile app send push notifications?", "not"),
    ("How do I get out of the Update Required screen?", "store"),
    ("Can I edit an exported document on my phone?", "read-only"),
    ("How do I answer a question assigned to me in the app?", "reply"),
    ("Can I search for a specific invoice in the mobile app?", "web"),
    ("Can I match an invoice to a PO on my phone?", "web"),
    ("Why did my app log me out?", "session"),
    # --- web app regressions ---
    ("What does the INYA report show?", "approv"),
    ("How do I use the pull back feature?", "pull back"),
    ("What is a Sub Admin and what can they do?", "admin"),
    ("How do I attach a delivery ticket to an invoice?", "match"),
    ("What's the difference between Approved and Verified statuses?", "api"),
    ("How do I trigger the document splitter?", "split"),
    ("Why is a vendor missing from the COI tracker?", "active job"),
    ("Can I bulk delete documents?", "does not"),
]


def ask(question):
    """Drive the Space's own respond() generator and return the final answer."""
    answer = ""
    for chunk in app.respond(question, [], "", 2000, 0.3, 0.95, None):
        answer = chunk
    return answer


def main():
    print(f"Knowledge base: {len(app.doc_context):,} chars\n")
    if len(app.doc_context) < 2000:
        sys.exit("Knowledge base looks empty or failed to load")

    problems = 0
    for question, expect in PROBES:
        before = len(would_have_emailed)
        try:
            answer = ask(question)
        except Exception as e:
            print(f"ERROR  {question}\n       {e}")
            problems += 1
            continue

        emailed = len(would_have_emailed) > before
        if emailed:
            verdict, note = "FAIL", "unanswered -> would have emailed the support alias"
        elif expect not in answer.lower():
            verdict, note = "WARN", f"answered but never mentions '{expect}'"
        else:
            verdict, note = "PASS", ""

        if verdict != "PASS":
            problems += 1
        print(f"{verdict}  {question}")
        if note:
            print(f"       {note}")

    print(f"\n{len(PROBES) - problems}/{len(PROBES)} clean")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
