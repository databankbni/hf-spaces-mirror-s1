"""Minimal free Telegram bot for the transcriber.

Send the bot a YouTube link, a voice message, or an audio/video file — it
replies with the finished TXT transcript. Runs as a long-polling daemon thread
inside the same Space (no extra hosting), so it is alive whenever the Space is.

Env (Space Secrets):
    TELEGRAM_BOT_TOKEN    bot token from @BotFather (bot is off without it)
    TELEGRAM_ALLOWED_IDS  comma-separated chat ids allowed to use the bot;
                          while empty, the bot only tells senders their chat id
    TELEGRAM_TRANSLATE    optional language code (e.g. "ru") — translate every
                          transcript the bot produces
"""

from __future__ import annotations

import os
import re
import shutil
import socket
import tempfile
import threading
import time
import zipfile

import requests

from transcriber import (TranscribeError, answer_question, get_supadata_channel_videos,
                         supadata_left, transcribe, usage_report, _proxy_url)

# Prefer IPv4: some hosting containers have half-broken IPv6, which makes
# api.telegram.org (dual-stack) hang/reset while IPv4-only APIs work fine.
_orig_getaddrinfo = socket.getaddrinfo


def _ipv4_first(host, *args, **kwargs):
    res = _orig_getaddrinfo(host, *args, **kwargs)
    v4 = [r for r in res if r[0] == socket.AF_INET]
    return v4 or res


socket.getaddrinfo = _ipv4_first

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
# TELEGRAM_API_BASE lets all bot traffic go through a relay (e.g. a Cloudflare
# Worker) when the host's direct route to api.telegram.org is blocked.
API_BASE = os.environ.get("TELEGRAM_API_BASE", "https://api.telegram.org").strip().rstrip("/")
API = f"{API_BASE}/bot{TOKEN}"
FILE_API = f"{API_BASE}/file/bot{TOKEN}"
ALLOWED = {s.strip() for s in os.environ.get("TELEGRAM_ALLOWED_IDS", "").split(",") if s.strip()}
TRANSLATE = os.environ.get("TELEGRAM_TRANSLATE", "").strip() or None
MODE = os.environ.get("TELEGRAM_MODE", "poll").strip().lower()
HOOK_SECRET = os.environ.get("TELEGRAM_HOOK_SECRET", "").strip()

_WORKERS = threading.Semaphore(2)     # at most 2 transcriptions at once
_STARTED = False
_PENDING: dict[int, str] = {}         # chat_id -> URL awaiting an option choice

_OPTIONS_KEYBOARD = {"inline_keyboard": [
    [{"text": "▶️ Plain text", "callback_data": "go|0|0|0"}],
    [{"text": "📝 + Summary & outline", "callback_data": "go|1|0|0"}],
    [{"text": "🎬 + SRT subtitles", "callback_data": "go|0|0|1"}],
]}
_PENDING_CH: dict[int, tuple[str, int, int]] = {}  # chat_id -> (source, count, token)
_CH_TOK: dict[int, int] = {}                       # stale-confirm protection
_LAST_TXT: dict[int, str] = {}                     # chat_id -> last transcript (for Q&A)
_ACTIVE: set = set()                               # (chat_id, source) jobs in flight
# Some datacenters (HF included) block api.telegram.org outright. If the direct
# route fails at startup, all bot traffic switches to the residential proxy
# (Webshare secrets) — set to a requests-style proxies dict when active.
_PROXIES: dict | None = None

HELP = (
    "🎬 Send me a YouTube link, a voice message, or an audio/video file — "
    "I'll reply with a clean TXT transcript (paragraphs, timestamps, chapters).\n\n"
    "📺 Whole channel: send \"@channel 20\" (or a channel link + count) — "
    "I'll transcribe the newest videos and send back one ZIP. Uses monthly credits.\n"
    "📦 Several links in one message — batch, one file each.\n"
    "💬 After a transcript is done, just type a question about the video — "
    "I'll answer from its content.\n\n"
    "/usage — remaining credits & limits\n\n"
    "Note: Telegram lets bots download files up to 20 MB — for bigger files "
    "use the web app."
)


def _log(msg: str) -> None:
    print(f"[telegram] {msg}", flush=True)


def _api(method: str, http_timeout: int = 35, **params) -> dict:
    # Up to 3 tries: the egress here intermittently kills TLS connections
    # (SSL EOF) — a fresh connection often goes through.
    for attempt in (1, 2, 3):
        try:
            r = requests.post(f"{API}/{method}", json=params, timeout=http_timeout,
                              proxies=_PROXIES)
            return r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        except Exception as e:
            if attempt == 3:
                _log(f"{method} failed: {e}")
            time.sleep(1.5 * attempt)
    return {}


def _send(chat_id, text: str) -> dict:
    return _api("sendMessage", chat_id=chat_id, text=text[:4000])


def _edit(chat_id, message_id, text: str) -> None:
    _api("editMessageText", chat_id=chat_id, message_id=message_id, text=text[:4000])


def _send_doc(chat_id, path: str, caption: str = "") -> None:
    try:
        with open(path, "rb") as f:
            r = requests.post(f"{API}/sendDocument",
                              data={"chat_id": chat_id, "caption": caption[:1000]},
                              files={"document": f}, timeout=180, proxies=_PROXIES)
        ok = (r.ok and r.headers.get("content-type", "").startswith("application/json")
              and r.json().get("ok"))
        if ok:
            return
        _log(f"sendDocument rejected: {r.status_code} {r.text[:200]}")
    except Exception as e:
        _log(f"sendDocument failed: {e}")
    _send(chat_id, "⚠️ Could not send the file back — please try again.")


def _download(file_id: str, workdir: str) -> str | None:
    """Fetch a Telegram file to disk (bot API limit: 20 MB)."""
    info = _api("getFile", file_id=file_id)
    fp = (info.get("result") or {}).get("file_path")
    if not fp:
        return None
    local = os.path.join(workdir, os.path.basename(fp) or "media.bin")
    try:
        with requests.get(f"{FILE_API}/{fp}", stream=True, timeout=300,
                          proxies=_PROXIES) as r:
            if r.status_code != 200:
                return None
            with open(local, "wb") as f:
                for chunk in r.iter_content(1 << 16):
                    f.write(chunk)
        return local
    except Exception as e:
        _log(f"file download failed: {e}")
        return None


def _extract_urls(text: str) -> list[str]:
    return [u.rstrip(").,") for u in re.findall(r"https?://\S+", text or "")]


def _extract_url(text: str) -> str | None:
    urls = _extract_urls(text)
    return urls[0] if urls else None


def _progress_editor(chat_id, message_id):
    """Progress callback that edits the status message at most every ~7s."""
    last = {"t": 0.0}

    def prog(frac: float, msg: str) -> None:
        now = time.time()
        if now - last["t"] >= 7:
            last["t"] = now
            pct = int(max(0.0, min(1.0, frac)) * 100)
            _edit(chat_id, message_id, f"⏳ {msg} — {pct}%")

    return prog


def _job(chat_id, url: str | None, media_file_id: str | None,
         want_summary: bool = False, use_claude: bool = False,
         want_srt: bool = False) -> None:
    # a second tap on the same video must not start a parallel duplicate job
    job_key = (chat_id, url or media_file_id)
    if job_key in _ACTIVE:
        _send(chat_id, "⏳ Already working on this one — hold on, the file is coming.")
        return
    _ACTIVE.add(job_key)
    try:
        _job_inner(chat_id, url, media_file_id, want_summary, use_claude, want_srt)
    finally:
        _ACTIVE.discard(job_key)


def _job_inner(chat_id, url: str | None, media_file_id: str | None,
               want_summary: bool, use_claude: bool, want_srt: bool) -> None:
    with _WORKERS:
        workdir = tempfile.mkdtemp(prefix="tgbot_")
        try:
            status = _send(chat_id, "⏳ Working on it… usually 1–3 minutes.")
            message_id = (status.get("result") or {}).get("message_id")
            prog = _progress_editor(chat_id, message_id) if message_id else None

            file_path = None
            if media_file_id:
                file_path = _download(media_file_id, workdir)
                if not file_path:
                    _send(chat_id, "⚠️ Could not download the file (bots are limited "
                                   "to 20 MB). For big files use the web app.")
                    return

            # a downloaded file wins over any link found in its caption
            filename, txt, srt = transcribe(None if file_path else url, file_path, None,
                                            want_summary=want_summary,
                                            use_claude=use_claude,
                                            translate_to=TRANSLATE, progress=prog)
            out_path = os.path.join(workdir, filename)
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(txt)
            if message_id:
                _edit(chat_id, message_id, "✅ Done — sending the file…")
            _send_doc(chat_id, out_path, caption=filename.rsplit(".", 1)[0])
            if want_srt:
                if srt:
                    srt_path = os.path.join(workdir, filename[:-4] + ".srt")
                    with open(srt_path, "w", encoding="utf-8") as f:
                        f.write(srt)
                    _send_doc(chat_id, srt_path, caption="SRT subtitles")
                else:
                    _send(chat_id, "⚠️ SRT is unavailable for this video "
                                   "(the source has no per-line timing).")
            _LAST_TXT[chat_id] = txt   # enables follow-up questions
        except TranscribeError as e:
            _send(chat_id, f"⚠️ {e}")
        except Exception as e:  # noqa: BLE001 — a bot must never die silently
            _log(f"job crashed: {e}")
            _send(chat_id, "⚠️ Unexpected error — please try again.")
        finally:
            shutil.rmtree(workdir, ignore_errors=True)


def _channel_source(text: str) -> tuple[str | None, int]:
    """Detect a channel reference + optional count: '@name 20' or a channel URL."""
    t = (text or "").strip()
    m = re.match(r"^(@[\w.\-]+)(?:\s+(\d+))?$", t)
    if m:
        return m.group(1), int(m.group(2) or 10)
    if "watch" in t or "youtu.be" in t or "/shorts/" in t:
        return None, 0
    m = re.search(r"(?:https?://)?(?:www\.)?youtube\.com/(@[\w.\-]+|channel/[\w\-]+|c/[\w.\-]+)", t)
    if m:
        cnt = re.search(r"\s(\d+)\s*$", t)
        return f"https://www.youtube.com/{m.group(1)}", int(cnt.group(1)) if cnt else 10
    return None, 0


def _channel_order(chat_id, source: str, count: int) -> None:
    """Ask for confirmation before spending Supadata credits on a channel."""
    left = supadata_left()
    if left is None:
        _send(chat_id, "⚠️ Can't check the credit balance right now — try again later.")
        return
    if left <= 3:
        _send(chat_id, f"⚠️ Only {left} monthly credits left — not enough for a channel "
                       "order. Use the Mac bulk script (unlimited, free) or wait for the reset.")
        return
    n = max(1, min(count, 100, left - 2))
    tok = _CH_TOK[chat_id] = _CH_TOK.get(chat_id, 0) + 1
    _PENDING_CH[chat_id] = (source, n, tok)
    note = "" if n == count else f" (trimmed from {count} — credits/limit)"
    _api("sendMessage", chat_id=chat_id,
         text=f"📺 Channel: {source}\nTranscribe the {n} newest videos{note}?\n"
              f"Cost: ~{n + 1} credits of the {left} you have left this month.",
         reply_markup={"inline_keyboard": [
             [{"text": f"✅ Start ({n} videos)", "callback_data": f"ch|go|{tok}"}],
             [{"text": "❌ Cancel", "callback_data": f"ch|no|{tok}"}]]})


def _channel_job(chat_id, source: str, n: int) -> None:
    supa_key = os.environ.get("SUPADATA_API_KEY", "")
    status = _send(chat_id, "📥 Getting the channel's video list…")
    mid = (status.get("result") or {}).get("message_id")

    def report(text: str) -> None:
        if mid:
            _edit(chat_id, mid, text)
        else:
            _send(chat_id, text)

    try:
        ids = get_supadata_channel_videos(source, n, supa_key)
    except Exception as e:  # noqa: BLE001
        report(f"⚠️ Could not list the channel: {str(e)[:150]}")
        return
    if not ids:
        report("⚠️ No videos found on this channel.")
        return
    workdir = tempfile.mkdtemp(prefix="tgbulk_")
    results: list[str] = []
    failed = 0
    stopped = ""
    try:
        last_edit = 0.0
        for i, vid in enumerate(ids, 1):
            if mid and time.time() - last_edit >= 3:   # Telegram edit rate limits
                last_edit = time.time()
                _edit(chat_id, mid, f"⏳ Video {i}/{len(ids)}… (done: {len(results)}"
                      + (f", failed: {failed}" if failed else "") + ")")
            try:
                filename, txt, _srt = transcribe(f"https://www.youtube.com/watch?v={vid}",
                                                 None, None, want_summary=False,
                                                 use_claude=False, translate_to=TRANSLATE,
                                                 paid_title=False)
                path = os.path.join(workdir, filename)
                k = 2
                while os.path.exists(path):
                    path = os.path.join(workdir, f"{filename[:-4]} ({k}).txt")
                    k += 1
                with open(path, "w", encoding="utf-8") as f:
                    f.write(txt)
                results.append(path)
            except TranscribeError as e:
                failed += 1
                _log(f"channel item {vid} failed: {e}")
                low = str(e).lower()
                if "quota" in low or "лимит" in low:   # credits ran out — stop burning
                    stopped = "Monthly quota ran out mid-job — sending what is done."
                    break
            except Exception as e:  # noqa: BLE001 — keep going through the list
                failed += 1
                _log(f"channel item {vid} crashed: {e}")
        if not results:
            report("⚠️ None of the videos could be transcribed "
                   "(no subtitles, or the monthly quota is used up).")
            return
        zpath = os.path.join(workdir, "transcripts.zip")
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
            for p in results:
                z.write(p, os.path.basename(p))
        report(f"✅ Done: {len(results)}" + (f" (failed: {failed})" if failed else "")
               + (f"\n⚠️ {stopped}" if stopped else "") + " — sending the ZIP…")
        _send_doc(chat_id, zpath, caption=f"📦 {source}: {len(results)} transcripts")
    except Exception as e:  # noqa: BLE001 — a bot must never die silently
        _log(f"channel job crashed: {e}")
        report("⚠️ Unexpected error — please try again.")
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _handle(msg: dict) -> None:
    chat_id = (msg.get("chat") or {}).get("id")
    if chat_id is None:
        return
    # Empty TELEGRAM_ALLOWED_IDS = PUBLIC (anyone). A non-empty list restricts access.
    if ALLOWED and str(chat_id) not in ALLOWED:
        _send(chat_id, f"🔒 Access denied. Your chat id: {chat_id}")
        return

    text = msg.get("text") or ""
    if text.startswith("/usage"):
        def report():
            try:
                _send(chat_id, usage_report())
            except Exception as e:  # noqa: BLE001
                _log(f"usage report failed: {e}")
                _send(chat_id, "⚠️ Could not fetch usage right now.")
        threading.Thread(target=report, daemon=True).start()
        return
    if text.startswith("/"):
        _send(chat_id, HELP)
        return

    media = (msg.get("voice") or msg.get("audio") or msg.get("video")
             or msg.get("video_note") or msg.get("document"))
    url = _extract_url(text) or _extract_url(msg.get("caption") or "")

    if not media:
        src, cnt = _channel_source(text)
        if src:   # threaded: the balance check must not block the polling loop
            threading.Thread(target=_channel_order, args=(chat_id, src, cnt),
                             daemon=True).start()
            return

    if not url and not media:
        # plain text after a finished transcript = a question about it
        last = _LAST_TXT.get(chat_id)
        if text.strip() and last:
            def qa():
                try:
                    _send(chat_id, answer_question(last, text) or "🤔 No answer.")
                except Exception as e:  # noqa: BLE001
                    _log(f"qa failed: {e}")
                    _send(chat_id, "⚠️ Could not answer right now — try again in a minute.")
            threading.Thread(target=qa, daemon=True).start()
            return
        _send(chat_id, HELP)
        return

    if media:   # files start right away (free mode)
        threading.Thread(target=_job, args=(chat_id, None, media.get("file_id")),
                         daemon=True).start()
        return
    urls = _extract_urls(text)
    if len(urls) > 1:   # batch: several links in one message → free mode, one by one
        batch = urls[:10]
        _send(chat_id, f"📦 Batch of {len(batch)} links — processing one by one (free mode)…"
              + ("" if len(urls) <= 10 else f"\n(only the first 10 of {len(urls)} taken)"))

        def batch_worker():
            for u in batch:
                _job(chat_id, u, None)
        threading.Thread(target=batch_worker, daemon=True).start()
        return
    # single link: ask which mode to use (same options as the web app)
    _PENDING[chat_id] = url
    _api("sendMessage", chat_id=chat_id, text="How should I process it?",
         reply_markup=_OPTIONS_KEYBOARD)


def _handle_callback(cb: dict) -> None:
    chat_id = ((cb.get("message") or {}).get("chat") or {}).get("id")
    _api("answerCallbackQuery", callback_query_id=cb.get("id"))
    if chat_id is None or (ALLOWED and str(chat_id) not in ALLOWED):
        return
    data = cb.get("data") or ""
    mid = (cb.get("message") or {}).get("message_id")
    if data.startswith("ch|"):
        parts = data.split("|")
        action = parts[1] if len(parts) > 1 else ""
        tok = parts[2] if len(parts) > 2 else ""
        if mid:   # remove the buttons so the choice can't be tapped twice
            _api("editMessageReplyMarkup", chat_id=chat_id, message_id=mid)
        pend = _PENDING_CH.get(chat_id)
        if not pend or str(pend[2]) != tok:   # stale confirm from an older order
            if action == "go":
                _send(chat_id, "This order is outdated — send the channel again.")
            return
        _PENDING_CH.pop(chat_id, None)
        if action == "go":
            threading.Thread(target=_channel_job, args=(chat_id, pend[0], pend[1]),
                             daemon=True).start()
        else:
            _send(chat_id, "Cancelled.")
        return
    if not data.startswith("go|"):
        return
    url = _PENDING.pop(chat_id, None)
    if not url:
        _send(chat_id, "Please send the link again.")
        return
    parts = data.split("|") + ["0", "0", "0"]
    s, c, f = parts[1], parts[2], parts[3]
    if mid:   # remove the buttons so the choice can't be tapped twice
        _api("editMessageReplyMarkup", chat_id=chat_id, message_id=mid)
    threading.Thread(target=_job,
                     args=(chat_id, url, None, s == "1", c == "1", f == "1"),
                     daemon=True).start()


def _diag() -> None:
    """Startup connectivity probes — tell flaky egress from domain-level blocks."""
    targets = [
        ("our-worker", f"{API}/getMe"),
        ("other-workers.dev", "https://welcome.developers.workers.dev/"),
        ("cloudflare.com", "https://www.cloudflare.com/robots.txt"),
        ("deno.dev", "https://fresh.deno.dev/"),
    ]
    for name, url in targets:
        results = []
        for _ in range(3):
            try:
                r = requests.get(url, timeout=12, proxies=_PROXIES)
                results.append(f"HTTP{r.status_code}")
            except Exception as e:
                results.append(type(e).__name__)
        _log(f"diag {name}: {' '.join(results)}")


def _loop() -> None:
    global _PROXIES
    _log("bot polling started")
    _diag()
    # Connectivity check: proves whether the host can reach api.telegram.org at
    # all (some datacenters block it the way they block YouTube).
    me = _api("getMe", http_timeout=25)
    _log(f"getMe direct: ok={me.get('ok')} user={(me.get('result') or {}).get('username')}")
    if not me.get("ok"):
        purl = _proxy_url()
        if purl:
            _PROXIES = {"http": purl, "https": purl}
            me = _api("getMe", http_timeout=40)
            _log(f"getMe via proxy: ok={me.get('ok')} "
                 f"user={(me.get('result') or {}).get('username')}")
            if not me.get("ok"):
                _PROXIES = None
                _log("proxy route failed too — bot will keep retrying directly")
        else:
            _log("no proxy configured — bot will keep retrying directly")
    _api("deleteWebhook")               # long polling requires no webhook set
    offset = 0
    cycles = 0
    fails = 0
    while True:
        try:
            resp = _api("getUpdates", http_timeout=65, offset=offset,
                        allowed_updates=["message", "callback_query"], timeout=50)
            if not resp.get("ok"):
                fails += 1
                _log(f"getUpdates failed #{fails}: {resp.get('error_code')} "
                     f"{resp.get('description') or 'empty/non-JSON response'}")
                if resp.get("error_code") == 409:   # a webhook is still set — remove it
                    _api("deleteWebhook")
                time.sleep(min(5 * fails, 60))
                continue
            fails = 0
            cycles += 1
            if cycles == 1 or cycles % 50 == 0:
                _log(f"polling OK (cycle {cycles})")
            for upd in resp.get("result", []):
                offset = max(offset, upd["update_id"] + 1)
                process_update(upd)
        except Exception as e:  # noqa: BLE001 — the polling thread must never die
            _log(f"loop error: {e}")
            time.sleep(5)


def process_update(upd: dict) -> None:
    """Dispatch one Telegram update (used by both polling and webhook modes)."""
    try:
        if upd.get("message"):
            _handle(upd["message"])
        elif upd.get("callback_query"):
            _handle_callback(upd["callback_query"])
    except Exception as e:  # noqa: BLE001
        _log(f"handler error: {e}")


def _webhook_setup() -> None:
    """Webhook mode: Telegram pushes updates to the relay (no constant polling)."""
    _log("bot webhook mode")
    me = _api("getMe", http_timeout=25)
    _log(f"getMe: ok={me.get('ok')} user={(me.get('result') or {}).get('username')}")
    params = {"url": f"{API_BASE}/tg-hook",
              "allowed_updates": ["message", "callback_query"]}
    if HOOK_SECRET:
        params["secret_token"] = HOOK_SECRET
    else:
        _log("WARNING: TELEGRAM_HOOK_SECRET is empty — the relay will reject updates")
    r = _api("setWebhook", **params)
    _log(f"setWebhook: ok={r.get('ok')} {r.get('description') or ''}")


def start_bot() -> None:
    """Start the bot once (idempotent): webhook registration or polling loop."""
    global _STARTED
    if _STARTED or not TOKEN:
        return
    _STARTED = True
    target = _webhook_setup if MODE == "webhook" else _loop
    threading.Thread(target=target, daemon=True).start()
