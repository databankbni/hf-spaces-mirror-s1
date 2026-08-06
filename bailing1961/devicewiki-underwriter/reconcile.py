"""reconcile.py -- multi-view reconciliation for DeviceWiki-Underwriter.

Turns validated per-view VLM reports into the session facts the decision
engine consumes. Owns the confirmed/suspected logic, challenge verification,
image-quality gating, and the Stage-2 placeholder fraud band (deterministic;
Dempster-Shafer fusion replaces it in Stage 3 behind the same field).

Confirmation policy (conservative by design):
  - Physical glass damage on the SCREEN (crack/shatter/scratch): confirmed
    only if the same (component, type) appears in BOTH front_off and
    front_on; severity/confidence = max over the two. Single view -> suspected.
  - Display-function damage (dead_pixels/discoloration/burn_in): only
    observable screen-ON; confirmed from front_on alone if confidence >= 0.70,
    else suspected.
  - touch_fault: never derivable from static photos; always downgraded to
    suspected with a warning (taxonomy rule).
  - Back-view findings (back_glass/housing/camera_lens/port) and housing
    findings from front views: confirmed if confidence >= 0.70, else suspected.
  - damage_type 'other': always suspected (routes to referral regardless).
  - severity 'none' findings are dropped.

ASCII only.
"""

import json

from jsonschema import Draft7Validator

from prompt_builder import build_schema
from vlm_client import strip_fences

GLASS_TYPES = {"crack", "shatter", "scratch"}
ON_ONLY_TYPES = {"dead_pixels", "discoloration", "burn_in"}
CONF_SINGLE_VIEW = 0.70


def validate_report(taxonomy, view, raw_text):
    """Parse + schema-validate one raw model output.
    Returns (report_dict, None) or (None, error_string)."""
    try:
        obj = json.loads(strip_fences(raw_text))
    except ValueError as e:
        return None, "not valid JSON: %s" % e
    errs = sorted(Draft7Validator(build_schema(taxonomy, view)).iter_errors(obj),
                  key=lambda e: e.path)
    if errs:
        return None, "; ".join(e.message for e in errs[:3])
    return obj, None


def get_view_report(client, taxonomy, view, image_path, prompt):
    """Call model, validate, single retry with error feedback.
    Returns (report or None, raw_texts list, error or None)."""
    raws = []
    raw = client.analyze_view(image_path, prompt, view)
    raws.append(raw)
    rep, err = validate_report(taxonomy, view, raw)
    if rep is not None:
        return rep, raws, None
    raw2 = client.analyze_view(image_path, prompt, view, feedback=err)
    raws.append(raw2)
    rep, err2 = validate_report(taxonomy, view, raw2)
    if rep is not None:
        return rep, raws, None
    return None, raws, err2


def _quality_ok(report):
    q = report["image_quality"]
    return (not q.get("blur", False)) and q.get("full_device_visible", False)


def _key(f):
    return (f["component"], f["damage_type"])


def reconcile(reports, challenge_code):
    """reports: dict view -> validated report (missing/None views allowed).
    Returns (session_fragment dict, warnings list)."""
    warnings = []
    usable = {}
    for view, rep in reports.items():
        if rep is None:
            warnings.append("view %s: no valid report (model output failed "
                            "validation twice or image missing)" % view)
            continue
        if not _quality_ok(rep):
            warnings.append("view %s: rejected by image-quality gate "
                            "(blur or device not fully visible)" % view)
            continue
        if rep["image_quality"].get("glare"):
            warnings.append("view %s: glare present; confidences may be "
                            "less reliable" % view)
        usable[view] = rep

    # ---- challenge + power ----
    fo = usable.get("front_on")
    code_read = (fo or {}).get("challenge_code_read")
    if challenge_code == "SKIPPED":
        challenge_verified = True
        warnings.append("challenge SKIPPED by flag: challenge_verified "
                        "SIMULATED as true (Gate A / quick runs only)")
    elif fo is None:
        challenge_verified = False
        warnings.append("no usable front_on view -> challenge cannot be "
                        "verified -> false")
    else:
        challenge_verified = (
            isinstance(code_read, str)
            and code_read.strip().upper() == challenge_code.strip().upper())
        if not challenge_verified:
            warnings.append("challenge mismatch: expected %r, model read %r"
                            % (challenge_code, code_read))
    powers_on = bool(fo.get("screen_appears_on")) if fo else None
    if powers_on is None:
        warnings.append("powers_on unknown (no usable front_on view); the "
                        "challenge failure already routes this to review")

    # ---- findings merge ----
    def findings(view):
        return [f for f in usable.get(view, {}).get("findings", [])
                if f.get("severity") != "none"]

    damage = []

    fo_keys = {_key(f): f for f in findings("front_off")}
    fon_keys = {_key(f): f for f in findings("front_on")}

    handled = set()
    # screen physical glass damage: dual-view confirmation
    for k in set(list(fo_keys) + list(fon_keys)):
        comp, dtype = k
        if comp != "screen" or dtype not in GLASS_TYPES:
            continue
        handled.add(k)
        both = k in fo_keys and k in fon_keys
        pool = [d for d in (fo_keys.get(k), fon_keys.get(k)) if d]
        sev = max((f["severity"] for f in pool),
                  key=lambda s: ["none", "cosmetic", "moderate", "severe"].index(s))
        conf = max(f["confidence"] for f in pool)
        status = "confirmed" if both else "suspected"
        if not both:
            warnings.append("screen %s seen in one view only -> suspected"
                            % dtype)
        damage.append({"component": comp, "type": dtype, "severity": sev,
                       "status": status, "confidence": round(conf, 2)})

    # remaining front-view findings + back view
    rest = [f for v in ("front_off", "front_on") for f in findings(v)
            if _key(f) not in handled] + findings("back")
    seen = set(handled)
    for f in rest:
        k = _key(f)
        if k in seen:
            continue
        seen.add(k)
        comp, dtype = k
        conf = f["confidence"]
        if dtype == "other":
            status = "suspected"
        elif dtype == "touch_fault":
            status = "suspected"
            warnings.append("touch_fault reported from a static photo; "
                            "downgraded to suspected (taxonomy rule)")
        elif comp == "screen" and dtype in ON_ONLY_TYPES:
            status = "confirmed" if conf >= CONF_SINGLE_VIEW else "suspected"
        else:
            status = "confirmed" if conf >= CONF_SINGLE_VIEW else "suspected"
        damage.append({"component": comp, "type": dtype,
                       "severity": f["severity"], "status": status,
                       "confidence": round(conf, 2)})

    # ---- Stage-2 placeholder fraud band (DS fusion arrives in Stage 3) ----
    fraud_band = "accept" if challenge_verified else "uncertain"

    fragment = {
        "powers_on": powers_on,
        "challenge_verified": challenge_verified,
        "fraud_band": fraud_band,
        "stale_path": False,
        "damage": damage,
    }
    return fragment, warnings
