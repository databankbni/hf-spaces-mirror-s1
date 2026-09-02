import csv
import io
import json
import os
import random
import re
import uuid
import warnings
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import traceback

import gradio as gr
from starlette.exceptions import StarletteDeprecationWarning

try:
    from huggingface_hub import CommitOperationAdd, HfApi
except Exception:  # pragma: no cover - keeps local-only mode available.
    CommitOperationAdd = None
    HfApi = None


warnings.filterwarnings("ignore", category=StarletteDeprecationWarning)


APP_DIR = Path(__file__).resolve().parent
SAMPLES_DIR = APP_DIR / "samples"
CSV_PATH = APP_DIR / "study_results.csv"
JSONL_PATH = APP_DIR / "study_results.jsonl"
CLASS_INDEX_PATH = APP_DIR / "imagenet_class_index.json"
CACHE_DIR = Path(os.environ.get("STUDY_CACHE_DIR", "/tmp/duodit_user_study_cache"))

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
CACHE_KEY_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
PREFERENCE_OPTIONS = ["Option A", "About the same", "Option B"]
LOCAL_BROWSER_CACHE_KEY = "duodit_user_study_progress_v2"
QUESTION_LIMIT = int(os.environ["QUESTION_LIMIT"]) if os.environ.get("QUESTION_LIMIT") else None
HF_TOKEN = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACEHUB_API_TOKEN")
HF_DATASET_PRIVATE = os.environ.get("HF_DATASET_PRIVATE", "true").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
HF_DEFAULT_NAMESPACE = (
    os.environ.get("HF_DATASET_NAMESPACE")
    or os.environ.get("SPACE_AUTHOR_NAME")
    or "mostafashahbazi"
).strip()
HF_DEFAULT_RESULTS_REPO_NAME = (
    os.environ.get("HF_RESULTS_REPO_NAME")
    or "duodit-user-study-results"
).strip()
HF_DATASET_REPO_ID = (
    os.environ.get("HF_DATASET_REPO_ID")
    or f"{HF_DEFAULT_NAMESPACE}/{HF_DEFAULT_RESULTS_REPO_NAME}"
).strip()
HF_RESULTS_DIR = os.environ.get("HF_RESULTS_DIR", "data/submissions").strip().strip("/")
PUBLIC_STUDY_URL = (
    os.environ.get("PUBLIC_STUDY_URL")
    or os.environ.get("GRADIO_PUBLIC_URL")
    or ""
).strip()
IS_HF_SPACE = bool(os.environ.get("SPACE_ID") or os.environ.get("SPACE_HOST"))
ENABLE_GRADIO_SHARE = (
    os.environ.get("ENABLE_GRADIO_SHARE")
    or os.environ.get("GRADIO_SHARE")
    or "true"
).lower() in {"1", "true", "yes", "on"}
DISABLE_AUTO_RELOAD_HEAD = """
<script>
(() => {
  const originalFetch = window.fetch ? window.fetch.bind(window) : null;
  if (originalFetch) {
    window.fetch = async (...args) => {
      const request = args[0];
      const url = typeof request === "string" ? request : request?.url || "";
      if (url.includes("/dev/reload")) {
        return new Response(JSON.stringify({}), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      return originalFetch(...args);
    };
  }

  const OriginalEventSource = window.EventSource;
  if (OriginalEventSource) {
    window.EventSource = function(url, config) {
      if (typeof url === "string" && url.includes("/dev/reload")) {
        console.warn("[study] blocked Gradio dev reload EventSource:", url);
        return {
          close() {},
          addEventListener() {},
          removeEventListener() {},
          dispatchEvent() { return false; },
          readyState: 2,
          url,
          withCredentials: false,
          onopen: null,
          onmessage: null,
          onerror: null,
        };
      }
      return new OriginalEventSource(url, config);
    };
    window.EventSource.prototype = OriginalEventSource.prototype;
  }

  try {
    const originalReload = window.location.reload.bind(window.location);
    window.location.reload = (...args) => {
      console.warn("[study] blocked automatic page reload.", args);
    };
    window.__study_original_reload__ = originalReload;
  } catch (error) {
    console.warn("[study] could not override window.location.reload", error);
  }
})();
</script>
"""
PERSIAN_CLASS_NAMES = {
    "house finch": "سهره خانگی",
    "robin": "سینه‌سرخ",
    "triceratops": "تریسراتوپس",
    "green mamba": "مامبای سبز",
    "harvestman": "درازپایان",
    "toucan": "توکان",
    "goose": "غاز",
    "jellyfish": "عروس دریایی",
    "nematode": "نماتود",
    "king crab": "خرچنگ شاه",
    "dugong": "دوگونگ",
    "Walker hound": "سگ شکاری واکر",
    "Ibizan hound": "سگ شکاری ایبیزن",
    "Saluki": "سالوکی",
    "golden retriever": "گلدن رتریور",
    "Gordon setter": "گوردون ستر",
    "komondor": "کوموندور",
    "boxer": "باکسر",
    "Tibetan mastiff": "ماستیف تبتی",
    "French bulldog": "بولداگ فرانسوی",
    "malamute": "مالاموت",
    "dalmatian": "دالمیشن",
    "Newfoundland": "نیوفاندلند",
    "miniature poodle": "پودل مینیاتوری",
    "white wolf": "گرگ سفید",
    "African hunting dog": "سگ شکارچی آفریقایی",
    "Arctic fox": "روباه قطبی",
    "lion": "شیر",
    "meerkat": "میرکت",
    "ladybug": "کفشدوزک",
    "rhinoceros beetle": "سوسک کرگدنی",
    "ant": "مورچه",
    "black-footed ferret": "سمور پاسیاه",
    "three-toed sloth": "تنبل سه‌انگشتی",
    "rock beauty": "ماهی فرشته‌ای صخره‌ای",
    "aircraft carrier": "ناو هواپیمابر",
    "ashcan": "سطل زباله",
    "barrel": "بشکه",
    "beer bottle": "بطری آبجو",
    "bookshop": "کتابفروشی",
    "cannon": "توپ",
    "carousel": "چرخ‌وفلک",
    "carton": "کارتن",
    "catamaran": "کاتاماران",
    "chime": "زنگ آویز",
    "clog": "کفش چوبی",
    "cocktail shaker": "شیکر کوکتل",
    "combination lock": "قفل رمزی",
    "crate": "صندوق",
    "cuirass": "زره سینه",
    "dishrag": "دستمال ظرف",
    "dome": "گنبد",
    "electric guitar": "گیتار برقی",
    "file": "پرونده",
    "fire screen": "محافظ شومینه",
    "frying pan": "ماهیتابه",
    "garbage truck": "کامیون حمل زباله",
    "hair slide": "گیره مو",
    "holster": "غلاف",
    "horizontal bar": "میله افقی",
    "hourglass": "ساعت شنی",
    "iPod": "آی‌پاد",
    "lipstick": "رژ لب",
    "miniskirt": "دامن کوتاه",
    "missile": "موشک",
    "mixing bowl": "کاسه مخلوط‌کردن",
    "oboe": "ابوا",
    "organ": "ارگ",
    "parallel bars": "میله‌های موازی",
    "pencil box": "جامدادی",
    "photocopier": "دستگاه کپی",
    "poncho": "پانچو",
    "prayer rug": "سجاده",
    "reel": "قرقره",
    "school bus": "اتوبوس مدرسه",
    "scoreboard": "تابلوی امتیازات",
    "slot": "شکاف",
    "snorkel": "اسنورکل",
    "solar dish": "بشقاب خورشیدی",
    "spider web": "تار عنکبوت",
    "stage": "صحنه",
    "tank": "تانک",
    "theater curtain": "پرده تئاتر",
    "tile roof": "سقف کاشی‌پوش",
    "tobacco shop": "دخانیات‌فروشی",
    "unicycle": "تک‌چرخه",
    "upright": "پیانوی دیواری",
    "vase": "گلدان",
    "wok": "ووک",
    "worm fence": "حصار چوبی زیگزاگی",
    "yawl": "قایق یاول",
    "street sign": "تابلوی خیابان",
    "consomme": "کنسومه",
    "trifle": "دسر ترافل",
    "hotdog": "هات‌داگ",
    "orange": "پرتقال",
    "cliff": "صخره",
    "coral reef": "آب‌سنگ مرجانی",
    "bolete": "قارچ بولت",
    "ear": "بلال ذرت",
}


def load_class_index() -> dict[str, dict[str, str]]:
    raw_index = json.loads(CLASS_INDEX_PATH.read_text(encoding="utf-8"))
    class_index = {}
    for key, value in raw_index.items():
        synset, class_name = value
        class_dir = f"class_{int(key):04d}"
        class_index[class_dir] = {
            "class_id": key,
            "synset": synset,
            "class_name": class_name.replace("_", " "),
            "class_name_fa": PERSIAN_CLASS_NAMES.get(class_name.replace("_", " "), ""),
        }
    return class_index


CLASS_INDEX = load_class_index()


def init_storage() -> None:
    CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    JSONL_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not CSV_PATH.exists():
        with CSV_PATH.open("w", newline="", encoding="utf-8") as file:
            writer = csv.writer(file)
            writer.writerow(
                [
                    "submission_id",
                    "participant_email",
                    "started_at",
                    "submitted_at",
                    "question_id",
                    "question_index",
                    "prompt_id",
                    "filename",
                    "class_dir",
                    "class_id",
                    "synset",
                    "class_name",
                    "class_name_fa",
                    "left_label",
                    "right_label",
                    "left_model",
                    "right_model",
                    "left_image",
                    "right_image",
                    "preference",
                ]
            )
    if not JSONL_PATH.exists():
        JSONL_PATH.touch()
    print(f"[study] storage ready: {CSV_PATH}")
    print(f"[study] storage ready: {JSONL_PATH}")


def save_submission_to_hf_dataset(rows: list[dict]) -> str:
    if not HF_DATASET_REPO_ID:
        return "Hugging Face Dataset not configured; saved local backup only."
    if not HF_TOKEN:
        return "HF_TOKEN is missing; saved local backup only."
    if HfApi is None or CommitOperationAdd is None:
        return "huggingface_hub is unavailable; saved local backup only."

    submission_id = rows[0]["submission_id"]
    submitted_at = rows[0]["submitted_at"].replace(":", "-")
    file_name = f"{submitted_at}_{submission_id}.jsonl"
    path_in_repo = f"{HF_RESULTS_DIR}/{file_name}" if HF_RESULTS_DIR else file_name
    payload = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows).encode(
        "utf-8"
    )

    try:
        api = HfApi(token=HF_TOKEN)
        api.create_repo(
            repo_id=HF_DATASET_REPO_ID,
            repo_type="dataset",
            private=HF_DATASET_PRIVATE,
            exist_ok=True,
        )
        api.create_commit(
            repo_id=HF_DATASET_REPO_ID,
            repo_type="dataset",
            operations=[
                CommitOperationAdd(
                    path_in_repo=path_in_repo,
                    path_or_fileobj=io.BytesIO(payload),
                )
            ],
            commit_message=f"Add user study submission {submission_id}",
        )
    except Exception as error:
        print("[study] Hugging Face Dataset save failed")
        print(traceback.format_exc())
        return f"Hugging Face Dataset save failed: {error}; saved local backup."

    return f"Saved to Hugging Face Dataset: {HF_DATASET_REPO_ID}/{path_in_repo}"


def load_pairs() -> list[dict]:
    duodit_dir = SAMPLES_DIR / "duodit200"
    baseline_dir = SAMPLES_DIR / "lightningdit"

    def sample_key(path: Path) -> tuple[str, str]:
        class_name = path.parent.name
        sample_id = path.stem.split("-", 1)[0]
        return class_name, sample_id

    duodit_files = {
        sample_key(path): path for path in duodit_dir.rglob("*.png") if path.is_file()
    }
    baseline_files = {
        sample_key(path): path for path in baseline_dir.rglob("*.png") if path.is_file()
    }
    shared_keys = sorted(set(duodit_files) & set(baseline_files))
    if not shared_keys:
        raise RuntimeError(
            "No matched image pairs were found in samples/duodit200 and samples/lightningdit."
        )
    if QUESTION_LIMIT is not None:
        shared_keys = shared_keys[:QUESTION_LIMIT]

    pairs = []
    for index, pair_key in enumerate(shared_keys, start=1):
        class_name, sample_id = pair_key
        class_info = CLASS_INDEX.get(
            class_name,
            {
                "class_id": class_name.removeprefix("class_"),
                "synset": "",
                "class_name": class_name.replace("_", " "),
            },
        )
        duodit_path = duodit_files[pair_key]
        baseline_path = baseline_files[pair_key]
        duo_left = random.choice([True, False])
        pairs.append(
            {
                "id": f"pair_{index:02d}",
                "prompt_id": f"{class_name}_{sample_id}",
                "filename": f"{class_name}/{duodit_path.name}",
                "class_dir": class_name,
                "class_id": class_info["class_id"],
                "synset": class_info["synset"],
                "class_name": class_info["class_name"],
                "class_name_fa": class_info.get("class_name_fa", ""),
                "left_label": "A",
                "right_label": "B",
                "left_model": "DuoDiT" if duo_left else "LightningDiT",
                "right_model": "LightningDiT" if duo_left else "DuoDiT",
                "left_image": str(duodit_path if duo_left else baseline_path),
                "right_image": str(baseline_path if duo_left else duodit_path),
            }
        )
    return pairs


QUESTION_BANK = load_pairs()


def empty_session() -> dict:
    return {
        "submission_id": None,
        "participant_email": "",
        "started_at": None,
        "pairs": [],
        "responses": {},
        "complete": False,
    }


def session_to_text(session: dict) -> str:
    return json.dumps(session, ensure_ascii=False)


def session_email(session: dict) -> str:
    return (session.get("participant_email") or "").strip().lower()


def email_input(value: str = "", interactive: bool = True) -> gr.Textbox:
    return gr.Textbox(
        value=value,
        label="Email address",
        type="email",
        placeholder="name@example.com",
        info="Required before the study starts.",
        autofocus=True,
        interactive=interactive,
    )


def configured_public_study_url() -> str:
    if PUBLIC_STUDY_URL:
        return PUBLIC_STUDY_URL

    space_host = os.environ.get("SPACE_HOST", "").strip()
    if space_host:
        if space_host.startswith(("http://", "https://")):
            return space_host
        return f"https://{space_host}"

    return ""


def public_link_markdown(preferred_url: str = "") -> str:
    url = (preferred_url or "").strip() or configured_public_study_url()
    if url:
        return (
            f"**Study access link for this build:** [{url}]({url})\n\n"
            "Participants can also enter the form through this link."
        )
    return (
        "**Public access link is enabled for this build.**\n\n"
        "After the page loads, this message will show the current form link. "
        "You can also use the public `gradio.live` link printed in the server log."
    )


def runtime_public_link_markdown(current_url: str = "") -> str:
    demo_object = globals().get("demo")
    share_url = getattr(demo_object, "share_url", "") if demo_object is not None else ""
    return public_link_markdown(share_url or current_url)


PUBLIC_LINK_LOAD_JS = f"""
() => {{
  return window.location.href;
}}
"""

RESTORE_BROWSER_STATE_JS = f"""
(browserState) => {{
  const storageKey = {json.dumps(LOCAL_BROWSER_CACHE_KEY)};

  const inspectState = (state) => {{
    if (!state || typeof state !== "object") {{
      return {{useful: false, active: false, responses: 0, index: 0, savedAt: 0, submissionId: ""}};
    }}
    let active = false;
    let responses = 0;
    let submissionId = "";
    try {{
      const session = state.session_json ? JSON.parse(state.session_json) : null;
      active = Array.isArray(session?.pairs) && session.pairs.length > 0;
      responses = session?.responses && typeof session.responses === "object"
        ? Object.keys(session.responses).length
        : 0;
      submissionId = session?.submission_id || "";
    }} catch (error) {{
      active = false;
    }}
    return {{
      useful: active || Boolean(state.email || state.cache_key),
      active,
      responses,
      index: Number.parseInt(state.current_index ?? 0, 10) || 0,
      savedAt: Date.parse(state.saved_at || "") || 0,
      submissionId,
    }};
  }};

  const chooseState = (localState, browserState) => {{
    const localInfo = inspectState(localState);
    const browserInfo = inspectState(browserState);
    if (!localInfo.useful) {{
      return browserState;
    }}
    if (!browserInfo.useful) {{
      return localState;
    }}
    if (localInfo.active !== browserInfo.active) {{
      return localInfo.active ? localState : browserState;
    }}
    if (
      localInfo.submissionId &&
      browserInfo.submissionId &&
      localInfo.submissionId === browserInfo.submissionId &&
      localInfo.responses !== browserInfo.responses
    ) {{
      return localInfo.responses > browserInfo.responses ? localState : browserState;
    }}
    return localInfo.savedAt >= browserInfo.savedAt ? localState : browserState;
  }};

  try {{
    const raw = window.localStorage.getItem(storageKey);
    if (!raw) {{
      return browserState;
    }}
    const localState = JSON.parse(raw);
    return chooseState(localState, browserState);
  }} catch (error) {{
    console.warn("[study] could not restore local browser cache", error);
    return browserState;
  }}
}}
"""

SAVE_BROWSER_STATE_JS = f"""
(browserState) => {{
  const storageKey = {json.dumps(LOCAL_BROWSER_CACHE_KEY)};
  if (!browserState || typeof browserState !== "object") {{
    return;
  }}

  let hasActiveSession = false;
  if (browserState.session_json) {{
    try {{
      const session = JSON.parse(browserState.session_json);
      hasActiveSession = Array.isArray(session?.pairs) && session.pairs.length > 0;
    }} catch (error) {{
      hasActiveSession = false;
    }}
  }}

  if (!hasActiveSession && !browserState.email && !browserState.cache_key) {{
    return;
  }}

  try {{
    window.localStorage.setItem(
      storageKey,
      JSON.stringify({{...browserState, saved_at: new Date().toISOString()}})
    );
  }} catch (error) {{
    console.warn("[study] could not save local browser cache", error);
  }}
  return browserState;
}}
"""


def cache_path(cache_key: str) -> Path:
    if not CACHE_KEY_RE.match(cache_key):
        raise ValueError("Invalid cache key.")
    return CACHE_DIR / f"{cache_key}.json"


def write_user_cache(session: dict, index: int) -> str | None:
    cache_key = session.get("submission_id")
    if not cache_key:
        return None

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "cached_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "current_index": int(index),
        "session": session,
    }
    destination = cache_path(cache_key)
    temporary = destination.with_name(f"{destination.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return cache_key


def read_user_cache(cache_key: str | None) -> tuple[dict, int] | None:
    if not cache_key:
        return None
    try:
        path = cache_path(cache_key)
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        session = payload.get("session")
        if not isinstance(session, dict) or not session.get("pairs"):
            return None
        return session, int(payload.get("current_index", 0))
    except Exception:
        print("[study] read_user_cache failed")
        print(traceback.format_exc())
        return None


def browser_state_value(session: dict, index: int, email_value: str | None = None) -> dict:
    try:
        cache_key = write_user_cache(session, index)
    except Exception:
        print("[study] write_user_cache failed; continuing with browser state only")
        print(traceback.format_exc())
        cache_key = session.get("submission_id")
    stored_email = session_email(session) or (email_value or "").strip().lower()
    return {
        "version": 2,
        "cache_key": cache_key,
        "email": stored_email,
        "session_json": session_to_text(session),
        "current_index": int(index),
        "saved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def text_to_session(text: str) -> dict:
    if not text:
        return empty_session()
    return json.loads(text)


def render_image(image_path: str, option_label: str) -> str:
    return (
        f'<div style="position:relative;border:1px solid var(--block-border-color);'
        f'border-radius:12px;overflow:hidden;min-height:260px;background:var(--block-background-fill)">'
        f'<div style="position:absolute;top:12px;left:12px;z-index:2;'
        f'padding:6px 10px;border-radius:999px;background:rgba(17,24,39,.82);'
        f'color:white;font-size:14px;font-weight:600">{option_label}</div>'
        f'<img src="/gradio_api/file={image_path}" alt="{option_label}" '
        f'style="display:block;width:100%;height:100%;min-height:260px;max-height:420px;'
        f'object-fit:contain;background:white" /></div>'
    )


def make_session(email: str) -> dict:
    normalized_email = (email or "").strip().lower()
    pairs = load_pairs()
    return {
        "submission_id": str(uuid.uuid4()),
        "participant_email": normalized_email,
        "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "pairs": pairs,
        "responses": {},
        "complete": False,
    }


def save_response(session: dict, index: int, choice: str) -> dict:
    next_session = deepcopy(session)
    pair = next_session["pairs"][index]
    next_session["responses"][pair["id"]] = choice
    return next_session


def first_unanswered_index(session: dict) -> int | None:
    responses = session.get("responses", {})
    for index, pair in enumerate(session.get("pairs", [])):
        if not responses.get(pair["id"]):
            return index
    return None


def question_ui(session: dict, index: int, message: str = "") -> tuple:
    if not session["pairs"]:
        return (
            "## Waiting to start",
            "Enter your email above, then press Start study.",
            "",
            "",
            gr.Radio(choices=PREFERENCE_OPTIONS, value=None, label="Which image is better overall?", info="Required"),
            gr.Button(value="Previous", visible=True, interactive=False),
            gr.Button(value="Next", visible=True, interactive=False),
            message,
        )

    pair = session["pairs"][index]
    saved_choice = session["responses"].get(pair["id"])
    next_label = "Submit study" if index == len(session["pairs"]) - 1 else "Next"
    return (
        f"## Pair {index + 1} of {len(session['pairs'])}",
        (
            "Compare the two images and answer the required question.\n\n"
            f"Class: **{pair['class_name']}**  \n"
            f"نام فارسی: **{pair['class_name_fa']}**  \n"
            f"Class ID: `{pair['class_id']}`  \n"
            f"Synset: `{pair['synset']}`"
        ),
        render_image(pair["left_image"], "Option A"),
        render_image(pair["right_image"], "Option B"),
        gr.Radio(choices=PREFERENCE_OPTIONS, value=saved_choice, label="Which image is better overall?", info="Required"),
        gr.Button(value="Previous", visible=True, interactive=index > 0),
        gr.Button(value=next_label, visible=True, interactive=not session.get("complete", False)),
        message,
    )


def intro_outputs(message: str, session: dict, index: int, email_value: str | None = None):
    display_email = session_email(session) if email_value is None else email_value
    return (
        session_to_text(session),
        index,
        browser_state_value(session, index, display_email),
        email_input(display_email, interactive=True),
        gr.Button("Start study", variant="primary", size="lg", interactive=True),
        gr.Markdown(value=message),
        *question_ui(session, index),
        gr.Markdown(value=""),
    )


def handled_error_outputs(message: str, session: dict | None = None, index: int = 0):
    safe_session = session if session is not None else empty_session()
    start_enabled = not bool(safe_session.get("pairs"))
    return (
        session_to_text(safe_session),
        index,
        browser_state_value(safe_session, index),
        email_input(session_email(safe_session), interactive=start_enabled),
        gr.Button("Start study", variant="primary", size="lg", interactive=start_enabled),
        gr.Markdown(value=f"Error: {message}"),
        *question_ui(safe_session, index, "A server error was handled. You can continue if the session is still valid."),
        gr.Markdown(value=""),
    )


def start_study(email: str):
    try:
        normalized_email = (email or "").strip().lower()
        if not normalized_email:
            return intro_outputs(
                "Enter your email address before starting the study.",
                empty_session(),
                0,
                normalized_email,
            )
        if not EMAIL_RE.match(normalized_email):
            return intro_outputs(
                "Enter a valid email address to continue.",
                empty_session(),
                0,
                normalized_email,
            )

        session = make_session(normalized_email)
        return (
            session_to_text(session),
            0,
            browser_state_value(session, 0),
            email_input(normalized_email, interactive=False),
            gr.Button("Start study", variant="primary", size="lg", interactive=False),
            gr.Markdown(value=""),
            *question_ui(session, 0),
            gr.Markdown(value=""),
        )
    except Exception as error:
        print("[study] start_study failed")
        print(traceback.format_exc())
        return handled_error_outputs(str(error), empty_session(), 0)


def previous_step(session_text: str, index: int, choice: str):
    try:
        session = text_to_session(session_text)
        current_index = int(index)
        if session["pairs"] and choice:
            session = save_response(session, current_index, choice)
        previous_index = max(0, current_index - 1)
        return (
            session_to_text(session),
            previous_index,
            browser_state_value(session, previous_index),
            email_input(session_email(session), interactive=False),
            gr.Button("Start study", variant="primary", size="lg", interactive=False),
            gr.Markdown(value=""),
            *question_ui(session, previous_index),
            gr.Markdown(value=""),
        )
    except Exception as error:
        print("[study] previous_step failed")
        print(traceback.format_exc())
        return handled_error_outputs(str(error), text_to_session(session_text), int(index or 0))


def write_submission(session: dict):
    missing_index = first_unanswered_index(session)
    if missing_index is not None:
        raise ValueError(f"Question {missing_index + 1} is required before submission.")

    init_storage()
    submitted_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rows = []
    for index, pair in enumerate(session["pairs"], start=1):
        rows.append(
            {
                "submission_id": session["submission_id"],
                "participant_email": session["participant_email"],
                "started_at": session["started_at"],
                "submitted_at": submitted_at,
                "question_id": pair["id"],
                "question_index": index,
                "prompt_id": pair["prompt_id"],
                "filename": pair["filename"],
                "class_dir": pair["class_dir"],
                "class_id": pair["class_id"],
                "synset": pair["synset"],
                "class_name": pair["class_name"],
                "class_name_fa": pair["class_name_fa"],
                "left_label": pair["left_label"],
                "right_label": pair["right_label"],
                "left_model": pair["left_model"],
                "right_model": pair["right_model"],
                "left_image": pair["left_image"],
                "right_image": pair["right_image"],
                "preference": session["responses"][pair["id"]],
            }
        )

    with CSV_PATH.open("a", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=rows[0].keys())
        writer.writerows(rows)

    with JSONL_PATH.open("a", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")

    hf_status = save_submission_to_hf_dataset(rows)
    print(
        f"[study] saved submission {session['submission_id']} "
        f"with {len(rows)} rows to {CSV_PATH.name} and {JSONL_PATH.name}"
    )
    print(f"[study] {hf_status}")
    return hf_status


def restore_from_browser(saved_state: dict | None):
    try:
        if not isinstance(saved_state, dict):
            return intro_outputs("", empty_session(), 0)
        saved_email = (saved_state.get("email") or "").strip().lower()
        cached = read_user_cache(saved_state.get("cache_key"))
        if cached is not None:
            session, index = cached
        else:
            session = text_to_session(saved_state.get("session_json", ""))
            index = int(saved_state.get("current_index", 0))
        if not session.get("pairs"):
            return intro_outputs("", empty_session(), 0, saved_email)
        index = max(0, min(index, len(session["pairs"]) - 1))
        return (
            session_to_text(session),
            index,
            browser_state_value(session, index),
            email_input(session_email(session) or saved_email, interactive=False),
            gr.Button("Start study", variant="primary", size="lg", interactive=False),
            gr.Markdown(value=""),
            *question_ui(session, index, "Progress restored from this browser."),
            gr.Markdown(value=""),
        )
    except Exception as error:
        print("[study] restore_from_browser failed")
        print(traceback.format_exc())
        return handled_error_outputs(str(error), empty_session(), 0)


def remember_current_choice(session_text: str, index: int, choice: str):
    try:
        session = text_to_session(session_text)
        current_index = int(index or 0)
        if session.get("pairs") and choice:
            session = save_response(session, current_index, choice)
        return session_to_text(session), browser_state_value(session, current_index)
    except Exception:
        print("[study] remember_current_choice failed")
        print(traceback.format_exc())
        return session_text, {"session_json": session_text or "", "current_index": int(index or 0)}


def remember_email(email: str, saved_state: dict | None):
    normalized_email = (email or "").strip().lower()
    state = saved_state if isinstance(saved_state, dict) else {}
    state["email"] = normalized_email
    return state, gr.Markdown(value="")


def persist_browser_state_noop(_saved_state: dict | None):
    return None


def next_or_submit(session_text: str, index: int, choice: str):
    try:
        session = text_to_session(session_text)
        if not session["pairs"]:
            return intro_outputs("Start the study first.", empty_session(), 0)

        current_index = int(index)
        if not choice:
            return (
                session_to_text(session),
                current_index,
                browser_state_value(session, current_index),
                email_input(session_email(session), interactive=False),
                gr.Button("Start study", variant="primary", size="lg", interactive=False),
                gr.Markdown(value=""),
                *question_ui(session, current_index, "Select one option before continuing."),
                gr.Markdown(value=""),
            )

        session = save_response(session, current_index, choice)

        if current_index == len(session["pairs"]) - 1:
            missing_index = first_unanswered_index(session)
            if missing_index is not None:
                return (
                    session_to_text(session),
                    missing_index,
                    browser_state_value(session, missing_index),
                    email_input(session_email(session), interactive=False),
                    gr.Button("Start study", variant="primary", size="lg", interactive=False),
                    gr.Markdown(value=""),
                    *question_ui(
                        session,
                        missing_index,
                        f"Question {missing_index + 1} is required before final submission.",
                    ),
                    gr.Markdown(value=""),
                )
            session["complete"] = True
            storage_status = write_submission(session)
            completion_message = (
                "## Submission complete\n"
                "Thank you for completing the study.\n\n"
                f"Submission ID: `{session['submission_id']}`\n\n"
                f"{storage_status}"
            )
            return (
                session_to_text(session),
                current_index,
                browser_state_value(session, current_index),
                email_input(session_email(session), interactive=False),
                gr.Button("Start study", variant="primary", size="lg", interactive=False),
                gr.Markdown(value=""),
                *question_ui(session, current_index),
                gr.Markdown(value=completion_message),
            )

        next_index = current_index + 1
        return (
            session_to_text(session),
            next_index,
            browser_state_value(session, next_index),
            email_input(session_email(session), interactive=False),
            gr.Button("Start study", variant="primary", size="lg", interactive=False),
            gr.Markdown(value=""),
            *question_ui(session, next_index),
            gr.Markdown(value=""),
        )
    except Exception as error:
        print("[study] next_or_submit failed")
        print(traceback.format_exc())
        return handled_error_outputs(str(error), text_to_session(session_text), int(index or 0))


with gr.Blocks(title="DuoDiT User Study") as demo:
    session_json = gr.Textbox(value="", visible=False)
    current_index = gr.Number(value=0, precision=0, visible=False)
    browser_state = gr.BrowserState(
        default_value=browser_state_value(empty_session(), 0),
        storage_key="duodit_user_study_progress",
    )

    gr.Markdown(
        f"""
# DuoDiT vs. LightningDiT User Study

- Enter your email to begin.
- Only one comparison panel is used, and its content changes as you move through the study.
- Each question is required before submission.
- Question count: `{QUESTION_LIMIT if QUESTION_LIMIT is not None else "all available pairs"}`
        """
    )
    public_link = gr.Markdown(public_link_markdown())
    current_url = gr.Textbox(value="", visible=False)
    email = gr.Textbox(
        label="Email address",
        type="email",
        placeholder="name@example.com",
        info="Required before the study starts.",
        autofocus=True,
    )
    start_button = gr.Button("Start study", variant="primary", size="lg")
    intro_message = gr.Markdown("")

    progress = gr.Markdown("## Waiting to start")
    helper = gr.Markdown("Enter your email above, then press Start study.")
    with gr.Row(equal_height=True):
        with gr.Column():
            left_html = gr.HTML(value="")
        with gr.Column():
            right_html = gr.HTML(value="")
    choice = gr.Radio(
        choices=PREFERENCE_OPTIONS,
        value=None,
        label="Which image is better overall?",
        info="Required",
    )
    nav_message = gr.Markdown("")
    with gr.Row():
        previous_button = gr.Button("Previous", variant="secondary", visible=True, interactive=False)
        next_button = gr.Button("Next", variant="primary", visible=True, interactive=False)

    completion = gr.Markdown("")

    outputs = [
        session_json,
        current_index,
        browser_state,
        email,
        start_button,
        intro_message,
        progress,
        helper,
        left_html,
        right_html,
        choice,
        previous_button,
        next_button,
        nav_message,
        completion,
    ]

    start_button.click(
        fn=start_study,
        inputs=[email],
        outputs=outputs,
        queue=False,
        show_progress="minimal",
    )
    email.change(
        fn=remember_email,
        inputs=[email, browser_state],
        outputs=[browser_state, intro_message],
        queue=False,
        show_progress="hidden",
    )
    demo.load(
        fn=restore_from_browser,
        inputs=[browser_state],
        outputs=outputs,
        js=RESTORE_BROWSER_STATE_JS,
        queue=False,
        show_progress="hidden",
    )
    demo.load(
        fn=runtime_public_link_markdown,
        inputs=[current_url],
        outputs=public_link,
        js=PUBLIC_LINK_LOAD_JS,
        queue=False,
        show_progress="hidden",
    )
    choice.change(
        fn=remember_current_choice,
        inputs=[session_json, current_index, choice],
        outputs=[session_json, browser_state],
        queue=False,
        show_progress="hidden",
    )
    browser_state.change(
        fn=persist_browser_state_noop,
        inputs=[browser_state],
        outputs=[],
        js=SAVE_BROWSER_STATE_JS,
        queue=False,
        show_progress="hidden",
    )
    previous_button.click(
        fn=previous_step,
        inputs=[session_json, current_index, choice],
        outputs=outputs,
        queue=False,
        show_progress="minimal",
    )
    next_button.click(
        fn=next_or_submit,
        inputs=[session_json, current_index, choice],
        outputs=outputs,
        queue=False,
        show_progress="minimal",
    )


if __name__ == "__main__":
    init_storage()
    launch_share = ENABLE_GRADIO_SHARE and not IS_HF_SPACE
    if ENABLE_GRADIO_SHARE and IS_HF_SPACE:
        print("[study] share=True is disabled on Hugging Face Spaces; use the Space URL instead.")
    demo.launch(
        share=launch_share,
        allowed_paths=[str(APP_DIR)],
        show_error=True,
        head=DISABLE_AUTO_RELOAD_HEAD,
    )
