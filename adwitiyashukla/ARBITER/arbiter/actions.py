from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Tuple

from .models import Action

SCHEMA: Dict[str, Tuple[Tuple[str, ...], Tuple[str, ...], str]] = {
    "click":        (("ref",),            (),            "Click element #ref."),
    "double_click": (("ref",),            (),            "Double click element #ref (fires two clicks fast)."),
    "click_at":     (("x", "y"),          (),            "Click absolute viewport coordinates. Fallback when no ref fits."),
    "type":         (("ref", "text"),     ("clear",),    "Type text into input #ref. clear=true empties it first."),
    "press_key":    (("key",),            (),            "Press a keyboard key, for example Enter, Tab, Escape."),
    "hover":        (("ref",),            (),            "Hover the pointer over element #ref."),
    "select_option": (("ref", "value"),   (),            "Choose an option in select #ref."),
    "check":        (("ref",),            (),            "Tick or untick checkbox #ref."),
    "drag":         (("ref", "to_ref"),   (),            "Drag element #ref onto element #to_ref."),
    "scroll":       (("direction",),      ("amount",),   "Scroll the page up or down."),
    "resize":       (("width", "height"), (),            "Resize the viewport. Use this for responsive or layout bugs."),
    "wait":         (("ms",),             (),            "Wait, for animations or async work. Max 3000."),
    "go_back":      ((),                  (),            "Browser back."),
    "reload":       ((),                  (),            "Reload the page."),
    "finish":       (("verdict", "reason"), (),          "End the run. verdict is REPRODUCED or NOT_REPRODUCED."),
}

VALID_VERDICTS = {"REPRODUCED", "NOT_REPRODUCED"}
MAX_WAIT_MS = 3000


class ActionError(ValueError):
    pass


def schema_for_prompt() -> str:
    lines = []
    for name, (req, opt, doc) in SCHEMA.items():
        args = ", ".join(['"{0}": ...'.format(a) for a in req])
        if opt:
            args += "".join([', "{0}": ... (optional)'.format(a) for a in opt])
        lines.append('  {{"action": "{0}"{1}}}  - {2}'.format(name, (", " + args) if args else "", doc))
    return "\n".join(lines)


def extract_json_block(text: str) -> str:
    fenced = re.findall(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    for block in reversed(fenced):
        if block.strip():
            return block.strip()
    start = min([i for i in (text.find("["), text.find("{")) if i != -1], default=-1)
    if start == -1:
        raise ActionError("no JSON found in model reply")
    depth, opener = 0, text[start]
    closer = "]" if opener == "[" else "}"
    for i in range(start, len(text)):
        if text[i] == opener:
            depth += 1
        elif text[i] == closer:
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    raise ActionError("unbalanced JSON in model reply")


def validate(raw: Dict[str, Any]) -> Action:
    if not isinstance(raw, dict):
        raise ActionError("action must be an object, got {0}".format(type(raw).__name__))
    name = raw.get("action")
    if name not in SCHEMA:
        raise ActionError("unknown action {0!r}, allowed: {1}".format(name, ", ".join(SCHEMA)))
    required, optional, _ = SCHEMA[name]
    args = {k: v for k, v in raw.items() if k != "action"}
    missing = [a for a in required if a not in args]
    if missing:
        raise ActionError("action {0} is missing {1}".format(name, ", ".join(missing)))
    extra = [k for k in args if k not in required and k not in optional]
    if extra:
        raise ActionError("action {0} got unexpected argument(s) {1}".format(name, ", ".join(extra)))

    for key in ("ref", "to_ref", "x", "y", "width", "height", "ms", "amount"):
        if key in args:
            try:
                args[key] = int(args[key])
            except (TypeError, ValueError):
                raise ActionError("{0}.{1} must be an integer, got {2!r}".format(name, key, args[key]))
    if name == "wait":
        args["ms"] = max(0, min(int(args["ms"]), MAX_WAIT_MS))
    if name == "scroll" and str(args.get("direction")).lower() not in {"up", "down"}:
        raise ActionError("scroll.direction must be up or down")
    if name == "finish" and args.get("verdict") not in VALID_VERDICTS:
        raise ActionError("finish.verdict must be one of {0}".format(sorted(VALID_VERDICTS)))
    return Action(name=name, args=args)


def parse(text: str) -> List[Action]:
    payload = json.loads(extract_json_block(text))
    if isinstance(payload, dict):
        payload = [payload]
    if not isinstance(payload, list) or not payload:
        raise ActionError("expected a JSON object or a non-empty array of actions")
    return [validate(item) for item in payload]
