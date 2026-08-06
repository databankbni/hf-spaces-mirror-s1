# ---------------------------------------------------------------------------
# app.py — Bhagwad Gita Reading Agent (Gradio entry point).
#
# Three subsystems, wired into one UI:
#   1. Reading engine  — deterministic, plays verses for a timed session
#                        and bookmarks the resume point. NO LLM.
#   2. Reminders       — opt-in daily email nudges (APScheduler + SMTP).
#   3. Ask the Sage    — optional smolagents chat panel (Llama-3.1-8B),
#                        the ONLY place an LLM is used.
#
# Cold-start: ensure the corpus + audio exist, open the SQLite-backed
# stores, start the scheduler, then launch the UI. Heavy components are
# created once at import and shared across Gradio worker threads.
# ---------------------------------------------------------------------------

import gradio as gr

from config import (
    AUDIO_DIR,
    DEFAULT_SESSION_MINUTES,
    FIRST_VERSE_ID,
    MAX_SESSION_MINUTES,
    MIN_SESSION_MINUTES,
)
from ingestion.build_audio import clean_for_tts, ensure_audio
from ingestion.build_corpus import ensure_corpus
from reader.session import ReadingSession
from reader.verse_store import VerseStore
from reminders.scheduler import ReminderScheduler
from users.bookmarks import BookmarkStore
from users.profile_store import ProfileStore
from users.remote_store import (
    pull_reflections_db,
    pull_users_db,
    push_reflections_db,
    push_users_db,
)
from agent.reflection_store import ReflectionStore


# --- Cold-start -------------------------------------------------------------
print("[app] ensuring corpus exists...")
ensure_corpus()
print("[app] ensuring audio exists (first run can take a while)...")
ensure_audio()

# Pull the durable copy of profiles/bookmarks BEFORE opening the user DB, so
# the Space resumes with real users despite its ephemeral filesystem.
print("[app] syncing user data from durable store...")
pull_users_db()
# Pull previously-generated AI reflections so they are never regenerated.
print("[app] syncing AI reflections from durable store...")
pull_reflections_db()

STORE = VerseStore()
PROFILES = ProfileStore()
BOOKMARKS = BookmarkStore(default_verse_id=STORE.first_verse_id())
SCHEDULER = ReminderScheduler(PROFILES, BOOKMARKS, STORE)
SCHEDULER.load_all()
SCHEDULER.start()

# Lazily-built chat agent (needs an HF token + network). Kept optional so
# the reader works even with no token configured.
_JUMP_SINK: dict = {}
_AGENT = None
# Durable cache of generated reflections, keyed by (verse_id, lang) so each
# verse's AI commentary is only ever produced once per language — and reused
# across restarts via the HF dataset mirror.
REFLECTIONS = ReflectionStore()


def _get_agent():
    global _AGENT
    if _AGENT is None:
        from agent.build_agent import build_agent

        _AGENT = build_agent(STORE, _JUMP_SINK)
    return _AGENT


# Build the agent eagerly, on the MAIN thread, at startup. The embedding
# model (SentenceTransformer) must be loaded here: loading it lazily inside a
# Gradio worker thread triggers a torch "Cannot copy out of meta tensor"
# crash. Warming it up now means reflection + chat just work later. Failures
# (e.g. no token) are non-fatal — the reader still runs.
try:
    print("[app] warming up the sage (loading embedding model + agent)...")
    _get_agent()
    print("[app] sage ready.")
except Exception as exc:  # noqa: BLE001
    print(f"[app] sage warm-up skipped: {type(exc).__name__}: {exc}")


# --- Overview (static context, no LLM) --------------------------------------
# A plain-language primer so a brand-new reader who knows nothing about the
# Mahabharata understands WHERE the Gita happens and WHY, before the shlokas
# begin. Shown automatically when a session starts at the very first verse;
# otherwise reachable any time via the "Overview" button.
OVERVIEW_EN = (
    "## 📖 The story behind the Gita\n\n"
    "The **Mahabharata** is one of the great epics of ancient India. At its "
    "heart is a conflict within a royal family — the five **Pandava** brothers "
    "and their hundred cousins, the **Kauravas** — over the throne of "
    "Hastinapura. Years of injustice, a rigged game of dice, exile, and failed "
    "peace talks finally lead to war on the field of **Kurukshetra**.\n\n"
    "The **Bhagavad Gita** (*“Song of the Lord”*) is a 700-verse conversation "
    "that takes place at the very start of that war. **Arjuna**, the greatest "
    "Pandava warrior, asks his charioteer and friend **Krishna** to drive him "
    "between the two armies. Seeing his own teachers, elders, and kinsmen ready "
    "to fight and die, Arjuna is overcome with grief and drops his bow, "
    "refusing to fight.\n\n"
    "Krishna — who is also a form of the divine — answers him. Their dialogue "
    "*is* the Gita: a timeless teaching on **duty (dharma)**, **acting without "
    "attachment to results (karma yoga)**, **devotion (bhakti)**, "
    "**knowledge (jnana)**, and the **eternal nature of the soul**.\n\n"
    "You don't need to know the whole Mahabharata to begin. Just this: a good "
    "person is paralyzed by a hard choice — and what follows is the wisdom that "
    "helps him, and us, act with clarity and peace.\n\n"
    "_Ready? Press **▶ Start / Resume reading** to hear the verses._"
)
OVERVIEW_HI = (
    "## 📖 गीता के पीछे की कथा\n\n"
    "**महाभारत** प्राचीन भारत के महान महाकाव्यों में से एक है। इसके केंद्र में एक "
    "राजपरिवार का संघर्ष है — पाँच **पांडव** भाई और उनके सौ चचेरे भाई **कौरव** — "
    "हस्तिनापुर के सिंहासन को लेकर। वर्षों का अन्याय, कपटपूर्ण द्यूत-क्रीड़ा, वनवास "
    "और असफल शांति-प्रयास अंततः **कुरुक्षेत्र** की भूमि पर युद्ध की ओर ले जाते हैं।\n\n"
    "**भगवद्गीता** (*“भगवान का गीत”*) 700 श्लोकों का वह संवाद है जो इसी युद्ध के "
    "आरम्भ में होता है। महान पांडव योद्धा **अर्जुन** अपने सारथी और मित्र **श्रीकृष्ण** "
    "से रथ को दोनों सेनाओं के बीच ले चलने को कहते हैं। अपने ही गुरुजनों, बड़े-बुज़ुर्गों "
    "और सगे-सम्बन्धियों को युद्ध के लिए तैयार देखकर अर्जुन शोक से भर जाते हैं, अपना "
    "धनुष रख देते हैं और युद्ध करने से मना कर देते हैं।\n\n"
    "श्रीकृष्ण — जो स्वयं ईश्वर का रूप हैं — उन्हें उत्तर देते हैं। उनका यही संवाद "
    "गीता है: **कर्तव्य (धर्म)**, **फल की आसक्ति के बिना कर्म (कर्मयोग)**, "
    "**भक्ति**, **ज्ञान**, और **आत्मा की शाश्वत प्रकृति** पर एक कालजयी शिक्षा।\n\n"
    "आरम्भ करने के लिए पूरा महाभारत जानना आवश्यक नहीं। बस इतना: एक अच्छा व्यक्ति "
    "एक कठिन चुनाव के सामने ठिठक जाता है — और आगे जो आता है वह वही ज्ञान है जो "
    "उसे, और हमें, स्पष्टता और शांति के साथ कर्म करने में सहायता करता है।\n\n"
    "_तैयार हैं? श्लोक सुनने के लिए **▶ Start / Resume reading** दबाएँ।_"
)


def _overview_markdown(lang_code: str) -> str:
    """The static overview text in the chosen language ("hi" or "en")."""
    return OVERVIEW_HI if lang_code == "hi" else OVERVIEW_EN


# --- Reading flow -----------------------------------------------------------
def _require_email(email: str) -> str:
    email = (email or "").strip().lower()
    if not email or "@" not in email:
        raise gr.Error("Please enter a valid email address first.")
    return email


def start_reading(email: str, lang: str = "en"):
    """Begin (or resume) a timed reading session for this user.

    `lang` selects the spoken translation that follows each Sanskrit shloka:
    "en" for English, "hi" for Hindi."""
    email = _require_email(email)
    profile = PROFILES.get_or_create(email)
    budget = profile.max_minutes * 60

    resume_id = BOOKMARKS.load_position(email)
    session = ReadingSession(STORE, resume_id, budget)
    playlist = list(session.iter_verses())

    state = {
        "email": email,
        "playlist": playlist,
        "idx": 0,
        "next_bookmark": session.next_bookmark,
        "minutes": profile.max_minutes,
        "lang": "hi" if str(lang).lower().startswith("hi") else "en",
    }
    return _render_step(state)


def next_verse(state: dict):
    """Advance to the next verse in the session playlist."""
    if not state or not state.get("playlist"):
        return _empty_render("Click “Start / Resume reading” to begin.")
    state = dict(state)
    state["idx"] = state["idx"] + 1
    return _render_step(state)


def prev_verse(state: dict):
    """Go back to the previous verse in the session playlist (stops at the
    first verse of this session)."""
    if not state or not state.get("playlist"):
        return _empty_render("Click “Start / Resume reading” to begin.")
    state = dict(state)
    # If the session already finished (idx past the end), step back onto the
    # last verse; otherwise just move one verse back, clamped to the start.
    last_idx = len(state["playlist"]) - 1
    current = min(state.get("idx", 0), last_idx)
    state["idx"] = max(0, current - 1)
    return _render_step(state)


def stop_reading(state: dict):
    """Stop now and bookmark the current verse so we resume here."""
    if not state or not state.get("playlist"):
        return _empty_render("Nothing is playing.")
    email = state["email"]
    playlist = state["playlist"]
    idx = min(state["idx"], len(playlist) - 1)
    if 0 <= idx < len(playlist):
        BOOKMARKS.save_position(email, playlist[idx].verse_id)
        push_users_db()
        ref = playlist[idx].ref
    else:
        ref = "the start"
    return (
        state,
        f"## Paused\nBookmarked at **{ref}**. Click “Start / Resume reading” to continue.",
        None,
        None,
        f"Paused at {ref}.",
        gr.update(interactive=True),
        gr.update(interactive=False),
    )


def _verse_markdown(pb, lang: str) -> str:
    """Render one verse's Sanskrit + chosen translation as markdown. `lang`
    is "hi" (Hindi) or "en" (English); Hindi falls back to English when a
    verse has no Hindi text."""
    if lang == "hi" and pb.hindi_text:
        translation_label = "Hindi (हिन्दी)"
        translation_text = pb.hindi_text
    else:
        translation_label = "English"
        translation_text = pb.english_text
    return (
        f"### {pb.ref} — {pb.title}\n\n"
        f"**Sanskrit**\n\n{pb.sanskrit_text}\n\n"
        f"---\n\n"
        f"**{translation_label}**\n\n{translation_text}"
    )


def _render_step(state: dict):
    """Render the verse at state['idx'], or a completion screen if past the
    end of the session playlist."""
    playlist = state["playlist"]
    idx = state["idx"]
    email = state["email"]

    if idx >= len(playlist):
        # Session playlist finished — bookmark the first unread verse.
        BOOKMARKS.save_position(email, state["next_bookmark"])
        push_users_db()
        nxt = STORE.get_verse(state["next_bookmark"])
        nxt_ref = nxt.ref if nxt else state["next_bookmark"]
        md = (
            f"## Session complete 🙏\n\n"
            f"Your {state['minutes']}-minute reading is done. "
            f"Next time you'll resume from **{nxt_ref}**."
        )
        return (
            state,
            md,
            None,
            None,
            f"Done. Next: {nxt_ref}.",
            gr.update(interactive=True),   # Start enabled
            gr.update(interactive=False),  # Next disabled
        )

    pb = playlist[idx]
    # Save the current verse as the resume point as we go.
    BOOKMARKS.save_position(email, pb.verse_id)

    md = _verse_markdown(pb, state.get("lang", "en"))
    status = f"Reading {pb.ref} — verse {idx + 1} of {len(playlist)} this session."
    # Only the Sanskrit player gets audio now; the translation starts
    # automatically when the Sanskrit clip finishes (see play_english), and
    # the next verse starts when that clip finishes (see next_verse). This
    # makes the session play hands-free, one verse after another.
    return (
        state,
        md,
        pb.sanskrit_audio,
        None,
        status,
        gr.update(interactive=True),
        gr.update(interactive=True),
    )


def play_english(state: dict):
    """Called when the Sanskrit clip finishes — auto-play the translation in
    the session's chosen language (English or Hindi)."""
    if not state or not state.get("playlist"):
        return None
    idx = state.get("idx", 0)
    playlist = state["playlist"]
    if 0 <= idx < len(playlist):
        pb = playlist[idx]
        if state.get("lang") == "hi" and pb.hindi_audio:
            return pb.hindi_audio
        return pb.english_audio
    return None


def change_language(lang: str, state: dict):
    """Switch the reading language on the fly. Updates the stored session
    language and immediately re-renders the current verse's translation so
    the user doesn't have to stop and restart. The translation audio picks
    up the new language automatically the next time it plays (play_english
    reads the live state)."""
    new_lang = "hi" if str(lang).lower().startswith("hi") else "en"
    if not state or not state.get("playlist"):
        # Nothing is playing yet — just remember the choice for next start.
        if isinstance(state, dict):
            state = dict(state)
            state["lang"] = new_lang
            return state, gr.update()
        return state, gr.update()

    state = dict(state)
    state["lang"] = new_lang
    idx = state.get("idx", 0)
    playlist = state["playlist"]
    if 0 <= idx < len(playlist):
        return state, _verse_markdown(playlist[idx], new_lang)
    return state, gr.update()


def _empty_render(message: str):
    return (
        {},
        f"## {message}",
        None,
        None,
        message,
        gr.update(interactive=True),
        gr.update(interactive=False),
    )


# --- Profile creation -------------------------------------------------------
def create_profile(name: str, email: str, minutes: int, opt_in: bool, time_local: str):
    """Create (or update) the user's profile from the sign-up form, then show
    a welcome that tells them where they'll start reading."""
    email = _require_email(email)
    profile, created = PROFILES.register(
        email,
        name=name,
        max_minutes=int(minutes),
        reminder_opt_in=bool(opt_in),
        reminder_time_local=(time_local or "").strip() or None,
    )
    if profile.reminder_opt_in and profile.reminder_time_local:
        SCHEDULER.subscribe(email, profile.reminder_time_local)
        reminder_line = f"Daily reminder set for **{profile.reminder_time_local}**."
    else:
        SCHEDULER.unsubscribe(email)
        reminder_line = "Reminders are off."

    # Persist the new/updated profile to the durable store right away.
    push_users_db()

    resume_id = BOOKMARKS.load_position(email)
    v = STORE.get_verse(resume_id)
    resume_ref = v.ref if v else resume_id
    greeting = profile.name or email
    if created:
        head = f"## Welcome, {greeting}! \U0001f64f Your profile is ready."
        resume_line = f"You'll start from the beginning \u2014 **{resume_ref}**."
    else:
        head = f"## Welcome back, {greeting}! \U0001f64f Profile updated."
        resume_line = f"You'll resume from **{resume_ref}**."
    msg = (
        f"{head}\n\n"
        f"- Session length: **{profile.max_minutes} minutes**\n"
        f"- {reminder_line}\n"
        f"- {resume_line}\n\n"
        f"Starting your reading now\u2026"
    )
    # Hide the profile form, reveal the reading page.
    return (
        msg,
        gr.update(visible=False),  # profile_page
        gr.update(visible=True),   # reading_page
    )


def edit_profile():
    """Go back to the profile form from the reading page."""
    return (
        gr.update(visible=True),   # profile_page
        gr.update(visible=False),  # reading_page
    )


def make_calendar_invite(email: str, reminder_time: str):
    """Build a downloadable .ics daily reminder (with the app URL inside) so
    the user's own calendar nudges them — no email credentials needed."""
    from reminders.calendar_invite import write_invite

    email = _require_email(email)
    profile = PROFILES.get(email)
    when = (reminder_time or "").strip() or (
        profile.reminder_time_local if profile else None
    )
    path = write_invite(email, when)
    return gr.update(value=str(path), visible=True)


# --- Landing (email-first) --------------------------------------------------
def enter_app(login_email: str):
    """Email-first entry. If the email already has a profile, go straight to
    the reading page (and resume). Otherwise open the create-profile form."""
    email = _require_email(login_email)
    profile = PROFILES.get(email)

    if profile is None:
        # Unknown email → send them to create a profile (prefilled).
        return (
            gr.update(visible=False),  # landing_page
            gr.update(visible=True),   # profile_page
            gr.update(visible=False),  # reading_page
            email,                     # email_box (prefill)
            "",                        # profile_status
        )

    # Known email → resume reading.
    greeting = profile.name or email
    resume_id = BOOKMARKS.load_position(email)
    v = STORE.get_verse(resume_id)
    ref = v.ref if v else resume_id
    msg = (
        f"## Welcome back, {greeting}! \U0001f64f\n"
        f"Resuming your {profile.max_minutes}-minute reading from **{ref}**\u2026"
    )
    return (
        gr.update(visible=False),  # landing_page
        gr.update(visible=False),  # profile_page
        gr.update(visible=True),   # reading_page
        email,                     # email_box
        msg,                       # profile_status
    )


def start_if_profile(email: str, lang: str = "en"):
    """Auto-start reading only when the email has a saved profile (used to
    resume after the landing page). New users see nothing until they submit
    the profile form."""
    email = (email or "").strip().lower()
    if not email or PROFILES.get(email) is None:
        return _empty_render("")
    return start_reading(email, lang)


def reset_marker(email: str, lang: str = "en"):
    """Reset this user's bookmark to the first verse and start a fresh
    reading session from the beginning of the book."""
    email = _require_email(email)
    BOOKMARKS.save_position(email, FIRST_VERSE_ID)
    push_users_db()
    return start_reading(email, lang)


def show_overview(state: dict):
    """Reveal the static overview on demand (the "Overview" button). Uses the
    session's current language, defaulting to English before a session starts."""
    lang_code = "hi" if (state or {}).get("lang") == "hi" else "en"
    return _overview_markdown(lang_code), gr.update(open=True)


def maybe_show_overview(state: dict):
    """Auto-show the overview ONLY when a session begins at the very first
    verse (a reader starting from the beginning). Returning readers who resume
    mid-book get an empty, collapsed panel — the "Overview" button still opens
    it whenever they want the context."""
    playlist = (state or {}).get("playlist") or []
    if playlist and playlist[0].verse_id == FIRST_VERSE_ID:
        lang_code = "hi" if state.get("lang") == "hi" else "en"
        return _overview_markdown(lang_code), gr.update(open=True)
    return "", gr.update(open=False)



# --- Ask the Sage (chat) ----------------------------------------------------
def _current_verse_id(state: dict, email: str) -> str | None:
    """The verse the seeker is currently on — the playing verse if a session
    is live, otherwise their saved bookmark. Used to ground the sage in only
    what they've heard so far."""
    if state and state.get("playlist"):
        idx = min(state.get("idx", 0), len(state["playlist"]) - 1)
        if 0 <= idx < len(state["playlist"]):
            return state["playlist"][idx].verse_id
    email = (email or "").strip().lower()
    if email and "@" in email:
        try:
            return BOOKMARKS.load_position(email)
        except Exception:  # noqa: BLE001
            return None
    return None


def ask_sage(
    message: str,
    history: list,
    email: str,
    lang: str = "English",
    state: dict | None = None,
):
    if not message or not message.strip():
        return "Please type a question."
    lang_code = "hi" if str(lang).lower().startswith("hi") else "en"
    up_to = _current_verse_id(state or {}, email)
    try:
        agent = _get_agent()
    except Exception as e:  # noqa: BLE001
        return f"[chat unavailable: {type(e).__name__}: {e}]"

    try:
        answer = str(agent.run(message.strip(), lang_code, up_to))
    except Exception as e:  # noqa: BLE001
        return f"[agent error: {type(e).__name__}: {e}]"

    # If the agent requested a jump, persist it for the user's next Resume.
    jumped = _JUMP_SINK.pop("verse_id", None)
    if jumped and (email or "").strip():
        BOOKMARKS.save_position(email.strip().lower(), jumped)
        push_users_db()
        v = STORE.get_verse(jumped)
        ref = v.ref if v else jumped
        if lang_code == "hi":
            answer += f"\n\n_(बुकमार्क {ref} पर ले जाया गया। “Start / Resume reading” दबाएँ।)_"
        else:
            answer += f"\n\n_(Bookmark moved to {ref}. Click “Start / Resume reading”.)_"
    return answer


def _reflection_text(verse_id: str, lang_code: str) -> str:
    """Raw reflection text for a verse + language, generated once and cached
    durably (in reflections.sqlite, mirrored to the HF dataset). Returns an
    error string (in brackets) if the chat model is unavailable."""
    cached = REFLECTIONS.get(verse_id, lang_code)
    if cached is not None:
        return cached
    try:
        agent = _get_agent()
    except Exception as e:  # noqa: BLE001
        return f"[reflection unavailable: {type(e).__name__}: {e}]"
    try:
        text = str(agent.reflect(verse_id, lang_code)).strip()
    except Exception as e:  # noqa: BLE001
        return f"[reflection error: {type(e).__name__}: {e}]"
    # Persist locally + push to the durable store so it's never regenerated.
    REFLECTIONS.put(verse_id, lang_code, text)
    push_reflections_db()
    return text


def reflect_on_verse(state: dict):
    """Generate (and cache) the sage's reflection on the verse currently being
    read, in the session's chosen language. Shown as text the seeker can read."""
    if not state or not state.get("playlist"):
        return "_Start a reading session first, then ask for a reflection._"
    idx = state.get("idx", 0)
    playlist = state["playlist"]
    if not (0 <= idx < len(playlist)):
        return "_No verse is being read right now._"

    pb = playlist[idx]
    lang_code = "hi" if state.get("lang") == "hi" else "en"
    text = _reflection_text(pb.verse_id, lang_code)
    if text.startswith("["):  # propagate availability/errors verbatim
        return text

    label = "संत का चिंतन" if lang_code == "hi" else "The sage reflects"
    hint = (
        "_इसे पढ़ें, या नीचे “🔊 चिंतन सुनें” दबाएँ। तैयार होने पर “▶ अगला श्लोक” दबाएँ।_"
        if lang_code == "hi"
        else "_Read it, or press “🔊 Listen to the reflection” below. "
        "Press “▶ Next verse” when you're ready._"
    )
    return f"**{label} — {pb.ref}**\n\n{text}\n\n{hint}"


def listen_to_reflection(state: dict):
    """Synthesize the current verse's reflection to speech (cached on disk)
    and return the audio path for the player. gTTS is hit once per
    verse+language, on the seeker's request — never in bulk."""
    if not state or not state.get("playlist"):
        return None
    idx = state.get("idx", 0)
    playlist = state["playlist"]
    if not (0 <= idx < len(playlist)):
        return None

    pb = playlist[idx]
    lang_code = "hi" if state.get("lang") == "hi" else "en"
    text = _reflection_text(pb.verse_id, lang_code)
    if not text or text.startswith("["):
        return None

    out_dir = AUDIO_DIR / "reflections"
    out_path = out_dir / f"{pb.verse_id}_{lang_code}.mp3"
    if not out_path.exists():
        out_dir.mkdir(parents=True, exist_ok=True)
        # English is cleaned so gTTS doesn't spell out ALL-CAPS names; the
        # Hindi voice reads Devanagari naturally.
        speech = clean_for_tts(text) if lang_code == "en" else text
        try:
            from gtts import gTTS

            gTTS(text=speech, lang=lang_code).save(str(out_path))
        except Exception:  # noqa: BLE001
            return None
    return str(out_path)



# --- UI ---------------------------------------------------------------------
with gr.Blocks(title="Bhagwad Gita Reading Agent") as demo:
    gr.Markdown(
        "# 🕉️ Bhagwad Gita Reading Agent\n"
        "Reads the Gita to you — Sanskrit shloka then English translation — "
        "for a timed session, and remembers where you left off."
    )

    session_state = gr.State({})

    # ----- Page 0: landing (email first) -----
    with gr.Group(visible=True) as landing_page:
        gr.Markdown("### Enter your email to begin")
        login_email = gr.Textbox(
            label="Your email",
            placeholder="you@example.com",
        )
        continue_btn = gr.Button("Continue ▶", variant="primary")
        gr.Markdown(
            "_New here? We'll help you create a profile. "
            "Returning? We'll pick up exactly where you left off._"
        )

    # ----- Page 1: profile -----
    with gr.Group(visible=False) as profile_page:
        gr.Markdown("### Create your profile")
        with gr.Row():
            name_box = gr.Textbox(
                label="Your name (optional)",
                placeholder="Arjuna",
                scale=2,
            )
            email_box = gr.Textbox(
                label="Your email (required)",
                placeholder="you@example.com",
                scale=3,
            )

        with gr.Accordion("Session length & daily reminder", open=True):
            minutes_slider = gr.Slider(
                minimum=MIN_SESSION_MINUTES,
                maximum=MAX_SESSION_MINUTES,
                value=DEFAULT_SESSION_MINUTES,
                step=5,
                label="Session length (minutes)",
            )
            reminder_checkbox = gr.Checkbox(label="Email me a daily reminder")
            reminder_time = gr.Textbox(
                label="Reminder time (24h HH:MM, your server's local time)",
                placeholder="07:30",
            )

        create_btn = gr.Button("Create / update my profile ▶", variant="primary")

    # ----- Page 2: reading -----
    with gr.Group(visible=False) as reading_page:
        profile_status = gr.Markdown()
        language_choice = gr.Radio(
            choices=["English", "Hindi"],
            value="English",
            label="Listen / chat in",
            info="Sanskrit shloka is always read first, then this translation.",
        )
        with gr.Row():
            overview_btn = gr.Button("📖 Overview — the story behind the Gita")
        with gr.Accordion(
            "📖 New to the Mahabharata? Start here", open=False
        ) as overview_accordion:
            overview_display = gr.Markdown()
        with gr.Row():
            start_btn = gr.Button("▶ Start / Resume reading", variant="primary")
            stop_btn = gr.Button("⏸ Stop & bookmark")
            prev_btn = gr.Button("⏮ Previous verse")
            next_btn = gr.Button("▶ Next verse", interactive=False)
            reset_btn = gr.Button("↺ Restart from beginning")
            edit_btn = gr.Button("✎ Edit profile")

        verse_display = gr.Markdown("Press Start to begin — verses will play one after another.")
        with gr.Row():
            sanskrit_player = gr.Audio(label="Sanskrit", autoplay=True)
            english_player = gr.Audio(label="Translation", autoplay=True)
        status_strip = gr.Markdown()

        with gr.Accordion("✨ Sage's reflection on this verse", open=True):
            gr.Markdown(
                "_After the Sanskrit and translation are read, the sage "
                "reflects on the verse's deeper teaching. Read it below, or "
                "press “🔊 Listen to the reflection.” (Needs the chat model.)_"
            )
            reflection_display = gr.Markdown()
            with gr.Row():
                reflect_btn = gr.Button("✨ Show reflection now")
                listen_reflect_btn = gr.Button("🔊 Listen to the reflection")
            reflection_player = gr.Audio(label="Reflection", autoplay=True)

        with gr.Accordion("Daily reminder (add to your calendar)", open=False):
            gr.Markdown(
                "Download a calendar invite with a daily reminder and a link "
                "back to this app — no email or password needed."
            )
            calendar_btn = gr.Button("📅 Get calendar reminder (.ics)")
            calendar_file = gr.File(label="Your reminder invite", visible=False)

        with gr.Accordion("Ask the Sage (about any verse)", open=False):
            gr.ChatInterface(
                fn=ask_sage,
                additional_inputs=[email_box, language_choice, session_state],
                examples=[
                    ["What does Krishna say about doing your duty without attachment?", None, "English", None],
                    ["Read me chapter 2 verse 47.", None, "English", None],
                    ["What does the Gita teach about fear?", None, "English", None],
                ],
            )

    # --- Wiring ---
    reader_outputs = [
        session_state,
        verse_display,
        sanskrit_player,
        english_player,
        status_strip,
        start_btn,
        next_btn,
    ]
    # Landing → resume (existing) or create-profile (new).
    overview_outputs = [overview_display, overview_accordion]
    continue_btn.click(
        enter_app,
        inputs=[login_email],
        outputs=[landing_page, profile_page, reading_page, email_box, profile_status],
    ).then(
        start_if_profile, inputs=[email_box, language_choice], outputs=reader_outputs
    ).then(
        maybe_show_overview, inputs=[session_state], outputs=overview_outputs
    )
    login_email.submit(
        enter_app,
        inputs=[login_email],
        outputs=[landing_page, profile_page, reading_page, email_box, profile_status],
    ).then(
        start_if_profile, inputs=[email_box, language_choice], outputs=reader_outputs
    ).then(
        maybe_show_overview, inputs=[session_state], outputs=overview_outputs
    )

    # Create/update profile → switch to the reading page → auto-start reading.
    create_btn.click(
        create_profile,
        inputs=[name_box, email_box, minutes_slider, reminder_checkbox, reminder_time],
        outputs=[profile_status, profile_page, reading_page],
    ).then(
        start_reading, inputs=[email_box, language_choice], outputs=reader_outputs
    ).then(
        maybe_show_overview, inputs=[session_state], outputs=overview_outputs
    )

    edit_btn.click(edit_profile, outputs=[profile_page, reading_page])

    start_btn.click(
        start_reading, inputs=[email_box, language_choice], outputs=reader_outputs
    ).then(
        lambda: ("", None), outputs=[reflection_display, reflection_player]
    ).then(
        maybe_show_overview, inputs=[session_state], outputs=overview_outputs
    )
    next_btn.click(
        next_verse, inputs=[session_state], outputs=reader_outputs
    ).then(lambda: ("", None), outputs=[reflection_display, reflection_player])
    prev_btn.click(
        prev_verse, inputs=[session_state], outputs=reader_outputs
    ).then(lambda: ("", None), outputs=[reflection_display, reflection_player])
    stop_btn.click(stop_reading, inputs=[session_state], outputs=reader_outputs)
    reset_btn.click(
        reset_marker, inputs=[email_box, language_choice], outputs=reader_outputs
    ).then(
        lambda: ("", None), outputs=[reflection_display, reflection_player]
    ).then(
        maybe_show_overview, inputs=[session_state], outputs=overview_outputs
    )

    # On-demand overview (the "Overview" button) — reveals the context any time.
    overview_btn.click(
        show_overview, inputs=[session_state], outputs=overview_outputs
    )

    # Sage's per-verse reflection (AI commentary), cached per verse + language.
    reflect_btn.click(
        reflect_on_verse, inputs=[session_state], outputs=[reflection_display]
    )
    listen_reflect_btn.click(
        listen_to_reflection, inputs=[session_state], outputs=[reflection_player]
    )

    # Switching English/Hindi re-renders the current verse immediately
    # (no need to stop and restart the session).
    language_choice.change(
        change_language,
        inputs=[language_choice, session_state],
        outputs=[session_state, verse_display],
    )

    # Calendar reminder download.
    calendar_btn.click(
        make_calendar_invite,
        inputs=[email_box, reminder_time],
        outputs=[calendar_file],
    )

    # Seamless playback: Sanskrit clip ends → translation plays. When the
    # translation ends we DON'T auto-advance: instead the sage reflects on the
    # verse (one inference, then shown as text). The seeker reads it — or
    # presses “🔊 Listen to the reflection” — and clicks “▶ Next verse” to go on.
    sanskrit_player.stop(play_english, inputs=[session_state], outputs=[english_player])
    english_player.stop(
        lambda: "_🧘 The sage is reflecting on this verse…_",
        outputs=[reflection_display],
    ).then(
        reflect_on_verse, inputs=[session_state], outputs=[reflection_display]
    )


if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7860)
