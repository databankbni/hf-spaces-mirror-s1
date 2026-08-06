"""prompt_builder.py -- builds per-view VLM prompts and validation schemas
from the COMPILED taxonomy artifact (artifacts/taxonomy_compiled.json).

Single-source guarantee: the damage vocabulary, severity anchors, and boundary
cautions the VLM sees are byte-identical to the vocabulary the rule engine
enforces, because both are read from the same compiled artifact.

ASCII only.
"""

import json
import os

VIEW_COMPONENTS = {
    "front_off": ["screen", "housing"],
    "front_on": ["screen", "housing"],
    "back": ["back_glass", "housing", "camera_lens", "port"],
}

VIEW_INSTRUCTIONS = {
    "front_off": ("This photo shows the FRONT of the device with the screen "
                  "OFF. Assess glass and housing damage only. Do not report "
                  "display-function damage types (dead_pixels, discoloration, "
                  "burn_in, touch_fault) from this view."),
    "front_on": ("This photo shows the FRONT of the device with the screen ON. "
                 "The screen should display a short verification code typed in "
                 "a notes app. Read the code EXACTLY as shown into "
                 "challenge_code_read (null if unreadable or absent). Also set "
                 "screen_appears_on. Assess screen glass damage and display "
                 "damage (dead_pixels, discoloration, burn_in). Never report "
                 "touch_fault from a static photo."),
    "back": ("This photo shows the BACK of the device. Assess back glass, "
             "housing, camera lens, and visible port condition."),
}


def load_taxonomy(artifacts_dir):
    path = os.path.join(artifacts_dir, "taxonomy_compiled.json")
    with open(path, "r", encoding="ascii") as f:
        return json.load(f)


def build_prompt(taxonomy, view):
    comps = VIEW_COMPONENTS[view]
    lines = []
    lines.append("You are a device-condition assessor for a protection-plan "
                 "onboarding system. You describe observable damage. You never "
                 "make eligibility decisions.")
    lines.append("")
    lines.append(VIEW_INSTRUCTIONS[view])
    lines.append("")
    lines.append("CLOSED VOCABULARY. You may ONLY use these values.")
    lines.append("components (this view): " + ", ".join(comps))
    lines.append("severities: " + ", ".join(taxonomy["severities"]))
    lines.append("")
    lines.append("severity anchors:")
    for sev, anchor in taxonomy["severity_anchors"].items():
        lines.append("- %s: %s" % (sev, anchor))
    lines.append("")
    lines.append("damage_type definitions (only types valid for this view's "
                 "components):")
    for name, spec in sorted(taxonomy["damage_types"].items()):
        if any(c in comps for c in spec["components"]):
            lines.append("- %s (on %s): %s"
                         % (name, "/".join(spec["components"]), spec["definition"]))
    lines.append("")
    lines.append("cautions:")
    for c in taxonomy["boundary_cautions"]:
        lines.append("- " + c)
    lines.append("")
    lines.append("If damage does not fit any definition, use damage_type "
                 "'other'. If a component shows no damage, omit it (do not "
                 "emit severity 'none' findings).")
    lines.append("")
    lines.append("Respond with ONLY one JSON object, no markdown fences, no "
                 "commentary, exactly this shape:")
    lines.append(json.dumps(example_object(view), indent=1))
    return "\n".join(lines)


def example_object(view):
    ex = {
        "view": view,
        "findings": [{
            "component": VIEW_COMPONENTS[view][0],
            "damage_type": "crack",
            "severity": "moderate",
            "location": "upper_left",
            "confidence": 0.8,
            "evidence_note": "short factual note",
        }],
        "image_quality": {"blur": False, "glare": False,
                          "full_device_visible": True},
        "challenge_code_read": None,
    }
    if view == "front_on":
        ex["screen_appears_on"] = True
    return ex


def build_schema(taxonomy, view):
    comps = VIEW_COMPONENTS[view]
    types = sorted(taxonomy["damage_types"].keys())
    schema = {
        "type": "object",
        "required": ["view", "findings", "image_quality"],
        "properties": {
            "view": {"const": view},
            "findings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["component", "damage_type", "severity",
                                 "confidence"],
                    "properties": {
                        "component": {"enum": comps},
                        "damage_type": {"enum": types},
                        "severity": {"enum": taxonomy["severities"]},
                        "location": {"type": "string"},
                        "confidence": {"type": "number",
                                       "minimum": 0, "maximum": 1},
                        "evidence_note": {"type": "string"},
                    },
                },
            },
            "image_quality": {
                "type": "object",
                "required": ["blur", "full_device_visible"],
                "properties": {
                    "blur": {"type": "boolean"},
                    "glare": {"type": "boolean"},
                    "full_device_visible": {"type": "boolean"},
                },
            },
            "challenge_code_read": {"type": ["string", "null"]},
        },
    }
    if view == "front_on":
        schema["required"].append("screen_appears_on")
        schema["properties"]["screen_appears_on"] = {"type": "boolean"}
    return schema
