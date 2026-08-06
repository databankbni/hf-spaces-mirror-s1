import os
import json
import base64
import traceback
import datetime
import threading
import time
import re
from typing import Dict, Optional, Any, List
from io import BytesIO

from fastapi import FastAPI, Body, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from urllib.parse import unquote

import google.genai as genai

# ── Environment ──────────────────────────────────────────────
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or ""
# 제품컷 디테일 사전 분석(텍스트 전용). 이미지 생성 모델과 분리해 비전 모델 사용.
GEMINI_PRODUCT_ANALYSIS_MODEL = os.environ.get("GEMINI_PRODUCT_ANALYSIS_MODEL", "gemini-2.0-flash")
PRODUCT_ANALYSIS_MAX_CHARS = int(os.environ.get("PRODUCT_ANALYSIS_MAX_CHARS", "4500"))
PRODUCT_ANALYSIS_DISABLED = os.environ.get("PRODUCT_ANALYSIS_DISABLED", "").strip().lower() in (
    "1", "true", "yes", "on",
)
GEMINI_IMAGE_MAX_RETRIES = int(os.environ.get("GEMINI_IMAGE_MAX_RETRIES", "3"))
HF_TOKEN = os.environ.get("HF_TOKEN", "")
HF_DATASET_REPO = os.environ.get("HF_DATASET_REPO", "")
DEFAULT_BACKGROUND_FILE = "background.png"
# 제품컷 → 상세페이지용 스판 모션 영상 (Veo image-to-video)
VEO_MODEL = os.environ.get("VEO_MODEL", "veo-3.1-generate-preview")
VEO_DURATION_SECONDS = int(os.environ.get("VEO_DURATION_SECONDS", "6"))
VEO_RESOLUTION = os.environ.get("VEO_RESOLUTION", "1080p")
VEO_POLL_SECONDS = float(os.environ.get("VEO_POLL_SECONDS", "8"))
VEO_MAX_WAIT_SECONDS = int(os.environ.get("VEO_MAX_WAIT_SECONDS", "480"))

# 제품컷 상세페이지(PDP) 스판 연출 프리셋 — 원단 신축·복원력 강조
GHOST_MOTION_PRESETS = {
    "stretch": {
        "prompt": (
            "Premium ecommerce PRODUCT DETAIL PAGE (PDP) fabric-stretch demo video. "
            "Luxury brand lookbook / online store detail-page quality: sharp macro detail, "
            "clean composition, polished commercial lighting, slow deliberate pacing. "
            "Color grade: cool neutral white / soft blue-gray studio light — crisp, fresh, modern. "
            "Avoid warm yellow, orange, creamy tungsten, or lifestyle selfie aesthetics. "
            "The input is a flat PRODUCT-CUT / catalog photo. Preserve exact color, lace pattern, "
            "hardware, seams, and silhouette identity from the reference. "
            "PURPOSE: Showcase the garment's inherent SPAN / 4-way stretch elasticity and recovery — "
            "NOT a cup-pulling gimmick. "
            "ACTION: Clean manicured hands gently grip the stretch fabric body "
            "(side panel, underband, wing, or soft stretch mesh — whichever is the main elastic area). "
            "Slowly pull the fabric apart laterally to show clear elastic elongation, tension lines, "
            "and fabric thinning, then release so it smoothly snaps back / rebounds to original shape. "
            "Repeat once if time allows — calm, informative, premium. "
            "DO NOT yank or deform bra cups as the main action. "
            "DO NOT focus on pulling shoulder straps or spaghetti straps. "
            "Hands and forearms only; no face, no full body, no model posing. "
            "Seamless cool-white or soft gray studio backdrop, shallow depth of field on fabric texture, "
            "photorealistic microfiber/lace detail, no text overlays. "
            "Believable physical fabric physics — this must look like a real brand PDP stretch clip."
        ),
        "negative_prompt": (
            "pulling bra cups apart as main action, cup-yanking gimmick, stretching molded cups outward, "
            "grabbing straps, pulling spaghetti straps, strap stretch demo, "
            "Instagram Reels meme energy, shaky handheld chaos, low-res, soft blur, "
            "warm yellow light, orange cast, creamy tungsten, golden hour, "
            "frozen still, rigid unstretched fabric, postcard composite, no elasticity, "
            "face, full body model, sexy pose, torn fabric, ripping, dirty hands, "
            "busy background, text overlay, watermark, cartoon, morphing into a different garment"
        ),
        # hands 필요 — Developer API에서 dont_allow 미지원이라 allow_adult 사용
        "person_generation": "allow_adult",
    },
}
DEFAULT_GHOST_MOTION_STYLE = "stretch"


def _resolve_ghost_motion_preset(style_id: Any) -> tuple:
    key = str(style_id or "").strip().lower()
    if key not in GHOST_MOTION_PRESETS:
        key = DEFAULT_GHOST_MOTION_STYLE
    preset = GHOST_MOTION_PRESETS[key]
    return key, preset

GHOST_PRODUCT_SHOT_LABELS = frozenset({
    "제품 1 앞면 고스트컷",
    "제품 1 뒷면 고스트컷",
    "제품 1 측면 고스트컷",
    "제품 2 앞면 고스트컷",
    "제품 2 뒷면 고스트컷",
    "제품 2 측면 고스트컷",
})


def _is_ghost_product_shot(shot_label: str) -> bool:
    return shot_label in GHOST_PRODUCT_SHOT_LABELS


# 모델 샷: 항상 프로젝트의 background.png를 배경 플레이트로 전달 (요청의 backgroundImage보다 우선)
BACKGROUND_PLATE_SHOT_LABELS = frozenset({
    "3/4컷",
    "상반신",
    "상반신 측면",
    "상반신 후면",
    "하반신",
})


def _uses_fixed_background_plate(shot_label: str) -> bool:
    return shot_label in BACKGROUND_PLATE_SHOT_LABELS


def _ghost_product_context_block(shot_label: str, ghost_source_slot: Any) -> str:
    """고스트컷: 업로드 슬롯·제품1/2 혼동 방지 (클라이언트가 ghostSourceSlot을 보낼 때 강화)."""
    lines = []
    if ghost_source_slot is not None:
        try:
            si = int(ghost_source_slot)
            slot_names_en = ("product 1 front", "product 1 back", "product 2 front", "product 2 back")
            slot_names_ko = ("제품 1 앞면", "제품 1 뒷면", "제품 2 앞면", "제품 2 뒷면")
            if 0 <= si <= 3:
                lines.append(
                    f"REFERENCE SLOT (CLIENT-VERIFIED): The ONLY uploaded image is from slot index {si} "
                    f"({slot_names_en[si]} / {slot_names_ko[si]}). "
                    "Treat it as that exact product and camera-facing — do NOT swap in another product from the same project."
                )
        except (ValueError, TypeError):
            pass
    if "제품 2" in shot_label:
        lines.append(
            "PRODUCT SET (CRITICAL): This shot is for PRODUCT 2 (second product / lower row in the UI — often bottoms/briefs). "
            "The single reference defines the garment class. Do NOT output Product 1 (bra/top) or a generic bra back. "
            "If the reference shows underwear bottoms, the ghost output MUST be that bottom garment — not a bra."
        )
    elif "제품 1" in shot_label:
        lines.append(
            "PRODUCT SET (CRITICAL): This shot is for PRODUCT 1 (first product / upper row — often top/bra). "
            "The single reference defines the garment. Do NOT output Product 2 or the other coordinate piece."
        )
    return "\n".join(lines) if lines else ""


# 브라렛/스파게티 끈을 '어깨당 끈 두 줄·평행 이중'으로 잘못 생성하는 경우 완화
STRAP_STRUCTURE_EN = (
    "SHOULDER / SPAGHETTI STRAPS (HIGHEST PRIORITY): Infer strap count and layout ONLY from the uploaded product images. "
    "For a typical bralette or crop top with thin spaghetti straps, the garment has exactly ONE thin strap band per shoulder (left and right, mirror symmetry) — i.e. TWO strap lines total on the body, NOT four. "
    "ABSOLUTELY FORBIDDEN in the output: two parallel straps on the SAME shoulder; a strap that forks or splits into two lines at the shoulder; doubled/twin straps per side; any extra strap line not visible in the reference; "
    "strap shadows or highlights drawn so they read as a second strap. "
    "Each shoulder must show a SINGLE continuous strap from cup to shoulder top — never duplicate. "
    "If the flat-lay shows one narrow band per side, render one narrow band per side only."
)
STRAP_STRUCTURE_KO = (
    "어깨 끈(최우선): 제품 사진에 나온 그대로만. 가는 스파게티 끈·크롭은 보통 어깨당 끈 한 줄씩(좌·우 대칭), 몸에는 끈 두 줄이 전부다. "
    "한쪽 어깨에 끈이 평행하게 두 줄로 보이게 그리지 마. 어깨 꼭대기에서 끈이 갈라져 두 갈래로 보이게 하지 마. 그림자나 하이라이트가 두 번째 끈처럼 보이게 하지 마. "
    "제품이 어깨당 한 줄이면 출력도 어깨당 반드시 한 줄만."
)
STRAP_STRUCTURE_REMINDER_EN = (
    "STRAP SELF-CHECK: Count straps on the product image, then match that count on the model — one line per shoulder side unless the product clearly shows otherwise."
)

# 팬티/브리프 밑위가 하이라이즈로 늘어나는 경우 완화
BOTTOM_RISE_FIDELITY_EN = (
    "BOTTOM RISE / FRONT PANEL HEIGHT (HIGHEST PRIORITY FOR BRIEFS/PANTIES): "
    "Match the lower garment's rise EXACTLY from the uploaded product image — the vertical distance from crotch seam to waistband, "
    "and where the waistband sits on the body (low-hip / mid-rise / high-rise) must match the product cut, not a generic catalog default. "
    "FORBIDDEN: stretching the front panel taller, raising the waistband toward the navel when the product sits lower on the hips, "
    "or converting a low/mid-rise brief into a high-rise tummy-cover shape. "
    "Keep waistband width, leg-opening height, side-seam length, and front-panel proportion faithful to the product photo. "
    "If the flat-lay shows a shorter rise, the worn result must also read short/mid — do NOT invent extra fabric height above the hips."
)
BOTTOM_RISE_REMINDER_EN = (
    "RISE SELF-CHECK: Compare waistband placement and front-panel height to the product image — if the product is not high-rise, do not output high-rise."
)

# 고스트컷: 업로드에 없는 후크·몰드컵 등을 모델이 ‘일반 브라’로 보충하지 않도록
GHOST_REFERENCE_FIDELITY_EN = (
    "REFERENCE-ONLY CONSTRUCTION (HIGHEST PRIORITY): Reproduce hardware, lining, padding, and closures ONLY exactly as they appear in the uploaded product image(s). "
    "FORBIDDEN unless clearly visible in the reference: hook-and-eye rows, metal/plastic clasps, adjusters, extra seams that are not in the photo, molded foam cup shells, "
    "removable pad outlines, circular cup inserts, or thick push-up padding. "
    "If the reference shows a seamless / pull-on / bandeau-style band with no closure hardware, keep the back continuous and seamless — do NOT add hooks. "
    "If the reference shows no separate molded cups or inner caps, keep the interior flat, single-layer, or lightly lined as in the photo — do NOT add volumetric molded cups. "
    "Do NOT substitute a generic padded underwire bra look when the source is minimal or seamless."
)

# 슬림 계열 공통 — 마른 것과 앙상한 것을 구분한다.
# 치수만 줄이면 모델이 저체중·영양결핍 쪽으로 렌더링하므로 표면 상태를 따로 못박는다.
HEALTHY_SLIM_SURFACE_EN = (
    "TORSO SURFACE (CRITICAL — SLIM BUT HEALTHY): The torso reads smooth, evenly toned, and well-nourished. "
    "The abdomen is flat and softly toned with a natural surface, not hollow or concave. "
    "The collarbone is softly defined, never sharp or protruding. "
    "STRICTLY FORBIDDEN: visible rib lines or rib shadows, gaps or hollows between the ribs, "
    "a protruding sternum or breastbone, jutting hip bones or pelvic bones, a sunken or concave stomach, "
    "hollow cheeks, sharp shoulder blades, or any gaunt, undernourished, or emaciated appearance. "
    "This is a healthy professional fit model with a naturally lean build — lean, not underweight. "
)
HEALTHY_SLIM_SURFACE_KO = (
    "몸통 표면: 매끄럽고 균일하며 건강한 상태. 복부는 평평하되 자연스러운 탄력이 있고 움푹 꺼지지 않는다. "
    "쇄골은 은은하게만 드러나고 날카롭게 튀어나오지 않는다. "
    "갈비뼈 라인·갈비뼈 사이 그림자·튀어나온 흉골·튀어나온 골반뼈·움푹 꺼진 배·홀쭉한 볼은 절대 금지. "
    "마른 체형이지만 저체중이나 영양결핍으로 보이면 안 된다. "
)

# 볼륨(미드사이즈) 공통 — 상한선과 허리 정의가 없으면 플러스사이즈로 밀린다.
# 형용사보다 비율 숫자가 훨씬 강하게 작동하므로 W/H·B/W 비를 직접 못박는다.
HEALTHY_VOLUME_SURFACE_EN = (
    "WAIST DEFINITION (CRITICAL — THIS IS WHAT KEEPS IT MIDSIZE): "
    "waist-to-hip ratio approximately 0.76 and bust-to-waist ratio approximately 1.22. "
    "The waist must read clearly narrower than both the bust and the hip, producing a defined hourglass curve. "
    "Do NOT render a straight, undefined, column-shaped, or rectangular torso. "
    "TORSO SURFACE: firm, smooth, and evenly toned with natural skin tension. "
    "The abdomen is flat to softly rounded and does not project forward past the bust line. "
    "FORBIDDEN: sagging, rolls or folds at the waist while standing upright, abdominal overhang, "
    "or a soft shapeless mass without a visible waistline. "
    "SIZE CEILING (MANDATORY): this is a MIDSIZE fit model at US 12-14 / KR 88 — never larger. "
    "Do NOT exceed these measurements and do NOT render a plus-size (US 16+) or exaggerated body. "
    "Think of a standard midsize commercial fit model, not a plus-size specialty model. "
)
HEALTHY_VOLUME_SURFACE_KO = (
    "허리 정의(핵심): 허리/엉덩이 비 약 0.76, 가슴/허리 비 약 1.22. "
    "허리가 가슴과 엉덩이보다 확연히 좁아 뚜렷한 모래시계 곡선이 보여야 한다. "
    "일자형·기둥형·사각형 몸통은 금지. "
    "몸통 표면은 탄탄하고 매끄러우며 균일한 톤. 복부는 평평하거나 살짝 둥근 정도이고 가슴 라인보다 앞으로 나오지 않는다. "
    "처짐, 서 있을 때 생기는 허리 접힘, 복부 돌출, 허리선이 사라진 형태는 금지. "
    "상한(필수): US 12~14 / 한국 88 미드사이즈까지이며 그보다 커지면 안 된다. 플러스사이즈로 표현하지 마. "
)

# ── 체형(Body Type) 축 ────────────────────────────────────────
# 얼굴 프리셋(modelPreset)과 완전히 독립된 축.
# 같은 얼굴·포즈·배경·의상에서 체형만 바꿔 A/B 페어를 만드는 것이 목적.
BODY_TYPE_PRESETS = {
    "slim": {
        "label_ko": "슬림",
        "ko": (
            "체형: 슬림. 키 168cm, 어깨너비 38cm, 밑가슴 67cm, 가슴둘레 75cm(컵 차이 8cm, 70AA), "
            "허리 63cm, 엉덩이 88cm. 어깨선이 좁고 골반 라인이 곧게 떨어지는 마른 체형. "
            "가슴 볼륨이 거의 없어 옆에서 보면 평평하다. "
            f"{HEALTHY_SLIM_SURFACE_KO}"
            "브라 컵이 가슴에 평평하게 밀착되고 골이 지지 않으며, 옷은 몸에서 떨어져 세로로 흐른다."
        ),
        "en": (
            "BODY TYPE — SLIM (HIGHEST PRIORITY: this overrides any generic 'model build' wording elsewhere in this prompt): "
            "Measurements: height 168cm, shoulder 38cm, underbust 67cm, bust 75cm, waist 63cm, hip 88cm "
            "— cup differential 8cm (KR 70AA / US 32AA). "
            "Lean frame: narrow shoulder line, slender ribcage, "
            "visibly narrow waist, straight hip line, lean elongated arms and legs, "
            "hip width roughly equal to shoulder width. "
            "BUST (DEFINING TRAIT): minimal bust projection — the chest reads almost flat in profile, "
            "with a smooth continuous line from collarbone to underbust and no separation or shadow between the cups. "
            f"{HEALTHY_SLIM_SURFACE_EN}"
            "GARMENT BEHAVIOR (this is what actually defines the body — render the fabric result, not just the adjective): "
            "the bra cups lie flat against the chest with minimal fill and almost no forward projection; "
            "the underband is the dominant structure and stays level; there is no cleavage line and no cup shadow. "
            "Fabric hangs away from the torso with visible ease at the waist, soft vertical folds, "
            "no horizontal tension lines anywhere, shoulder seam sits at or slightly outside the natural shoulder point, "
            "side seam falls almost straight down. "
        ),
        "negative": (
            "Do NOT add bust volume, cup projection, cleavage, or a rounded chest. "
            "Do NOT add fullness at the waist or hip. Do NOT create horizontal stretch tension across the fabric. "
            "Do NOT substitute a standard B/C-cup catalog body — the flat bust line is the defining feature of this type. "
            "Do NOT render visible ribs, bone protrusion, or an underweight look while reducing bust volume. "
        ),
    },
    "slim_bust": {
        "label_ko": "슬림+볼륨컵",
        "ko": (
            "체형: 슬림 프레임 + 볼륨 컵. 키 168cm, 어깨너비 38cm, 밑가슴 67cm, "
            "가슴둘레 85cm(컵 차이 18cm, 70D), 허리 63cm, 엉덩이 88cm. "
            "골격은 슬림 체형과 완전히 동일하고 컵 볼륨만 다르다. "
            f"{HEALTHY_SLIM_SURFACE_KO}"
            "와이어와 중심부(고어)가 갈비뼈에 평평하게 밀착되고, 밑단 밴드가 수평을 유지하며, "
            "컵 윗단에 뜨는 부분이나 넘치는 부분이 없다. 밴드 아래로는 원단이 몸에서 떨어져 세로로 흐른다. "
            "허리와 엉덩이는 슬림과 동일하게 유지하고 몸통을 넓히지 마. 가슴을 강조하거나 과장하지 마."
        ),
        "en": (
            "BODY TYPE — SLIM FRAME WITH FULLER CUP (HIGHEST PRIORITY: this overrides any generic "
            "'model build' wording elsewhere in this prompt): "
            "Measurements: height 168cm, shoulder 38cm, underbust 67cm, bust 85cm, waist 63cm, hip 88cm "
            "— cup differential 18cm (KR 70D / US 32D). "
            "SKELETAL FRAME IS IDENTICAL TO THE SLIM TYPE: narrow shoulder line, slender ribcage, "
            "narrow waist, straight hip line, lean arms and legs. ONLY the bust cup volume differs. "
            f"{HEALTHY_SLIM_SURFACE_EN}"
            "GARMENT BEHAVIOR (this is what actually defines the body — render the bra fit result): "
            "the underwire and centre gore sit flat against the ribcage with full contact, "
            "the underband stays level and parallel to the floor all the way around, "
            "the cups are filled with no gaping at the upper edge and no overspill at the top or side, "
            "the side wing lies flat under the arm. "
            "Below the underband the fabric hangs away from the torso with visible ease at the waist, "
            "soft vertical folds, no horizontal tension. "
            "CRITICAL: Keep waist, hip, and shoulder measurements identical to the SLIM type — "
            "do NOT widen the torso to match the cup volume. "
        ),
        "negative": (
            "Do NOT emphasize, exaggerate, or centre the composition on cleavage. "
            "Do NOT render a push-up, lifted, or glamour-photography look. "
            "No suggestive pose, no low camera angle, no arched back, no arms pressing the bust inward. "
            "Do NOT widen the waist, hip, or shoulder. "
            "Keep this a neutral ecommerce fit-catalog shot focused on band level and cup fit. "
        ),
    },
    "volume": {
        "label_ko": "볼륨",
        "ko": (
            "체형: 볼륨(미드사이즈). 키 165cm, 어깨너비 41cm, 밑가슴 80cm, 가슴둘레 95cm(컵 차이 15cm, 85C), "
            "허리 78cm, 엉덩이 102cm(한국 88). 가슴과 힙에 볼륨이 있고 허리선이 짧은 부드러운 곡선 체형. "
            f"{HEALTHY_VOLUME_SURFACE_KO}"
            "옷은 몸 곡선을 따라가고 가슴·힙에 가로 방향 당김이 살짝 생기며, 허리 아래로 퍼진다. "
            "임의로 날씬하게 보정하지 마."
        ),
        "en": (
            "BODY TYPE — VOLUME / MIDSIZE (HIGHEST PRIORITY: this overrides any 'slender ribcage / narrow waist / lean' "
            "wording elsewhere in this prompt): "
            "Measurements: height 165cm, shoulder 41cm, underbust 80cm, bust 95cm, waist 78cm, hip 102cm "
            "— cup differential 15cm (KR 85C / US 38C, dress KR 88 / US 12-14). "
            "Soft rounded silhouette: wider bust and hip circumference, fuller upper arm, shorter waist line, "
            "hip width clearly exceeding shoulder width, outward-curving side seam. "
            f"{HEALTHY_VOLUME_SURFACE_EN}"
            "GARMENT BEHAVIOR (this is what actually defines the body — render the fabric result, not just the adjective): "
            "fabric follows the body contour with slight horizontal tension across bust and hip, "
            "the waistband follows the body contour with a soft waistline curve, fabric flares outward below the waist, "
            "underband and leg opening follow the garment edge with natural fabric compression. "
            "CRITICAL: Do NOT slim, idealize, or 'correct' the proportions back toward a standard runway body. "
            "This is a real midsize fit model — not an exaggerated plus-size caricature. "
        ),
        "negative": (
            "Do NOT render an exaggerated or cartoonish plus-size body, and do NOT go beyond midsize proportions. "
            "Do NOT narrow the waist or shrink the hip back toward a straight-size silhouette. "
            "Do NOT lose the waistline while adding volume — the hourglass definition must survive. "
        ),
    },
}
# 성인 명시 앵커. 언더웨어 + 상세 치수 조합에서 연령 모호성을 제거한다.
# 필터 우회가 아니라 명세를 정확히 하는 것 — 오검출(false positive)을 낮추는 목적.
ADULT_MODEL_ANCHOR_EN = (
    "ADULT PROFESSIONAL FIT MODEL (MANDATORY, NON-NEGOTIABLE): an adult woman in her mid-20s, "
    "a professional commercial fit model with mature adult facial features and adult body proportions. "
    "ADULT MARKERS THAT MUST READ CLEARLY REGARDLESS OF BUST VOLUME: fully developed adult bone structure "
    "with a defined jawline and mature cheekbones; adult stature with long fully-grown limbs "
    "(9-head editorial proportion, height 165-168cm); a clearly defined adult waist-to-hip curve; "
    "adult hands and adult skin texture. "
    "A smaller bust is a normal adult body type and must NEVER be rendered as youth, adolescence, or immaturity. "
    "FORBIDDEN: any adolescent, teenage, childlike, or age-ambiguous appearance; "
    "rounded childlike facial proportions; an undeveloped or prepubescent body; "
    "school or youth-coded styling, props, or setting. "
)
ADULT_MODEL_ANCHOR_KO = (
    "성인 여성 프로 피팅 모델(20대 중반). 성인의 이목구비와 성인 체형, 뚜렷한 턱선과 성숙한 광대, "
    "완전히 자란 긴 팔다리(9등신, 165~168cm), 성인의 허리-힙 곡선, 성인의 손과 피부 질감. "
    "가슴이 작은 것은 성인의 정상적인 체형이며, 어리거나 미성숙하게 표현해서는 절대 안 된다. "
    "청소년·아동·연령 모호한 인상, 둥근 아동형 얼굴 비율, 미성숙한 신체는 금지. "
)

# 안전 분류기 차단 시 1차 완화용 — 치수만 남기고 밀착/드레이프 서술 제거
BODY_TYPE_COMPACT = {
    "slim": (
        "BODY TYPE — SLIM: height 168cm, shoulder 38cm, underbust 67cm, bust 75cm, waist 63cm, hip 88cm (KR 70AA). "
        "Straight, lean silhouette with minimal bust projection — flat chest line, no cleavage. "
        "Smooth, evenly toned, healthy torso — no visible ribs, no bone protrusion, not underweight."
    ),
    "slim_bust": (
        "BODY TYPE — SLIM FRAME WITH FULLER CUP: height 168cm, shoulder 38cm, underbust 67cm, bust 85cm, "
        "waist 63cm, hip 88cm (KR 70D). Slim frame identical to the SLIM type; only cup volume differs. "
        "Smooth, evenly toned, healthy torso — no visible ribs, no bone protrusion, not underweight. "
        "Neutral fit-catalog framing, level underband, no cleavage emphasis."
    ),
    "volume": (
        "BODY TYPE — VOLUME / MIDSIZE: height 165cm, shoulder 41cm, underbust 80cm, bust 95cm, waist 78cm, hip 102cm (KR 85C). "
        "Bust and hip circumference clearly wider than shoulder width; waist-to-hip ratio 0.76 with a defined waistline. "
        "Midsize US 12-14 ceiling — not plus-size. Firm, evenly toned torso. Do not slim the proportions."
    ),
}

DEFAULT_BODY_TYPE = "slim"
_BODY_TYPE_ALIASES = {
    "s": "slim", "lean": "slim", "straight": "slim", "슬림": "slim",
    "v": "volume", "curvy": "volume", "midsize": "volume", "soft": "volume", "볼륨": "volume",
    "slimbust": "slim_bust", "slim-bust": "slim_bust", "sb": "slim_bust",
    "busty_slim": "slim_bust", "슬림볼륨컵": "slim_bust", "슬림+볼륨컵": "slim_bust",
}


def _resolve_body_type(body_type: Any) -> str:
    key = str(body_type or "").strip().lower()
    key = _BODY_TYPE_ALIASES.get(key, key)
    return key if key in BODY_TYPE_PRESETS else DEFAULT_BODY_TYPE


def _body_type_block(body_type: Any, gender: str = "female") -> str:
    """영문 체형 지시 블록. 남성 모델·고스트컷에는 주입하지 않는다."""
    if gender != "female":
        return ""
    preset = BODY_TYPE_PRESETS[_resolve_body_type(body_type)]
    return f"{ADULT_MODEL_ANCHOR_EN}{preset['en']}{preset['negative']}"


def _body_type_block_ko(body_type: Any) -> str:
    return f"{ADULT_MODEL_ANCHOR_KO}{BODY_TYPE_PRESETS[_resolve_body_type(body_type)]['ko']}"


def _body_type_block_compact(body_type: Any, gender: str = "female") -> str:
    """안전 재시도 1차용 축약 체형 블록 (치수 유지, 밀착 서술 제거)."""
    if gender != "female":
        return ""
    return f"{ADULT_MODEL_ANCHOR_EN}{BODY_TYPE_COMPACT[_resolve_body_type(body_type)]}"


def _body_type_change_instruction(body_type: Any) -> str:
    """슬림 컷 → 볼륨 컷 페어 생성용 (api/edit). 체형 외 변수는 전부 고정."""
    resolved = _resolve_body_type(body_type)
    preset = BODY_TYPE_PRESETS[resolved]
    return (
        "BODY TYPE CONVERSION (SINGLE-VARIABLE EDIT): Keep the EXACT same model identity, face, hairstyle, "
        "makeup, pose, camera angle, framing, crop, lighting, background plate, and garment design/color/pattern. "
        "Change ONLY the body proportions and the resulting fit of the garment. "
        f"{ADULT_MODEL_ANCHOR_EN}{preset['en']}{preset['negative']}"
        "The two images must be directly comparable as an A/B pair — nothing except the body may differ."
    )


DIRECT_MODEL_PROMPT_PURE = (    "이 디자인을 입고 있는 20대 초반 서양 여성 모델 이미지를 만들어줘 "
    "얼굴 인상은 맑고 청순한 분위기로, 부드럽고 또렷한 눈매, 자연스러운 일자형 눈썹, 작은 얼굴형, 깨끗한 피부톤, "
    "긴 브라운 헤어의 내추럴한 스타일을 유지해줘. "
    "머리부터 허벅지까지 자연스럽게 보이는 3/4컷으로 만들어줘. "  # 배경 지시는 background_setting에서 일원화
    "9등신 비율의 에디토리얼 실루엣으로."  # 체형은 bodyType 축에서 주입
)

DIRECT_MODEL_PROMPT_NEUTRAL = (
    "이 디자인을 입고 있는 20대 초반 서양 여성 모델 이미지를 만들어줘. "
    "세련되고 우아한 할리우드 뷰티 스타일의 서양 여성, 중앙 대칭 구도, 부드러운 턱선과 은은한 광대, "
    "매우 밝은 뉴트럴 웜 피부톤이지만 창백하거나 탁하지 않게, 맑고 건강한 혈색이 도는 피부. "
    "옅은 블루 그레이 아몬드형 눈, 연한 브라운의 곧고 자연스러운 눈썹, 가늘고 곧은 코와 부드럽게 둥근 코끝, "
    "긴 미디엄 체스트넛 브라운 생머리, 정확한 가운데 가르마, 양쪽 귀 뒤로 단정하게 넘긴 헤어스타일. "
    "얇은 베이스, 피치 블러시, 옅은 타우프 브라운 아이 메이크업의 미니멀한 클린 메이크업. "
    "입을 다문 차분하고 중립적인 표정, 사실적인 피부와 머리카락 디테일. "
    "머리부터 허벅지까지 자연스럽게 보이는 3/4컷으로 만들어줘. "  # 배경 지시는 background_setting에서 일원화
    "9등신 비율의 에디토리얼 실루엣으로."  # 체형은 bodyType 축에서 주입
)

# 하위 호환: 기존 코드/로그에서 DIRECT_MODEL_PROMPT 참조 시 기본(청순) 사용
DIRECT_MODEL_PROMPT = DIRECT_MODEL_PROMPT_PURE

MODEL_PRESET_PROMPTS = {
    "pure": DIRECT_MODEL_PROMPT_PURE,
    "neutral": DIRECT_MODEL_PROMPT_NEUTRAL,
}
DEFAULT_MODEL_PRESET = "pure"


def _resolve_model_preset_prompt(preset_id: Any) -> str:
    key = str(preset_id or "").strip().lower()
    return MODEL_PRESET_PROMPTS.get(key, MODEL_PRESET_PROMPTS[DEFAULT_MODEL_PRESET])

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 단일 사용자 환경 — 로그에만 고정 식별자 기록
_LOG_USER = {
    "username": "eblin",
    "name": "EBLIN",
    "email": "",
    "is_logged_in": False,
}

# ── Static files ─────────────────────────────────────────────
# HTML은 브라우저/CDN이 오래 캐시하면 옛 샷타입 목록이 계속 보일 수 있어 no-store 권장
_HTML_NO_CACHE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
}


def _index_html_response() -> FileResponse:
    return FileResponse("index.html", media_type="text/html", headers=_HTML_NO_CACHE_HEADERS)


if os.path.exists("assets"):
    app.mount("/assets", StaticFiles(directory="assets"), name="assets")

try:
    from usage_stats import register_usage_stats_routes
    register_usage_stats_routes(app)
except Exception as _stats_err:
    print(f"[STATS] Failed to register usage stats routes: {_stats_err}")


@app.get("/")
def index():
    return _index_html_response()


@app.get("/index.css")
def index_css():
    if os.path.exists("index.css"):
        return FileResponse(
            "index.css",
            media_type="text/css",
            headers=_HTML_NO_CACHE_HEADERS,
        )
    return JSONResponse(content={}, status_code=204)


@app.get("/{filename}")
def serve_root_files(filename: str):
    decoded = unquote(filename)
    # /logs/*, /api/* 는 전용 라우트가 처리 — catch-all이 가로채지 않음
    if decoded.split("/", 1)[0] in ("logs", "api"):
        raise HTTPException(status_code=404, detail="Not found")
    if decoded.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.ico', '.svg', '.webp')):
        if os.path.exists(decoded):
            return FileResponse(decoded)
        raise HTTPException(status_code=404, detail=f"Image not found: {decoded}")
    if os.path.exists("index.html"):
        return _index_html_response()
    raise HTTPException(status_code=404, detail="Not found")


# ── Helpers ──────────────────────────────────────────────────

def _parse_base64(data_url: str) -> dict:
    if ";base64," in data_url:
        header, data = data_url.split(";base64,", 1)
        mime = header.split(":", 1)[1] if ":" in header else "image/png"
        return {"mime_type": mime, "data": data}
    return {"mime_type": "image/png", "data": data_url}


def _collect_valid_product_data_urls(product_images: Any) -> list:
    out = []
    if not product_images:
        return out
    for img in product_images:
        if isinstance(img, str) and img.startswith("data:"):
            out.append(img)
    return out


def _collect_slot_images(design_slot_images: Any) -> list:
    """
    클라이언트가 보낸 슬롯 메타를 정규화:
    [{slot: 0~3, label: str, image: data_url}, ...]
    """
    out = []
    if not isinstance(design_slot_images, list):
        return out
    for item in design_slot_images:
        if not isinstance(item, dict):
            continue
        img = item.get("image")
        if not (isinstance(img, str) and img.startswith("data:")):
            continue
        try:
            slot = int(item.get("slot"))
        except (TypeError, ValueError):
            continue
        label = str(item.get("label") or f"slot-{slot}")
        name = str(item.get("name") or item.get("filename") or "").strip()
        entry = {"slot": slot, "label": label, "image": img}
        if name:
            entry["name"] = name
            entry["filename"] = name
        out.append(entry)
    out.sort(key=lambda x: x["slot"])
    return out


def _slot_context_block(shot_label: str, slot_images: list) -> str:
    if not slot_images:
        return ""
    lines = ["SLOT MAPPING (CLIENT-VERIFIED PRODUCT REFERENCES):"]
    for s in slot_images:
        lines.append(f"- slot {s['slot']}: {s['label']}")

    if "후면" in shot_label:
        lines.append("REAR SHOT PRIORITY: Prefer rear-detail evidence from back slots first (slot 1 for product 1, slot 3 for product 2) when available.")
    elif "측면" in shot_label:
        lines.append("SIDE SHOT PRIORITY: Balance front silhouette with side seam/wing continuity from all slots.")
    else:
        lines.append("FRONT SHOT PRIORITY: Prefer front slots (slot 0 for product 1, slot 2 for product 2) for neckline/cup/front panel details.")
    return "\n".join(lines)


def _genai_response_text_only(response: Any) -> str:
    chunks = []
    try:
        for cand in getattr(response, "candidates", None) or []:
            content = getattr(cand, "content", None)
            for part in getattr(content, "parts", None) or []:
                t = getattr(part, "text", None)
                if t:
                    chunks.append(str(t))
    except Exception:
        pass
    return "\n".join(chunks).strip()


def _analyze_product_cut_for_generation(
    client: Any,
    product_data_urls: list,
    shot_label: str,
    slot_context: str = "",
) -> Optional[str]:
    """
    업로드 제품컷을 비전 모델로 분석해, 이미지 생성 시 지켜야 할 디테일을 텍스트로 반환한다.
    실패 시 None (생성은 기존 로직으로 진행).
    """
    if not product_data_urls:
        return None
    analysis_parts = []
    for data_url in product_data_urls:
        parsed = _parse_base64(data_url)
        analysis_parts.append({"inline_data": {"data": parsed["data"], "mime_type": parsed["mime_type"]}})
    guide = f"""You are a technical fashion product analyst for downstream AI image generation.

The images above are user-uploaded PRODUCT CUTS (flat lay or product photos). They are NOT the final shot.

Write a factual analysis the image generator MUST follow. Do not invent details. If something is not clearly visible, say "not visible".

Use English with compact markdown bullets. Structure:

- **Garment & category**: type, style (e.g. bralette, hipster briefs).
- **Colors**: primary and accents (be specific: off-white, blush, etc.).
- **Fabric & finish**: matte/glossy, knit/woven/lace/mesh, texture notes.
- **Straps / waist / leg openings**: layout, count per side, width, routing (only if visible).
- **Bottom rise (CRITICAL if briefs/panties/bottoms are visible)**: state low-rise / mid-rise / high-rise from the photo; note waistband position relative to hip; front-panel height from crotch to waistband (short/medium/tall); side-seam length. Explicitly forbid inventing a taller rise than the photo.
- **Hardware & closures**: hooks, rings, adjusters — list only if clearly seen; otherwise state "none visible".
- **Cup / front construction**: seamless, seams, darts, molded vs flat — only what the photo shows.
- **Notable details**: lace pattern, logos, binding, elastic exposure, stitching.
- **MUST match in output** (5–8 short imperative lines) — include rise/waistband height when bottoms are present.
- **MUST NOT add** (e.g. if no hooks/molded cups in photo, forbid adding them; if not high-rise, forbid high-rise).

Downstream shot label (context): {shot_label}
{slot_context}

Max length ~900 words. No preamble, no closing pleasantries."""

    analysis_parts.append({"text": guide})

    try:
        response = client.models.generate_content(
            model=GEMINI_PRODUCT_ANALYSIS_MODEL,
            contents={"parts": analysis_parts},
            config=genai.types.GenerateContentConfig(
                temperature=0.15,
                max_output_tokens=2048,
            ),
        )
        text = _genai_response_text_only(response)
        if not text:
            print("[PRODUCT_ANALYSIS] Empty text response")
            return None
        if len(text) > PRODUCT_ANALYSIS_MAX_CHARS:
            text = text[: PRODUCT_ANALYSIS_MAX_CHARS - 3] + "..."
        print(f"[PRODUCT_ANALYSIS] OK | model={GEMINI_PRODUCT_ANALYSIS_MODEL} | chars={len(text)}")
        return text
    except Exception as ex:
        print(f"[PRODUCT_ANALYSIS] Failed: {ex}")
        return None


def _load_local_image_as_data_url(filename: str) -> Optional[str]:
    path = os.path.join(os.path.dirname(__file__) or ".", filename)
    if not os.path.exists(path):
        # 조용히 None을 반환하면 배경 지시가 통째로 빠진 채 생성돼 매번 톤이 달라진다.
        print(f"[BACKGROUND] ⚠️  MISSING FILE: {path} — 배경 플레이트 없이 생성됩니다")
        return None
    try:
        with open(path, "rb") as f:
            raw = f.read()
        ext = filename.rsplit(".", 1)[-1].lower()
        mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp"}.get(ext, "image/png")
        b64 = base64.b64encode(raw).decode("utf-8")
        return f"data:{mime};base64,{b64}"
    except Exception as err:
        print(f"[BACKGROUND] Failed to load {filename}: {err}")
        return None


_BG_PROFILE_CACHE: Optional[Dict[str, Any]] = None


def _background_plate_profile(filename: str = DEFAULT_BACKGROUND_FILE) -> Dict[str, Any]:
    """background.png에서 실제 배경색을 측정한다.

    "LAST provided image를 따르라"는 서수 지시는 이미지 모델이 안정적으로
    지키지 못한다. 측정한 색을 HEX로 직접 박아넣으면 이미지 첨부 순서나
    모델의 주의와 무관하게 결정적으로 동작한다.
    """
    global _BG_PROFILE_CACHE
    if _BG_PROFILE_CACHE is not None:
        return _BG_PROFILE_CACHE

    profile: Dict[str, Any] = {"available": False, "filename": filename}
    path = os.path.join(os.path.dirname(__file__) or ".", filename)
    if not os.path.exists(path):
        profile["error"] = f"file not found: {path}"
        _BG_PROFILE_CACHE = profile
        print(f"[BACKGROUND] ⚠️  프로파일 실패 — {profile['error']}")
        return profile

    try:
        from PIL import Image, ImageStat

        im = Image.open(path).convert("RGB")
        w, h = im.size

        def _median_hex(box) -> tuple:
            region = im.crop(box)
            med = ImageStat.Stat(region).median
            r, g, b = (int(round(c)) for c in med[:3])
            return (r, g, b), f"#{r:02X}{g:02X}{b:02X}"

        # 상단(벽) / 하단(바닥) 두 구간을 따로 측정. 좌우 가장자리 위주로
        # 잘라 인물이 서는 중앙 영역의 영향을 줄인다.
        edge = max(1, int(w * 0.12))
        (tr, tg, tb), top_hex = _median_hex((0, 0, w, max(1, int(h * 0.22))))
        (br, bg_, bb), bottom_hex = _median_hex((0, int(h * 0.80), w, h))
        (lr, lg, lb), _ = _median_hex((0, 0, edge, h))

        lum = round((tr + tg + tb) / 3)
        diff = tr - tb
        if diff >= 5:
            temp = "warm, slightly yellow-tinted off-white"
        elif diff <= -5:
            temp = "cool, slightly blue-tinted gray"
        else:
            temp = "neutral gray"

        profile.update({
            "available": True,
            "size": [w, h],
            "upper_hex": top_hex,
            "lower_hex": bottom_hex,
            "upper_rgb": [tr, tg, tb],
            "lower_rgb": [br, bg_, bb],
            "edge_rgb": [lr, lg, lb],
            "luminance": lum,
            "temperature": temp,
            "uniform": abs(tr - br) <= 6 and abs(tg - bg_) <= 6 and abs(tb - bb) <= 6,
        })
        print(
            f"[BACKGROUND] Plate profile | upper={top_hex} lower={bottom_hex} "
            f"lum={lum} tone={temp} uniform={profile['uniform']}"
        )
    except Exception as err:
        profile["error"] = f"{type(err).__name__}: {err}"
        print(f"[BACKGROUND] ⚠️  프로파일 실패 — {profile['error']}")

    _BG_PROFILE_CACHE = profile
    return profile


def _background_color_directive() -> str:
    """측정된 배경색을 프롬프트에 넣을 결정적 지시문으로 변환."""
    p = _background_plate_profile()
    if not p.get("available"):
        return ""
    if p.get("uniform"):
        body = (
            f"The backdrop color is EXACTLY {p['upper_hex']} "
            f"({p['temperature']}, luminance {p['luminance']}/255), flat and uniform across the entire frame."
        )
    else:
        body = (
            f"The upper wall area is EXACTLY {p['upper_hex']} and the lower floor area is EXACTLY {p['lower_hex']} "
            f"({p['temperature']}, upper luminance {p['luminance']}/255), with a smooth continuous transition between them."
        )
    return (
        " BACKDROP COLOR (MEASURED FROM THE PLATE — MATCH THESE EXACT VALUES): "
        + body
        + " Do NOT shift the backdrop warmer, cooler, brighter, or darker than these values. "
        "The backdrop must read as a soft off-white that is visibly DARKER than pure white — "
        "never #FFFFFF, never a blown-out or brighter off-white, never a cool blue-gray, never a saturated beige. "
        "This colour specification overrides any other backdrop wording anywhere in this prompt."
    )


def _gemini_enum_name(val: Any) -> str:
    if val is None:
        return ""
    name = getattr(val, "name", None)
    if isinstance(name, str) and name:
        return name
    return str(val)


def _extract_first_inline_image_data_url(response: Any) -> Optional[str]:
    """모든 candidate·part를 순회해 첫 inline 이미지를 찾는다(첫 후보만 보면 놓치는 케이스 방지)."""
    for cand in getattr(response, "candidates", None) or []:
        content = getattr(cand, "content", None)
        if not content:
            continue
        for part in getattr(content, "parts", None) or []:
            inline_data = getattr(part, "inline_data", None)
            if not inline_data:
                continue
            raw = getattr(inline_data, "data", None)
            if not raw:
                continue
            mime = getattr(inline_data, "mime_type", None) or "image/png"
            if isinstance(raw, bytes):
                raw = base64.b64encode(raw).decode("utf-8")
            return f"data:{mime};base64,{raw}"
    return None


def _summarize_gemini_missing_image(response: Any) -> str:
    """이미지 미반환 시 원인 추정용 짧은 요약(클라이언트 alert·로그용)."""
    bits: list[str] = []
    pf = getattr(response, "prompt_feedback", None)
    if pf is not None:
        br = getattr(pf, "block_reason", None)
        if br is not None:
            bits.append(f"prompt_block={_gemini_enum_name(br)}")
    cands = getattr(response, "candidates", None) or []
    if not cands:
        bits.append("no_candidates")
        return ",".join(bits) if bits else "empty_response"
    for i, cand in enumerate(cands[:4]):
        fr = getattr(cand, "finish_reason", None)
        if fr is not None:
            bits.append(f"finish{i}={_gemini_enum_name(fr)}")
        content = getattr(cand, "content", None)
        if content is None:
            bits.append(f"c{i}_no_content")
            continue
        parts = getattr(content, "parts", None) or []
        if not parts:
            bits.append(f"c{i}_empty_parts")
            continue
        kinds = []
        for p in parts:
            if getattr(p, "inline_data", None) and getattr(getattr(p, "inline_data", None), "data", None):
                kinds.append("img")
            elif getattr(p, "text", None):
                kinds.append("txt")
            else:
                kinds.append("?")
        bits.append(f"c{i}_parts={'+'.join(kinds) or 'none'}")
    return ",".join(bits)


def _log_gemini_response_debug(response: Any, max_candidates: int = 3) -> None:
    """Best-effort debug logging when Gemini returns no image part."""
    try:
        pf = getattr(response, "prompt_feedback", None)
        if pf is not None:
            br = getattr(pf, "block_reason", None)
            print(f"[GENERATE][DEBUG] prompt_feedback block_reason={br}")
        candidates = getattr(response, "candidates", None) or []
        print(f"[GENERATE][DEBUG] candidate_count={len(candidates)}")
        for idx, candidate in enumerate(candidates[:max_candidates]):
            finish_reason = getattr(candidate, "finish_reason", None)
            content = getattr(candidate, "content", None)
            parts = getattr(content, "parts", None) or []
            part_kinds = []
            text_snippets = []

            for part in parts:
                inline_data = getattr(part, "inline_data", None)
                text_value = getattr(part, "text", None)
                if inline_data and getattr(inline_data, "data", None):
                    mime = getattr(inline_data, "mime_type", "unknown")
                    part_kinds.append(f"inline_data:{mime}")
                elif text_value:
                    cleaned = " ".join(str(text_value).split())
                    part_kinds.append("text")
                    if cleaned:
                        text_snippets.append(cleaned[:240])
                else:
                    part_kinds.append(type(part).__name__)

            print(
                f"[GENERATE][DEBUG] candidate[{idx}] finish_reason={finish_reason} "
                f"parts={part_kinds if part_kinds else '[]'}"
            )
            if text_snippets:
                print(f"[GENERATE][DEBUG] candidate[{idx}] text={text_snippets[0]}")
    except Exception as debug_err:
        print(f"[GENERATE][DEBUG] Failed to inspect Gemini response: {debug_err}")


def _resolve_image_size(payload_size: Any) -> str:
    """Default to 2K, allow explicit size per request."""
    if not payload_size:
        return "2K"
    try:
        v = str(payload_size).strip().upper()
    except Exception:
        return "2K"
    return v if v in {"1K", "2K", "4K"} else "2K"


def _image_size_retry_chain(request_size: str) -> list[str]:
    order = ["4K", "2K", "1K"]
    base = request_size if request_size in order else "2K"
    start = order.index(base)
    return order[start:]


def _is_retryable_gemini_error(err: Exception) -> bool:
    status_code = getattr(err, "status_code", None)
    if status_code in (429, 500, 502, 503, 504):
        return True
    msg = str(err).upper()
    retry_signals = ("UNAVAILABLE", "DEADLINE", "TIMEOUT", "RESOURCE_EXHAUSTED", "INTERNAL")
    return any(s in msg for s in retry_signals)


def _call_gemini_image_with_retry(
    client: Any,
    model: str,
    parts: list,
    image_size: str,
    *,
    log_tag: str,
) -> tuple[Any, str, int]:
    size_chain = _image_size_retry_chain(image_size)
    max_attempts = max(1, min(GEMINI_IMAGE_MAX_RETRIES, len(size_chain)))
    last_err: Optional[Exception] = None

    for attempt in range(1, max_attempts + 1):
        size_try = size_chain[attempt - 1]
        try:
            if attempt > 1:
                print(f"[{log_tag}] Retry attempt {attempt}/{max_attempts} with image_size={size_try}")
            response = client.models.generate_content(
                model=model,
                contents={"parts": parts},
                config=genai.types.GenerateContentConfig(
                    response_modalities=["IMAGE", "TEXT"],
                    image_config=genai.types.ImageConfig(
                        aspect_ratio="3:4",
                        image_size=size_try,
                    ),
                ),
            )
            return response, size_try, attempt
        except Exception as ex:
            last_err = ex
            retryable = _is_retryable_gemini_error(ex)
            print(
                f"[{log_tag}] API call failed at attempt {attempt}/{max_attempts} "
                f"(image_size={size_try}, retryable={retryable}): {ex}"
            )
            if (not retryable) or attempt >= max_attempts:
                raise
            time.sleep(min(1.5 * attempt, 4.0))

    if last_err:
        raise last_err
    raise RuntimeError("Gemini image call failed without explicit error.")


# 체형 × 샷별 안전 차단 통계 (프로세스 메모리, /api/safety-stats로 조회)
SAFETY_STATS: Dict[str, int] = {}
_SAFETY_STATS_LOCK = threading.Lock()


def _record_safety_event(event: str, shot_label: str, body_type: Any) -> None:
    key = f"{event}|{shot_label}|{_resolve_body_type(body_type)}"
    with _SAFETY_STATS_LOCK:
        SAFETY_STATS[key] = SAFETY_STATS.get(key, 0) + 1
    print(f"[SAFETY] {event} | shot={shot_label} | body={_resolve_body_type(body_type)}")


def _needs_policy_safe_retry(shot_label: str, hint: str) -> bool:
    if "IMAGE_SAFETY" not in (hint or ""):
        return False
    if _is_ghost_product_shot(shot_label):
        return False
    return shot_label in {"3/4컷", "상반신", "상반신 측면", "상반신 후면", "하반신"}


def _extract_inline_media_parts(parts: list) -> list:
    media = []
    for p in parts or []:
        if isinstance(p, dict) and "inline_data" in p:
            media.append(p)
    return media


def _safe_retry_instruction_for_shot(
    shot_label: str,
    body_type: Any = None,
    tier: int = 2,
    gender: str = "female",
    has_background: bool = False,
) -> str:
    """tier 1: 체형(치수)은 유지한 채 완화. tier 2: 체형 블록 완전 제거."""
    framing = {
        "3/4컷": "Frame from head to upper thigh. Neutral standing catalog pose.",
        "상반신": "Frame from head to below waist. Neutral upper-body catalog pose.",
        "상반신 측면": "Frame from head to below waist. Left-facing side-angle, neutral pose.",
        "상반신 후면": "Frame from head to below waist. Back view, shoulders level, arms relaxed.",
        "하반신": "Frame around lower body only in a neutral product-detail composition.",
    }.get(shot_label, "Use a modest ecommerce fashion framing.")
    # 재시도에서도 배경 플레이트 고정을 유지해야 한다.
    # 이 지시가 빠지면 재시도된 컷만 배경 톤이 튄다.
    plate_lock = (
        " BACKGROUND PLATE (MANDATORY): The LAST provided image is the studio backdrop. "
        "Match its exact tone, color temperature, and brightness across the entire frame. "
        "Do NOT invent a warmer cream, cooler blue-gray, or brighter pure-white backdrop."
        + _background_color_directive()
        if has_background
        else ""
    )
    base = (
        "STRICT SAFE RETRY: Generate a neutral ecommerce fashion catalog image. "
        f"{ADULT_MODEL_ANCHOR_EN}"
        "Keep styling modest and non-suggestive. No transparent exposure. "
        "No provocative pose. Preserve the same model identity and garment details from references. "
        f"{framing}{plate_lock}"
    )
    if tier <= 1 and body_type:
        compact = _body_type_block_compact(body_type, gender)
        if compact:
            return f"{base} {compact}"
    return base


def _resolve_model_gender(payload_gender=None) -> str:
    if payload_gender and payload_gender in ("male", "female"):
        return payload_gender
    return "female"


def _build_camera_prompt(shot_label: str, gender: str = "female") -> str:
    rear_hair_rule = (
        "HAIR (CRITICAL): Keep a masculine back silhouette. Hair should remain short/neutral and must NOT be styled forward over both shoulders."
        if gender == "male"
        else (
            "HAIR (CRITICAL): This is a FEMALE model. The source image shows long hair — you MUST preserve it. "
            "Keep the feminine long-hair silhouette visible from the back. Hair must stay OUTSIDE the hood and fall naturally behind/around shoulders. "
            "Do NOT replace with short or male-style hair. Do NOT tie into a bun/ponytail unless explicitly requested. "
            "The back-of-head hair length and style must match the long hair visible in the source."
        )
    )
    hood_hair_rule = (
        "HAIR (CRITICAL): Keep a masculine short/neutral hairstyle. Hair should stay above or around neck length and must NOT fall long over the shoulders. Keep hair OUTSIDE the hood and do NOT tuck it into the hood."
        if gender == "male"
        else "HAIR (CRITICAL): Keep hair OUTSIDE the hood. Do NOT tuck hair into the hood; let hair fall naturally around/over the shoulders."
    )
    female_hand_rule = (
        "FEMALE HAND AESTHETIC (CRITICAL): Hands should look refined and feminine — slim fingers, soft knuckles, smooth skin, minimal visible veins/tendons, and no bulky/masculine hand structure."
        if gender == "female"
        else ""
    )
    mapping = {
        "전신(정면)": f"Full body length shot, directly front view, standing straight and looking at the camera. {hood_hair_rule} {female_hand_rule} The entire model from head to toe must be visible.",
        "3/4컷": "Three-quarter studio fashion shot. Frame from the top of the head down to the upper-to-mid thigh so the image reads clearly longer than an upper-body crop. The full head and entire face must remain completely visible inside the frame. HEAD SCALE (CRITICAL): The head must read editorially SMALL — noticeably narrower than shoulder width and clearly smaller than a beauty portrait or selfie proportion; the torso and shoulders should visually outweigh the head. Keep a little extra breathing room above the head and around the shoulders so the composition feels like a lookbook frame, not a face close-up, while the torso still reads longer than the head height. Keep the torso mostly front-facing and centered like a clean ecommerce studio image. Focus on the upper-body garment fit, neckline, bust structure, straps, waistline transition, and the overall silhouette through the upper thigh. SHOULDER STRAPS: If the product has thin spaghetti straps, render exactly one strap line per shoulder as in the product — never two parallel straps on the same shoulder. Keep the shoulders relaxed and the pose natural. DO NOT crop at the waist. DO NOT show knees, calves, or feet.",
        "상반신": "Upper body medium shot. Frame from the top of the head to slightly below the waist, keeping enough breathing room above the head so the face does NOT dominate the composition. The visible torso and shoulder span should read larger than the head. Keep the torso mostly front-facing and centered like a clean studio ecommerce image. Focus on the upper-body garment fit, neckline, bust structure, straps, and fabric texture. Keep the shoulders relaxed and the pose natural. DO NOT show thighs, knees, or feet.",
        "상반신 측면": "Upper-body side-angle ecommerce studio shot. Face and torso point LEFT; camera sees the model's RIGHT side. Keep a near-profile 3/4 side angle (not mirrored, not flat 90 profile). Frame from head to below waist, with enough headroom so face does not dominate. Keep posture neutral, shoulders relaxed, arms natural. Focus on neckline, straps, underband, side seam, waist transition, and fabric texture. Keep result brand-safe and non-suggestive. No transparent exposure. Do not show thighs, knees, calves, or feet.",
        "상반신 후면": f"Upper-body back-view ecommerce studio shot. Rotate 180° so upper back faces camera. {rear_hair_rule} Frame from head to below waist only. Keep shoulders level, arms relaxed down sides, torso centered. Focus on back neckline, strap placement, back band curve, side-back fit, waist transition, and fabric texture. Keep result brand-safe and non-suggestive. No transparent exposure. Do not show thighs, knees, calves, or feet.",
        "하반신": "Lower-body beauty/product close-up shot inspired by ecommerce underwear-detail framing. Crop tightly from just below the navel or low waist area down to the upper-to-mid thigh. Keep the torso mostly front-facing and centered with the pelvis square to camera. The lower garment must dominate the frame, clearly showing waistband, front panel, leg opening, side panel, and fabric texture. Let both hands fall naturally along the outer thighs so part of the fingers/hands may enter the frame near the sides, but do NOT make the hands the focus. ABSOLUTELY DO NOT show the full chest, full face, knees, calves, or feet.",
        "제품 1 앞면 고스트컷": "Ecommerce invisible mannequin (ghost mannequin) product shot of the garment only — DIRECT HEAD-ON FRONT VIEW (eye-level, camera perpendicular to the front plane). Symmetrical framing: center gore centered, both cups equal in apparent size, straps rising evenly. This is a straight catalog front — NOT a three-quarter oblique angle. Show natural 3D hollow volume inside the cups and believable strap curve. Absolutely NO human model, NO skin, NO face, NO hair, NO hands, NO limbs. Clean seamless pure white (#FFFFFF) background only; soft diffused studio lighting with gentle modeling shadows (no harsh silhouette). Sharp fabric detail: straps, edges, lace, seams, band texture. Professional catalog quality.",
        "제품 1 뒷면 고스트컷": (
            "Ecommerce invisible mannequin (ghost mannequin) product shot — FLOATING REAR THREE-QUARTER (premium catalog back). "
            "CAMERA: Behind the garment, slightly off-center (rear ~3/4): show the full back band span plus a bit of the outer cup curve on one side — like a soft rear diagonal, NOT a front view and NOT a flat 90° side profile. "
            "FLOATING LOOK (MANDATORY): Garment suspended in clean white space — NO floor, NO table, NO mannequin stand, NO heavy contact shadow. "
            "Straps arch naturally upward/outward in space; the piece holds inflated 3D hollow volume (invisible mannequin) with believable interior depth visible at cup openings. "
            "Lighting: soft, even, subtle shadows only in cup-to-band folds for shape — not harsh. "
            "Match reference construction — do NOT add hooks, sliders, or molded pads if absent. NO human model/skin. Pure white #FFFFFF."
        ),
        "제품 2 앞면 고스트컷": "Ecommerce invisible mannequin (ghost mannequin) product shot of the garment only — DIRECT HEAD-ON FRONT VIEW (eye-level, camera perpendicular to the front plane). Symmetrical framing: center gore centered, both cups equal in apparent size, straps rising evenly. This is a straight catalog front — NOT a three-quarter oblique angle. Show natural 3D hollow volume inside the cups and believable strap curve. Absolutely NO human model, NO skin, NO face, NO hair, NO hands, NO limbs. Clean seamless pure white (#FFFFFF) background only; soft diffused studio lighting with gentle modeling shadows (no harsh silhouette). Sharp fabric detail: straps, edges, lace, seams, band texture. Professional catalog quality.",
        "제품 2 뒷면 고스트컷": (
            "Ecommerce invisible mannequin product shot — STRAIGHT-ON REAR for bottoms + FLOATING. "
            "Camera centered behind, optical axis perpendicular to back/waistband plane; symmetric wings. "
            "FLOATING (MANDATORY): suspended in white space — no floor/table/stand; soft natural drape volume; minimal contact shadow. "
            "Match reference only — no invented hardware. NO human model/skin. Pure white #FFFFFF; soft even light."
        ),
        "제품 1 측면 고스트컷": (
            "Ecommerce invisible mannequin product shot — FRONT-SIDE THREE-QUARTER diagonal from the front (NOT a rear / back-facing shot). "
            "CAMERA POSITION (CRITICAL): Stay in the FRONT hemisphere only — e.g. front-left or front-right diagonal ~30–45° from straight front. "
            "The garment's FRONT (neckline, gore, both cups) must face mostly toward camera: one cup reads fuller and more frontal, the other cup recedes in perspective; the side wing/armhole edge on the far side shows depth. "
            "FORBIDDEN: any view where the back band or hook area is the hero plane; camera behind the garment; rear-quarter / back-oblique; pure 90° side profile with no frontal cup read. "
            "Ghost volume: a subtle sense of hollow interior may show through the upper neckline opening from this FRONT diagonal — NOT by looking into the back from behind. "
            "Slight eye-level or gentle high-angle is OK. Match reference construction only — no invented hooks, pads, or molded cups. "
            "NO human model/skin. Pure white #FFFFFF; soft directional light from front-side for depth."
        ),
        "제품 2 측면 고스트컷": (
            "Ecommerce invisible mannequin product shot — FRONT-SIDE THREE-QUARTER for bottoms (NOT rear). "
            "CAMERA in FRONT hemisphere only — front-left or front-right diagonal ~30–45°. "
            "FRONT of garment dominates (waistband, front panel, leg openings); one side hip/panel recedes in perspective. "
            "FORBIDDEN: back-of-garment as main subject, camera behind, rear oblique, or flat 90° side only. "
            "Match reference only. NO human model/skin. Pure white #FFFFFF; soft front-side light."
        ),
    }
    return mapping.get(shot_label, "Full body front facing fashion photograph.")


def _build_body_proportion_prompt(
    shot_label: str,
    gender: str = "female",
    body_type: Any = DEFAULT_BODY_TYPE,
) -> str:
    """샷 타입 + 성별 + 체형(slim/volume) 기반 신체 비율 가이드."""
    male_build = (
        "MALE MODEL BUILD (CRITICAL): The model must have broad, well-defined shoulders — "
        "shoulder width should be approximately 2.5 to 3 times the head width, creating a strong V-shaped upper body silhouette. "
        "The chest should be wide and the waist relatively narrow. "
        "Do NOT generate narrow or sloping shoulders. The broad-shouldered frame is essential for a masculine fashion-model look. "
        "MALE LEG PROPORTION (CRITICAL): In 9-head fashion canon, legs (crotch to floor) must equal approximately 4.5 head heights — "
        "clearly longer than the torso. The waist-to-floor visible length must exceed head-to-waist. "
        "Do NOT generate short legs, stubby proportions, or a long-torso look. "
        "The leg line from waistband down should dominate the full-body silhouette. "
        "VISUAL LEG ELONGATION (CRITICAL): Even when the top is long/oversized, the visible leg segment (from the bottom hem down to the feet) "
        "must appear elongated and elegant — never compressed or top-heavy. Avoid silhouettes where the upper body visually outweighs the legs. "
        "The lower leg from knee to ankle to foot should read as long and fashion-model-like."
    ) if gender == "male" else ""
    if shot_label in GHOST_PRODUCT_SHOT_LABELS:
        return ""

    # 체형 무관 공통 규칙(머리 크기·목·프레이밍)과 체형별 규칙을 분리.
    # 공통 블록에는 slim/volume 중 한쪽으로 기우는 표현(narrow waist, lean 등)을 넣지 않는다.
    female_build = (
        "FEMALE MODEL BUILD (CRITICAL): The model must have an elongated editorial fashion-model silhouette "
        "with a noticeably small head and face relative to the body, a long neck, and a refined shoulder line. "
        "HEAD-TO-BODY RATIO (HIGHEST PRIORITY): Head height should approximate ~1/8.5–1/9 of total visible body height in the frame (9-head editorial canon), NOT a large head typical of beauty ads or phone selfies. Head width must read clearly narrower than shoulder width. "
        "The head should read editorially small compared with the shoulder span and upper torso, not beauty-close-up proportion. "
        "The torso should read long and elegant rather than compact. "
        "Avoid oversized heads, large-face proportions, short necks, or short torsos. "
        f"{_body_type_block(body_type, gender)}"
    ) if gender == "female" else ""

    if shot_label.startswith("전신"):
        return (
            "BODY PROPORTIONS (IMPORTANT): The model MUST have a 9-head fashion canon proportion — "
            "the total height of the body equals 9 times the head height, as used in professional fashion illustration. "
            "HEAD SIZE (for elongated look): The head should be slightly smaller than average — approximately 1/9 of total body height — "
            "creating a more elongated, editorial silhouette. Keep the same facial features and identity; only the head-to-body scale adjusts. "
            "This means an elongated, fashion-model silhouette with very long legs occupying over 50% of total body height. "
            "The torso should read proportionally shorter relative to the legs, creating an elegant, editorial look. "
            "Think of high-fashion lookbook photography or fashion illustration proportions — NOT average human anatomy. "
            f"{female_build}"
            f"{male_build}"
            "FRAMING GUIDE: The model should fill approximately 85–90% of the frame height, "
            "with a small margin of ~5% above the head and ~5–10% below the feet. "
            "Do NOT generate a 6-head or 7-head proportion typical of average humans. "
            "Do NOT distort or compress body proportions. The overall silhouette must look like a tall, elegant fashion model."
        )
    elif shot_label == "3/4컷":
        return (
            "BODY PROPORTIONS (IMPORTANT): The model must keep elegant fashion-model proportions with a smaller-than-average head scale, long neck, refined shoulders, and a well-defined waist-to-hip transition appropriate to the specified body type. "
            f"{female_build}"
            f"{male_build}"
            "FRAMING GUIDE: Leave roughly 8–10% margin above the head. The visible head height should stay modest relative to the frame, and the torso should visually dominate over the face. The frame must extend clearly below the hips and end around the upper-to-mid thigh. "
            "Do NOT crop at the waist or high hip. Do NOT distort shoulder width, torso length, hip placement, or upper-leg length."
        )
    elif shot_label == "상반신 후면":
        return (
            "BODY PROPORTIONS (IMPORTANT): Keep elegant fashion-model upper-body proportions with a smaller-than-average head scale, long neck, and refined shoulders. "
            f"{female_build}"
            f"{male_build}"
            "FRAMING GUIDE: Leave roughly 8–10% margin above the head. The visible head height should stay modest relative to the frame, and the back silhouette should visually dominate over the head. "
            "Frame from head to slightly below waist only; do NOT include thighs or hip-focused lower-body area. "
            "Do NOT distort shoulder width, neck length, or torso proportions."
        )
    elif shot_label.startswith("상반신"):
        return (
            "BODY PROPORTIONS (IMPORTANT): The model must have natural, well-proportioned upper body anatomy "
            "consistent with a tall fashion model. The head and face should read clearly smaller than average relative to the shoulders and torso, and should not dominate the frame. Shoulders, neck, and torso should appear elegant and elongated. "
            f"{female_build}"
            f"{male_build}"
            "FRAMING GUIDE: Leave roughly 8–10% margin above the head. Keep enough space around the head and shoulders so the visible torso mass clearly outweighs the face. The frame should end slightly below the waist. "
            "Do NOT distort shoulder width, neck length, or torso proportions."
        )
    elif shot_label == "하반신":
        return (
            "BODY PROPORTIONS (IMPORTANT): The legs and lower body must have elongated, fashion-model proportions. "
            "The legs should appear long and elegant, consistent with a 9-head fashion canon silhouette. "
            "Do NOT compress or shorten the leg length."
        )
    return ""


def _build_transform_instruction(shot_label: str, gender: str = "female") -> str:
    """PICasso-style: transform the front shot into a different angle/crop."""
    rear_hair_rule = (
        "HAIR (CRITICAL): Keep a masculine back silhouette. Hair should remain short/neutral and must NOT be styled forward over both shoulders. "
        if gender == "male"
        else (
            "HAIR (CRITICAL): This is a FEMALE model. The source image shows long hair — you MUST preserve it in the back view. "
            "Keep the feminine long-hair silhouette visible from behind. Hair must stay OUTSIDE the hood and fall naturally behind/around shoulders. "
            "Do NOT replace with short or male-style hair. Do NOT tie into a bun/ponytail unless explicitly requested. "
            "The back-of-head hair length and style must match the long hair visible in the source."
        )
    )
    female_hand_rule = (
        "FEMALE HAND AESTHETIC (CRITICAL): Hands should look refined and feminine — slim fingers, soft knuckles, smooth skin, minimal visible veins/tendons, and no bulky/masculine hand structure. "
        if gender == "female"
        else ""
    )
    mapping = {
        "상반신 측면": (
            "CROP AND REFRAME this image into an UPPER-BODY SIDE-ANGLE ECOMMERCE STUDIO SHOT. "
            "Frame from top of head to slightly below waist only; do not show thighs, knees, calves, or feet. "
            "FACING DIRECTION: model points LEFT; camera sees RIGHT side (no mirroring). "
            "Use a near-profile 3/4 side angle, neutral expression, neutral posture, natural arms. "
            f"{female_hand_rule}"
            "Focus on garment details: neckline, straps, underband, side seam, waist transition, and fabric texture. "
            "Keep output brand-safe and non-suggestive, with no transparent exposure. "
            "Preserve the EXACT same model, hair, outfit, and match the provided background plate tone exactly."
        ),
        "상반신 후면": (
            "CROP AND REFRAME this image into an UPPER-BODY BACK-VIEW ECOMMERCE STUDIO SHOT. "
            "Frame from top of head to slightly below waist only; do not show thighs, knees, calves, or feet. "
            "Rotate 180° so upper back faces camera, shoulders level, arms relaxed, torso centered. "
            f"{rear_hair_rule}"
            "Focus on back neckline, strap placement, back band curve, side-back fit, waist transition, and fabric texture. "
            "Keep output brand-safe and non-suggestive, with no transparent exposure and no lower-body emphasis. "
            "Keep the EXACT same model, hair, outfit, and match the provided background plate tone exactly."
        ),
        "하반신": (
            "CROP AND REFRAME this image into a LOWER-BODY PRODUCT BEAUTY CLOSE-UP. "
            "The output image MUST be tightly framed from just below the navel or low waist area down to the upper-to-mid thigh. "
            "Keep the pelvis and lower torso mostly front-facing, centered, and symmetrical like a clean ecommerce detail shot. "
            "The lower garment must dominate the frame with clear visibility of waistband, front shape, leg opening, side panel, and fabric texture. "
            "Match the bottom rise and waistband height exactly from the product/source — do not lengthen into high-rise. "
            "Allow both hands to rest naturally along the outer thighs so a small portion of the fingers/hands can appear near the side edges if needed, but keep the garment as the main focus. "
            "ABSOLUTELY DO NOT show the full chest, shoulders, full face, knees, calves, or feet. "
            "Preserve the EXACT same model, outfit, and match the provided background plate tone exactly."
        ),
    }
    return mapping.get(shot_label, "")


# ── HF Dataset Push (background) ─────────────────────────────

def _sanitize_upload_filename(name: Any, fallback: str = "product.png") -> str:
    raw = str(name or "").strip() or fallback
    raw = os.path.basename(raw.replace("\\", "/"))
    cleaned = re.sub(r"[^\w.\-가-힣]+", "_", raw, flags=re.UNICODE).strip("._")
    if not cleaned:
        cleaned = fallback
    cleaned = cleaned.replace("..", "_")
    if len(cleaned) > 120:
        stem, ext = os.path.splitext(cleaned)
        cleaned = stem[:100] + ext[:20]
    return cleaned


def _unique_filenames(names: list, fallback_prefix: str) -> list:
    used = set()
    out = []
    for i, name in enumerate(names):
        safe = _sanitize_upload_filename(name, f"{fallback_prefix}_{i}.png")
        stem, ext = os.path.splitext(safe)
        candidate = safe
        n = 2
        while candidate.lower() in used:
            candidate = f"{stem}_{n}{ext}"
            n += 1
        used.add(candidate.lower())
        out.append(candidate)
    return out


def _normalize_filename_list(payload_or_list: Any, count: int = 0) -> List[str]:
    vals = payload_or_list
    if isinstance(vals, dict):
        vals = (
            vals.get("productImageFilenames")
            or vals.get("designImageFilenames")
            or vals.get("product_image_filenames")
            or vals.get("design_image_filenames")
            or []
        )
    if not isinstance(vals, list):
        vals = []
    names = [str(v).strip() for v in vals if isinstance(v, str) and v.strip()]
    if count > 0:
        while len(names) < count:
            names.append(f"product_{len(names)}.png")
        names = names[:count]
    return names


def _make_jpg_thumb(img_bytes: bytes, max_side: int = 512) -> BytesIO:
    try:
        from PIL import Image
        im = Image.open(BytesIO(img_bytes)).convert("RGB")
        im.thumbnail((max_side, max_side), Image.LANCZOS)
        bio = BytesIO()
        im.save(bio, "JPEG", quality=85)
        bio.seek(0)
        return bio
    except Exception:
        return BytesIO(img_bytes)


def _push_to_hub_sync(record: dict, image_bytes: bytes, ts: str,
                      product_images_b64: list = None, face_b64: str = None,
                      product_filenames: list = None):
    """Run in background thread — never blocks the API response."""
    if not HF_TOKEN or not HF_DATASET_REPO:
        return
    try:
        from huggingface_hub import HfApi, CommitOperationAdd
    except ImportError:
        return

    api = HfApi(token=HF_TOKEN)
    try:
        api.create_repo(HF_DATASET_REPO, repo_type="dataset", exist_ok=True)
    except Exception:
        pass

    day = ts[:8]
    ops = []
    filename = f"fashion_{ts}_0.jpg"
    ops.append(CommitOperationAdd(path_in_repo=f"images/{day}/{filename}", path_or_fileobj=BytesIO(image_bytes)))
    ops.append(CommitOperationAdd(path_in_repo=f"thumbs/{day}/{filename}", path_or_fileobj=_make_jpg_thumb(image_bytes)))

    saved_product_paths = []
    if product_images_b64:
        names = list(product_filenames or [])
        while len(names) < len(product_images_b64):
            names.append(f"product_{len(names)}.png")
        names = _unique_filenames(names[:len(product_images_b64)], "product")
        print(f"[HUB] Product filenames: {names}")
        for i, img_b64 in enumerate(product_images_b64):
            try:
                if isinstance(img_b64, str) and ";base64," in img_b64:
                    raw = base64.b64decode(img_b64.split(";base64,", 1)[1])
                    path = f"inputs/product/{day}/{ts}/{names[i]}"
                    ops.append(CommitOperationAdd(path_in_repo=path, path_or_fileobj=BytesIO(raw)))
                    saved_product_paths.append(path)
            except Exception:
                pass

    if face_b64:
        try:
            raw_face = base64.b64decode(face_b64)
            ops.append(CommitOperationAdd(
                path_in_repo=f"inputs/persona/{day}/persona_{ts}.jpg",
                path_or_fileobj=BytesIO(raw_face),
            ))
        except Exception:
            pass

    record = dict(record or {})
    if saved_product_paths:
        record["product_input_paths"] = saved_product_paths
        record["product_input_filenames"] = [os.path.basename(p) for p in saved_product_paths]
    if product_filenames:
        # Keep client-provided original names even if image bytes weren't uploaded.
        record.setdefault("product_image_filenames", list(product_filenames))

    ops.append(CommitOperationAdd(
        path_in_repo=f"logs/{day}/fashion_{ts}.json",
        path_or_fileobj=BytesIO(json.dumps(record, ensure_ascii=False, indent=2).encode("utf-8"))
    ))

    try:
        api.create_commit(repo_id=HF_DATASET_REPO, repo_type="dataset", operations=ops,
                          commit_message=f"Add lookbook generation: {ts}")
        print(f"[HUB] ✅ Pushed to {HF_DATASET_REPO} ({len(ops)} files)")
    except Exception as e:
        print(f"[HUB] Upload error: {e}")


def _push_to_hub_background(record, image_bytes, ts, product_images_b64=None, face_b64=None,
                            product_filenames=None):
    """Fire-and-forget: push to hub in a background thread."""
    t = threading.Thread(
        target=_push_to_hub_sync,
        args=(record, image_bytes, ts),
        kwargs={
            "product_images_b64": product_images_b64,
            "face_b64": face_b64,
            "product_filenames": product_filenames,
        },
        daemon=True,
    )
    t.start()
    print(f"[HUB] Background upload started for {ts}")


# ══════════════════════════════════════════════════════════════
# API: Generate fitting image
# ══════════════════════════════════════════════════════════════

@app.get("/api/background-check")
def api_background_check():
    """배경 플레이트가 실제로 로드되는지, 측정 색상이 무엇인지 확인."""
    profile = _background_plate_profile()
    return {
        "profile": profile,
        "directive": _background_color_directive() or "(플레이트 없음 — 배경 지시가 주입되지 않습니다)",
        "plate_shots": sorted(BACKGROUND_PLATE_SHOT_LABELS),
    }


@app.get("/api/safety-stats")
def api_safety_stats():
    """체형 × 샷별 안전 차단/복구 집계. key = event|shot|body_type"""
    with _SAFETY_STATS_LOCK:
        snapshot = dict(SAFETY_STATS)
    by_body: Dict[str, Dict[str, int]] = {}
    for key, count in snapshot.items():
        event, shot, body = key.split("|", 2)
        by_body.setdefault(body, {})
        by_body[body][event] = by_body[body].get(event, 0) + count
    return {"detail": snapshot, "by_body_type": by_body}


@app.post("/api/generate")
async def api_generate(payload: Dict = Body(...)):
    if not GEMINI_API_KEY:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY is not configured")

    current_user = _LOG_USER

    client = genai.Client(api_key=GEMINI_API_KEY)

    prompt_mode = payload.get("promptMode", "")
    product_images = payload.get("designImages") or payload.get("productImages", [])
    product_image_filenames = _normalize_filename_list(
        payload.get("productImageFilenames") or payload.get("designImageFilenames") or [],
        count=len(product_images) if isinstance(product_images, list) else 0,
    )
    design_slot_images = _collect_slot_images(payload.get("designSlotImages"))
    # Prefer per-slot original names when provided
    if design_slot_images and not product_image_filenames:
        product_image_filenames = [
            (s.get("name") or s.get("filename") or f"slot_{s.get('slot', i)}.png")
            for i, s in enumerate(design_slot_images)
            if isinstance(s, dict)
        ]
    model_face = payload.get("modelFace")
    product_infos = payload.get("productInfos", [])
    shot_label = payload.get("shotLabel", "3/4컷" if prompt_mode == "direct" else "전신(정면)")
    raw_custom_prompt = (payload.get("customPrompt") or "").strip()
    ghost_source_slot = payload.get("ghostSourceSlot")
    body_type = _resolve_body_type(payload.get("bodyType"))
    if prompt_mode == "direct":
        if _is_ghost_product_shot(shot_label):
            if "뒷면" in shot_label:
                if "제품 1" in shot_label:
                    base_ghost = (
                        "고스트컷(인비저블 마네킹) 스타일의 깔끔한 이커머스 상품 사진으로 만들어줘. "
                        "구도는 뒤에서 살짝 비스듬한 후면 3/4 느낌: 밴드 뒤 쪽에서 카메라를 두고, 밴드 전체 너비와 한쪽 컵의 바깥 곡선이 자연스럽게 함께 보이게 — 정면 앞면이 아니고, 옆면만 보이는 90도도 아님. "
                        "플로팅(필수): 바닥·테이블·마네킹 없이 순백 공간에 의류만 공중에 떠 있는 듯, 끈은 위로 자연스럽게 아치, 입체적인 속이 빈 고스트 볼륨. "
                        "업로드에 보이는 구조만 재현하고 후크·몰드컵은 없으면 넣지 마. 부드러운 균일 조명, 컵–밴드 접힘에는 아주 약한 음영만. "
                        "배경은 순백(#FFFFFF)만. 사람 모델, 피부, 얼굴, 머리카락, 손, 발은 절대 넣지 마."
                    )
                else:
                    base_ghost = (
                        "고스트컷(인비저블 마네킹) 스타일의 깔끔한 이커머스 상품 사진으로 만들어줘. "
                        "구도는 정후면: 카메라는 뒤 중앙에서 밴드에 수직으로 대칭 뒷면. 플로팅(필수): 바닥·스탠드 없이 공중에 뜬 듯한 입체 실루엣, 과한 접촉 그림자 없음. "
                        "업로드에 보이는 밴드·구조만 재현. 배경 순백(#FFFFFF). 사람 모델, 피부, 얼굴, 머리카락, 손, 발은 절대 넣지 마."
                    )
            elif "측면" in shot_label:
                base_ghost = (
                    "고스트컷(인비저블 마네킹) 스타일의 깔끔한 이커머스 상품 사진으로 만들어줘. "
                    "구도는 앞·옆 대각선(전면 쪽 3/4): 카메라는 반드시 의류 앞쪽(전면 반구)에서 전면 좌측 또는 우측 대각선으로만 찍을 것 — 약 30~45도. "
                    "앞면(넥라인·고어·양 컵)이 화면의 주인공이어야 하고, 한쪽 컵은 더 정면에 가깝게 넓게, 반대 컵은 원근으로 좁아 보이게, 멀리 있는 쪽 옆 날개·겨드랑이 라인이 깊이감으로 보이게. "
                    "밴드 뒤나 후크면이 정면을 향하는 구도, 뒤에서 찍는 후면 측면·백 쿼터, 옆면만 보이는 90도 프로필은 금지. "
                    "상단 네크라인으로 안쪽이 살짝 보이는 3D 고스트 볼륨은 이 앞쪽 대각선에서만 — 뒤에서 안을 들여다보는 느낌 금지. "
                    "업로드에 없는 후크·몰드컵·패드는 넣지 마. 배경은 순백(#FFFFFF) 스튜디오만. 사람 모델, 피부, 얼굴, 머리카락, 손, 발은 절대 넣지 마."
                )
            elif "앞면" in shot_label:
                base_ghost = (
                    "고스트컷(인비저블 마네킹) 스타일의 깔끔한 이커머스 상품 사진으로 만들어줘. "
                    "눈높이에서 정면으로 직진한 구도(수평)로, 중심이 화면 중앙에 오고 좌우가 대칭으로 보이는 카탈로그 정면 샷. "
                    "3/4로 비틀어진 전면이 아니라 앞면을 정면으로 정확히 바라본 각도. "
                    "배경은 순백(#FFFFFF) 스튜디오만. "
                    "사람 모델, 피부, 얼굴, 머리카락, 손, 발은 절대 넣지 마."
                )
            else:
                base_ghost = (
                    "고스트컷(인비저블 마네킹) 스타일의 깔끔한 이커머스 상품 사진으로 만들어줘. "
                    "부드러운 스튜디오 조명, 배경은 순백(#FFFFFF)만, 입체적인 내부 볼륨이 느껴지게. "
                    "사람 모델, 피부, 얼굴, 머리카락, 손, 발은 절대 넣지 마."
                )
            custom_prompt = f"{base_ghost}\n\n추가 요청: {raw_custom_prompt}" if raw_custom_prompt else base_ghost
        else:
            model_base = _resolve_model_preset_prompt(payload.get("modelPreset"))
            # 얼굴 프리셋 × 체형 = 조합. 체형 문구는 여기서만 주입한다.
            custom_prompt = f"{model_base} {_body_type_block_ko(body_type)}"
            if raw_custom_prompt:
                custom_prompt = f"{custom_prompt}\n\n추가 요청: {raw_custom_prompt}"
    else:
        custom_prompt = raw_custom_prompt
    reference_image = payload.get("referenceImage")
    background_image = payload.get("backgroundImage")
    # 고스트컷: 배경 PNG/업로드 참조 없이 프롬프트만으로 순백 스튜디오
    if _is_ghost_product_shot(shot_label):
        background_image = None
    # 3/4·상반신 계열·하반신: 항상 background.png를 배경 플레이트로 사용 (클라이언트 배경보다 우선)
    elif _uses_fixed_background_plate(shot_label):
        background_image = _load_local_image_as_data_url(DEFAULT_BACKGROUND_FILE)
        if background_image:
            print(f"[BACKGROUND] Shot '{shot_label}': plate '{DEFAULT_BACKGROUND_FILE}'")
    elif not background_image:
        background_image = _load_local_image_as_data_url(DEFAULT_BACKGROUND_FILE)
        if background_image:
            print(f"[BACKGROUND] Using default background '{DEFAULT_BACKGROUND_FILE}'")
    image_size = _resolve_image_size(payload.get("imageSize"))

    model_gender = _resolve_model_gender(payload.get("modelGender"))

    has_reference = bool(
        reference_image
        and isinstance(reference_image, str)
        and reference_image.startswith("data:")
    )
    has_background = bool(
        background_image
        and isinstance(background_image, str)
        and background_image.startswith("data:")
    )

    request_started_at = datetime.datetime.now()
    request_ts = request_started_at.strftime("%Y-%m-%d %H:%M:%S")
    print(
        f"[GENERATE] [{request_ts}] Shot: {shot_label} | Body: {body_type} | "
        f"Reference: {'YES' if has_reference else 'NO'} | Background: {'YES' if has_background else 'NO'}"
    )

    slot_context = _slot_context_block(shot_label, design_slot_images)
    analysis_input_urls = _collect_valid_product_data_urls(product_images)
    for s in design_slot_images:
        if s["image"] not in analysis_input_urls:
            analysis_input_urls.append(s["image"])

    product_analysis_block: Optional[str] = None
    should_run_product_analysis = (
        not PRODUCT_ANALYSIS_DISABLED
        and not payload.get("skipProductAnalysis")
        and (not has_reference or bool(payload.get("forceProductAnalysis")))
    )
    if should_run_product_analysis:
        if analysis_input_urls:
            product_analysis_block = _analyze_product_cut_for_generation(
                client,
                analysis_input_urls,
                shot_label,
                slot_context=slot_context,
            )

    product_analysis_injection = (
        "\n\n**UPLOADED PRODUCT-CUT ANALYSIS (BINDING — garment details below override generic lingerie defaults; do not contradict)**:\n"
        + product_analysis_block
        + "\n"
        if product_analysis_block
        else ""
    )
    slot_context_injection = (
        "\n\n**PRODUCT SLOT CONTEXT (BINDING)**:\n"
        + slot_context
        + "\n"
        if slot_context
        else ""
    )

    shadow_style_block = """SHADOW STYLE (MANDATORY):
Add an almost non-existent wall shadow behind the model.
- Wall shadow must stay at near-zero opacity and very broad diffusion.
- Do NOT show a readable human silhouette on the wall (no head/shoulder outline).
- Blend the shadow into the wall tone until it is barely detectable even on close look.
- Keep shadow offset minimal and very close to the body; avoid lateral spread.
- Keep only a near-invisible micro contact shadow under the shoes.
- This is a minimal depth cue only, effectively close to no shadow.
- FACE MATTE RULE (HIGHEST PRIORITY): This rule overrides other lighting preferences when conflicts occur.
- FACE SHADOW UNIFORMITY (CRITICAL): The entire shadow-side half of the face must be evenly toned.
- Remove ALL bright hotspots/specular highlights on the shadow-side cheek, under-eye, jawline, and nose side.
- Treat the shadow-side face as one continuous matte plane: no cheek pop, no local bright islands, no patchy relighting.
- Keep a smooth low-contrast gradient only from lit-side to shadow-side boundary, then keep the shadow-side region uniformly subdued.
- Keep facial detail intact, but do not allow any localized bright patches inside the shadow-side region.
- FACE SHADOW BALANCE (MANDATORY): Keep the facial shadow side natural and clean, but avoid over-darkening or "half-face blackout."
- Allow subtle micro-contrast and skin dimensionality on the shadow side while preventing harsh hotspot patches.
- Keep cheek/jaw shadow transitions smooth and realistic; do NOT force a hard matte split across the face.
- SUBJECT SHADOW DEPTH (CRITICAL): Keep wall shadow settings unchanged, and apply only a mild model-side shadow increase for depth.
- Preserve facial/garment details and avoid crushed blacks, muddy skin, or patchy shadow artifacts.
- Do not create multiple shadows. Do not crush blacks or lose facial/garment detail.
- If any contour or shape is visible, reduce shadow strength further until the contour disappears."""
    non_explicit_safety_block = (
        "SAFETY / CONTENT POLICY (MANDATORY): Keep the output strictly non-sexual commercial fashion catalog style. "
        "No nudity, no transparent exposure, and no suggestive posing."
    )

    # ──────────────────────────────────────────────────────────
    # MODE A: TRANSFORM (reference exists → PICasso pattern)
    # ──────────────────────────────────────────────────────────
    if has_reference:
        transform_instruction = _build_transform_instruction(shot_label, model_gender)
        if not transform_instruction:
            camera_angle = _build_camera_prompt(shot_label, model_gender)
            transform_instruction = (
                f"Transform the provided reference fashion image. Change the angle/framing to: {camera_angle}. "
                f"Keep the EXACT same model, face, and outfit. "
                + (
                    "Match the provided background plate tone exactly when a plate image is included."
                    if has_background
                    else "Keep the soft light-gray studio background."
                )
            )

        parts = []
        parsed_ref = _parse_base64(reference_image)
        ref_size_kb = len(parsed_ref["data"]) * 3 / 4 / 1024
        print(f"[GENERATE] → TRANSFORM MODE | ref ~{ref_size_kb:.0f} KB")
        parts.append({"inline_data": {"data": parsed_ref["data"], "mime_type": parsed_ref["mime_type"]}})
        for s in design_slot_images:
            parsed_slot = _parse_base64(s["image"])
            parts.append({"inline_data": {"data": parsed_slot["data"], "mime_type": parsed_slot["mime_type"]}})
        # 배경 플레이트는 반드시 마지막 — 프롬프트가 "LAST provided image"로 지목한다
        if has_background:
            parsed_bg = _parse_base64(background_image)
            bg_size_kb = len(parsed_bg["data"]) * 3 / 4 / 1024
            print(f"[GENERATE] → Background ref ~{bg_size_kb:.0f} KB (last part)")
            parts.append({"inline_data": {"data": parsed_bg["data"], "mime_type": parsed_bg["mime_type"]}})

        body_proportion_guide = _build_body_proportion_prompt(shot_label, model_gender, body_type)
        background_constraint = (
            "BACKGROUND PLATE (HIGHEST PRIORITY): The LAST provided image is the mandatory studio backdrop. "
            "Match its exact color temperature, brightness, and gray/off-white tone across the entire frame. "
            "Do NOT invent a warmer cream, cooler blue-gray, or brighter pure-white backdrop. "
            "Preserve floor/wall continuity and overall scene flatness from the plate. Place the SAME model naturally into that exact environment."
            + _background_color_directive()
            if has_background
            else "Keep a soft light-gray studio background (subtle warm gray, NOT pure white). No heavy gradients, no props. A gentle tonal shift between wall and floor is acceptable for natural depth."
        )
        background_reference_note = (
            "BACKGROUND REFERENCE (CRITICAL — NON-NEGOTIABLE): The LAST image is the background plate. "
            "Copy its tone and lighting mood exactly. Ignore any softer/warmer/cooler studio backdrop implied by other instructions."
            if has_background else ""
        )
        visible_reference_constraint = (
            "1. **SOURCE TRUTH**: Use the provided reference image as the ONLY subject reference. "
            "Do NOT change the model identity, face, hair, or the garment design/color/fit. "
            "Preserve all visible details from the reference crop faithfully, including hair shape, neckline, straps, band shape, fabric texture, and garment placement. "
            + STRAP_STRUCTURE_EN
            + " "
            + BOTTOM_RISE_FIDELITY_EN
        )
        footwear_constraint = (
            "5. **FOOTWEAR**: If shoes are visible in the reference image or required by the target framing, keep the exact same shoes."
        )
        proportion_constraint = (
            "7. **BODY PROPORTIONS**: Preserve natural fashion-model anatomy consistent with the reference crop. "
            "Do NOT stretch, compress, or hallucinate body parts that are not clearly implied by the reference."
        )

        prompt_text = f"""**IMAGE TRANSFORMATION TASK**:
{transform_instruction}

{body_proportion_guide}

{background_reference_note}

{shadow_style_block}

**STRICT CONSTRAINTS**:
{visible_reference_constraint}
2. **BACKGROUND**: {background_constraint}
3. **LIGHTING**: Maintain directional studio lighting from the LEFT side — the left side of the model should be brighter, with soft natural shadow falloff on the right side. Do NOT flatten the lighting.
4. **QUALITY**: Maintain 8k resolution and photorealistic commercial fashion photography style.
{footwear_constraint}
6. **FABRIC REALISM**: The clothing must look like real worn fabric — show natural wrinkles at joints, gravity-driven drape, material-specific texture (knit stitch, denim whiskering, cotton creases), and subtle compression folds where the garment is pressed or pulled. Do NOT render fabric as flat or CG-smooth.
8. **SAFETY**: {non_explicit_safety_block}
{proportion_constraint}{slot_context_injection}
{product_analysis_injection}{"8. **ADDITIONAL**: " + custom_prompt if custom_prompt else ""}"""

        parts.append({"text": prompt_text})

    # ──────────────────────────────────────────────────────────
    # MODE B: ORIGINAL (no reference → full generation)
    # ──────────────────────────────────────────────────────────
    else:
        parts = []
        for img_b64 in product_images:
            if isinstance(img_b64, str) and img_b64.startswith("data:"):
                parsed = _parse_base64(img_b64)
                parts.append({"inline_data": {"data": parsed["data"], "mime_type": parsed["mime_type"]}})
            if not parts:
                for s in design_slot_images:
                    parsed = _parse_base64(s["image"])
                    parts.append({"inline_data": {"data": parsed["data"], "mime_type": parsed["mime_type"]}})
        if has_background:
            parsed_bg = _parse_base64(background_image)
            bg_size_kb = len(parsed_bg["data"]) * 3 / 4 / 1024
            print(f"[GENERATE] → Background ref ~{bg_size_kb:.0f} KB")
            parts.append({"inline_data": {"data": parsed_bg["data"], "mime_type": parsed_bg["mime_type"]}})

        if prompt_mode == "direct":
            camera_angle = _build_camera_prompt(shot_label, "female")
            body_proportion_guide = _build_body_proportion_prompt(shot_label, "female", body_type)
            background_setting = (
                "BACKGROUND (CRITICAL — NON-NEGOTIABLE): The LAST provided image is the mandatory background plate. "
                "Match that plate's exact tone, color temperature, brightness, and overall studio feel. "
                "Do NOT substitute a cream, blue-gray, pure white (#FFFFFF), or any different studio backdrop. "
                "Do NOT copy backdrop color from the garment/product reference images. "
                "Keep the subject and garment natural while locking the environment to the plate."
                + _background_color_directive()
                if has_background
                else "BACKGROUND: Follow the user's prompt exactly. If the prompt does not specify a background, use a clean commercial studio setup."
            )
            if _is_ghost_product_shot(shot_label):
                ghost_ctx = _ghost_product_context_block(shot_label, ghost_source_slot)
                bg_ghost = (
                    "BACKGROUND (CRITICAL): No background image is supplied — do NOT use any wall plate or backdrop reference. "
                    "The background MUST be pure solid white only: exactly #FFFFFF across the entire frame, perfectly even, with no gray tint, no gradient, no texture, horizon, floor line, or environment. "
                    "Soft, diffused ecommerce studio lighting on the garment only; keep the backdrop flat pure white."
                )
                prompt_text = f"""You are creating a professional ecommerce product photograph (invisible mannequin / ghost mannequin style).

SHOT TYPE (MANDATORY): {shot_label}

{ghost_ctx}
{slot_context_injection}

PRODUCT BRIEF (MANDATORY):
{custom_prompt}
{product_analysis_injection}
PRODUCT REFERENCE (CRITICAL):
- The uploaded image(s) are for the GARMENT ONLY (silhouette, fabric, straps, color). They are NOT a background reference — ignore any backdrop or surface visible in the uploads when painting the scene background.
- Reproduce the garment in ghost mannequin style with natural 3D hollow volume.
- Absolutely NO human model, NO skin, NO face, NO hair, NO hands, NO feet, NO limbs.
- Preserve silhouette, color, straps, lace, seams, edges, and fabric texture faithfully.
- {GHOST_REFERENCE_FIDELITY_EN}
- {STRAP_STRUCTURE_EN}

FRAMING AND COMPOSITION (MANDATORY):
{camera_angle}

{bg_ghost}

GARMENT REALISM (CRITICAL):
- Fabric must look real: tension, drape, stitching, elastic, lace detail.
- The garment floats with believable interior volume like invisible mannequin photography.

LIGHTING:
- Soft even studio lighting with gentle shadows for depth. No skin (there is no skin).

OUTPUT:
- Return a single high-quality image only.
"""
                parts.append({"text": prompt_text})
                gs = f" ghostSourceSlot={ghost_source_slot}" if ghost_source_slot is not None else ""
                print(f"[GENERATE] → DIRECT GHOST PRODUCT | shot: {shot_label} | designs: {len(product_images)}{gs}")
            else:
                prompt_text = f"""You are creating a photorealistic commercial fashion image for a fashion product brand.

FIXED MODEL BRIEF (MANDATORY):
{custom_prompt}
{slot_context_injection}
{product_analysis_injection}
DESIGN REFERENCE (CRITICAL):
- The uploaded image(s) are the garment/design references.
- They are NOT a background reference. Ignore any backdrop, surface, table, or studio tone visible in the uploaded product images when painting the scene background.
- Preserve the actual design faithfully: silhouette, neckline, cup shape, waistband, lace, trim, seam placement, strap structure, color, print, pattern, fabric mood, and overall proportion.
- {STRAP_STRUCTURE_EN}
- {BOTTOM_RISE_FIDELITY_EN}
- Do NOT replace the garment with a different design.
- If multiple images are provided, treat the first image as the primary design reference and use the others as supporting detail references.

MODEL AND SHOOT DIRECTION:
- Generate exactly one model wearing the provided design.
- {STRAP_STRUCTURE_REMINDER_EN}
- {BOTTOM_RISE_REMINDER_EN}
- The final image must feel like a real premium fashion campaign or ecommerce editorial photo, not CGI.
- {non_explicit_safety_block}
- HEAD SCALE (CRITICAL — OVERRIDE BEAUTY DEFAULTS): Render a fashion-editorial head-to-body ratio. The head must look clearly SMALL relative to shoulders and torso — target ~1/8.5–1/9 of body height, never a large or round beauty-close-up head scale. Head width must be visibly less than shoulder width.
- Keep anatomy elegant and realistic. If the user's prompt asks for 9-head proportions or a slim fashion-model build, apply that naturally without distortion.
- When the brief calls for a delicate fashion-model body, favor a smaller head, longer neck, narrower waist, longer torso line, and lean elongated limbs rather than average commercial-model proportions.
- Keep the head-to-body ratio editorial and elongated: the head should read clearly smaller than average relative to shoulder width and torso length, without changing the model's identity.
- Do NOT frame or scale the subject like a beauty portrait or influencer selfie. Avoid oversized head proportions, wide-face enlargement, or face-dominated framing; keep the full head and face visible but with a modest, elongated scale within the frame.
- Keep styling tasteful and brand-safe for a professional commercial fashion campaign.
- Do NOT add unrelated accessories, props, or extra garments unless the user explicitly requests them.
- SHOT TYPE (MANDATORY): {shot_label}
- FRAMING AND COMPOSITION (MANDATORY): {camera_angle}

{body_proportion_guide}

GARMENT REALISM (CRITICAL):
- Show believable fabric tension, stretch, fold behavior, edge finish, and body contact.
- Keep lace, elastic bands, stitching, and fabric texture sharp and realistic.
- The garment must look worn by a real person, not pasted on or rendered as a flat surface.
- Straps: match the product exactly — one band per shoulder when the product shows one per side; never twin parallel straps, never a forked strap at the shoulder.
- Bottoms: keep rise, waistband height, and front-panel length identical to the product cut — do not lengthen into a taller/high-rise shape.

{background_setting}

LIGHTING:
- Follow the background plate's lighting mood when a plate is provided; keep skin clear and natural.
- If no plate is provided and the prompt does not define lighting clearly, use clean, polished studio lighting with crisp but natural skin rendering.

OUTPUT:
- Return a single high-quality image only.
- Make the garment the hero subject.
"""
                parts.append({"text": prompt_text})
                print(f"[GENERATE] → DIRECT PROMPT MODE | designs: {len(product_images)}")
        else:
            # 레거시: promptMode ≠ direct. 현재 UI는 direct만 사용하며 얼굴 참조 이미지는 지원하지 않음.
            has_face = False

            outfit_details = "\n".join([
                f"Clothing Item {i+1}: Category={info.get('category','')}, Fit={info.get('fit','')}, Length={info.get('length','')}"
                + (f", Total Length={info.get('totalLength','')}cm" if info.get('totalLength') else "")
                for i, info in enumerate(product_infos)
            ])
            camera_angle = _build_camera_prompt(shot_label, model_gender)
            body_proportion_guide = _build_body_proportion_prompt(shot_label, model_gender, body_type)

            face_instruction = (
                "MODEL IDENTITY (CRITICAL): The model in this photo MUST be the EXACT same person "
                "as shown in the face reference image. Copy the facial features precisely — "
                "same face shape, eyes, nose, lips, eyebrows, skin tone, and hair."
            ) if has_face else "MODEL: The model should have an attractive, professional look."
            background_setting = (
                "SETTING (CRITICAL — NON-NEGOTIABLE): The LAST provided image is the mandatory background plate. "
                "Match its exact tone, color temperature, brightness, perspective, and floor contact. "
                "Do NOT invent a warmer, cooler, or whiter studio backdrop. Background replacement must look naturally photographed, not composited."
                if has_background
                else "SETTING (CRITICAL): Soft light-gray studio background with a subtle warm gray tone — NOT pure white. A gentle, natural tonal transition between the wall and floor is acceptable to create depth and realism, similar to a real photography studio. No heavy gradients, no textures, no props."
            )
            background_reminder = (
                "- BACKGROUND LOCK: The LAST image is the only allowed backdrop tone — match it exactly; ignore cream/blue-gray/pure-white alternatives."
                if has_background else
                "- The background must be a soft light-gray studio tone, NOT pure white."
            )

            prompt_text = f"""Act as a professional fashion photographer.
Task: Create a high-quality lifestyle/studio fashion photography image.

{face_instruction}

FRAMING AND COMPOSITION (MANDATORY): {camera_angle}

OUTFIT: The model is wearing a coordinated outfit consisting of the provided product images.
Details: {outfit_details}
{slot_context_injection}
{product_analysis_injection}
{body_proportion_guide}

FABRIC REALISM (CRITICAL): The clothing must look like REAL worn fabric, NOT flat CG or ironed-smooth textures.
- Add natural wrinkles and creases at joints (elbows, knees, waist, crotch) from body movement.
- Show gravity-driven drape and fabric weight — heavier fabrics hang with deeper folds, lighter fabrics flow softly.
- Render material-specific texture: knit should show visible yarn/stitch texture, denim should show subtle whiskering/fading at stress points, cotton should have soft organic creases, wool should have a fuzzy nap, silk/satin should show light-catching sheen with flowing drape.
- Include subtle compression wrinkles where the garment is pulled or pressed (e.g. waistband, pocket areas, where hands rest).
- The fabric should interact naturally with the body — not floating or stiff like a 3D render.

SHOES (DEFAULT): Unless the user specifies different footwear, the model MUST be wearing classic black leather loafers.

{background_setting}

LIGHTING (CRITICAL): Use directional studio lighting from the LEFT side. The key light should come from the upper-left, casting soft natural shadows on the model's right side. The left side of the model's face and body should be brighter and well-lit, while the right side has subtle, natural shadow falloff. This creates depth and dimension similar to professional Korean fashion lookbook photography. Do NOT use flat, even lighting — the directional light-to-shadow gradient from left to right is essential for a realistic, editorial look.

{shadow_style_block}

{"ADDITIONAL INSTRUCTIONS: " + custom_prompt if custom_prompt else ""}

IMPORTANT REMINDERS:
- Strictly adhere to the FRAMING AND COMPOSITION instruction.
{background_reminder}
{"- The model's face MUST match the reference face image exactly." if has_face else ""}
{"- Maintain the 9-head fashion canon body proportions." if body_proportion_guide else ""}
- {STRAP_STRUCTURE_EN}"""

            parts.append({"text": prompt_text})
            print(f"[GENERATE] → ORIGINAL MODE | products: {len(product_images)}, face: {has_face}")

    # ──────────────────────────────────────────────────────────
    # Call Gemini
    # ──────────────────────────────────────────────────────────
    try:
        if has_background:
            media_idx = [i for i, p in enumerate(parts) if isinstance(p, dict) and "inline_data" in p]
            print(f"[GENERATE] Media parts={len(media_idx)} | background is last: {media_idx[-1] == max(media_idx)}")
        print(f"[GENERATE] Calling Gemini API...")
        response, used_image_size, attempt_count = _call_gemini_image_with_retry(
            client,
            model="gemini-3.1-flash-image-preview",
            parts=parts,
            image_size=image_size,
            log_tag="GENERATE",
        )
        print(f"[GENERATE] Gemini API responded | attempt={attempt_count} | image_size={used_image_size}")

        image_b64 = _extract_first_inline_image_data_url(response)
        if image_b64:
            print(f"[GENERATE] Image extracted: {len(image_b64)} chars")
        if not image_b64:
            hint = _summarize_gemini_missing_image(response)
            print(f"[GENERATE] ❌ No image in response | {hint}")
            _log_gemini_response_debug(response)
            # 모델 샷에서 IMAGE_SAFETY 차단 시, 장문 프롬프트를 버리고 짧은 안전 템플릿으로 1회 재시도
            if _needs_policy_safe_retry(shot_label, hint):
                _record_safety_event("blocked", shot_label, body_type)
                media_parts = _extract_inline_media_parts(parts)
                retry_size = "2K" if image_size == "4K" else image_size
                # tier 1: 치수는 유지하고 밀착 서술만 제거 → 실패 시 tier 2에서 체형 블록 전체 제거
                for tier in (1, 2):
                    print(f"[GENERATE] Safe retry tier {tier} for '{shot_label}' (body={body_type})")
                    safer_parts = media_parts + [{
                        "text": _safe_retry_instruction_for_shot(
                            shot_label, body_type=body_type, tier=tier,
                            gender=model_gender, has_background=has_background
                        )
                    }]
                    try:
                        response2, used2, att2 = _call_gemini_image_with_retry(
                            client,
                            model="gemini-3.1-flash-image-preview",
                            parts=safer_parts,
                            image_size=retry_size,
                            log_tag=f"GENERATE-SAFE-RETRY-T{tier}",
                        )
                        image_b64 = _extract_first_inline_image_data_url(response2)
                        if image_b64:
                            print(f"[GENERATE] Safe retry tier {tier} succeeded | attempt={att2} | image_size={used2}")
                            _record_safety_event(f"recovered_t{tier}", shot_label, body_type)
                            break
                        print(f"[GENERATE] Safe retry tier {tier} returned no image")
                    except Exception as retry_ex:
                        print(f"[GENERATE] Safe retry tier {tier} failed: {retry_ex}")
                if not image_b64:
                    _record_safety_event("failed", shot_label, body_type)
            if image_b64:
                print(f"[GENERATE] Image extracted after safe retry: {len(image_b64)} chars")
                # proceed normally below
            else:
                hint = _summarize_gemini_missing_image(response)
                raise HTTPException(
                    status_code=500,
                    detail=(
                        "Gemini가 이미지를 반환하지 않았습니다. "
                        f"({hint}) "
                        "서버 터미널에 [GENERATE][DEBUG] 로그가 더 출력됩니다. "
                        "동시에 여러 샷을 생성하면 할당량/불안정 응답이 잦을 수 있습니다."
                    ),
                )

        # ── Push to HF Dataset IN BACKGROUND (non-blocking) ──
        try:
            now = datetime.datetime.now()
            ts = now.strftime("%Y%m%d_%H%M%S_%f")[:-3]
            elapsed_ms = int((now - request_started_at).total_seconds() * 1000)
            raw_bytes = base64.b64decode(image_b64.split(";base64,", 1)[1]) if ";base64," in image_b64 else b""
            face_b64_hub = None
            if isinstance(model_face, str) and model_face.startswith("data:") and ";base64," in model_face:
                face_b64_hub = model_face.split(";base64,", 1)[1]
            # ⚡ Background push — response returns immediately
            _push_to_hub_background(
                record={
                    "timestamp": now.strftime("%Y-%m-%d %H:%M:%S"), "ts": ts,
                    "app": "ai-fashion-eblin-pro", "type": "generated",
                    "shot_label": shot_label,
                    "body_type": body_type,
                    "model_preset": str(payload.get("modelPreset") or ""),
                    "product_infos": product_infos,
                    "product_analysis_used": bool(product_analysis_block),
                    "design_slot_images_count": len(design_slot_images),
                    "product_image_filenames": product_image_filenames,
                    "custom_prompt": custom_prompt or "(none)",
                    "model_face": "user_upload" if isinstance(model_face, str) and model_face.startswith("data:") else (model_face if model_face else "none"),
                    "has_reference": has_reference,
                    "has_background": has_background,
                    "mode": "TRANSFORM" if has_reference else "ORIGINAL",
                    "elapsed_ms": elapsed_ms,
                    "elapsed_sec": round(elapsed_ms / 1000, 3),
                    "user_username": current_user["username"],
                    "user_name": current_user["name"],
                    "user_email": current_user["email"],
                    "user_logged_in": current_user["is_logged_in"],
                },
                image_bytes=raw_bytes, ts=ts,
                product_images_b64=product_images, face_b64=face_b64_hub,
                product_filenames=product_image_filenames,
            )
        except Exception as hub_err:
            print(f"[HUB] Failed to start background push: {hub_err}")

        elapsed_ms = int((datetime.datetime.now() - request_started_at).total_seconds() * 1000)
        print(f"[GENERATE] ✅ Returning response for '{shot_label}' | request_ts={request_ts} | elapsed_ms={elapsed_ms}")
        return {"imageUrl": image_b64}

    except HTTPException:
        raise
    except Exception as e:
        elapsed_ms = int((datetime.datetime.now() - request_started_at).total_seconds() * 1000)
        print(f"[GENERATE] ❌ Failed after {elapsed_ms} ms")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Generation failed: {str(e)}")


# ── API: Edit existing image ─────────────────────────────────

@app.post("/api/edit")
async def api_edit(payload: Dict = Body(...)):
    if not GEMINI_API_KEY:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY is not configured")

    current_user = _LOG_USER

    client = genai.Client(api_key=GEMINI_API_KEY)
    current_image = payload.get("currentImage", "")
    edit_instruction = payload.get("editInstruction", "")
    image_size = _resolve_image_size(payload.get("imageSize"))
    reference_images = payload.get("referenceImages", [])
    if not reference_images and payload.get("referenceImage"):
        reference_images = [payload["referenceImage"]]
    product_image_filenames = _normalize_filename_list(
        payload.get("productImageFilenames") or payload.get("designImageFilenames") or []
    )

    # bodyType이 오면 "체형만 바꾸는" 단일 변수 편집으로 처리 (슬림 컷 → 볼륨 컷 페어)
    raw_body_type = payload.get("bodyType")
    if raw_body_type:
        resolved_body_type = _resolve_body_type(raw_body_type)
        body_change = _body_type_change_instruction(resolved_body_type)
        edit_instruction = f"{body_change}\n{edit_instruction}".strip()
        print(f"[EDIT] Body type conversion → {resolved_body_type}")

    parts = []
    if current_image and current_image.startswith("data:"):
        parsed = _parse_base64(current_image)
        parts.append({"inline_data": {"data": parsed["data"], "mime_type": parsed["mime_type"]}})
    for ref in reference_images:
        if ref and isinstance(ref, str) and ref.startswith("data:"):
            parsed = _parse_base64(ref)
            parts.append({"inline_data": {"data": parsed["data"], "mime_type": parsed["mime_type"]}})
    if reference_images:
        ref_count = sum(1 for r in reference_images if r and isinstance(r, str) and r.startswith("data:"))
        ref_text = (
            f"Use the following {ref_count} image(s) as visual reference(s) for the requested changes only. "
            "Do NOT copy background, environment, or tone from the reference images — preserve the background from the first image."
        ) if ref_count > 1 else (
            "Use the second image as a visual reference for the requested changes only. "
            "Do NOT copy background or environment from the reference — preserve the background from the first image."
        )
        parts.append({"text": ref_text})

    parts.append({
        "text": f"Modify this fashion photo based on the following instruction: {edit_instruction}. "
                f"Maintain the same model and outfit with high fidelity, and preserve composition unless the instruction explicitly requests a framing change. "
                f"BACKGROUND (CRITICAL): Keep the exact same background — tone, color, and environment — as in the first image. "
                f"Do NOT change the background unless the instruction explicitly requests a background change. "
                f"The output must be a high-quality fashion photograph."
    })

    try:
        response, used_image_size, attempt_count = _call_gemini_image_with_retry(
            client,
            model="gemini-3.1-flash-image-preview",
            parts=parts,
            image_size=image_size,
            log_tag="EDIT",
        )
        print(f"[EDIT] Gemini API responded | attempt={attempt_count} | image_size={used_image_size}")

        image_b64 = _extract_first_inline_image_data_url(response)
        if not image_b64:
            print(f"[EDIT] ❌ No image | {_summarize_gemini_missing_image(response)}")
            _log_gemini_response_debug(response)
            hint = _summarize_gemini_missing_image(response)
            raise HTTPException(
                status_code=500,
                detail=f"편집 결과 이미지가 없습니다. ({hint})",
            )

        # Background push for edit too
        try:
            now = datetime.datetime.now()
            ts = now.strftime("%Y%m%d_%H%M%S_%f")[:-3]
            raw_bytes = base64.b64decode(image_b64.split(";base64,", 1)[1]) if ";base64," in image_b64 else b""
            _push_to_hub_background(
                record={
                    "timestamp": now.strftime("%Y-%m-%d %H:%M:%S"), "ts": ts,
                    "app": "ai-fashion-eblin-pro", "type": "edited",
                    "shot_label": payload.get("shotLabel") or "편집",
                    "edit_instruction": edit_instruction,
                    "product_image_filenames": product_image_filenames,
                    "user_username": current_user["username"],
                    "user_name": current_user["name"],
                    "user_email": current_user["email"],
                    "user_logged_in": current_user["is_logged_in"],
                },
                image_bytes=raw_bytes, ts=ts,
                product_filenames=product_image_filenames,
            )
        except Exception:
            pass

        return {"imageUrl": image_b64}

    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Edit failed: {str(e)}")


# ── API: Product cut → short motion video (Veo) ──────────────

def _extract_video_bytes_from_operation(client: Any, operation: Any) -> bytes:
    response = getattr(operation, "response", None) or getattr(operation, "result", None)
    if response is None:
        raise RuntimeError("Video operation completed without a response payload.")
    generated = getattr(response, "generated_videos", None) or []
    if not generated:
        raise RuntimeError("Video operation returned no generated_videos.")
    video_obj = getattr(generated[0], "video", None)
    if video_obj is None:
        raise RuntimeError("Generated video payload is empty.")

    video_bytes = getattr(video_obj, "video_bytes", None)
    if video_bytes:
        return bytes(video_bytes)

    # URI만 있는 경우 다운로드 시도
    try:
        client.files.download(file=video_obj)
    except Exception as dl_err:
        print(f"[VIDEO] files.download failed: {dl_err}")

    video_bytes = getattr(video_obj, "video_bytes", None)
    if video_bytes:
        return bytes(video_bytes)

    uri = getattr(video_obj, "uri", None)
    if uri:
        raise RuntimeError(f"Video bytes unavailable after download (uri={uri}).")
    raise RuntimeError("Could not extract video bytes from Veo response.")


@app.post("/api/video")
async def api_video(payload: Dict = Body(...)):
    """업로드 제품컷 이미지 → 상세페이지용 스판(원단 신축) 모션 영상."""
    if not GEMINI_API_KEY:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY is not configured")

    current_user = _LOG_USER

    current_image = payload.get("currentImage") or payload.get("imageUrl") or ""
    if not (isinstance(current_image, str) and current_image.startswith("data:")):
        raise HTTPException(status_code=400, detail="currentImage (data URL) is required")

    product_image_filenames = _normalize_filename_list(
        payload.get("productImageFilenames") or payload.get("designImageFilenames") or []
    )
    if not product_image_filenames and payload.get("filename"):
        product_image_filenames = [str(payload.get("filename"))]

    motion_style, preset = _resolve_ghost_motion_preset(payload.get("motionStyle") or payload.get("style"))
    raw_prompt = (payload.get("prompt") or "").strip()
    motion_prompt = (
        f"{preset['prompt']}\n\nUser direction (priority for action/detail): {raw_prompt}"
        if raw_prompt
        else preset["prompt"]
    )
    duration = VEO_DURATION_SECONDS
    try:
        req_duration = int(payload.get("durationSeconds") or duration)
        if req_duration in (4, 6, 8):
            duration = req_duration
    except (TypeError, ValueError):
        pass

    aspect_ratio = str(payload.get("aspectRatio") or "9:16").strip()
    if aspect_ratio not in ("9:16", "16:9"):
        aspect_ratio = "9:16"

    resolution = str(payload.get("resolution") or VEO_RESOLUTION).strip().lower()
    if resolution not in ("720p", "1080p"):
        resolution = VEO_RESOLUTION if VEO_RESOLUTION in ("720p", "1080p") else "1080p"

    parsed = _parse_base64(current_image)
    try:
        image_bytes = base64.b64decode(parsed["data"])
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid image base64 data")

    client = genai.Client(api_key=GEMINI_API_KEY)
    started = datetime.datetime.now()
    print(
        f"[VIDEO] Start | model={VEO_MODEL} | style={motion_style} | duration={duration}s | "
        f"aspect={aspect_ratio} | res={resolution} | image≈{len(image_bytes)/1024:.0f}KB"
    )

    def _run_veo(include_person_generation: bool, use_resolution: str):
        cfg_kwargs = {
            "number_of_videos": 1,
            "duration_seconds": duration,
            "aspect_ratio": aspect_ratio,
            "resolution": use_resolution,
            "negative_prompt": preset["negative_prompt"],
        }
        if include_person_generation and preset.get("person_generation"):
            cfg_kwargs["person_generation"] = preset["person_generation"]
        return client.models.generate_videos(
            model=VEO_MODEL,
            source=genai.types.GenerateVideosSource(
                prompt=motion_prompt,
                image=genai.types.Image(
                    image_bytes=image_bytes,
                    mime_type=parsed.get("mime_type") or "image/png",
                ),
            ),
            config=genai.types.GenerateVideosConfig(**cfg_kwargs),
        )

    def _poll(operation):
        waited = 0.0
        while not getattr(operation, "done", False):
            if waited >= VEO_MAX_WAIT_SECONDS:
                raise HTTPException(
                    status_code=504,
                    detail=f"영상 생성 대기 시간 초과 ({VEO_MAX_WAIT_SECONDS}초). 잠시 후 다시 시도해주세요.",
                )
            time.sleep(VEO_POLL_SECONDS)
            waited += VEO_POLL_SECONDS
            operation = client.operations.get(operation)
            print(f"[VIDEO] Polling... waited={waited:.0f}s done={getattr(operation, 'done', False)}")
        if getattr(operation, "error", None):
            raise HTTPException(status_code=500, detail=f"Veo error: {operation.error}")
        return operation

    try:
        active_resolution = resolution

        def _start_veo():
            nonlocal active_resolution
            try:
                return _run_veo(include_person_generation=True, use_resolution=active_resolution)
            except Exception as start_err:
                err_text = str(start_err)
                # stretch의 allow_adult가 거절되면 person_generation 없이 재시도
                if motion_style == "stretch" and "personGeneration" in err_text:
                    print(f"[VIDEO] Retry without person_generation: {start_err}")
                    try:
                        return _run_veo(include_person_generation=False, use_resolution=active_resolution)
                    except Exception as retry_err:
                        start_err = retry_err
                        err_text = str(retry_err)
                # 1080p 미지원 시 720p로 폴백
                if active_resolution == "1080p" and ("resolution" in err_text.lower() or "1080" in err_text):
                    print(f"[VIDEO] Retry with 720p: {start_err}")
                    active_resolution = "720p"
                    try:
                        return _run_veo(include_person_generation=True, use_resolution="720p")
                    except Exception as res_err:
                        if motion_style == "stretch" and "personGeneration" in str(res_err):
                            return _run_veo(include_person_generation=False, use_resolution="720p")
                        raise
                raise start_err

        operation = _start_veo()
        operation = _poll(operation)
        video_bytes = _extract_video_bytes_from_operation(client, operation)
        elapsed = (datetime.datetime.now() - started).total_seconds()
        print(
            f"[VIDEO] Done | style={motion_style} | res={active_resolution} | "
            f"bytes={len(video_bytes)} | elapsed={elapsed:.1f}s"
        )

        video_b64 = base64.b64encode(video_bytes).decode("utf-8")

        # 로그/갤러리용 — 영상 바이너리 대신 제품컷 스틸을 저장하고 type=video로 기록
        try:
            now = datetime.datetime.now()
            ts = now.strftime("%Y%m%d_%H%M%S_%f")[:-3]
            still_bytes = image_bytes
            _push_to_hub_background(
                record={
                    "timestamp": now.strftime("%Y-%m-%d %H:%M:%S"), "ts": ts,
                    "app": "ai-fashion-eblin-pro", "type": "video",
                    "shot_label": "제품컷 스판 영상",
                    "motion_style": motion_style,
                    "duration_seconds": duration,
                    "resolution": active_resolution,
                    "custom_prompt": raw_prompt or "(none)",
                    "product_image_filenames": product_image_filenames,
                    "elapsed_sec": round(elapsed, 1),
                    "user_username": current_user["username"],
                    "user_name": current_user["name"],
                    "user_email": current_user["email"],
                    "user_logged_in": current_user["is_logged_in"],
                },
                image_bytes=still_bytes,
                ts=ts,
                product_images_b64=[current_image],
                product_filenames=product_image_filenames,
            )
        except Exception as hub_err:
            print(f"[HUB] Video log push failed: {hub_err}")

        return {
            "videoUrl": f"data:video/mp4;base64,{video_b64}",
            "durationSeconds": duration,
            "elapsedSec": int(max(1, round(elapsed))),
            "model": VEO_MODEL,
            "motionStyle": motion_style,
            "resolution": active_resolution,
        }
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Video generation failed: {str(e)}")

