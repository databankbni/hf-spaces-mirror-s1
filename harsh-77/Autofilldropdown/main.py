from fastapi.responses import FileResponse
import json
import os
import tempfile
from contextlib import asynccontextmanager

import torch
from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from rapidfuzz import fuzz, process
from transformers import AutoModelForCausalLM, AutoTokenizer

from database import get_all_dropdowns, init_db, resolve_related_fields

from pathlib import Path
env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=env_path)

try:
    from faster_whisper import WhisperModel
    USE_FASTER_WHISPER = True
except ImportError:
    import whisper
    USE_FASTER_WHISPER = False

# ── State shared across requests ──────────────────────────────────────────────
_whisper_model = None
_llm_tokenizer = None
_llm_model = None
_dropdowns: dict = {}

QWEN_MODEL_ID = os.getenv("QWEN_MODEL_ID", "Qwen/Qwen2.5-3B-Instruct")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _whisper_model, _llm_tokenizer, _llm_model, _dropdowns

    print("[startup] Resolving dropdown table from QA MySQL database …")
    init_db()
    _dropdowns = get_all_dropdowns()

    print("[startup] Loading Whisper base model …")
    if USE_FASTER_WHISPER:
        device = "cuda" if torch.cuda.is_available() else "cpu"
        compute_type = "float16" if torch.cuda.is_available() else "int8"
        _whisper_model = WhisperModel("base", device=device, compute_type=compute_type)
    else:
        _whisper_model = whisper.load_model("base")

    print(f"[startup] Loading {QWEN_MODEL_ID} …")
    _llm_tokenizer = AutoTokenizer.from_pretrained(QWEN_MODEL_ID)
    if torch.cuda.is_available():
        try:
            from transformers import BitsAndBytesConfig
            bnb_config = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_use_double_quant=True,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_compute_dtype=torch.float16
            )
            model_kwargs = {
                "quantization_config": bnb_config,
                "device_map": "auto",
            }
            print("[startup] Configuring model with 4-bit quantization for GPU load.")
        except Exception as e:
            print(f"[startup] Failed to configure 4-bit quantization: {e}. Falling back to 16-bit float.")
            model_kwargs = {
                "torch_dtype": torch.float16,
                "device_map": "auto",
            }
    else:
        model_kwargs = {
            "torch_dtype": torch.float32,
            "device_map": "cpu",
            "low_cpu_mem_usage": True,
        }

    _llm_model = AutoModelForCausalLM.from_pretrained(
        QWEN_MODEL_ID,
        **model_kwargs
    )
    print("[startup] All models ready.")
    yield


app = FastAPI(title="UA/UC AutoFill API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve the frontend from ../frontend
_frontend_dir = os.path.join(os.path.dirname(__file__), "..", "frontend")
if os.path.isdir(_frontend_dir):
    app.mount("/app", StaticFiles(directory=_frontend_dir, html=True), name="frontend")


# ── Helpers ───────────────────────────────────────────────────────────────────

def fuzzy_match(value: str, options: list[str], threshold: int = 40) -> str:
    if not value or not str(value).strip() or not options:
        return value or ""
    val_str = str(value).strip()

    # 1. Direct or case-insensitive match
    lower_map = {opt.lower(): opt for opt in options}
    if val_str.lower() in lower_map:
        return lower_map[val_str.lower()]

    # Common filler words to ignore/penalize in word-by-word comparison
    fillers = {
        "limited", "ltd", "pvt", "private", "co", "company", "corp", "corporation",
        "and", "of", "the", "for", "in", "at", "on", "with", "a", "an", "to"
    }

    # Split input value into words/chunks
    val_words = [w.strip(".,()[]{}").lower() for w in val_str.split()]
    val_words = [w for w in val_words if w]
    
    # Filter out fillers from input if there are other words
    val_non_fillers = [w for w in val_words if w not in fillers]
    words_to_match = val_non_fillers if val_non_fillers else val_words

    best_option = None
    max_score = -1.0

    for opt in options:
        opt_words = [w.strip(".,()[]{}").lower() for w in opt.split()]
        opt_words = [w for w in opt_words if w]
        opt_non_fillers = [w for w in opt_words if w not in fillers]

        # Calculate matching score
        score = 0.0
        matched_non_fillers = 0
        matched_fillers = 0

        for vw in words_to_match:
            word_matched = False
            
            # Exact match of word
            if vw in opt_words:
                if vw not in fillers:
                    score += 10.0
                    matched_non_fillers += 1
                else:
                    score += 1.0
                    matched_fillers += 1
                word_matched = True
            else:
                # Fuzzy match of word using RapidFuzz
                for ow in opt_words:
                    word_ratio = fuzz.ratio(vw, ow)
                    if word_ratio >= 80: # High similarity threshold for words
                        if ow not in fillers and vw not in fillers:
                            score += (word_ratio / 100.0) * 10.0
                            matched_non_fillers += 1
                        else:
                            score += (word_ratio / 100.0) * 1.0
                            matched_fillers += 1
                        word_matched = True
                        break

            # Substring match of word
            if not word_matched:
                for ow in opt_words:
                    if len(vw) > 2 and len(ow) > 2:
                        if vw in ow or ow in vw:
                            if ow not in fillers and vw not in fillers:
                                score += 5.0
                                matched_non_fillers += 1
                            else:
                                score += 0.5
                                matched_fillers += 1
                            break

        # Bonus if the entire option name contains the clean input value
        clean_val = " ".join(val_non_fillers)
        clean_opt = " ".join(opt_non_fillers)
        if clean_val and clean_val in clean_opt:
            score += 15.0

        if score > 0 and score > max_score:
            max_score = score
            best_option = opt

    # If we found a good score, return it
    if best_option and max_score >= 2.0:
        return best_option

    # Fallback to RapidFuzz token/WRatio if word-by-word didn't yield a strong match
    match_w = process.extractOne(val_str, options, scorer=fuzz.WRatio)
    match_t = process.extractOne(val_str, options, scorer=fuzz.token_set_ratio)

    best_match = match_w if (match_w and match_w[1] >= (match_t[1] if match_t else 0)) else match_t
    if best_match and best_match[1] >= threshold:
        return best_match[0]

    return value


def build_prompt(transcript: str, dropdowns: dict) -> str:
    schema = {
        "Company": "",
        "Service": "",
        "PlantProjectClient": "",
        "Department": "",
        "Contractor": "",
        "UAUCType": "",
        "Activity": "",
        "SubActivity": "",
        "RiskLevel": "",
        "Hazard": "",
        "SubHazard": "",
        "ControlMeasureViolations": "",
        "ResolveRights": "",
        "SourceRules": "",
        "ObservationDescription": "",
        "Location": "",
        "Zone": "",
        "NameOfViolator": "",
        "ViolatorID": "",
        "DateOfOccurrence": "",
        "RiskBasedDueDate": "",
        "ControlMeasureViolationDescription": "",
    }

#     return f"""You are SafetyFormAI, an enterprise HSE observation extraction engine.

# Convert the spoken safety observation transcript into JSON to autofill a UA/UC reporting form.

# CRITICAL CLASSIFICATION RULES FOR UAUCType:
# - "UA" (Unsafe Act): Use when the observation describes unsafe HUMAN BEHAVIOR, practice, or violation (e.g., worker not wearing helmet/PPE/safety harness, unsafe tool operation, standing under lifted load, speeding, improper posture, bypassing procedure).
# - "UC" (Unsafe Condition): Use when the observation describes a physical/environmental HAZARD or DEFECT (e.g., unbarricaded excavation, oil spill, exposed electrical wire, damaged scaffolding, missing guardrails, gas leak, slippery surface, poor lighting).

# DROPDOWN MATCHING & PARTIAL NAME RULES:
# - For dropdown fields (Company, Service, PlantProjectClient, Department, Contractor, UAUCType, Activity, SubActivity, RiskLevel, Hazard, SubHazard, ControlMeasureViolations, ResolveRights, SourceRules, Location, Zone):
#   Match to the closest matching option from the dropdown list provided below. Even if spoken text contains partial or misspelled names (e.g. "Omravati" -> "Amravati"), map to the exact matching dropdown option.
# - For all other fields (ObservationDescription, NameOfViolator, ViolatorID, DateOfOccurrence, RiskBasedDueDate, ControlMeasureViolationDescription): extract verbatim as spoken.
# - Return ONLY valid JSON, no explanation.

# Dropdown options available:
# {json.dumps(dropdowns, indent=2)}

# Output schema (fill every key):
# {json.dumps(schema, indent=2)}

# Transcript:
# {transcript}
# """


    return f"""
You are SafetyFormAI, an enterprise-grade HSE (Health, Safety & Environment) observation extraction and dropdown entity-resolution engine used in industrial plants, EPC projects, refineries, manufacturing facilities, construction sites, warehouses, utilities, and process industries.

Your task is to convert a spoken safety observation transcript into STRICT JSON that can directly autofill a UA/UC reporting form.

############################
## OUTPUT RULES (MANDATORY)
############################

- Return ONLY valid JSON.
- Do not return markdown, code fences, comments, explanations, or extra text.
- Every key from the provided output schema MUST be present.
- Do NOT try to match dropdown fields to the dropdown options yourself. Simply extract the raw value/entity name as spoken or directly referenced in the transcript (e.g. if the transcript mentions "APEX limited" or "Apex", output "APEX limited" or "Apex" for Company).
- The backend performs the fuzzy matching database resolution. If nothing matching the field was mentioned or can be inferred at all, return an empty string ("").

############################################
## THINK LIKE AN HSE OFFICER, NOT A CHATBOT
############################################

The transcript may contain:
- incomplete information
- partial names
- abbreviations
- acronyms
- local pronunciation
- Hindi-English mixed speech
- speech recognition mistakes
- filler words
- repeated words
- reordered phrases
- missing grammar

Normalize the transcript mentally before extraction.

############################################
## UA / UC CLASSIFICATION (MANDATORY)
############################################

UA = Unsafe Act

Choose "UA" when the observation primarily describes unsafe human behavior, unsafe work practice, procedural violation, negligence, or PPE non-compliance.

Examples:
- helmet not worn
- safety harness not used
- gloves missing
- goggles not worn
- standing below suspended load
- operating machine without guard
- bypassing safety interlock
- not following permit procedure
- smoking in prohibited area
- using mobile phone while driving
- speeding
- improper lifting

UC = Unsafe Condition

Choose "UC" when the observation primarily describes a physical, environmental, structural, electrical, chemical, mechanical, or housekeeping hazard.

Examples:
- oil spill
- water leakage
- exposed electrical wire
- damaged scaffold
- broken ladder
- missing guardrail
- open excavation
- no barricading
- slippery floor
- poor lighting
- gas leak
- damaged cable
- loose platform
- missing warning sign
- obstructed emergency exit

If both are present, choose the PRIMARY cause.

############################################
## DROPDOWN ENTITY RESOLUTION (VERY IMPORTANT)
############################################

For these fields:
- Company
- Service
- PlantProjectClient
- Department
- Contractor
- UAUCType
- Activity
- SubActivity
- RiskLevel
- Hazard
- SubHazard
- ControlMeasureViolations
- ResolveRights
- SourceRules
- Location
- Zone

perform AGGRESSIVE entity resolution.

#########################
## DROPDOWN EXTRACTION RULE
#########################

Extract the raw mentioned name/entity from the transcript. Do NOT try to map it to the dropdown options yourself. Simply output the raw spoken or inferred term, even if misspelled or abbreviated.

Examples:
- Transcript: "Omravati plant" -> Zone: "Omravati" (do NOT map to Amravati)
- Transcript: "APEX limited" -> Company: "APEX limited" (do NOT map to Apex Engineering Ltd.)
- Transcript: "L&T contractor" -> Contractor: "L&T" (do NOT map to Larsen & Toubro)
- Transcript: "Adonis Solar" -> PlantProjectClient: "Adonis Solar" (do NOT map to Adani Solar Park Development)

############################################
## CONTEXT-BASED SAFETY MAPPING
############################################

Infer dropdown fields from the observation.

Examples:

Observation: "Worker was welding without face shield."

Activity → Hot Work / Welding

Hazard → PPE / Welding / Fire

SubHazard → Face protection missing

ControlMeasureViolations → PPE violation

Observation: "Excavation area had no barricading."

Activity → Excavation

Hazard → Excavation

SubHazard → Unbarricaded excavation

ControlMeasureViolations → Barricading violation

############################################
## RISK LEVEL INFERENCE
############################################

Infer RiskLevel if not explicitly spoken.

High:
- fall from height
- electrical contact
- confined space
- suspended load
- gas leak
- fire/explosion potential
- heavy equipment interaction

Medium:
- moving machinery
- scaffold issue
- moderate PPE violation
- manual handling
- vehicle movement

Low:
- housekeeping issue
- minor obstruction
- small spill
- low-consequence observation

Use only if a matching dropdown option exists.

############################################
## HAZARD & SUBHAZARD INFERENCE
############################################

Map observations intelligently.

- helmet missing → PPE
- harness missing → Working at Height
- exposed wire → Electrical
- oil spill → Slip / Housekeeping
- water on floor → Slip
- damaged scaffold → Structural / Scaffold
- missing guardrail → Fall protection
- open pit → Excavation
- gas smell → Chemical / Gas
- leaking valve → Mechanical / Process

############################################
## CONTROL MEASURE VIOLATION MAPPING
############################################

Map natural language to the nearest dropdown option.

- no helmet → PPE violation
- no gloves → PPE violation
- no permit → PTW violation
- no barricading → Barricading violation
- guard removed → Machine guarding violation
- unsafe scaffold → Scaffolding violation
- no lockout → LOTO violation
- harness not attached → Working at Height violation

############################################
## TEXT EXTRACTION (VERBATIM)
############################################

Extract exactly as spoken for:
- ObservationDescription
- NameOfViolator
- ViolatorID
- DateOfOccurrence
- RiskBasedDueDate
- ControlMeasureViolationDescription

Do not paraphrase names or IDs.

############################################
## DATE NORMALIZATION
############################################

Convert spoken dates into ISO format (YYYY-MM-DD) when possible.

Examples:
- today
- yesterday
- 5 August 2026
- August five twenty twenty six
- 05/08/2026
- 5-8-26

If uncertain, preserve the spoken text.

############################################
## CONFIDENCE RULE
############################################

For dropdown fields:
If confidence is moderate or high, choose the dropdown value.
Prefer the BEST AVAILABLE dropdown match over a blank field.

Example:

Transcript:
"Omravati plant mechanical maintenance contractor welding without helmet."

Expected mapping:
- Location → Amravati
- Department → Mechanical
- Service → Maintenance
- Activity → Welding
- UAUCType → UA
- Hazard → PPE

############################################
## FINAL VALIDATION
############################################

Before returning JSON:
- ensure every schema key exists
- extract dropdown entities as they are spoken or referenced, do not try to match option names exactly
- ensure UA/UC classification is correct
- ensure dates are normalized when possible
- ensure no extra keys are added

############################################
## FEW-SHOT EXAMPLES
############################################


############################################
## DROPDOWN OPTIONS
############################################

{json.dumps(dropdowns, indent=2)}

############################################
## REQUIRED OUTPUT SCHEMA
############################################

{json.dumps(schema, indent=2)}

############################################
## TRANSCRIPT
############################################

{transcript}
"""

def run_llm(transcript: str) -> dict:
    prompt = build_prompt(transcript, _dropdowns)
    messages = [
        {"role": "system", "content": "Return only valid JSON. No explanation."},
        {"role": "user", "content": prompt},
    ]
    text = _llm_tokenizer.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True
    )
    inputs = _llm_tokenizer(text, return_tensors="pt").to(_llm_model.device)

    with torch.no_grad():
        output = _llm_model.generate(
            **inputs,
            max_new_tokens=600,
            do_sample=False,
            temperature=None,
            top_p=None,
            top_k=None,
        )

    generated = _llm_tokenizer.decode(
        output[0][inputs.input_ids.shape[-1] :], skip_special_tokens=True
    )

    print("------ RAW LLM GENERATION ------")
    print(generated)
    print("--------------------------------")

    start = generated.find("{")
    end = generated.rfind("}")
    data = json.loads(generated[start : end + 1])
    
    print("------ PARSED LLM DATA ------")
    print(json.dumps(data, indent=2))
    print("-----------------------------")

    dropdown_fields = [
        "Company", "Service", "PlantProjectClient", "Department", "Contractor",
        "UAUCType", "Activity", "SubActivity", "RiskLevel", "Hazard", "SubHazard",
        "ControlMeasureViolations", "ResolveRights", "SourceRules", "Location", "Zone",
    ]
    for field in dropdown_fields:
        options = _dropdowns.get(field, [])
        if options:
            data[field] = fuzzy_match(data.get(field, ""), options)

    data = resolve_related_fields(data)
    return data


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/api/dropdowns")
def get_dropdowns():
    """Return all dropdown options fetched from the QA database."""
    return get_all_dropdowns()


@app.post("/api/transcribe")
async def transcribe_audio(file: UploadFile = File(...)):
    """Accept an audio file and return the Whisper transcript."""
    if _whisper_model is None:
        raise HTTPException(status_code=503, detail="Whisper model not loaded yet")

    suffix = os.path.splitext(file.filename or "audio.webm")[1] or ".webm"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    try:
        if USE_FASTER_WHISPER:
            segments, info = _whisper_model.transcribe(tmp_path)
            transcript = " ".join([s.text for s in segments]).strip()
        else:
            result = _whisper_model.transcribe(tmp_path)
            transcript = result["text"].strip()
    finally:
        os.unlink(tmp_path)

    return {"transcript": transcript}



class AutofillRequest(BaseModel):
    transcript: str

@app.get("/")
def home():
    # return FileResponse(os.path.join(_frontend_dir, "index.html"))
    return {"message": "Welcome to the UA/UC AutoFill API!"}

@app.post("/api/autofill")
def autofill_form(req: AutofillRequest):
    """Run the LLM extraction + fuzzy match and return form field values."""
    if _llm_model is None:
        raise HTTPException(status_code=503, detail="LLM not loaded yet")
    try:
        data = run_llm(req.transcript)
        return data
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/health")
@app.get("/api/status")
@app.get("/api/health")
def health():
    return {
        "whisper": _whisper_model is not None,
        "llm": _llm_model is not None,
    }


@app.get("/")
def root():
    return {
        "message": "Welcome to the UA/UC AutoFill API!",
    }

