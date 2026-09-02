from __future__ import annotations

import json
import os
import shutil
import sys
import threading
import traceback
from pathlib import Path
from uuid import uuid4

import gradio as gr
import time

APP_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = Path(
    os.getenv("MOK_PROJECT_ROOT", str(APP_DIR.parent.parent))
).resolve()

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ai_director.creative_studio.intelligence.m15_learning.runtime.mok_internet_deployment_boundary import MOKInternetBoundaryViolation
from ai_director.creative_studio.intelligence.m15_learning.runtime.mok_internet_deployment_boundary import MOKInternetDeploymentBoundary
from ai_director.creative_studio.intelligence.m15_learning.runtime.mok_internet_deployment_boundary import MOKNativeWebKnowledgeAuthority
from ai_director.creative_studio.intelligence.m15_learning.runtime.mok_native_production_observer import MOKNativeProductionObserver
from ai_director.creative_studio.intelligence.m15_learning.runtime.mok_public_autonomous_production_bridge import MOKPublicAutonomousProductionBridge
from ai_director.creative_studio.intelligence.m15_learning.runtime.mok_public_ingress_guard import MOKPublicIngressGuard

boundary = MOKInternetDeploymentBoundary(PROJECT_ROOT)
observer = MOKNativeProductionObserver(PROJECT_ROOT)
bridge = MOKPublicAutonomousProductionBridge()
ingress_guard = MOKPublicIngressGuard(
    window_seconds=60,
    max_requests_per_window=3,
)
production_lock = threading.Lock()

# Public contention lease.
# Admission/isolation only ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â‚¬Å¾Ã‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â¦ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â never production authority.
production_lease_guard = threading.Lock()
production_lease_until = 0.0
PRODUCTION_LEASE_SECONDS = 5.0

PUBLIC_PRODUCTION_ROOT = (
    PROJECT_ROOT
    / "output"
    / "mok_h10_1e_gradio_production"
).resolve()

PUBLIC_PRODUCTION_ROOT.mkdir(
    parents=True,
    exist_ok=True,
)


def _public_failure(code):
    return json.dumps(boundary.public_error(code), indent=2)


def _request_identity(request):
    if request is None:
        return "direct-call"

    try:
        headers = dict(request.headers or {})
    except Exception:
        headers = {}

    cloudflare_ip = str(
        headers.get("cf-connecting-ip") or ""
    ).strip()

    if cloudflare_ip:
        return "cf:" + cloudflare_ip

    client = getattr(request, "client", None)
    host = getattr(client, "host", None)

    if host:
        return "ip:" + str(host)

    session_hash = getattr(
        request,
        "session_hash",
        None,
    )

    if session_hash:
        return "session:" + str(session_hash)

    return "unknown"


def _rate_limited_response(admission):
    payload = boundary.public_error("MOK_RATE_LIMITED")

    if not isinstance(payload, dict):
        payload = {"error": "MOK_RATE_LIMITED"}

    payload.update({
        "rate_limited": True,
        "request_id": admission["request_id"],
        "retry_after_seconds": (
            admission["retry_after_seconds"]
        ),
        "ui_authority": "NONE",
        "ingress_authority": "ADMISSION_ONLY",
    })

    return json.dumps(payload, indent=2)


def health_status():
    try:
        health = observer.snapshot()
        return json.dumps({
            "ok": health.get("production_health") == "HEALTHY",
            "production_health": health.get("production_health"),
            "autonomy_verified": health.get("autonomy_verified"),
            "autonomy_percent": health.get("autonomy_percent"),
            "autonomy_regression_detected": health.get("autonomy_regression_detected"),
            "ui_authority": "NONE",
            "transport_queue": False,
        }, indent=2)
    except Exception:
        return _public_failure("MOK_HEALTH_UNAVAILABLE")


def validate_public_request(brief):
    try:
        brief = "" if brief is None else str(brief).strip()
        if not brief:
            raise MOKInternetBoundaryViolation("Production brief is required.")

        brief_bytes = len(brief.encode("utf-8"))
        boundary.validate_request_size(brief_bytes)

        return json.dumps({
            "ok": True,
            "request_boundary": "VERIFIED",
            "brief_bytes": brief_bytes,
            "public_command_input": False,
            "public_output_path_input": False,
            "transport_queue": False,
        }, indent=2)
    except MOKInternetBoundaryViolation:
        return _public_failure("MOK_REQUEST_REJECTED")
    except Exception:
        return _public_failure("MOK_REQUEST_FAILED")


def run_canonical_production(
    brief,
    assets=None,
    request: gr.Request = None,
):
    try:
        brief = "" if brief is None else str(brief).strip()
        assets = [] if assets is None else list(assets)
        normalized_assets = []
        for asset in assets:
            if not asset:
                continue
            try:
                asset_path = Path(str(asset)).expanduser().resolve()
            except Exception:
                continue
            if asset_path.is_file():
                normalized_assets.append(str(asset_path))
        assets = normalized_assets

        if not brief:
            raise MOKInternetBoundaryViolation("Production brief is required.")

        boundary.validate_request_size(len(brief.encode("utf-8")))

        admission = ingress_guard.admit(
            _request_identity(request)
        )

        if not admission["allowed"]:
            return (
                _rate_limited_response(admission),
                None,
            )

        public_request_id = admission["request_id"]

        # ------------------------------------------------------------
        # MOK PUBLIC SINGLE-OWNER BURST LEASE
        # Admission/isolation only. No execution authority.
        # ------------------------------------------------------------
        global production_lease_until

        with production_lease_guard:
            lease_now = time.monotonic()

            if lease_now < production_lease_until:
                return (_public_failure("MOK_PRODUCTION_BUSY"), None)

            production_lease_until = (
                lease_now + PRODUCTION_LEASE_SECONDS
            )

        if not production_lock.acquire(blocking=False):
            return (_public_failure("MOK_PRODUCTION_BUSY"), None)

        try:
            # --------------------------------------------------------
            # PUBLIC INGRESS -> MOK NATIVE AUTONOMOUS AUTHORITY
            #
            # The public surface supplies INTENT only.
            # It does not supply a command or output artifact path.
            # --------------------------------------------------------
            runtime_context = bridge.build_runtime_context(
                request=brief,
                assets=assets,
                metadata={
                    "milestone": "MOK-H10.5G.3",
                    "surface": "GRADIO_HTTP_API",
                    "cost_usd": 0,
                    "public_command_input": False,
                    "public_output_path_input": False,
                    "gradio_queue": False,
                    "public_request_id": public_request_id,
                },
            )

            result = bridge.runtime_authority.execute_authoritative_production(
                runtime_context
            )

            if not isinstance(result, dict):
                raise RuntimeError("Canonical MOK authority returned invalid result.")

            verified = (
                result.get("executed") is True
                and result.get("success") is True
                and result.get("verified") is True
                and result.get("synthetic") is False
                and result.get("status") == "REAL_PRODUCTION_ARTIFACT_VERIFIED"
            )

            # --------------------------------------------------------
            # ARTIFACT MUST COME FROM MOK RESULT/EVIDENCE.
            # PUBLIC UI NEVER SELECTS THE PRODUCTION OUTPUT PATH.
            # --------------------------------------------------------
            # --------------------------------------------------------
            # AUTHORITATIVE MOK VERIFIED ARTIFACT CONTRACT
            #
            # The public adapter does not infer an artifact from
            # command arguments, stdout, requested paths, or UI input.
            #
            # It consumes only the artifact explicitly emitted by
            # MOK's independent verification evidence.
            # --------------------------------------------------------
            verification = result.get("verification")

            if not isinstance(verification, dict):
                verification = {}

            verified_artifacts = verification.get("artifacts")

            if not isinstance(verified_artifacts, list):
                verified_artifacts = []

            artifact_value = None

            for verified_artifact in verified_artifacts:
                if not isinstance(verified_artifact, dict):
                    continue

                if verified_artifact.get("verified") is not True:
                    continue

                candidate_path = verified_artifact.get("path")

                if candidate_path:
                    artifact_value = candidate_path
                    break

            artifact = None

            if artifact_value:
                artifact = Path(str(artifact_value)).resolve()

            artifact_verified = (
                verified
                and artifact is not None
                and artifact.is_file()
                and artifact.stat().st_size > 0
            )

            public_result = {
                "ok": artifact_verified,
                "status": result.get("status"),
                "executed": result.get("executed"),
                "verified": result.get("verified"),
                "synthetic": result.get("synthetic"),
                "learning_updated": result.get("learning_updated"),
                "next_action": result.get("next_action"),
                "artifact_size_bytes": (
                    artifact.stat().st_size
                    if artifact is not None and artifact.is_file()
                    else 0
                ),
                "ui_authority": "NONE",
                "canonical_authority": result.get("authority"),
                "request_id": public_request_id,
                "ingress_admitted": True,
                "ingress_authority": "ADMISSION_ONLY",
                "ingress_client_token": admission["client_token"],
                "public_command_input": False,
                "public_output_path_input": False,
                "transport_queue": False,
            }

            if not artifact_verified:
                return (json.dumps(public_result, indent=2), None)

            return (
                json.dumps(public_result, indent=2),
                str(artifact),
            )

        finally:
            production_lock.release()

    except MOKInternetBoundaryViolation:
        return (_public_failure("MOK_REQUEST_REJECTED"), None)
    except Exception as exc:
        diagnostic = {
            "event": "MOK_CANONICAL_PRODUCTION_EXCEPTION",
            "exception_type": type(exc).__name__,
            "exception_message": str(exc),
            "traceback": traceback.format_exc(),
        }
        print(
            "MOK_R27_11D_DIAGNOSTIC=" + json.dumps(
                diagnostic,
                ensure_ascii=False,
            ),
            flush=True,
        )
        return (_public_failure("MOK_PRODUCTION_FAILED"), None)


# ============================================================
# MOK-H10.6B-R3 ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â SIMPLIFIED VIEWER EXPERIENCE
#
# Presentation / ingress only.
# Production authority remains exclusively with MOK.
# ============================================================

def _viewer_file_paths(files):
    if not files:
        return []
    if not isinstance(files, (list, tuple)):
        files = [files]
    paths = []
    for item in files:
        if item is None:
            continue
        value = getattr(item, "name", item)
        if value:
            paths.append(str(value))
    return paths


def build_viewer_brief(
    project_type,
    experience,
    photos,
    videos,
    logos,
    documents,
    audio,
):
    project_type = str(project_type or "").strip()
    experience = str(experience or "").strip()

    asset_context = {
        "photos": _viewer_file_paths(photos),
        "videos": _viewer_file_paths(videos),
        "logos": _viewer_file_paths(logos),
        "documents": _viewer_file_paths(documents),
        "audio": _viewer_file_paths(audio),
    }

    lines = [
        "Viewer creative intent:",
        f"Project type: {project_type or 'Not specified'}",
        f"Desired experience: {experience or 'Not specified'}",
        "",
        "Viewer-provided creative assets:",
        json.dumps(asset_context, indent=2),
        "",
        "MOK retains autonomous authority for production planning, execution, output selection, and verification.",
    ]

    return chr(10).join(lines)




# ============================================================
# MOK R25.3B Ã¢â‚¬â€ VIEWER ASSET TRANSPORT ONLY
# ZERO production authority.
# MOK decides autonomously how uploaded assets are used.
# ============================================================
def _mok_collect_viewer_assets(*groups):
    assets = []
    seen = set()

    def collect(value):
        if value is None:
            return

        if isinstance(value, (list, tuple, set)):
            for item in value:
                collect(item)
            return

        candidate = None

        if isinstance(value, dict):
            candidate = (
                value.get('path')
                or value.get('name')
                or value.get('file')
            )
        elif isinstance(value, (str, Path)):
            candidate = str(value)
        else:
            candidate = getattr(value, 'name', None)

        if not candidate:
            return

        try:
            path = Path(str(candidate)).expanduser().resolve()
        except Exception:
            return

        if not path.is_file():
            return

        key = str(path).lower()

        if key in seen:
            return

        seen.add(key)
        assets.append(str(path))

    for group in groups:
        collect(group)

    return assets


def run_viewer_production(
    project_type,
    experience,
    photos,
    videos,
    logos,
    documents,
    audio,
    request: gr.Request = None,
):
    viewer_intent = build_viewer_brief(
        project_type,
        experience,
        photos,
        videos,
        logos,
        documents,
        audio,
    )

    viewer_assets = _mok_collect_viewer_assets(
        photos,
        videos,
        logos,
        documents,
        audio,
    )

    yield (
        "<div class='mok-progress-wrap'>"
        "<div class='mok-progress-label'>10% &mdash; Request received</div>"
        "<div class='mok-progress-track'>"
        "<div class='mok-progress-fill' style='width:10%'></div>"
        "</div>"
        "<div class='mok-progress-message'>"
        "MOK has your request and is deciding how to create it."
        "</div>"
        "</div>",
        gr.skip(),
        gr.skip(),
    )

    yield (
        "<div class='mok-progress-wrap'>"
        "<div class='mok-progress-label'>25% &mdash; Assets ready</div>"
        "<div class='mok-progress-track'>"
        "<div class='mok-progress-fill' style='width:25%'></div>"
        "</div>"
        "<div class='mok-progress-message'>"
        f"MOK received {len(viewer_assets)} real source asset(s)."
        "</div>"
        "</div>",
        gr.skip(),
        gr.skip(),
    )

    yield (
        "<div class='mok-progress-wrap'>"
        "<div class='mok-progress-label'>40% &mdash; Autonomous production underway</div>"
        "<div class='mok-progress-track'>"
        "<div class='mok-progress-fill' style='width:40%'></div>"
        "</div>"
        "<div class='mok-progress-message'>"
        "MOK is autonomously planning, executing, selecting the output, and verifying the result."
        "</div>"
        "</div>",
        gr.skip(),
        gr.skip(),
    )

    try:
        production_evidence, verified_result = run_canonical_production(
            viewer_intent,
            assets=viewer_assets,
            request=request,
        )
    except Exception:
        yield (
            "<div class='mok-progress-wrap'>"
            "<div class='mok-progress-label'>Production stopped</div>"
            "<div class='mok-progress-track'>"
            "<div class='mok-progress-fill' style='width:10%'></div>"
            "</div>"
            "<div class='mok-progress-message'>"
            "MOK could not finish this production. No completed result is being claimed."
            "</div>"
            "</div>",
            gr.skip(),
            gr.skip(),
        )
        raise

    if not verified_result:
        yield (
            "<div class='mok-progress-wrap'>"
            "<div class='mok-progress-label'>Production not verified</div>"
            "<div class='mok-progress-track'>"
            "<div class='mok-progress-fill' style='width:40%'></div>"
            "</div>"
            "<div class='mok-progress-message'>"
            "MOK did not return a verified real artifact. Completion is not being claimed."
            "</div>"
            "</div>",
            production_evidence,
            gr.skip(),
        )
        return

    verified_path = Path(str(verified_result)).resolve()

    if not verified_path.is_file() or verified_path.stat().st_size <= 0:
        yield (
            "<div class='mok-progress-wrap'>"
            "<div class='mok-progress-label'>Verification failed</div>"
            "<div class='mok-progress-track'>"
            "<div class='mok-progress-fill' style='width:40%'></div>"
            "</div>"
            "<div class='mok-progress-message'>"
            "The returned result is not a valid verified artifact. 100% is withheld."
            "</div>"
            "</div>",
            production_evidence,
            gr.skip(),
        )
        return

    yield (
        "<div class='mok-progress-wrap'>"
        "<div class='mok-progress-label'>100% &mdash; Complete</div>"
        "<div class='mok-progress-track'>"
        "<div class='mok-progress-fill' style='width:100%'></div>"
        "</div>"
        "<div class='mok-progress-message'>"
        "Your creation is ready."
        "</div>"
        "</div>",
        production_evidence,
        verified_result,
    )



# MOK_H10_8C_H_H_B_R7_WEB_AUTHORITY
_MOK_NATIVE_WEB_KNOWLEDGE = MOKNativeWebKnowledgeAuthority(
    timeout_seconds=1.5,
    max_results=4,
    cache_seconds=300.0,
)


# ============================================================
# MOK SR-1.3W â€” NATIVE SEMANTIC IDENTITY INTELLIGENCE
# ============================================================

def _mok_identity_memory_path():
    import os

    override = str(
        os.environ.get("MOK_IDENTITY_MEMORY_PATH") or ""
    ).strip()

    if override:
        return override

    return os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "_mok_learned_identity_intents.json",
    )


def _mok_load_identity_memory():
    import json
    import os

    path = _mok_identity_memory_path()

    if not os.path.isfile(path):
        return {}

    try:
        with open(path, "r", encoding="utf-8") as handle:
            value = json.load(handle)

        if not isinstance(value, dict):
            return {}

        return {
            str(key): str(intent)
            for key, intent in value.items()
            if str(key).strip() and str(intent).strip()
        }
    except Exception:
        return {}


def _mok_learn_identity_alias(normalized, intent, confidence):
    import json
    import os

    phrase = str(normalized or "").strip().lower()
    intent = str(intent or "").strip()

    if not phrase or not intent:
        return False

    # Learn only strong classifications.
    if float(confidence or 0.0) < 0.74:
        return False

    memory = _mok_load_identity_memory()

    if memory.get(phrase) == intent:
        return False

    memory[phrase] = intent

    path = _mok_identity_memory_path()
    directory = os.path.dirname(path)

    if directory:
        os.makedirs(directory, exist_ok=True)

    temp_path = path + ".tmp"

    try:
        with open(temp_path, "w", encoding="utf-8") as handle:
            json.dump(
                memory,
                handle,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )

        os.replace(temp_path, path)
        print(
            "MOK_IDENTITY_PHRASE_LEARNED "
            + repr(phrase)
            + " -> "
            + intent,
            flush=True,
        )
        return True
    except Exception as exc:
        try:
            if os.path.isfile(temp_path):
                os.remove(temp_path)
        except Exception:
            pass

        print(
            "MOK_IDENTITY_LEARNING_SKIPPED " + repr(str(exc)),
            flush=True,
        )
        return False


def _mok_resolve_identity_intent(normalized):
    from difflib import SequenceMatcher

    text = str(normalized or "").strip().lower()

    if not text:
        return None, 0.0

    learned = _mok_load_identity_memory()

    learned_intent = learned.get(text)

    if learned_intent:
        return learned_intent, 1.0

    examples = {
        "name_origin": [
            "what does mok mean",
            "what is the meaning of mok",
            "where does the name mok come from",
            "where did mok get its name",
            "how did mok get its name",
            "how did you get the name mok",
            "why are you called mok",
            "why is it called mok",
            "why the name mok",
            "what is behind the name mok",
            "what is the origin of the name mok",
            "where did your name come from",
            "how did you get your name",
            "what does your name mean",
            "does mok come from mokam",
            "is mok from mokam",
            "is mok named after mokam",
            "is the name mok related to mokam",
            "what does mok stand for",
            "does mok stand for anything",
            "why did andreas call it mok",
            "why did andreas name it mok",
            "how was the name mok chosen",
            "how was mok named",
        ],
    }

    best_intent = None
    best_score = 0.0

    for intent, phrases in examples.items():
        for phrase in phrases:
            score = SequenceMatcher(
                None,
                text,
                phrase,
            ).ratio()

            if score > best_score:
                best_score = score
                best_intent = intent

    words = set(text.split())

    name_terms = {
        "name",
        "named",
        "called",
        "meaning",
        "mean",
        "origin",
        "originate",
        "originated",
    }

    source_terms = {
        "from",
        "come",
        "comes",
        "came",
        "get",
        "got",
        "chosen",
        "choose",
        "why",
        "where",
        "how",
    }

    mok_present = (
        "mok" in words
        or "mokam" in words
        or "your" in words
    )

    name_evidence = bool(words.intersection(name_terms))
    source_evidence = bool(words.intersection(source_terms))

    if mok_present and name_evidence:
        best_score = max(best_score, 0.78)
        best_intent = "name_origin"

    if mok_present and name_evidence and source_evidence:
        best_score = max(best_score, 0.88)
        best_intent = "name_origin"

    if "mokam" in words and "mok" in words:
        best_score = max(best_score, 0.90)
        best_intent = "name_origin"

    if "stand for" in text and "mok" in text:
        best_score = max(best_score, 0.94)
        best_intent = "name_origin"

    if best_score < 0.64:
        return None, best_score

    print(
        "MOK_IDENTITY_INTENT "
        + str(best_intent)
        + " confidence="
        + format(best_score, ".3f"),
        flush=True,
    )

    return best_intent, best_score


# ============================================================
# MOK_SR_1_3X_CONVERSATIONAL_AUTHORITY
# MOK_SR_1_3X2_COMPOSITIONAL_INTENT
# ============================================================

def _mok_conversation_memory_path():
    import os

    override = str(
        os.environ.get("MOK_CONVERSATION_MEMORY_PATH") or ""
    ).strip()

    if override:
        return override

    return os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "_mok_conversation_memory.json",
    )


def _mok_new_conversation_memory():
    return {
        "schema": "mok.conversation.v3",
        "active": False,
        "goal": "",
        "project_type": "",
        "audience": "",
        "desired_feeling": "",
        "assets": "",
        "animation_preference": "",
        "pending_slot": "",
        "asked_slots": [],
        "completed_slots": [],
        "turn_count": 0,
        "last_intent": "",
        "ready_for_creation": False,
        "learned_intents": {},
        "turns": [],
    }


def _mok_load_conversation_memory():
    import json
    import os

    path = _mok_conversation_memory_path()

    if not os.path.isfile(path):
        return _mok_new_conversation_memory()

    try:
        with open(path, "r", encoding="utf-8") as handle:
            value = json.load(handle)

        if not isinstance(value, dict):
            return _mok_new_conversation_memory()

        memory = _mok_new_conversation_memory()
        memory.update(value)

        for name in ["asked_slots", "completed_slots", "turns"]:
            if not isinstance(memory.get(name), list):
                memory[name] = []

        if not isinstance(memory.get("learned_intents"), dict):
            memory["learned_intents"] = {}

        return memory

    except Exception:
        return _mok_new_conversation_memory()


def _mok_save_conversation_memory(memory):
    import json
    import os

    path = _mok_conversation_memory_path()
    directory = os.path.dirname(path)

    if directory:
        os.makedirs(directory, exist_ok=True)

    temp_path = path + ".tmp"

    try:
        with open(temp_path, "w", encoding="utf-8") as handle:
            json.dump(
                memory,
                handle,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )

        os.replace(temp_path, path)
        return True

    except Exception as exc:
        print(
            "MOK_CONVERSATION_MEMORY_WRITE_SKIPPED "
            + repr(str(exc)),
            flush=True,
        )
        return False


def _mok_conversation_tokens(text):
    import re

    value = str(text or "").lower()
    value = re.sub(r"[^a-z0-9\s]", " ", value)
    return [word for word in value.split() if word]


def _mok_word_matches(word, roots):
    value = str(word or "").lower()

    for root in roots:
        if value == root or value.startswith(root):
            return True

    return False


def _mok_count_concepts(words, roots):
    count = 0

    for word in words:
        if _mok_word_matches(word, roots):
            count += 1

    return count


def _mok_creative_goal_evidence(text):
    words = _mok_conversation_tokens(text)

    if not words:
        return 0.0

    motivation_roots = {
        "want", "need", "idea", "concept", "goal",
        "plan", "trying", "help", "wish", "hope",
    }

    action_roots = {
        "creat", "mak", "produc", "build", "introduc",
        "communicat", "explain", "understand", "show",
        "present", "tell", "inspir", "promot", "attract",
        "engag", "discover", "teach", "share", "highlight",
        "convinc", "reach", "demonstrat", "celebrat",
    }

    subject_roots = {
        "people", "person", "viewer", "audien", "customer",
        "buyer", "travell", "tourist", "visitor",
        "destination", "brand", "business", "company",
        "product", "service", "event", "family", "famil",
        "story", "message", "experience", "video", "film",
        "photo", "content", "campaign",
    }

    medium_roots = {
        "video", "film", "movie", "cinematic", "animation",
        "photo", "story", "campaign", "content",
    }

    motivation = _mok_count_concepts(words, motivation_roots)
    action = _mok_count_concepts(words, action_roots)
    subject = _mok_count_concepts(words, subject_roots)
    medium = _mok_count_concepts(words, medium_roots)

    score = 0.0

    # Explicit creative medium.
    if medium >= 1 and (motivation >= 1 or action >= 1):
        score = max(score, 0.96)

    # Human goal + meaningful action + subject.
    if motivation >= 1 and action >= 1 and subject >= 1:
        score = max(score, 0.95)

    # Goal/action composition without explicit medium.
    if motivation >= 1 and action >= 1:
        score = max(score, 0.88)

    # Strong communicative action aimed at a subject.
    if action >= 1 and subject >= 1:
        score = max(score, 0.84)

    # Idea/concept + recognizable subject.
    if motivation >= 1 and subject >= 1:
        score = max(score, 0.82)

    return score


def _mok_resolve_conversation_intent(text, memory):
    normalized = " ".join(_mok_conversation_tokens(text))

    if not normalized:
        return None, 0.0

    learned = memory.get("learned_intents") or {}

    if normalized in learned:
        return str(learned[normalized]), 1.0

    # --------------------------------------------------------
    # Context has the highest authority in a follow-up turn.
    # If MOK just asked for audience, the next natural reply
    # is interpreted as audience rather than reclassified.
    # --------------------------------------------------------

    pending = str(memory.get("pending_slot") or "").strip()

    pending_map = {
        "audience": "audience",
        "desired_feeling": "feeling",
        "assets": "assets",
        "animation_preference": "animation",
    }

    if pending in pending_map:
        return pending_map[pending], 0.99

    creative_score = _mok_creative_goal_evidence(normalized)

    if creative_score >= 0.80:
        return "creative_project", creative_score

    words = _mok_conversation_tokens(normalized)

    if memory.get("active"):

        audience_roots = {
            "people", "audien", "travell", "tourist",
            "visitor", "customer", "viewer", "family",
            "famil", "adult", "child", "buyer",
        }

        feeling_roots = {
            "feel", "inspir", "excit", "curious", "eager",
            "premium", "memor", "emotion", "confiden",
            "calm", "happy", "trust", "understand",
        }

        asset_roots = {
            "photo", "picture", "video", "clip", "logo",
            "document", "script", "music", "audio",
            "narration", "image",
        }

        animation_roots = {
            "animat", "motion", "movement", "parallax",
            "zoom", "pan", "transition", "cinemagraph",
        }

        if _mok_count_concepts(words, animation_roots) >= 1:
            return "animation", 0.84

        if _mok_count_concepts(words, asset_roots) >= 1:
            return "assets", 0.82

        if _mok_count_concepts(words, feeling_roots) >= 1:
            return "feeling", 0.80

        if _mok_count_concepts(words, audience_roots) >= 1:
            return "audience", 0.78

    return None, 0.0


def _mok_learn_conversation_intent(text, intent, confidence, memory):
    normalized = " ".join(_mok_conversation_tokens(text))

    if not normalized or not intent:
        return False

    if float(confidence or 0.0) < 0.78:
        return False

    learned = memory.setdefault("learned_intents", {})

    if learned.get(normalized) == intent:
        return False

    learned[normalized] = intent

    if len(learned) > 500:
        for key in list(learned.keys())[:100]:
            learned.pop(key, None)

    print(
        "MOK_CONVERSATION_INTENT_LEARNED "
        + repr(normalized)
        + " -> "
        + str(intent),
        flush=True,
    )

    return True


def _mok_record_conversation_turn(memory, text, intent, confidence):
    from datetime import datetime, timezone

    turns = memory.setdefault("turns", [])

    turns.append({
        "time": datetime.now(timezone.utc).isoformat(),
        "user": str(text or "").strip(),
        "intent": str(intent or "").strip(),
        "confidence": round(float(confidence or 0.0), 4),
    })

    memory["turns"] = turns[-100:]


def _mok_clean_slot_value(slot, text):
    import re

    value = str(text or "").strip()

    if slot == "audience":
        value = re.sub(
            r"^\s*(for|it is for|this is for)\s+",
            "",
            value,
            flags=re.IGNORECASE,
        ).strip()

    return value.strip(" .,!?;:")


def _mok_set_conversation_slot(memory, slot, text):
    value = _mok_clean_slot_value(slot, text)

    if not value:
        return False

    memory[slot] = value

    completed = memory.setdefault("completed_slots", [])

    if slot not in completed:
        completed.append(slot)

    memory["pending_slot"] = ""
    return True


def _mok_project_type_from_goal(text):
    words = _mok_conversation_tokens(text)

    travel_roots = {
        "travel", "tourist", "tourism", "destination", "visitor",
    }

    brand_roots = {
        "brand", "business", "company", "product", "service",
    }

    if _mok_count_concepts(words, travel_roots) >= 1:
        return "travel experience"

    if _mok_count_concepts(words, brand_roots) >= 1:
        return "brand experience"

    if any(word.startswith("film") or word == "movie" for word in words):
        return "cinematic film"

    if any(word.startswith("video") for word in words):
        return "cinematic video"

    return "creative experience"


def _mok_next_consultant_question(memory):
    sequence = [
        (
            "audience",
            "Who is this experience for?"
        ),
        (
            "desired_feeling",
            "What should the viewer feel, understand, or remember after experiencing it?"
        ),
        (
            "assets",
            "What material do you already have â€” photos, video clips, documents, scripts, logos, music, audio, narration, or nothing yet?"
        ),
        (
            "animation_preference",
            "How would you like the visuals to move? You can describe the result you imagine, or I can help you choose an animation approach."
        ),
    ]

    asked = memory.setdefault("asked_slots", [])

    for slot, question in sequence:

        if str(memory.get(slot) or "").strip():
            continue

        if slot not in asked:
            asked.append(slot)

        memory["pending_slot"] = slot
        return question

    memory["pending_slot"] = ""
    memory["ready_for_creation"] = True
    return None


def _mok_creation_ready_guidance(memory):
    project_type = str(
        memory.get("project_type")
        or "creative experience"
    )

    audience = str(
        memory.get("audience")
        or "your intended viewers"
    )

    return (
        "I have enough direction to move forward with the "
        + project_type
        + " for "
        + audience
        + ". Below this conversation, upload any photos, video clips, documents, scripts, logos, music, audio, or narration you want me to use, then click Create with MOK. "
        + "Review the result when it is ready. If you want different animation, movement, pacing, tone, or creative direction, tell me what you would like changed and I will guide the refinement with you."
    )


# ============================================================
# MOK_SR_1_4A_CONTINUOUS_LEARNING_AUTHORITY
# ============================================================

def _mok_learning_memory_path():
    import os

    override = str(
        os.environ.get("MOK_LEARNING_MEMORY_PATH") or ""
    ).strip()

    if override:
        return override

    return os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "_mok_continuous_learning.json",
    )


def _mok_new_learning_memory():
    return {
        "schema": "mok.learning.v1",
        "interaction_count": 0,
        "intent_phrasing": {},
        "preferences": {},
        "accepted_choices": {},
        "rejected_choices": {},
        "successful_paths": {},
        "feedback_history": [],
    }


def _mok_load_learning_memory():
    import json
    import os

    path = _mok_learning_memory_path()

    if not os.path.isfile(path):
        return _mok_new_learning_memory()

    try:
        with open(path, "r", encoding="utf-8") as handle:
            value = json.load(handle)

        if not isinstance(value, dict):
            return _mok_new_learning_memory()

        memory = _mok_new_learning_memory()
        memory.update(value)

        for key in [
            "intent_phrasing",
            "preferences",
            "accepted_choices",
            "rejected_choices",
            "successful_paths",
        ]:
            if not isinstance(memory.get(key), dict):
                memory[key] = {}

        if not isinstance(memory.get("feedback_history"), list):
            memory["feedback_history"] = []

        return memory

    except Exception:
        return _mok_new_learning_memory()


def _mok_save_learning_memory(memory):
    import json
    import os

    path = _mok_learning_memory_path()
    directory = os.path.dirname(path)

    if directory:
        os.makedirs(directory, exist_ok=True)

    temp_path = path + ".tmp"

    try:
        with open(temp_path, "w", encoding="utf-8") as handle:
            json.dump(
                memory,
                handle,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )

        os.replace(temp_path, path)
        return True

    except Exception as exc:
        print(
            "MOK_LEARNING_WRITE_SKIPPED " + repr(str(exc)),
            flush=True,
        )
        return False


def _mok_increment_counter(mapping, key):
    key = str(key or "").strip().lower()

    if not key:
        return

    mapping[key] = int(mapping.get(key) or 0) + 1


def _mok_extract_learning_signals(text, intent, conversation_memory):
    normalized = " ".join(_mok_conversation_tokens(text))
    words = set(normalized.split())

    signals = {
        "intent": str(intent or "").strip(),
        "phrase": normalized,
        "preferences": [],
        "accepted": [],
        "rejected": [],
    }

    preference_groups = {
        "animation": {
            "parallax", "zoom", "pan", "motion",
            "movement", "cinematic", "subtle",
            "dynamic", "smooth", "gentle", "energetic",
        },
        "tone": {
            "emotional", "premium", "warm", "dramatic",
            "inspiring", "inspired", "calm", "exciting",
            "professional", "elegant",
        },
        "pacing": {
            "fast", "slow", "gentle", "energetic",
            "smooth", "quick", "relaxed",
        },
    }

    for category, terms in preference_groups.items():
        found = sorted(words.intersection(terms))

        for value in found:
            signals["preferences"].append(
                category + ":" + value
            )

    positive_terms = {
        "like", "love", "great", "good", "perfect",
        "excellent", "yes", "keep", "works", "nice",
    }

    negative_terms = {
        "dislike", "hate", "wrong", "change", "different",
        "bad", "remove", "replace", "dont", "don't",
        "not",
    }

    if words.intersection(positive_terms):
        current_animation = str(
            conversation_memory.get("animation_preference") or ""
        ).strip()

        if current_animation:
            signals["accepted"].append(
                "animation:" + current_animation
            )

    if words.intersection(negative_terms):
        current_animation = str(
            conversation_memory.get("animation_preference") or ""
        ).strip()

        if current_animation:
            signals["rejected"].append(
                "animation:" + current_animation
            )

    return signals


def _mok_record_learning_signals(text, intent, conversation_memory):
    # MOK_SR_1_7B_1_DO_NOT_LEARN_UNCLEAR_MEANING
    if _mok_sr17_learning_blocked(text, conversation_memory):
        print(
            "MOK_LEARNING_SKIPPED_UNCLEAR_MEANING "
            + repr(str(text or "").strip()),
            flush=True,
        )
        return _mok_load_learning_memory()

    # MOK_SR_1_6_LEARN_ONLY_RESOLVED_TURNS
    sr16_turn = _mok_sr16_interpret_turn(text, conversation_memory)
    if not sr16_turn.get("intentional"):
        return _mok_load_learning_memory()
    if not sr16_turn.get("complete"):
        return _mok_load_learning_memory()

    # MOK_SR_1_4B6_DO_NOT_LEARN_UNRESOLVED_CORRECTION
    if _mok_b6_is_correction_or_refusal(text):
        print(
            "MOK_LEARNING_SKIPPED_CORRECTION "
            + repr(str(text or "").strip()),
            flush=True,
        )
        return _mok_load_learning_memory()

    # MOK_SR_1_4B5_LEARN_ONLY_RESOLVED_MEANING
    if not str(intent or "").strip():
        return _mok_load_learning_memory()

    if _mok_b5_is_incomplete(text):
        return _mok_load_learning_memory()

    from datetime import datetime, timezone

    learning = _mok_load_learning_memory()
    signals = _mok_extract_learning_signals(
        text,
        intent,
        conversation_memory,
    )

    learning["interaction_count"] = (
        int(learning.get("interaction_count") or 0) + 1
    )

    phrase = str(signals.get("phrase") or "").strip()
    intent_name = str(signals.get("intent") or "").strip()

    if phrase and intent_name:
        learned_phrasing = learning.setdefault(
            "intent_phrasing",
            {},
        )

        existing = learned_phrasing.get(phrase)

        if not isinstance(existing, dict):
            existing = {
                "intent": intent_name,
                "count": 0,
            }

        existing["intent"] = intent_name
        existing["count"] = int(existing.get("count") or 0) + 1
        learned_phrasing[phrase] = existing

    preferences = learning.setdefault("preferences", {})

    for preference in signals.get("preferences") or []:
        _mok_increment_counter(preferences, preference)

    accepted = learning.setdefault("accepted_choices", {})

    for choice in signals.get("accepted") or []:
        _mok_increment_counter(accepted, choice)

    rejected = learning.setdefault("rejected_choices", {})

    for choice in signals.get("rejected") or []:
        _mok_increment_counter(rejected, choice)

    feedback = learning.setdefault("feedback_history", [])

    feedback.append({
        "time": datetime.now(timezone.utc).isoformat(),
        "text": str(text or "").strip(),
        "intent": intent_name,
        "preferences": signals.get("preferences") or [],
        "accepted": signals.get("accepted") or [],
        "rejected": signals.get("rejected") or [],
    })

    learning["feedback_history"] = feedback[-250:]

    _mok_save_learning_memory(learning)

    print(
        "MOK_CONTINUOUS_LEARNING_UPDATED "
        + "intent=" + repr(intent_name)
        + " interactions="
        + str(learning["interaction_count"]),
        flush=True,
    )

    return learning


def _mok_preferred_values(category, limit=3):
    learning = _mok_load_learning_memory()
    preferences = learning.get("preferences") or {}

    prefix = str(category or "").strip().lower() + ":"

    matches = []

    for key, count in preferences.items():
        if str(key).startswith(prefix):
            matches.append((
                str(key).split(":", 1)[1],
                int(count or 0),
            ))

    matches.sort(key=lambda item: item[1], reverse=True)

    return [value for value, count in matches[:limit]]


def _mok_record_successful_conversation_path(conversation_memory):
    # MOK_SR_1_4B5_SUCCESS_PATH_ONCE
    if bool(conversation_memory.get("success_recorded")):
        return False

    if not bool(conversation_memory.get("ready_for_creation")):
        return False

    learning = _mok_load_learning_memory()
    paths = learning.setdefault("successful_paths", {})

    completed = conversation_memory.get("completed_slots") or []
    path = " -> ".join(str(item) for item in completed)

    if not path:
        return False

    _mok_increment_counter(paths, path)
    _mok_save_learning_memory(learning)

    print(
        "MOK_SUCCESSFUL_CONSULTATION_PATH_LEARNED "
        + repr(path),
        flush=True,
    )

    conversation_memory["success_recorded"] = True
    _mok_save_conversation_memory(conversation_memory)
    return True


def _mok_consultative_conversation(user_text, normalized):
    memory = _mok_load_conversation_memory()
    text = str(user_text or "").strip()

    if not text:
        return None

    intent, confidence = _mok_resolve_conversation_intent(
        text,
        memory,
    )

    # MOK_SR_1_4A_CONTINUOUS_LEARNING_BINDING
    _mok_record_learning_signals(
        text,
        intent,
        memory,
    )


    pending = str(memory.get("pending_slot") or "").strip()

    if intent != "creative_project" and not memory.get("active"):
        return None

    memory["active"] = True
    memory["turn_count"] = int(memory.get("turn_count") or 0) + 1
    memory["last_intent"] = str(intent or "")

    _mok_record_conversation_turn(
        memory,
        text,
        intent,
        confidence,
    )

    _mok_learn_conversation_intent(
        text,
        intent,
        confidence,
        memory,
    )

    if not str(memory.get("goal") or "").strip():
        if intent == "creative_project":
            memory["goal"] = text
            memory["project_type"] = _mok_project_type_from_goal(text)

    if pending == "audience" or intent == "audience":
        _mok_set_conversation_slot(memory, "audience", text)

    elif pending == "desired_feeling" or intent == "feeling":
        _mok_set_conversation_slot(memory, "desired_feeling", text)

    elif pending == "assets" or intent == "assets":
        _mok_set_conversation_slot(memory, "assets", text)

    elif pending == "animation_preference" or intent == "animation":
        _mok_set_conversation_slot(memory, "animation_preference", text)

    question = _mok_next_consultant_question(memory)

    _mok_save_conversation_memory(memory)

    if question:
        return question

    _mok_record_successful_conversation_path(memory)
    return _mok_creation_ready_guidance(memory)


# ============================================================
# MOK_SR_1_4B5_DIALOGUE_OWNERSHIP_AUTHORITY
# ============================================================

def _mok_b5_dialogue_text(text):
    return " ".join(_mok_conversation_tokens(text))


def _mok_b5_tokens(text):
    return list(_mok_conversation_tokens(text))


def _mok_b5_has_negative_preference(text):
    value = _mok_b5_dialogue_text(text)
    tokens = _mok_b5_tokens(text)

    direct = [
        "dont like",
        "do not like",
        "dont want",
        "do not want",
        "dislike",
    ]

    for phrase in direct:
        if phrase in value:
            return True

    # Tokenized apostrophe form:
    # don't -> don t
    for i in range(len(tokens) - 2):
        triplet = tokens[i:i + 3]

        if triplet == ["don", "t", "like"]:
            return True

        if triplet == ["don", "t", "want"]:
            return True

    for i in range(len(tokens) - 2):
        triplet = tokens[i:i + 3]

        if triplet == ["do", "not", "like"]:
            return True

        if triplet == ["do", "not", "want"]:
            return True

    return "dislike" in tokens


def _mok_b5_is_acknowledgement(text):
    value = _mok_b5_dialogue_text(text)

    if not value:
        return False

    phrases = [
        "ok i got you",
        "okay i got you",
        "ok i got it",
        "okay i got it",
        "got it",
        "i understand",
        "i understand now",
        "that makes sense",
        "sounds good",
        "thank you",
        "thanks",
        "okay thanks",
        "ok thanks",
        "perfect thanks",
        "alright thanks",
    ]

    return any(phrase in value for phrase in phrases)


def _mok_b5_is_incomplete(text):
    value = _mok_b5_dialogue_text(text)
    words = value.split()

    if not words:
        return True

    if value in {
        "mok", "so", "since", "because",
        "well", "and", "but", "then",
    }:
        return True

    endings = [
        "what im trying to say is",
        "what i m trying to say is",
        "what i am trying to say is",
        "what i mean is",
        "the reason is",
        "i want my family to feel like",
        "i want them to feel like",
    ]

    if any(value.endswith(ending) for ending in endings):
        return True

    if words[-1] in {
        "because", "since", "although", "while",
        "and", "but", "if", "when", "like",
    }:
        return True

    return False


def _mok_b5_reset_project(memory):
    learned_intents = memory.get("learned_intents") or {}

    memory["active"] = False
    memory["project_type"] = ""
    memory["goal"] = ""
    memory["audience"] = ""
    memory["desired_feeling"] = ""
    memory["assets"] = ""
    memory["animation_preference"] = ""
    memory["pending_slot"] = ""
    memory["asked_slots"] = []
    memory["completed_slots"] = []
    memory["last_intent"] = ""
    memory["turn_count"] = 0
    memory["ready_for_creation"] = False
    memory["success_recorded"] = False
    memory["clarification_pending"] = None
    memory["turns"] = []
    memory["learned_intents"] = learned_intents

    return memory


def _mok_b5_is_new_project(text, memory):
    if not bool(memory.get("ready_for_creation")):
        return False

    value = _mok_b5_dialogue_text(text)

    return any(marker in value for marker in [
        "i want to create",
        "i want to make",
        "i need to create",
        "help me create",
        "help me make",
        "i have a new idea",
        "another project",
        "new project",
        "different project",
    ])


def _mok_b5_closure(memory):
    if bool(memory.get("ready_for_creation")):
        return (
            "Absolutely. If anything else comes up, just reach out â€” "
            "I'm here to help and guide you through it. "
            "When you're ready, upload your photos, videos, documents, "
            "logos, music, audio, narration, or other inputs below, "
            "then click Create with MOK."
        )

    return (
        "Absolutely. If you need anything else, just ask. "
        "I'm here to help and guide you through it."
    )


def _mok_b5_post_ready_feedback(text, memory):
    value = _mok_b5_dialogue_text(text)
    tokens = set(_mok_b5_tokens(text))

    avoid = []
    prefer = []

    negative = _mok_b5_has_negative_preference(text)

    if negative and "zoom" in tokens:
        if "aggressive" in tokens:
            avoid.append("aggressive zoom effects")
        else:
            avoid.append("zoom effects")

    if "like a lot of animation" in value:
        prefer.append("more animation")

    if "like more animation" in value:
        prefer.append("more animation")

    if "subtle movement" in value:
        prefer.append("subtle movement")

    if "cinematic movement" in value:
        prefer.append("cinematic movement")

    if avoid or prefer:
        avoided = memory.setdefault("avoid_preferences", [])
        preferred = memory.setdefault("preferred_preferences", [])

        for item in avoid:
            if item not in avoided:
                avoided.append(item)

        for item in prefer:
            if item not in preferred:
                preferred.append(item)

        _mok_save_conversation_memory(memory)

        _mok_record_learning_signals(
            text,
            "preference_feedback",
            memory,
        )

        parts = []

        if avoid:
            parts.append("avoid " + ", ".join(avoid))

        if prefer:
            parts.append("favor " + ", ".join(prefer))

        return (
            "Understood. I'll "
            + " and ".join(parts)
            + ". I'll keep that in mind as we refine the project."
        )

    if "emotional" in tokens and "simple" in tokens:
        memory["desired_feeling"] = "emotional but simple"
        _mok_save_conversation_memory(memory)

        _mok_record_learning_signals(
            text,
            "feeling",
            memory,
        )

        return (
            "I understand. You want the experience to feel emotional "
            "but still simple. I'll keep that balance in the creative direction."
        )

    if "feel like they were actually there" in value:
        memory["desired_feeling"] = "feel like they were actually there"
        _mok_save_conversation_memory(memory)

        _mok_record_learning_signals(
            text,
            "feeling",
            memory,
        )

        return (
            "I understand. You want viewers to feel like they were actually there. "
            "I'll keep that objective in the project context."
        )

    return None


# MOK_SR_1_4B6_CORRECTION_PRIORITY

def _mok_b6_is_correction_or_refusal(text):
    value = _mok_b5_dialogue_text(text)
    tokens = set(_mok_b5_tokens(text))

    if not value:
        return False

    phrases = [
        "thats not quite what i want",
        "that s not quite what i want",
        "thats not what i want",
        "that s not what i want",
        "thats not quite what i meant",
        "that s not quite what i meant",
        "thats not what i meant",
        "that s not what i meant",
        "thats not right",
        "that s not right",
        "not quite",
        "not exactly",
        "you misunderstood me",
        "you misunderstood",
        "thats close but not quite",
        "that s close but not quite",
        "no thats not",
        "no that s not",
        "no i meant",
        "i meant something different",
    ]

    if any(phrase in value for phrase in phrases):
        return True

    if "no" in tokens and ("want" in tokens or "meant" in tokens):
        return True

    if "wrong" in tokens or "incorrect" in tokens:
        return True

    return False


def _mok_b6_correction_response(text, memory):
    value = _mok_b5_dialogue_text(text)

    memory["clarification_pending"] = {
        "kind": "correction",
        "original": str(text or "").strip(),
        "previous_pending_slot": str(memory.get("pending_slot") or "").strip(),
    }

    _mok_save_conversation_memory(memory)

    if "not quite" in value:
        return (
            "Understood â€” I may not have interpreted that correctly. "
            "What part should I change, or what did you mean instead?"
        )

    return (
        "Thanks for correcting me. "
        "Tell me what you meant instead, and I'll adjust my understanding."
    )


def _mok_b6_is_asr_tolerant_acknowledgement(text):
    value = _mok_b5_dialogue_text(text)

    if _mok_b5_is_acknowledgement(text):
        return True

    tolerated = [
        "ok i got your tanks",
        "okay i got your tanks",
        "ok i got you tanks",
        "okay i got you tanks",
        "i got your tanks",
        "got your tanks",
        "ok i got you tank",
    ]

    return any(phrase in value for phrase in tolerated)


# ============================================================
# MOK_SR_1_6_NATIVE_TURN_UNDERSTANDING
# MOK_SR_1_6_3_PREFERENCE_FEEDBACK_PRECEDENCE
# ============================================================

def _mok_sr16_text(text):
    return " ".join(_mok_conversation_tokens(text))


def _mok_sr16_tokens(text):
    return list(_mok_conversation_tokens(text))


def _mok_sr16_question(text):
    value = _mok_sr16_text(text)
    tokens = _mok_sr16_tokens(text)

    if not value:
        return False

    starters = {
        "what", "why", "how", "when", "where", "who",
        "which", "can", "could", "would", "will", "do",
        "does", "did", "is", "are", "am", "should",
        "may", "might",
    }

    return (
        "?" in str(text or "")
        or bool(tokens and tokens[0] in starters)
    )


def _mok_sr16_incomplete(text):
    value = _mok_sr16_text(text)
    tokens = _mok_sr16_tokens(text)

    if not value:
        return True

    if _mok_b5_is_incomplete(text):
        return True

    endings = [
        "can you",
        "could you",
        "would you",
        "will you",
        "what about",
        "how about",
        "i want to",
        "i need to",
        "so can you",
        "and can you",
    ]

    if any(value.endswith(item) for item in endings):
        return True

    if tokens and tokens[-1] in {
        "and", "but", "because", "or", "if",
        "so", "then", "to", "with",
    }:
        return True

    return False


def _mok_sr16_non_user_turn(text, memory=None):
    value = _mok_sr16_text(text)
    tokens = _mok_sr16_tokens(text)

    if memory is None:
        memory = _mok_load_conversation_memory()

    if not value:
        return True

    exact_echoes = {
        "mok",
        "mok autonomous ai studio",
        "autonomous ai studio",
        "ai studio",
        "listening",
        "waiting",
        "speak to mok",
    }

    if value in exact_echoes:
        return True

    pending = str(memory.get("pending_slot") or "").strip()

    if pending:
        return False

    if len(tokens) <= 2:
        if _mok_sr16_question(text):
            return False

        if _mok_b6_is_asr_tolerant_acknowledgement(text):
            return False

        if _mok_b6_is_correction_or_refusal(text):
            return False

        return True

    return False


def _mok_sr16_preference_feedback(text):
    value = _mok_sr16_text(text)
    tokens = set(_mok_sr16_tokens(text))

    negative_markers = [
        "i dont like",
        "i do not like",
        "i dont want",
        "i do not want",
        "i dislike",
        "avoid",
        "please avoid",
        "not too much",
        "less of",
        "no zoom",
    ]

    positive_markers = [
        "i like",
        "i prefer",
        "i want more",
        "i would like more",
        "i do like",
        "favor",
        "use more",
    ]

    preference_subjects = {
        "zoom", "zooms", "animation", "animations",
        "movement", "movements", "effect", "effects",
        "transition", "transitions", "pacing", "tone",
        "style", "styles",
    }

    has_subject = bool(tokens.intersection(preference_subjects))

    if not has_subject:
        return False

    if any(marker in value for marker in negative_markers):
        return True

    if any(marker in value for marker in positive_markers):
        return True

    return False


def _mok_sr16_options_request(text):
    value = _mok_sr16_text(text)
    tokens = set(_mok_sr16_tokens(text))

    # MOK_SR_1_6_3_OPTIONS_REQUIRE_REQUEST_INTENT
    # Preference feedback such as 'I like more animation'
    # must never become a request for a list of alternatives.
    if _mok_sr16_preference_feedback(text):
        return False

    option_words = {
        "more", "other", "another", "different",
        "option", "options", "alternative", "alternatives",
        "choice", "choices",
    }

    creative_words = {
        "animation", "animations", "movement", "movements",
        "effect", "effects", "style", "styles",
        "transition", "transitions",
    }

    request_phrases = [
        "can you give",
        "can you show",
        "can you suggest",
        "do you have",
        "are there",
        "what other",
        "what more",
        "give me more",
        "show me more",
        "list more",
        "apart from",
        "besides those",
        "any more",
        "other options",
        "more options",
    ]

    has_option_language = (
        bool(tokens.intersection(option_words))
        and bool(tokens.intersection(creative_words))
    )

    if not has_option_language:
        return False

    if _mok_sr16_question(text):
        return True

    if any(phrase in value for phrase in request_phrases):
        return True

    return False


def _mok_sr16_explanation_request(text):
    value = _mok_sr16_text(text)

    return (
        value.startswith("why ")
        or "why do you recommend" in value
        or "why would you recommend" in value
        or "why did you recommend" in value
        or "explain why" in value
        or "what is the reason" in value
    )


def _mok_sr16_recommendation_request(text):
    value = _mok_sr16_text(text)
    tokens = set(_mok_sr16_tokens(text))

    if _mok_sr16_explanation_request(text):
        return False

    if "what do you think would work best" in value:
        return True

    if "what would work best" in value:
        return True

    if "what do you recommend" in value:
        return True

    if "what would you recommend" in value:
        return True

    return (
        _mok_sr16_question(text)
        and bool(tokens.intersection({"recommend", "suggest", "best"}))
    )


def _mok_sr16_summary_request(text):
    value = _mok_sr16_text(text)

    return (
        "what have you understood" in value
        or "what do you understand about my project" in value
        or "summarize my project" in value
        or "project so far" in value
    )


def _mok_sr16_slot_mismatch(text, memory):
    slot = str(memory.get("pending_slot") or "").strip()
    tokens = set(_mok_sr16_tokens(text))

    if not slot:
        return None

    if _mok_sr16_question(text):
        return "question"

    if _mok_sr16_options_request(text):
        return "question"

    if slot == "audience":
        if tokens.intersection({
            "feel", "feeling", "emotional", "excited",
            "immersed", "alive", "happy", "sad",
        }):
            return "feeling"

    if slot == "desired_feeling":
        if tokens.intersection({
            "photo", "photos", "video", "videos",
            "music", "audio", "document", "documents",
            "logo", "logos", "script", "scripts",
        }):
            return "assets"

    if slot == "assets":
        if tokens.intersection({
            "zoom", "animation", "animations", "movement",
            "pan", "panning", "cinematic", "transition",
        }):
            return "animation"

    return None


def _mok_sr16_interpret_turn(text, memory=None):
    if memory is None:
        memory = _mok_load_conversation_memory()

    result = {
        "dialogue_act": "statement",
        "intentional": True,
        "complete": True,
        "confidence": 0.70,
        "slot_mismatch": None,
    }

    if _mok_sr16_non_user_turn(text, memory):
        result["dialogue_act"] = "ignore"
        result["intentional"] = False
        result["confidence"] = 0.99
        return result

    if _mok_sr16_incomplete(text):
        result["dialogue_act"] = "incomplete"
        result["complete"] = False
        result["confidence"] = 0.94
        return result

    if _mok_b6_is_correction_or_refusal(text):
        result["dialogue_act"] = "correction"
        result["confidence"] = 0.96
        return result

    if _mok_b6_is_asr_tolerant_acknowledgement(text):
        result["dialogue_act"] = "acknowledgement"
        result["confidence"] = 0.96
        return result

    # MOK_SR_1_6_3_PREFERENCE_BEFORE_ALTERNATIVES
    if _mok_sr16_preference_feedback(text):
        result["dialogue_act"] = "preference_feedback"
        result["confidence"] = 0.97
        return result

    if _mok_sr16_options_request(text):
        result["dialogue_act"] = "request_alternatives"
        result["confidence"] = 0.95
        return result

    if _mok_sr16_explanation_request(text):
        result["dialogue_act"] = "request_explanation"
        result["confidence"] = 0.97
        return result

    if _mok_sr16_recommendation_request(text):
        result["dialogue_act"] = "request_recommendation"
        result["confidence"] = 0.95
        return result

    if _mok_sr16_summary_request(text):
        result["dialogue_act"] = "request_context_summary"
        result["confidence"] = 0.95
        return result

    mismatch = _mok_sr16_slot_mismatch(text, memory)

    if mismatch:
        result["dialogue_act"] = "slot_mismatch"
        result["slot_mismatch"] = mismatch
        result["confidence"] = 0.91
        return result

    if _mok_sr16_question(text):
        result["dialogue_act"] = "question"
        result["confidence"] = 0.90
        return result

    if str(memory.get("pending_slot") or "").strip():
        result["dialogue_act"] = "consultant_answer"
        result["confidence"] = 0.92
        return result

    return result


def _mok_sr16_animation_options(memory):
    return [
        "gentle parallax depth",
        "horizontal cinematic pan",
        "vertical reveal",
        "layered foreground-background drift",
        "soft floating camera movement",
        "subtle handheld-style motion",
        "photo-to-photo match movement",
        "masked subject reveal",
        "depth-map orbit",
        "slow pull-back reveal",
        "multi-photo collage motion",
        "foreground wipe transition",
    ]


def _mok_sr16_project_summary(memory):
    facts = []

    goal = str(memory.get("goal") or memory.get("project_type") or "").strip()
    audience = str(memory.get("audience") or "").strip()
    feeling = str(memory.get("desired_feeling") or "").strip()
    assets = str(memory.get("assets") or "").strip()
    movement = str(memory.get("animation_preference") or "").strip()

    if goal:
        facts.append("your project is " + goal)
    if audience:
        facts.append("it is for " + audience)
    if feeling:
        facts.append("you want viewers to feel " + feeling)
    if assets:
        facts.append("you have " + assets)
    if movement:
        facts.append("your movement direction is " + movement)

    if not facts:
        return "I don't have enough resolved project information yet."

    return "So far, I understand that " + "; ".join(facts) + "."


def _mok_sr16_semantic_response(text, normalized=None):
    memory = _mok_load_conversation_memory()
    understanding = _mok_sr16_interpret_turn(text, memory)
    act = understanding.get("dialogue_act")

    print(
        "MOK_TURN_UNDERSTANDING "
        + "act=" + repr(act)
        + " confidence=" + str(understanding.get("confidence")),
        flush=True,
    )

    if act in {"ignore", "preference_feedback"}:
        return None

    if act == "incomplete":
        return (
            "I heard the beginning of your question, but it sounds like you weren't finished. "
            "Please continue — I'm listening."
        )

    if act == "request_alternatives":
        options = _mok_sr16_animation_options(memory)
        memory["last_recommendation"] = {"type": "animation_options", "options": options}
        _mok_save_conversation_memory(memory)
        return "Here are additional approaches: " + "; ".join(options)

    if act == "request_recommendation":
        response = (
            "I would start with gentle parallax depth, smooth pans, layered movement, "
            "and selective reveals. That gives the experience energy while keeping it natural."
        )
        memory["last_recommendation"] = {"type": "creative_recommendation", "text": response}
        _mok_save_conversation_memory(memory)
        return response

    if act == "request_explanation":
        last = memory.get("last_recommendation") or {}
        if last:
            return (
                "I recommend that because it fits what you've told me so far. "
                "It gives the experience visual energy while respecting the feeling and "
                "creative preferences you've already established."
            )
        return "Which recommendation would you like me to explain?"

    if act == "request_context_summary":
        return _mok_sr16_project_summary(memory)

    return None


# ============================================================
# MOK_SR_1_7B_1_PERSISTENT_CLARIFICATION_AUTHORITY
# ============================================================

def _mok_sr17_text(text):
    return " ".join(_mok_conversation_tokens(text))


def _mok_sr17_tokens(text):
    return list(_mok_conversation_tokens(text))


def _mok_sr17_missing_preference_object(text):
    value = _mok_sr17_text(text)

    broken_negative = [
        "i don t like but",
        "i dont like but",
        "i do not like but",
        "i don t want but",
        "i dont want but",
        "i do not want but",
    ]

    if any(marker in value for marker in broken_negative):
        return True

    broken_positive = [
        "but i like more",
        "but i want more",
        "and i like more",
        "and i want more",
    ]

    if any(value.endswith(marker) for marker in broken_positive):
        return True

    return False


def _mok_sr17_slot_evidence(text, memory):
    slot = str(memory.get("pending_slot") or "").strip()
    tokens = set(_mok_sr17_tokens(text))

    if not slot:
        return True

    evidence = {
        "audience": {
            "family", "friend", "friends", "people", "viewer",
            "viewers", "audience", "customer", "customers",
            "client", "clients", "team", "employees", "children",
            "kids", "daughter", "son", "wife", "husband",
            "partner", "parents", "everyone", "public",
        },
        "desired_feeling": {
            "feel", "feeling", "emotional", "emotion", "excited",
            "excitement", "happy", "joy", "warm", "nostalgic",
            "immersed", "connected", "alive", "inspired", "calm",
            "dramatic", "fun", "moving", "simple",
        },
        "assets": {
            "photo", "photos", "picture", "pictures", "video",
            "videos", "clip", "clips", "music", "audio",
            "narration", "voice", "document", "documents",
            "script", "scripts", "note", "notes", "logo",
            "logos", "image", "images", "file", "files",
        },
        "animation_preference": {
            "animation", "animations", "movement", "movements",
            "zoom", "pan", "panning", "parallax", "cinematic",
            "motion", "transition", "transitions", "subtle",
            "slow", "fast", "smooth", "dynamic", "minimal",
            "gentle",
        },
    }

    expected = evidence.get(slot)

    if expected is None:
        return True

    return bool(tokens.intersection(expected))


def _mok_sr17_assess_meaning(text, memory=None):
    if memory is None:
        memory = _mok_load_conversation_memory()

    result = {
        "needs_clarification": False,
        "reason": "",
        "prompt": "",
        "confidence": 1.0,
    }

    turn = _mok_sr16_interpret_turn(text, memory)

    if not turn.get("intentional"):
        return result

    if not turn.get("complete"):
        result["needs_clarification"] = True
        result["reason"] = "incomplete_turn"
        result["confidence"] = 0.20
        result["prompt"] = (
            "I heard the beginning of what you were saying, but it sounds unfinished. "
            "Please finish your thought. I'm listening."
        )
        return result

    if _mok_sr17_missing_preference_object(text):
        result["needs_clarification"] = True
        result["reason"] = "missing_preference_object"
        result["confidence"] = 0.25
        result["prompt"] = (
            "I caught part of your preference, but an important part was missing. "
            "Please repeat the full preference so I don't guess."
        )
        return result

    act = str(turn.get("dialogue_act") or "")

    resolved_acts = {
        "question",
        "request_alternatives",
        "request_recommendation",
        "request_explanation",
        "request_context_summary",
        "correction",
        "acknowledgement",
        "preference_feedback",
    }

    if act in resolved_acts:
        return result

    if act == "consultant_answer":
        if not _mok_sr17_slot_evidence(text, memory):
            pending = str(memory.get("pending_slot") or "").strip()

            prompts = {
                "audience": (
                    "I may not have understood who you mean. "
                    "Who exactly is this experience for?"
                ),
                "desired_feeling": (
                    "I may have misheard the feeling you want. "
                    "How should people feel when they experience it?"
                ),
                "assets": (
                    "I may not have understood what material you have. "
                    "Do you have photos, videos, audio, documents, or something else?"
                ),
                "animation_preference": (
                    "I may have misheard the movement style. "
                    "Could you describe how you want the visuals to move?"
                ),
            }

            result["needs_clarification"] = True
            result["reason"] = "weak_pending_slot_fit"
            result["confidence"] = 0.40
            result["prompt"] = prompts.get(
                pending,
                "I want to make sure I understood correctly. Could you say that another way?"
            )
            return result

    return result


def _mok_sr17_set_pending(memory, text, assessment):
    old = memory.get("clarification_pending") or {}
    attempts = int(old.get("attempts") or 0) + 1

    memory["clarification_pending"] = {
        "original": str(text or "").strip(),
        "reason": str(assessment.get("reason") or "").strip(),
        "attempts": attempts,
        "pending_slot": str(memory.get("pending_slot") or "").strip(),
    }

    _mok_save_conversation_memory(memory)
    return attempts


def _mok_sr17_clear_pending(memory):
    if memory.get("clarification_pending"):
        memory.pop("clarification_pending", None)
        _mok_save_conversation_memory(memory)


def _mok_sr17_dialogue_gate(text):
    memory = _mok_load_conversation_memory()
    previous = memory.get("clarification_pending") or {}
    assessment = _mok_sr17_assess_meaning(text, memory)

    if assessment.get("needs_clarification"):
        attempts = _mok_sr17_set_pending(
            memory,
            text,
            assessment,
        )

        print(
            "MOK_CLARIFICATION_REQUIRED "
            + "reason=" + repr(assessment.get("reason"))
            + " attempts=" + str(attempts)
            + " transcript=" + repr(str(text or "").strip()),
            flush=True,
        )

        prompt = str(assessment.get("prompt") or "").strip()

        if attempts >= 2:
            return (
                prompt
                + " I still don't want to guess. "
                + "Please say it again in your own words."
            )

        return prompt

    if previous:
        print(
            "MOK_CLARIFICATION_RESOLVED "
            + repr(str(text or "").strip()),
            flush=True,
        )
        _mok_sr17_clear_pending(memory)

    return None


def _mok_sr17_learning_blocked(text, conversation_memory):
    assessment = _mok_sr17_assess_meaning(
        text,
        conversation_memory,
    )
    return bool(assessment.get("needs_clarification"))


def _mok_sr17_safe_synthesize(response):
    try:
        return synthesize_mok_voice(response)
    except Exception as exc:
        print(
            "MOK_TTS_DEGRADED "
            + type(exc).__name__
            + ": "
            + str(exc),
            flush=True,
        )
        print("MOK_TEXT_RESPONSE_PRESERVED", flush=True)
        return None


def _mok_b5_dialogue_response(text, normalized=None):
    # MOK_SR_1_7B_1_CLARIFICATION_GATE_BINDING
    sr17_clarification = _mok_sr17_dialogue_gate(text)

    if sr17_clarification:
        return sr17_clarification

    # MOK_SR_1_6_SEMANTIC_GATE_BINDING
    sr16_understanding = _mok_sr16_interpret_turn(
        text,
        _mok_load_conversation_memory(),
    )

    sr16_response = _mok_sr16_semantic_response(text, normalized)

    if sr16_response:
        return sr16_response

    if sr16_understanding.get("dialogue_act") in {
        "question",
        "request_alternatives",
        "request_recommendation",
        "request_explanation",
        "request_context_summary",
    }:
        return None

    memory = _mok_load_conversation_memory()
    value = _mok_b5_dialogue_text(text)

    if not value:
        return "I didn't catch that clearly. Could you say it again?"

    if _mok_b5_is_incomplete(text):
        return (
            "I may have caught you before you finished. "
            "Please continue or repeat the complete thought â€” I'm listening."
        )

    # MOK_SR_1_4B6_CORRECTION_PRIORITY_BINDING
    if _mok_b6_is_correction_or_refusal(text):
        return _mok_b6_correction_response(text, memory)

    if _mok_b6_is_asr_tolerant_acknowledgement(text):
        return _mok_b5_closure(memory)

    if _mok_b5_is_new_project(text, memory):
        _mok_b5_reset_project(memory)
        _mok_save_conversation_memory(memory)

        print(
            "MOK_NEW_PROJECT_CONTEXT_STARTED",
            flush=True,
        )

        return None

    # Consultant owns explicit pending-slot answers.
    pending_slot = str(memory.get("pending_slot") or "").strip()

    if (
        pending_slot in {
            "audience",
            "desired_feeling",
            "assets",
            "animation_preference",
        }
        and not bool(memory.get("ready_for_creation"))
    ):
        return None

    if bool(memory.get("ready_for_creation")):
        feedback = _mok_b5_post_ready_feedback(text, memory)

        if feedback:
            return feedback

        if _mok_b5_has_negative_preference(text):
            return (
                "I understand that you want something changed, "
                "but I want to make sure I understand exactly what. "
                "Which part would you like me to avoid or change?"
            )

    return None


def ask_mok(question):
    import re

    # MOK_H10_8C_H_H_B_R4_TRANSCRIPT_CORRECTNESS
    text = str(question or "").strip()
    normalized = text.lower()
    normalized = re.sub(r"[^a-z0-9\s]", " ", normalized)
    normalized = " ".join(normalized.split())

    if not normalized:
        return "Hello! How can I help you?"

    # Whisper may render the spoken name MOK phonetically.
    mok_aliases = {
        "mok",
        "moke",
        "mock",
        "mooc",
        "moc",
        "monk",
        "mark",
        "mook",
    }

    words = normalized.split()

    canonical_words = [
        "mok" if word in mok_aliases else word
        for word in words
    ]

    normalized = " ".join(canonical_words)
    words = normalized.split()

    greeting_words = {
        "hi",
        "hello",
        "hey",
    }

    is_simple_greeting = (
        len(words) <= 3
        and any(word in greeting_words for word in words)
        and ("mok" in words or len(words) == 1)
    )

    if is_simple_greeting:
        return "Hello! How can I help you?"

    # --------------------------------------------------------
    # CREATOR INTENT
    # Tolerant of normal ASR tense/word variations.
    # --------------------------------------------------------

    creator_verbs = {
        "build",
        "built",
        "builds",
        "create",
        "created",
        "creates",
        "make",
        "made",
        "makes",
        "develop",
        "developed",
        "design",
        "designed",
        "architect",
        "architected",
    }

    creator_intent = (
        "who" in words
        and any(word in creator_verbs for word in words)
        and ("you" in words or "mok" in words)
    )

    if creator_intent:
        return (
            "MOK Autonomous AI Studio was created and architected "
            "by Andreas Mokam and built from scratch."
        )

    # MOK_SR_1_3W_SEMANTIC_IDENTITY_INTENT
    name_identity_intent, name_identity_confidence = _mok_resolve_identity_intent(normalized)

    if name_identity_intent == "name_origin":
        _mok_learn_identity_alias(
            normalized,
            name_identity_intent,
            name_identity_confidence,
        )
        return (
            "The name MOK comes from Mokam â€” Andreas Mokam, "
            "the person who created, architected, and built this application from scratch."
        )


    if any(value in normalized for value in [
        "who are you",
        "what are you",
        "what is mok",
        "tell me about yourself",
    ]):
        return (
            "I am MOK Autonomous AI Studio. "
            "I help turn your ideas and creative materials into finished experiences."
        )

    # --------------------------------------------------------
    # CAPABILITY / HELP INTENT
    # --------------------------------------------------------

    if any(value in normalized for value in [
        "what can you do",
        "what can mok do",
        "what can you create",
        "what are your capabilities",
        "how can you help me",
        "how can mok help me",
        "how can you help",
        "what can you do for me",
    ]):
        return (
            "I can help you turn your idea into a finished creative experience. "
            "You can give me photos, videos, logos, documents, scripts, notes, music, or narration. "
            "Tell me what you want to achieve and I will guide you."
        )

    if any(value in normalized for value in [
        "what kind of videos",
        "what kinds of videos",
        "what videos can you create",
        "types of videos",
    ]):
        return (
            "I can help create cinematic stories, brand videos, photo animations, "
            "logo presentations, promotional pieces, visual narratives, and other creative video experiences. "
            "You can also show me a reference style and describe the movement or presentation you want."
        )

    if any(value in normalized for value in [
        "what should i upload",
        "what can i upload",
        "what should i give you",
    ]):
        return (
            "Upload whatever helps explain your idea: photos, videos, logos, scripts, notes, "
            "documents, music, audio, or narration. You can also start with only an idea."
        )

    if any(value in normalized for value in [
        "how do i use",
        "how to use",
        "guide me",
        "how do i start",
        "how do i get started",
    ]):
        return (
            "Tell me what you want to create, add any material you want me to use, "
            "then describe the experience you want. I will guide you from there."
        )

    # MOK_H10_8C_H_H_B_R6_R3_R1_SCOPE_GUARD
    out_of_scope_patterns = [
        r"\bwhat is the temperature\b",
        r"\bwhat s the temperature\b",
        r"\btemperature (today|outside|right now|now)\b",
        r"\bhow hot is it (today|outside|right now|now)\b",
        r"\bhow cold is it (today|outside|right now|now)\b",
        r"\bwhat is the weather\b",
        r"\bwhat s the weather\b",
        r"\bweather (today|outside|right now|tomorrow)\b",
        r"\bweather forecast\b",
        r"\bforecast (today|tomorrow)\b",
        r"\bwill it rain\b",
        r"\bis it raining\b",
        r"\bwill it snow\b",
        r"\bis it snowing\b",
        r"\bwhat is the score\b",
        r"\bwhat s the score\b",
        r"\bsports score\b",
        r"\bgame score\b",
        r"\bwho won the game\b",
        r"\bwhat is the stock price\b",
        r"\bwhat s the stock price\b",
        r"\bshare price\b",
        r"\bbitcoin price\b",
        r"\bcrypto price\b",
        r"\bexchange rate\b",
        r"\bcurrent president\b",
        r"\bcurrent prime minister\b",
        r"\belection results?\b",
        r"\blatest news\b",
        r"\bbreaking news\b",
        r"\btraffic right now\b",
        r"\blottery results?\b",
        r"\blottery numbers?\b",
        r"\bwhat time is it\b",
        r"\bwhat is the time\b",
        r"\bwhat date is it\b",
        r"\bwhat day is it\b",
    ]

    if any(
        re.search(pattern, normalized)
        for pattern in out_of_scope_patterns
    ):
        return (
            "I cannot provide an answer for that because it is out of my scope."
        )

    # MOK_R7_R1_USER_STOP_AUTHORITY
    stop_phrases = {
        "stop",
        "stop mok",
        "mok stop",
        "please stop",
        "stop now",
        "stop searching",
        "stop the search",
        "stop web search",
        "stop web",
        "stop providing web content",
        "that is enough",
        "enough",
    }

    if normalized in stop_phrases:
        return "Okay. I have stopped."

    # MOK_SR_1_3X_CONVERSATIONAL_BINDING
    # MOK_SR_1_4B5_DIALOGUE_OWNERSHIP_BINDING
    dialogue_response = _mok_b5_dialogue_response(
        text,
        normalized,
    )

    if dialogue_response:
        return dialogue_response

    consultative_response = _mok_consultative_conversation(
        text,
        normalized,
    )

    if consultative_response:
        return consultative_response


    # MOK_H10_8C_H_H_B_R7_WEB_BINDING
    web_supplement = _MOK_NATIVE_WEB_KNOWLEDGE.supplement(text)

    if web_supplement:
        return web_supplement

    return (
        "Tell me what you would like to create or what you are trying to achieve. "
        "If you need help, I can guide you step by step."
    )

_MOK_VOICE_MODEL = None
_MOK_STOP_VOICE_MODEL = None




# MOK_H10_8C_H_H_B_R4_R4B_LATE_VOICE_RUNTIME
def _ensure_mok_voice_runtime_path():
    import sys
    from pathlib import Path

    voice_runtime = (
        Path(__file__).resolve().parent
        / ".mok_voice_runtime"
    )

    voice_runtime_text = str(voice_runtime)

    if (
        voice_runtime.is_dir()
        and voice_runtime_text not in sys.path
    ):
        sys.path.append(voice_runtime_text)

    return voice_runtime_text


def _get_mok_voice_model():
    global _MOK_VOICE_MODEL

    if _MOK_VOICE_MODEL is None:
        _ensure_mok_voice_runtime_path()
        from faster_whisper import WhisperModel

        _MOK_VOICE_MODEL = WhisperModel(
            "base.en",
            device="cpu",
            compute_type="int8",
            cpu_threads=8,
            num_workers=1,
        )

    return _MOK_VOICE_MODEL



# MOK_H10_8C_H_H_B_R1_LATENCY_OPTIMIZATION
def _mok_prewarm_voice_runtime():
    started = time.perf_counter()

    try:
        _get_mok_voice_model()
        _ensure_mok_voice_runtime_path()
        import edge_tts

        elapsed_ms = (time.perf_counter() - started) * 1000.0

        print(
            "MOK_VOICE_PREWARM_READY ms={:.1f}".format(elapsed_ms),
            flush=True,
        )
    except Exception as exc:
        print(
            "MOK_VOICE_PREWARM_DEFERRED",
            type(exc).__name__,
            str(exc),
            flush=True,
        )


def _start_mok_voice_prewarm():
    worker = threading.Thread(
        target=_mok_prewarm_voice_runtime,
        name="mok-voice-prewarm",
        daemon=True,
    )

    worker.start()


_mok_prewarm_voice_runtime()
# MOK_SR_1_3O_FAST_STOP_MODEL
def _get_mok_stop_voice_model():
    global _MOK_STOP_VOICE_MODEL

    if _MOK_STOP_VOICE_MODEL is None:
        _ensure_mok_voice_runtime_path()
        from faster_whisper import WhisperModel

        _MOK_STOP_VOICE_MODEL = WhisperModel(
            "tiny.en",
            device="cpu",
            compute_type="int8",
            cpu_threads=8,
            num_workers=1,
        )

    return _MOK_STOP_VOICE_MODEL


def transcribe_mok_stop(audio_path):
    model = _get_mok_stop_voice_model()

    segments, _ = model.transcribe(
        audio_path,
        language="en",
        beam_size=1,
        best_of=1,
        temperature=0.0,
        condition_on_previous_text=False,
        initial_prompt="Stop. MOK stop. Stop MOK. Please stop. Stop now.",
    )

    text = ' '.join(
        str(segment.text or '').strip()
        for segment in segments
        if str(segment.text or '').strip()
    )

    return text.strip()



def transcribe_mok_voice(audio_path):
    # MOK_H10_8C_H_H_B_R4_R1_ASR_CONTEXT
    audio_path = str(audio_path or "").strip()

    if not audio_path:
        return ""

    model = _get_mok_voice_model()

    mok_initial_prompt = (
        "MOK Autonomous AI Studio. Natural spoken creative conversation."
    )

    mok_hotwords = (
        "MOK Moke Mock Mooc Mook Mark "
        "who built you who created you who made you "
        "how can you help me "
        "what can you do "
        "what kind of videos can you create"
    )

    segments, info = model.transcribe(
        audio_path,
        language="en",
        task="transcribe",
        beam_size=1,
        best_of=1,
        without_timestamps=True,
        word_timestamps=False,
        temperature=0.0,
        condition_on_previous_text=False,
        initial_prompt=mok_initial_prompt,
        vad_filter=False,
        max_new_tokens=64,
    )

    transcript = " ".join(
        segment.text.strip()
        for segment in segments
        if segment.text and segment.text.strip()
    ).strip()

    print(
        "MOK_ASR_AUDIO duration_s={:.2f} voiced_s={:.2f}".format(
            float(info.duration),
            float(info.duration_after_vad),
        ),
        flush=True,
    )

    return transcript


def synthesize_mok_voice(response_text):
    # MOK_H10_8C_H_H_B_R5E_AUDIO_BYTES
    import os
    import tempfile
    import edge_tts

    response_text = str(response_text or "").strip()

    if not response_text:
        return None

    handle = tempfile.NamedTemporaryFile(
        suffix=".mp3",
        delete=False,
    )

    output_path = handle.name
    handle.close()

    try:
        communicator = edge_tts.Communicate(
            response_text,
            voice="en-US-JennyNeural",
            rate="+0%",
            volume="+0%",
            pitch="+0Hz",
        )

        communicator.save_sync(output_path)

        with open(output_path, "rb") as audio_file:
            audio_bytes = audio_file.read()

        if len(audio_bytes) <= 1000:
            raise RuntimeError("Generated MOK speech audio is unexpectedly small.")

        return audio_bytes
    finally:
        try:
            os.remove(output_path)
        except OSError:
            pass



def ask_mok_voice(audio_path):
    transcript = transcribe_mok_voice(audio_path)

    if not transcript:
        response = "I could not clearly hear that. Please try again."
        return "", synthesize_mok_voice(response)

    response = ask_mok(transcript)
    response_audio = synthesize_mok_voice(response)

    return transcript, response_audio



# MOK_H10_8C_H_H_A_R3_CONVERSATION_STATE
def _mok_session_history(value):
    if not isinstance(value, list):
        return []

    result = []

    for item in value:
        if isinstance(item, dict):
            result.append(dict(item))

    return result


def _mok_store_turn(history, viewer_text, mok_text, channel):
    updated = _mok_session_history(history)

    updated.append({
        "role": "viewer",
        "content": str(viewer_text or "").strip(),
        "channel": str(channel),
    })

    updated.append({
        "role": "mok",
        "content": str(mok_text or "").strip(),
        "channel": str(channel),
    })

    return updated



# MOK_R9_1A_HUMAN_CONVERSATION_LAYER
def _mok_human_conversation_response(text, conversation_history):
    # MOK_R23_HUMAN_CREATIVE_CONSULTANT
    import re

    raw = str(text or '').strip()
    normalized = raw.lower()
    normalized = re.sub(r'[^a-z0-9\s]', ' ', normalized)
    normalized = ' '.join(normalized.split())
    history = _mok_session_history(conversation_history)

    def turn_value(turn, *keys):
        if not isinstance(turn, dict):
            return ''
        for key in keys:
            value = turn.get(key)
            if value:
                return str(value)
        return ''

    recent_turns = history[-6:] if history else []
    recent_viewer = ' '.join(
        turn_value(turn, 'viewer_text', 'viewer', 'user_text', 'user')
        for turn in recent_turns
    ).lower()

    last_mok = ''
    if history:
        last_mok = turn_value(
            history[-1],
            'mok_text',
            'mok',
            'assistant_text',
            'assistant',
        ).lower()

    if not normalized:
        return (
            'I am here. Tell me what you are thinking about creating, even if the idea is still rough. '
            'I can help you shape it step by step.'
        )

    greetings = {
        'hi', 'hello', 'hey', 'hey mok', 'hello mok', 'hi mok',
        'good morning', 'good afternoon', 'good evening'
    }

    if normalized in greetings:
        return (
            'Hi! I am glad you are here. What would you like to create today? '
            'It could be a cinematic video, short film, travel experience, brand or product advertisement, '
            'social-media content, a wedding video, or something completely different.'
        )

    if normalized in {
        'how are you', 'how are you doing', 'how is it going',
        'mok how are you', 'hello mok how are you', 'hi mok how are you'
    }:
        return (
            'I am doing well, thank you. I am ready to work with you. '
            'What are you hoping to create or accomplish today?'
        )

    if normalized in {'i am good', 'im good', 'i am fine', 'im fine', 'doing well', 'doing good'}:
        return (
            'Good to hear. Tell me what you have in mind. It does not need to be perfectly explained; '
            'I will ask questions to help turn the idea into a clear creative direction.'
        )

    if any(phrase in normalized for phrase in [
        'what can you create',
        'what can you make',
        'what should i create',
        'help me create',
        'guide me',
        'where do i start',
    ]):
        return (
            'We can start with your goal rather than the technology. I can help shape a cinematic video, '
            'short film, wedding or event video, travel experience, brand or product advertisement, '
            'social-media content, documentary-style story, or another creative format. '
            'What do you want the viewer to see, feel, remember, or do after watching it?'
        )

    # Contextual yes/no answers make the conversation continue naturally.
    if normalized in {'yes', 'yes i do', 'yeah', 'yep', 'sure', 'i do'} and last_mok:
        if 'photo' in last_mok or 'video' in last_mok or 'upload' in last_mok:
            return (
                'Great. Upload the photos and videos you want me to work with, plus any logo, invitation, '
                'notes, music, narration, or other material that matters to you. '
                'Next, what feeling should the finished piece have: romantic, joyful, elegant, cinematic, energetic, or something else?'
            )
        if 'animation' in last_mok or 'movement' in last_mok:
            return (
                'Great. We can use a combination rather than forcing one movement throughout. '
                'Would you like the motion to feel elegant and gentle, energetic and playful, dramatic and cinematic, or mixed according to each moment?'
            )

    if normalized in {'no', 'not yet', 'i do not', 'i dont'} and last_mok:
        if 'photo' in last_mok or 'video' in last_mok or 'upload' in last_mok:
            return (
                'That is fine. We can begin from the idea and build a production plan first. '
                'Tell me the occasion, the people or subject involved, and the feeling you want the finished video to create.'
            )

    wedding_context = (
        'wedding' in normalized
        or (len(normalized.split()) <= 8 and 'wedding' in recent_viewer)
    )

    if wedding_context:
        if 'animation' in normalized or 'movement' in normalized:
            return (
                'For a wedding video, I can help you plan movements such as slow zooms, gentle pans, '
                'horizontal or vertical scrolling, diagonal movement, circular motion, photo collages, '
                'star or shape-based reveals, and combinations that change with the moment. '
                'Do you prefer elegant and subtle motion, something lively, or a mixture? '
                'If you have a reference video, you can upload it too.'
            )

        if any(word in normalized for word in ['picture', 'photo', 'video', 'upload', 'logo', 'gift', 'invitation']):
            return (
                'Yes. Those materials can help me make the wedding story more personal. Upload the photos and videos, '
                'and you can also include invitations, a wedding logo or monogram, gift images, written notes, music, '
                'voice narration, or anything meaningful. What part of the wedding should receive the strongest emphasis?'
            )

        if 'wedding' in normalized:
            return (
                'Absolutely. I can help you create a wedding video. Do you already have photos and video clips from the wedding? '
                'You can upload them together with invitations, a logo or monogram, music, notes, gift images, or other meaningful material. '
                'After that, I will help you choose the story, mood, pacing, transitions, and animation style.'
            )

    if any(word in normalized for word in ['animation', 'animate', 'zoom', 'scroll', 'circular', 'diagonal']):
        return (
            'We can design the movement around the emotion of the piece. Options include zooming in or out, '
            'slow pans, horizontal or vertical scrolling, diagonal movement, circular motion, layered collages, '
            'shape-based reveals, or a combination. If you are unsure, tell me the mood you want and I can recommend a mix. '
            'You can also give me a reference video or ask me to help compare reference animation styles.'
        )

    if any(phrase in normalized for phrase in [
        'sample video', 'reference video', 'imitate this', 'like this video',
        'show me samples', 'show animation samples'
    ]):
        if 'upload' in normalized or 'reference video' in normalized or 'sample video' in normalized:
            return (
                'Yes. Upload the reference video and tell me what you like about it: the pacing, camera feel, '
                'transitions, typography, music, color, animation, or overall mood. I can use those qualities as creative guidance '
                'without requiring you to describe every technical detail.'
            )

        reference_answer = str(ask_mok(raw) or '').strip()
        if reference_answer:
            return reference_answer + ' Tell me which style feels closest to what you want, and I will help narrow it down.'

    project_types = [
        ('travel', 'travel experience'),
        ('advertisement', 'brand or product advertisement'),
        ('advert', 'brand or product advertisement'),
        ('brand', 'brand story or advertisement'),
        ('product', 'product story or advertisement'),
        ('social media', 'social-media content'),
        ('short film', 'short film'),
        ('cinematic video', 'cinematic video'),
    ]

    for keyword, project_name in project_types:
        if keyword in normalized:
            return (
                'Yes, I can help you shape a ' + project_name + '. '
                'Let us make the creative goal clear first: who is it for, what should the viewer feel or understand, '
                'and what photos, video, audio, documents, logos, or reference material do you already have?'
            )

    if any(phrase in normalized for phrase in [
        'what should i upload', 'what can i upload', 'what should i give you'
    ]):
        return (
            'Upload whatever helps me understand the project: photos, video clips, logos, scripts, notes, documents, '
            'music, narration, invitations, reference videos, or other meaningful material. '
            'You can also begin with only an idea and I will help determine what else would be useful.'
        )

    # Preserve MOK's broad authoritative question-answering path.
    answer = str(ask_mok(raw) or '').strip()

    if answer:
        return answer

    return (
        'Tell me a little more about what you are trying to achieve. '
        'I can ask questions and help turn an incomplete idea into a practical creative plan.'
    )


def ask_mok_session_text(question, conversation_history):
    text = str(question or "").strip()
    history = _mok_session_history(conversation_history)

    if not text:
        return "", "", history

    response_started = time.perf_counter()
    response = _mok_human_conversation_response(text, history)
    response_ms = (time.perf_counter() - response_started) * 1000.0
    print(
        "MOK_TEXT_RESPONSE input={!r} response={!r} latency_ms={:.1f}".format(
            text,
            response,
            response_ms,
        ),
        flush=True,
    )

    history = _mok_store_turn(
        history,
        text,
        response,
        "text",
    )

    # Clear the existing question box for the next turn.
    return "", response, history


# MOK_H10_8C_H_H_B_R4_R3_STABLE_REUSABLE_MICROPHONE
def ask_mok_session_voice(audio_path, conversation_history):
    history = _mok_session_history(conversation_history)
    turn_started = time.perf_counter()

    if not audio_path:
        return "", None, history

    transcription_started = time.perf_counter()
    transcript = transcribe_mok_voice(audio_path)
    transcript = str(transcript or "").strip()
    print(
        "MOK_VOICE_TRANSCRIPT:",
        repr(transcript),
        flush=True,
    )
    transcription_ms = (time.perf_counter() - transcription_started) * 1000.0

    if not transcript:
        response = "I could not clearly hear that. Please try again."
        response_audio = synthesize_mok_voice(response)

        return "", response_audio, history

    response_started = time.perf_counter()
    response = _mok_human_conversation_response(transcript, history)
    response_ms = (time.perf_counter() - response_started) * 1000.0
    synthesis_started = time.perf_counter()
    response_audio = synthesize_mok_voice(response)
    synthesis_ms = (time.perf_counter() - synthesis_started) * 1000.0
    total_ms = (time.perf_counter() - turn_started) * 1000.0

    print(
        "MOK_VOICE_LATENCY transcription_ms={:.1f} mok_ms={:.1f} tts_ms={:.1f} total_ms={:.1f}".format(
            transcription_ms,
            response_ms,
            synthesis_ms,
            total_ms,
        ),
        flush=True,
    )

    history = _mok_store_turn(
        history,
        transcript,
        response,
        "voice",
    )

    # Return None to the microphone component so it resets
    # and is ready for the viewer's next spoken turn.
    return "", response_audio, history


# MOK_H10_8C_H_H_B_R6_CONTINUOUS_CONVERSATION
# MOK_SR_1_4B2_END_OF_QUESTION_THRESHOLD
_MOK_END_OF_QUESTION_SILENCE_SECONDS = 1.15
_MOK_MINIMUM_SPEECH_SECONDS = 0.30
_MOK_STREAM_PREROLL_CHUNKS = 4


def _mok_voice_stream_state(value):
    if not isinstance(value, dict):
        value = {}

    state = dict(value)

    if not isinstance(state.get("chunks"), list):
        state["chunks"] = []

    state.setdefault("sample_rate", 0)
    state.setdefault("speech_started", False)
    state.setdefault("speech_seconds", 0.0)
    state.setdefault("silence_seconds", 0.0)
    state.setdefault("noise_rms", 0.003)
    state.setdefault("mute_until", 0.0)
    state.setdefault("turn_number", 0)
    state.setdefault("stop_chunks", [])
    state.setdefault("stop_speech_seconds", 0.0)
    state.setdefault("stop_silence_seconds", 0.0)

    return state


def _mok_reset_stream_turn(state):
    state["chunks"] = []
    state["sample_rate"] = 0
    state["speech_started"] = False
    state["speech_seconds"] = 0.0
    state["silence_seconds"] = 0.0
    state["stop_chunks"] = []
    state["stop_speech_seconds"] = 0.0
    state["stop_silence_seconds"] = 0.0
    return state


def _mok_stream_chunk(audio_chunk):
    import numpy as np

    if not isinstance(audio_chunk, tuple) or len(audio_chunk) != 2:
        return None, None

    sample_rate, samples = audio_chunk

    try:
        sample_rate = int(sample_rate)
    except Exception:
        return None, None

    data = np.asarray(samples)

    if sample_rate <= 0 or data.size == 0:
        return None, None

    if data.ndim > 1:
        data = data.astype(np.float32).mean(axis=1)
    else:
        data = data.astype(np.float32)

    peak = float(np.max(np.abs(data))) if data.size else 0.0

    if peak > 1.5:
        data = data / 32768.0

    data = np.clip(data, -1.0, 1.0).astype(np.float32)

    return sample_rate, data


def _mok_stream_rms(samples):
    import numpy as np

    if samples is None or samples.size == 0:
        return 0.0

    return float(np.sqrt(np.mean(np.square(samples), dtype=np.float64)))


def _mok_stream_to_wav(sample_rate, samples):
    import tempfile
    import wave
    import numpy as np

    handle = tempfile.NamedTemporaryFile(
        suffix=".wav",
        delete=False,
    )

    path = handle.name
    handle.close()

    pcm = np.clip(samples, -1.0, 1.0)
    pcm = (pcm * 32767.0).astype(np.int16)

    with wave.open(path, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(int(sample_rate))
        wav_file.writeframes(pcm.tobytes())

    return path


def _mok_response_audio_seconds(audio_bytes, response_text):
    import io

    try:
        import av
        container = av.open(io.BytesIO(audio_bytes))

        try:
            if container.duration is not None:
                return max(
                    0.5,
                    float(container.duration) / 1000000.0,
                )
        finally:
            container.close()
    except Exception:
        pass

    text = str(response_text or "")
    return max(0.8, min(12.0, len(text) / 14.0))


# MOK_R7_R1_STOP_HANDLER

# MOK_R9_1C_RELIABLE_COMPLETED_VOICE_TURN
# MOK_R23_REUSABLE_COMPLETED_VOICE_TURN
def _mok_complete_human_voice_turn(audio_value, conversation_history, stream_state):
    import os
    import re
    import time

    history = _mok_session_history(conversation_history)
    state = _mok_voice_stream_state(stream_state)
    turn_started = time.perf_counter()

    sample_rate, samples = _mok_stream_chunk(audio_value)

    if sample_rate is None or samples is None:
        response = 'I could not clearly hear that. Please try again.'
        _mok_reset_stream_turn(state)
        return response, history, state, None

    wav_path = _mok_stream_to_wav(sample_rate, samples)

    try:
        asr_started = time.perf_counter()
        transcript = transcribe_mok_voice(wav_path)
        transcription_ms = (time.perf_counter() - asr_started) * 1000.0
    finally:
        try:
            os.remove(wav_path)
        except OSError:
            pass

    transcript = str(transcript or '').strip()

    transcript = re.sub(
        r'\b(?:mook|moke|mock|mooc)\b',
        'MOK',
        transcript,
        flags=re.IGNORECASE,
    )

    print('MOK_R23_TRANSCRIPT: ' + repr(transcript), flush=True)

    if not transcript:
        response = 'I could not clearly hear that. Please try again.'
        _mok_reset_stream_turn(state)
        return response, history, state, None

    mok_started = time.perf_counter()
    response = _mok_human_conversation_response(transcript, history)
    mok_ms = (time.perf_counter() - mok_started) * 1000.0

    history = _mok_store_turn(
        history,
        transcript,
        response,
        'voice',
    )

    _mok_reset_stream_turn(state)
    state['turn_number'] = int(state.get('turn_number', 0)) + 1

    response_ready_ms = (time.perf_counter() - turn_started) * 1000.0

    print(
        'MOK_R23_RESPONSE_READY '
        + 'transcription_ms={:.1f} mok_ms={:.1f} response_ready_ms={:.1f}'.format(
            transcription_ms,
            mok_ms,
            response_ready_ms,
        ),
        flush=True,
    )

    # Fourth output clears the microphone so another question
    # can be recorded immediately.
    return response, history, state, None


# MOK_R23_CLEAN_COMPLETE_MP3_TTS
def _mok_stream_human_voice_response(response_text):
    import time

    text = str(response_text or '').strip()

    if not text:
        return None

    started = time.perf_counter()
    audio_path = synthesize_mok_voice(text)
    ready_ms = (time.perf_counter() - started) * 1000.0

    print(
        'MOK_R23_CLEAN_TTS_READY_MS={:.1f}'.format(ready_ms),
        flush=True,
    )

    return audio_path


# MOK_SR_1_3Q_NEW_VOICE_SESSION
def _mok_start_new_voice_session(stream_state):
    state = _mok_voice_stream_state(stream_state)
    _mok_reset_stream_turn(state)
    state["user_stopped"] = False
    state["mute_until"] = 0.0
    state["stop_chunks"] = []
    state["stop_speech_seconds"] = 0.0
    state["stop_silence_seconds"] = 0.0
    print("MOK_NEW_VOICE_SESSION_STARTED", flush=True)
    return state


def _mok_user_stop_voice_stream(stream_state):
    state = _mok_voice_stream_state(stream_state)
    _mok_reset_stream_turn(state)
    state["user_stopped"] = True
    state["mute_until"] = 0.0
    print("MOK_USER_STOPPED_STREAM", flush=True)
    return state


def _mok_continuous_voice_turn(
    audio_chunk,
    conversation_history,
    stream_state,
):
    import os
    import time
    import numpy as np
    import gradio as gr

    history = _mok_session_history(conversation_history)
    state = _mok_voice_stream_state(stream_state)

    # MOK_SR_1_3B_TERMINAL_USER_STOP_GATE
    # A deliberate microphone Stop is authoritative for the current
    # streaming session. Gradio may deliver trailing stream callbacks
    # after the viewer presses Stop; those callbacks must never reopen
    # speech processing or mutate the stopped session.
    if state.get("user_stopped"):
        _mok_reset_stream_turn(state)
        state["mute_until"] = 0.0
        return gr.skip(), gr.skip(), history, state


    sample_rate, samples = _mok_stream_chunk(audio_chunk)

    if sample_rate is None or samples is None:
        return gr.skip(), gr.skip(), history, state

    now = time.monotonic()

    if now < float(state.get("mute_until", 0.0)):
        # MOK is speaking, but the microphone remains available
        # for a deliberate viewer interruption ("stop").
        chunk_seconds = float(samples.shape[0]) / float(sample_rate)
        rms = _mok_stream_rms(samples)
        stop_threshold = max(
            0.008,
            min(0.030, float(state.get("noise_rms", 0.003)) * 3.0),
        )
        voiced = rms >= stop_threshold

        stop_chunks = state.setdefault("stop_chunks", [])
        stop_speech = float(state.get("stop_speech_seconds", 0.0))
        stop_silence = float(state.get("stop_silence_seconds", 0.0))

        if voiced:
            stop_chunks.append(samples)
            state["stop_speech_seconds"] = stop_speech + chunk_seconds
            state["stop_silence_seconds"] = 0.0
        elif stop_chunks:
            stop_chunks.append(samples)
            state["stop_silence_seconds"] = stop_silence + chunk_seconds
        else:
            return gr.skip(), gr.skip(), history, state

        if float(state.get("stop_speech_seconds", 0.0)) < 0.10:
            return gr.skip(), gr.skip(), history, state

        if float(state.get("stop_silence_seconds", 0.0)) < 0.10:
            return gr.skip(), gr.skip(), history, state

        interrupt_audio = np.concatenate(stop_chunks, axis=0)
        interrupt_path = _mok_stream_to_wav(sample_rate, interrupt_audio)

        try:
            interrupt_text = transcribe_mok_stop(interrupt_path)
        finally:
            try:
                os.remove(interrupt_path)
            except OSError:
                pass

        interrupt_text = str(interrupt_text or "").strip()
        interrupt_normalized = " ".join(
            interrupt_text.lower().replace(",", " ").replace(".", " ").split()
        )

        stop_phrases = {
            "stop",
            "stop mok",
            "mok stop",
            "please stop",
            "stop now",
            "that is enough",
            "enough",
        }

        state["stop_chunks"] = []
        state["stop_speech_seconds"] = 0.0
        state["stop_silence_seconds"] = 0.0

        # MOK_SR_1_3R_SPOKEN_INTERRUPT_CONTINUES_LISTENING
        if interrupt_normalized in stop_phrases:
            _mok_reset_stream_turn(state)
            state["user_stopped"] = False
            state["mute_until"] = 0.0
            print(
                "MOK_GLOBAL_STOP_AUTHORITY transcript={!r}".format(
                    interrupt_text
                ),
                flush=True,
            )
            # None clears the autoplaying MOK audio component.
            return "Okay. I have stopped.", None, history, state

        # Ignore non-stop speech while MOK is still speaking.
        _mok_reset_stream_turn(state)
        return gr.skip(), gr.skip(), history, state

    chunk_seconds = float(samples.shape[0]) / float(sample_rate)
    rms = _mok_stream_rms(samples)

    noise_rms = float(state.get("noise_rms", 0.003))

    if not state.get("speech_started") and rms < 0.030:
        noise_rms = (noise_rms * 0.92) + (rms * 0.08)
        state["noise_rms"] = noise_rms

    speech_threshold = max(
        0.006,
        min(0.030, noise_rms * 3.0),
    )

    voiced = rms >= speech_threshold
    state["sample_rate"] = sample_rate

    if not state.get("speech_started"):
        state["chunks"].append(samples)

        if len(state["chunks"]) > _MOK_STREAM_PREROLL_CHUNKS:
            state["chunks"] = state["chunks"][-_MOK_STREAM_PREROLL_CHUNKS:]

        if not voiced:
            return gr.skip(), gr.skip(), history, state

        state["speech_started"] = True
        state["speech_seconds"] = chunk_seconds
        state["silence_seconds"] = 0.0

        print(
            "MOK_CONTINUOUS_SPEECH_STARTED "
            + "rms={:.5f} threshold={:.5f}".format(
                rms,
                speech_threshold,
            ),
            flush=True,
        )

        return gr.skip(), gr.skip(), history, state

    state["chunks"].append(samples)

    if voiced:
        state["speech_seconds"] = float(state.get("speech_seconds", 0.0)) + chunk_seconds
        state["silence_seconds"] = 0.0
    else:
        state["silence_seconds"] = float(state.get("silence_seconds", 0.0)) + chunk_seconds

    if float(state.get("speech_seconds", 0.0)) < _MOK_MINIMUM_SPEECH_SECONDS:
        return gr.skip(), gr.skip(), history, state

    if float(state.get("silence_seconds", 0.0)) < _MOK_END_OF_QUESTION_SILENCE_SECONDS:
        return gr.skip(), gr.skip(), history, state

    print(
        "MOK_END_OF_QUESTION_DETECTED "
        + "speech_s={:.2f} silence_s={:.2f}".format(
            float(state.get("speech_seconds", 0.0)),
            float(state.get("silence_seconds", 0.0)),
        ),
        flush=True,
    )

    turn_started = time.perf_counter()

    complete_audio = np.concatenate(state["chunks"], axis=0)
    wav_path = _mok_stream_to_wav(sample_rate, complete_audio)

    try:
        asr_started = time.perf_counter()
        transcript = transcribe_mok_voice(wav_path)
        transcription_ms = (time.perf_counter() - asr_started) * 1000.0
    finally:
        try:
            os.remove(wav_path)
        except OSError:
            pass

    transcript = str(transcript or "").strip()

    if not transcript:
        _mok_reset_stream_turn(state)
        return gr.skip(), gr.skip(), history, state

    print("MOK_CONTINUOUS_TRANSCRIPT: " + repr(transcript), flush=True)

    mok_started = time.perf_counter()
    # MOK_SR_1_3S_RESPONSE_STAGE_EVIDENCE
    # MOK_SR_1_6_INTENTIONAL_VOICE_TURN_GATE     # MOK_SR_1_7B_1_EXECUTABLE_INTENTIONAL_TURN_GATE     sr16_voice_turn = _mok_sr16_interpret_turn(         transcript,         _mok_load_conversation_memory(),     )      if not sr16_voice_turn.get("intentional"):         print(             "MOK_SILENT_TURN_IGNORED transcript=" + repr(transcript),             flush=True,         )         _mok_reset_stream_turn(state)         return gr.skip(), gr.skip(), history, state 
    print("MOK_RESPONSE_START transcript=" + repr(transcript), flush=True)
    response = _mok_human_conversation_response(transcript, history)
    print("MOK_RESPONSE_READY chars=" + str(len(str(response or ""))), flush=True)
    mok_ms = (time.perf_counter() - mok_started) * 1000.0

    tts_started = time.perf_counter()
    print("MOK_TTS_START", flush=True)
    response_audio = _mok_sr17_safe_synthesize(response)
    print("MOK_TTS_READY bytes=" + str(len(response_audio or b"")), flush=True)
    tts_ms = (time.perf_counter() - tts_started) * 1000.0

    total_ms = (time.perf_counter() - turn_started) * 1000.0

    history = _mok_store_turn(
        history,
        transcript,
        response,
        "voice",
    )

    response_seconds = _mok_response_audio_seconds(
        response_audio,
        response,
    )

    _mok_reset_stream_turn(state)

    state["turn_number"] = int(state.get("turn_number", 0)) + 1
    state["mute_until"] = time.monotonic() + response_seconds + 0.35

    print(
        "MOK_VOICE_LATENCY "
        + "transcription_ms={:.1f} mok_ms={:.1f} tts_ms={:.1f} total_ms={:.1f}".format(
            transcription_ms,
            mok_ms,
            tts_ms,
            total_ms,
        ),
        flush=True,
    )

    print(
        "MOK_CONTINUOUS_TURN_COMPLETE "
        + "turn={} resume_after_s={:.2f}".format(
            state["turn_number"],
            response_seconds + 0.35,
        ),
        flush=True,
    )

    return response, response_audio, history, state


def mok_session_conversation_snapshot(conversation_history):
    return _mok_session_history(conversation_history)



def viewer_status_message():
    return (
        "<div class='mok-progress-wrap'>"
        "<div class='mok-progress-label'>0% &mdash; Ready</div>"
        "<div class='mok-progress-track'>"
        "<div class='mok-progress-fill' style='width:0%'></div>"
        "</div>"
        "<div class='mok-progress-message'>"
        "</div>"
        "</div>"
    )



MOK_VIEWER_PROGRESS_CSS = '\n.mok-progress-wrap {\n    width: 100%;\n    padding: 14px 2px 8px 2px;\n}\n.mok-progress-label {\n    font-size: 1rem;\n    font-weight: 600;\n    margin-bottom: 8px;\n}\n.mok-progress-track {\n    width: 100%;\n    height: 18px;\n    border-radius: 999px;\n    background: rgba(127, 127, 127, 0.20);\n    overflow: hidden;\n}\n.mok-progress-fill {\n    height: 100%;\n    border-radius: 999px;\n    background: currentColor;\n    transition: width 0.35s ease;\n}\n.mok-progress-message {\n    margin-top: 9px;\n    font-size: 0.95rem;\n    opacity: 0.85;\n}\n'

# MOK_H10_8C_H_H_B_R4_R5_SINGLE_MICROPHONE_AUTHORITY

# MOK_R9_1A_PRESENTATION_POLISH
MOK_R9_1_UI_CSS = '''
.gradio-container {
    background: linear-gradient(145deg, #f8fbff 0%, #f2f0ff 52%, #fff8f2 100%) !important;
    color: #172033 !important;
}
.gradio-container h1 {
    font-weight: 900 !important;
    letter-spacing: -0.025em !important;
    color: #172554 !important;
}
.gradio-container h2 {
    font-weight: 850 !important;
    color: #312e81 !important;
}
.gradio-container h3 {
    font-weight: 800 !important;
    color: #4338ca !important;
}
.gradio-container p,
.gradio-container label,
.gradio-container .label-wrap {
    font-weight: 650 !important;
}
.gradio-container button {
    font-weight: 800 !important;
    border-radius: 12px !important;
    transition: transform 0.15s ease, box-shadow 0.15s ease !important;
}
.gradio-container button:hover {
    transform: translateY(-1px);
    box-shadow: 0 8px 20px rgba(49, 46, 129, 0.14) !important;
}
.gradio-container .primary {
    background: linear-gradient(135deg, #4338ca, #2563eb) !important;
    color: white !important;
}
.gradio-container textarea,
.gradio-container input,
.gradio-container select {
    font-weight: 600 !important;
}
.gradio-container .block {
    border-radius: 14px !important;
}
@media (max-width: 768px) {
    .gradio-container h1 { font-size: 1.75rem !important; }
    .gradio-container h2 { font-size: 1.35rem !important; }
    .gradio-container button { min-height: 46px !important; }
}
'''

with gr.Blocks(title="MOK Autonomous AI Studio", css=MOK_R9_1_UI_CSS) as demo:
    gr.Markdown(
        """
        # **MOK Autonomous AI Studio**

        ### **Create without needing technical production knowledge**

        Tell MOK what you want to experience or create.
        Add whatever material you already have.
        MOK handles the production decisions autonomously.
        """
    )

    gr.Markdown("## Ask MOK")

    gr.Markdown(
        "Hi, I'm MOK. How can I help you?"
    )

    mok_question = gr.Textbox(
        label="Your question",
        placeholder="Type your question here...",
        lines=2,
    )

    ask_button = gr.Button("Send")

    mok_answer = gr.Textbox(
        label="MOK reply",
        interactive=False,
        lines=3,
    )

    # Invisible per-viewer conversation memory.
    conversation_state = gr.State(value=[])
    # MOK_H10_8C_H_H_B_R6_STREAM_STATE
    voice_stream_state = gr.State(value={})

    # MOK_MINIMAL_VOICE_UI_R2
    gr.HTML(""
        "<style>"
        "#mok_voice_input audio { display:none !important; }"
        "#mok_voice_input select { display:none !important; }"
        "#mok_voice_input input[type=range] { display:none !important; }"
        "#mok_voice_input button[aria-label*=Download] { display:none !important; }"
        "#mok_voice_input button[aria-label*=Share] { display:none !important; }"
        "#mok_voice_input button[aria-label*=Play] { display:none !important; }"
        "#mok_voice_input button[aria-label*=Pause] { display:none !important; }"
        "#mok_voice_reply { display:none !important; }"
        "</style>"
    )
    # MOK_HG_R1_SPEAK_LABEL
    gr.Markdown("**Speak to MOK**")
    # MOK_HG_R1_CLEAN_VOICE_CSS
    gr.HTML(
        """<style>

        /* MOK_R8_R6_10_NATIVE_GRADIO_MICROPHONE_UI */
        @media (max-width: 900px) {
            .gradio-container {
                width: 100% !important;
                max-width: 100% !important;
                padding-left: 14px !important;
                padding-right: 14px !important;
                overflow-x: hidden !important;
            }

            .gradio-container .row {
                flex-wrap: wrap !important;
            }

            .gradio-container .column,
            .gradio-container .form,
            .gradio-container .block {
                min-width: 0 !important;
                max-width: 100% !important;
            }

            .gradio-container img,
            .gradio-container video,
            .gradio-container audio {
                max-width: 100% !important;
            }
        }

        @media (max-width: 640px) {
            .gradio-container {
                padding-left: 10px !important;
                padding-right: 10px !important;
            }

            .gradio-container h1 {
                font-size: clamp(1.55rem, 7vw, 2rem) !important;
                line-height: 1.15 !important;
            }

            .gradio-container h2 {
                font-size: clamp(1.2rem, 5vw, 1.55rem) !important;
            }

            .gradio-container button {
                min-height: 44px !important;
                touch-action: manipulation !important;
            }

            .gradio-container textarea,
            .gradio-container input,
            .gradio-container select {
                width: 100% !important;
                max-width: 100% !important;
                font-size: 16px !important;
            }

            .gradio-container .wrap,
            .gradio-container .container {
                max-width: 100% !important;
                overflow-wrap: anywhere !important;
            }
        }

        </style>"""
    )


    mok_voice = gr.Audio(
        sources=["microphone"],
        streaming=True,
        type="numpy",
        label="Speak to MOK",
        show_label=False,
        container=False,
        elem_id="mok_voice_input",
    )

    # MOK_SR_1_3Z_STABLE_BROWSER_VOICE_STATE
    gr.HTML(
        '''
        <style>
        #mok_voice_input button {
            min-width: 170px !important;
        }

        #mok_voice_input .mok-stable-listening {
            min-width: 190px !important;
        }
        </style>

        <script>
        (() => {
            const ROOT_ID = 'mok_voice_input';
            const ACTIVE_LABEL = 'Listening â€” click to stop';
            const READY_LABEL = 'Speak';

            function normalizeButton(button) {
                if (!button) return;

                const raw = (
                    button.innerText ||
                    button.textContent ||
                    button.getAttribute('aria-label') ||
                    button.getAttribute('title') ||
                    ''
                ).trim();

                const value = raw.toLowerCase();

                if (
                    value === 'stop' ||
                    value === 'waiting' ||
                    value.includes('stop recording') ||
                    value.includes('waiting')
                ) {
                    if (button.textContent !== ACTIVE_LABEL) {
                        button.textContent = ACTIVE_LABEL;
                    }

                    button.setAttribute('aria-label', ACTIVE_LABEL);
                    button.classList.add('mok-stable-listening');
                    return;
                }

                if (
                    value === 'record' ||
                    value.includes('start recording')
                ) {
                    if (button.textContent !== READY_LABEL) {
                        button.textContent = READY_LABEL;
                    }

                    button.setAttribute('aria-label', READY_LABEL);
                    button.classList.remove('mok-stable-listening');
                }
            }

            function normalizeVoiceControl() {
                const root = document.getElementById(ROOT_ID);

                if (!root) return;

                const buttons = root.querySelectorAll('button');

                buttons.forEach(normalizeButton);
            }

            let scheduled = false;

            function scheduleNormalize() {
                if (scheduled) return;

                scheduled = true;

                requestAnimationFrame(() => {
                    scheduled = false;
                    normalizeVoiceControl();
                });
            }

            // MOK_SR_1_5A_SINGLE_STABLE_VOICE_PRESENTATION_AUTHORITY
            function stabilizeVoicePresentation() {
                // Normalize synchronously so Gradio's transient
                // Record / Stop / Waiting labels do not become the
                // presentation authority between DOM mutations.
                normalizeVoiceControl();

                // Keep the existing animation-frame pass as a
                // second stabilization after Gradio finishes
                // mutating the microphone control.
                scheduleNormalize();
            }

            const observer = new MutationObserver(stabilizeVoicePresentation);

            observer.observe(document.documentElement, {
                childList: true,
                subtree: true,
                characterData: true,
                attributes: true,
                attributeFilter: ['aria-label', 'title', 'class']
            });

            normalizeVoiceControl();

            window.addEventListener('load', () => {
                normalizeVoiceControl();
                setTimeout(normalizeVoiceControl, 250);
                setTimeout(normalizeVoiceControl, 750);
            });
        })();
        </script>
        ''',
        visible=True,
    )


    gr.Markdown(
        "**Speak to MOK** â€” start the microphone and ask your question naturally. "
        "Pause when you finish and MOK will answer automatically. "
        "Say **Stop** while MOK is speaking to interrupt the reply, then continue with your next question. "
        "Click **Stop** when you want to leave voice mode."
    )


    mok_voice_reply = gr.Audio(
        label="",
        autoplay=True,
        interactive=False,
        visible="hidden",
        format="mp3",
        elem_id="mok_voice_reply",
        streaming=False,
    )



    gr.Markdown("## 1. What would you like MOK to create?")

    project_type = gr.Dropdown(
        choices=[
            "Cinematic Video",
            "Short Film",
            "Brand / Product Experience",
            "Social Media Content",
            "Presentation / Story",
            "Creative Project",
            "Other",
        ],
        label="Choose your project",
        value="Cinematic Video",
    )

    gr.Markdown("## 2. Add anything you want MOK to work with")

    with gr.Row():
        photos = gr.File(
            label="Photos / Pictures",
            file_count="multiple",
            type="filepath",
        )
        videos = gr.File(
            label="Video Clips",
            file_count="multiple",
            type="filepath",
        )

    with gr.Row():
        logos = gr.File(
            label="Logo / Brand Assets",
            file_count="multiple",
            type="filepath",
        )
        documents = gr.File(
            label="Files / Documents / Scripts / Notes",
            file_count="multiple",
            type="filepath",
        )

    audio = gr.File(
        label="Music / Audio / Narration",
        file_count="multiple",
        type="filepath",
    )

    gr.Markdown("## 3. Describe the experience you want")

    experience = gr.Textbox(
        label="Tell MOK what you want",
        placeholder=(
            "Example: Create an emotional cinematic brand story using my logo and photos. "
            "Make it feel inspiring, premium, and memorable."
        ),
        lines=6,
        max_lines=12,
    )

    create_button = gr.Button(
        "Create with MOK",
        variant="primary",
    )

    gr.Markdown("## 4. Production progress")

    progress = gr.HTML(
        value=viewer_status_message(),
        label="Production progress",
    )

    production_output = gr.JSON(
        label="MOK Production Evidence",
        visible=False,
    )

    video_output = gr.Video(
        label="Your creation",
    )

    with gr.Accordion("MOK System Health", open=False):
        health_button = gr.Button("Refresh Health")
        health_output = gr.Code(
            label="Runtime Health",
            language="json",
        )

    create_button.click(
        fn=run_viewer_production,
        inputs=[
            project_type,
            experience,
            photos,
            videos,
            logos,
            documents,
            audio,
        ],
        outputs=[
            progress,
            production_output,
            video_output,
        ],
        api_name="produce",
        queue=True,
    )

    ask_button.click(
        fn=ask_mok_session_text,
        inputs=[
            mok_question,
            conversation_state,
        ],
        outputs=[
            mok_question,
            mok_answer,
            conversation_state,
        ],
        api_name="ask_mok",
        queue=False,
    )

    mok_question.submit(
        fn=ask_mok_session_text,
        inputs=[
            mok_question,
            conversation_state,
        ],
        outputs=[
            mok_question,
            mok_answer,
            conversation_state,
        ],
        api_name=False,
        show_api=False,
        queue=False,
    )
    # MOK_H10_8C_H_H_B_R6_CONTINUOUS_STREAM_BINDING
    # MOK_R9_1C_RELIABLE_VOICE_TURN_BINDING
    # MOK_R24_NATIVE_CONTINUOUS_CONVERSATION_AUTHORITY
    mok_voice_stream_event = mok_voice.stream(
        fn=_mok_continuous_voice_turn,
        inputs=[
            mok_voice,
            conversation_state,
            voice_stream_state,
        ],
        outputs=[
            mok_answer,
            mok_voice_reply,
            conversation_state,
            voice_stream_state,
        ],
        stream_every=0.25,
        time_limit=900,
        show_progress="hidden",
        queue=False,
    )

    # MOK_SR_1_3Q_SPEAK_START_BINDING
    mok_voice.start_recording(
        fn=_mok_start_new_voice_session,
        inputs=voice_stream_state,
        outputs=voice_stream_state,
        queue=False,
        show_progress="hidden",
    )

    health_button.click(
        fn=health_status,
        inputs=None,
        outputs=health_output,
        api_name="health",
        queue=False,
    )

    demo.load(
        fn=health_status,
        inputs=None,
        outputs=health_output,
        queue=False,
    )


if __name__ == "__main__":
    # MOK_R8_GRADIO_QUEUE_FOR_CANCELLATION
    demo.queue()

    demo.launch(
        server_name="0.0.0.0",
        server_port=int(os.getenv("PORT", "7860")),
        show_error=False,
        allowed_paths=[str((PROJECT_ROOT / "output" / "mok_native_production").resolve())],
    )
# MOK-H10.8C-F-R3 presentation deployment 20260817-034000



