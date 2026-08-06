"""vlm_client.py -- GLM-4V-Flash perception client for DeviceWiki-Underwriter.

PRIVATE-CORE-ADJACENT MODULE (ships to Space in Stage 3, contains no IP:
it is a thin API wrapper; the prompt CONTENT comes from the compiled taxonomy
artifact, and decisions never happen here).

Modes:
  real : calls zhipuai GLM-4V-Flash. Requires env ZHIPUAI_API_KEY. VPN OFF.
  mock : returns canned per-view reports (no API, no network). Used by the
         Stage 2 Gate A pipeline test.

Contract: analyze_view() returns the RAW model text; validation/parsing is
the caller's job (reconcile.py), which owns the single retry with error
feedback.

ASCII only.
"""

import base64
import io
import os

MODEL = "glm-4v-flash"
MAX_SIDE = 1024
JPEG_QUALITY = 88

MOCK_REPORTS = {
    "front_off": """
{"view": "front_off",
 "findings": [
   {"component": "screen", "damage_type": "crack", "severity": "moderate",
    "location": "upper_left", "confidence": 0.78,
    "evidence_note": "single continuous fracture line from top-left corner"},
   {"component": "housing", "damage_type": "dent", "severity": "cosmetic",
    "location": "left_edge", "confidence": 0.60,
    "evidence_note": "small edge scuff"}],
 "image_quality": {"blur": false, "glare": true, "full_device_visible": true},
 "challenge_code_read": null}
""",
    "front_on": """
{"view": "front_on",
 "findings": [
   {"component": "screen", "damage_type": "crack", "severity": "moderate",
    "location": "upper_left", "confidence": 0.82,
    "evidence_note": "fracture line persists with screen on, crosses lit pixels"}],
 "image_quality": {"blur": false, "glare": false, "full_device_visible": true},
 "screen_appears_on": true,
 "challenge_code_read": "@CODE@"}
""",
    "back": """
{"view": "back",
 "findings": [
   {"component": "back_glass", "damage_type": "scratch", "severity": "cosmetic",
    "location": "center", "confidence": 0.75,
    "evidence_note": "light surface abrasions"}],
 "image_quality": {"blur": false, "glare": false, "full_device_visible": true},
 "challenge_code_read": null}
""",
}


def encode_image(path):
    """Resize + re-encode to keep the payload small; returns base64 str."""
    from PIL import Image
    img = Image.open(path).convert("RGB")
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=JPEG_QUALITY)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def strip_fences(text):
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t
        if t.rstrip().endswith("```"):
            t = t.rstrip()[:-3]
    return t.strip()


class VLMClient:
    def __init__(self, mock=False, challenge_code=None):
        self.mock = mock
        self.challenge_code = challenge_code or ""
        self.calls = 0
        if not mock:
            key = os.environ.get("ZHIPUAI_API_KEY")
            if not key:
                raise SystemExit(
                    "ZHIPUAI_API_KEY not set. Set it and retry (VPN OFF for zhipu API).")
            from zhipuai import ZhipuAI
            self.client = ZhipuAI(api_key=key)

    def analyze_view(self, image_path, prompt, view, feedback=None):
        """One model call for one view. feedback = validation error text for
        the single retry; appended so the model can correct its output."""
        self.calls += 1
        if self.mock:
            return MOCK_REPORTS[view].replace("@CODE@", self.challenge_code)
        text = prompt
        if feedback:
            text += ("\n\nYour previous output failed validation: " + feedback
                     + "\nOutput ONLY the corrected JSON object, nothing else.")
        b64 = encode_image(image_path)
        resp = self.client.chat.completions.create(
            model=MODEL,
            temperature=0.1,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": b64}},
                    {"type": "text", "text": text},
                ],
            }],
        )
        return resp.choices[0].message.content
