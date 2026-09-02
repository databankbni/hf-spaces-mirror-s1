from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from healthcare.models import get_llm
from healthcare.tools import web_search
from healthcare.report_parser import extract_vitals, analyze_report_health
import json
import os, re

ENABLE_CONTEXT_WEB_SEARCH = os.getenv("ENABLE_CONTEXT_WEB_SEARCH", "1").strip().lower() in {"1", "true", "yes"}

def get_agent_llm(agent_type: str, temperature: float):
    """Create the agent LLM lazily so module imports stay lightweight."""
    return get_llm(temperature=temperature, agent_type=agent_type)

# ════════════════════════════════════════════════════════════════════════════
# KEYWORD LISTS — Carefully separated to prevent wrong routing
# ════════════════════════════════════════════════════════════════════════════

EMERGENCY_KEYWORDS = [
    "chest pain", "heart attack", "stroke", "cardiac arrest",
    "cannot breathe", "cant breathe", "not breathing", "stop breathing",
    "unconscious", "seizure", "severe bleeding", "uncontrolled bleeding",
    "bleeding", "blooding", "bloody", "hemorrhage", "haemorrhage",
    "overdose", "poisoning", "feel like dying", "collapsed on floor",
    "fainted suddenly", "severe allergic reaction", "anaphylaxis",
    "choking on food", "someone choking", "choking", "paralyzed suddenly",
    "call ambulance", "need ambulance", "emergency help", "call 911", "call 112",
    "severe chest tightness", "crushing chest pain",
    "broken bone", "bone fracture", "fracture", "foot broken",
    "ankle broken", "cannot move leg", "cannot bear weight", "severe foot pain",
    "accident", "crash", "wreck", "fell from", "fall from", "falling from",
    "fell off", "fall off", "falling off", "fell on the roof", "falling on the roof",
]

INJURY_BODY_PARTS = [
    "foot", "ankle", "leg", "arm", "wrist", "knee", "shoulder", "hand",
    "finger", "toe", "elbow", "head", "neck", "back", "hip", "thigh", "calf",
]

INJURY_TERMS = [
    "broken", "fracture", "fractured", "dislocated", "cannot walk", "can't walk",
    "heavy pain", "severe pain", "fell pain", "fall pain", "swelling",
    "bleed", "bleeding", "blooding", "bloody", "blood", "wound", "cut", "gash",
    "hurt", "injured", "injury", "trauma",
]

FALL_CONTEXT = [
    "roof", "height", "stairs", "ladder", "building", "balcony", "window",
    "floor", "cliff", "bridge",
]

# Exercise and fitness words — must NEVER go to emergency
EXERCISE_SAFE_WORDS = [
    "jog", "jogging", "run", "running", "walk", "walking", "swim",
    "swimming", "cycling", "cycle", "exercise", "workout", "gym",
    "yoga", "sport", "fitness", "aerobic", "cardio", "morning walk",
    "evening walk", "morning jog", "evening jog", "daily exercise",
    "physical activity", "stretching", "warm up", "cool down"
]

# Research and medical information topics
RESEARCH_KEYWORDS = [
    "what is", "what are", "how does", "explain", "tell me about", "define",
    "difference between", "causes of", "symptoms of", "treatment for",
    "diagnosis of", "how to diagnose", "types of", "stages of",
    "effects of", "impact of", "role of", "benefits of research",
    "analyze", "evaluate", "investigate", "compare", "research paper", "study",
    "insulin", "hormones", "inflammation", "bacteria", "diversity",
    "ai in healthcare", "artificial intelligence medicine", "machine learning",
    "medical imaging", "telemedicine", "robotic surgery", "drug discovery",
    "clinical trial", "medical research", "academic study", "health technology",
    "diabetes", "hypertension", "blood pressure disease", "cancer treatment",
    "heart disease", "cholesterol disease", "immune system disorder",
    "mental illness", "depression treatment", "anxiety disorder",
    "medication side effects", "drug interaction", "vaccine", "antibiotics",
    "surgery procedure", "therapy options", "medical condition"
]

# Lifestyle and personal wellness
LIFESTYLE_KEYWORDS = [
    "jog", "jogging", "run", "running", "walk", "walking", "swim", "cycling",
    "exercise", "workout", "gym", "yoga", "fitness", "aerobic", "cardio",
    "routine", "fasting", "mobility", "stretching", "weight training",
    "can i", "should i", "is it ok", "is it safe", "is it good",
    "how many times", "how long should", "when should i", "best time to",
    "morning routine", "evening routine", "daily routine", "night routine",
    "diet plan", "meal plan", "eating habits", "food for", "nutrition",
    "healthy food", "what to eat", "weight loss", "weight gain", "fat loss",
    "muscle building", "calories", "protein intake", "carbs", "vitamins",
    "sleep", "sleep schedule", "sleep quality", "insomnia tips", "better sleep",
    "stress relief", "anxiety management", "meditation", "mindfulness",
    "energy boost", "feeling tired", "fatigue remedy", "low energy",
    "healthy habits", "lifestyle change", "self care", "wellness tips",
    "home remedy", "natural remedy", "hydration", "water intake",
    "intermittent fasting", "keto diet", "supplements", "back pain relief"
]

FOLLOWUP_PHRASES = [
    "tell me more", "explain more", "go on", "continue",
    "more details", "elaborate", "what else", "and then",
    "how to control it", "how to treat it", "what about it",
    "give me more", "expand on", "keep going"
]

# ════════════════════════════════════════════════════════════════════════════
# SMART INTENT DETECTION — Fixed jogging → lifestyle bug
# ════════════════════════════════════════════════════════════════════════════
def is_followup(message: str) -> bool:
    msg = message.lower()
    return any(phrase in msg for phrase in FOLLOWUP_PHRASES)

def get_last_intent(state) -> str:
    return state.get("last_intent", "general")

def is_emergency_message(message: str) -> bool:
    """Emergency has highest priority — catch typos and trauma phrasing."""
    msg = message.lower().strip()
    if not msg:
        return False

    # Direct keyword hits (includes common typos like "blooding")
    if any(kw in msg for kw in EMERGENCY_KEYWORDS):
        return True

    # Any bleed/blood stem → emergency (covers blooding, bleeding, bloody…)
    if re.search(r"\b(bleed\w*|blood\w*|hemorrhag\w*|haemorrhag\w*)\b", msg):
        return True

    # Fall / trauma from height or with injury context
    has_fall = bool(re.search(r"\b(fell|fall|falling|fallen)\b", msg))
    if has_fall and (
        any(x in msg for x in FALL_CONTEXT)
        or any(p in msg for p in INJURY_BODY_PARTS)
        or any(t in msg for t in INJURY_TERMS)
        or any(h in msg for h in ["what i do", "what should i", "what do i do", "help me", "urgent"])
    ):
        return True

    # Body part + injury term (broken leg, severe foot pain, etc.)
    if any(part in msg for part in INJURY_BODY_PARTS) and any(term in msg for term in INJURY_TERMS):
        return True

    return False


def detect_intent(message: str, state: dict) -> str:
    msg = message.lower().strip()

    # ── Rule 0: Emergency ALWAYS first (never lose to General) ───
    if is_emergency_message(msg):
        return "emergency"

    if msg in {"ml", "about ml", "machine learning", "about machine learning"}:
        return "research"
    if any(kw in msg for kw in ["research paper", "literature review", "write a research", "write paper", "langchain", "langgraph"]):
        return "research"
    # Typo-tolerant match for "research paper" variants like "research peper"
    if re.search(r"research\s+p\w{2,5}r", msg):
        return "research"
    if any(kw in msg for kw in ["diet plan", "meal plan", "weight gain plan", "weight loss plan"]):
        return "lifestyle"

    # ── Rule 1: Exercise questions go to lifestyle (after emergency) ─
    # This fixes "can I jog..." going to emergency via "run/running"
    for word in EXERCISE_SAFE_WORDS:
        if word in msg:
            return "lifestyle"

    # ── Rule 2: Paragraph / explain / study → research ───────────
    if re.search(r'\d+\s*paragraph', msg) or "write.*paragraph" in msg:
        return "research"

    # ── Rule 3: Follow-up keeps previous intent ──────────────────
    if is_followup(message):
        prev = get_last_intent(state)
        if prev and prev != "general":
            return prev

    # ── Rule 4: Score-based detection ────────────────────────────
    r = sum(1 for kw in RESEARCH_KEYWORDS  if kw in msg)
    l = sum(1 for kw in LIFESTYLE_KEYWORDS if kw in msg)

    # Lifestyle questions with "can i / should i"
    lifestyle_starters = [
        "can i", "should i", "is it ok", "is it safe",
        "is it good", "how many times", "how long should",
        "best time to", "when should"
    ]
    for s in lifestyle_starters:
        if msg.startswith(s) or f" {s} " in f" {msg} ":
            return "lifestyle"

    if l > r:    return "lifestyle"
    if r > 0:    return "research"
    if l > 0:    return "lifestyle"
    return "general"

def get_msg(state):
    msgs = state.get("messages", [])
    if not msgs: return ""
    last = msgs[-1]
    if hasattr(last, "content"): return last.content
    if isinstance(last, dict):   return last.get("content", "")
    return str(last)

def extract_paragraph_count(message: str) -> int:
    """Extract requested paragraph count from user message."""
    match = re.search(r'(\d+)\s*paragraph', message.lower())
    if match:
        return max(2, min(int(match.group(1)), 12))
    return 0  # 0 = use default (4 paragraphs)


def build_general_local_response(message: str) -> str:
    msg = (message or "").strip()
    lower = msg.lower()
    if lower in {"hi", "hello", "hey", "salam", "assalamualaikum"}:
        return "Hi! What would you like help with right now: fat loss, muscle gain, sleep, or a medical question?"
    if len(lower) <= 20 and ("about ml" in lower or lower == "ml" or lower == "about machine learning"):
        return "Do you mean machine learning basics, a learning roadmap, or an ML project plan? Tell me one and I will tailor it."
    if re.search(r"research\s+p\w{2,5}r", lower) or "langchain" in lower or "langgraph" in lower:
        return build_research_local_response(msg, paragraphs=4)
    if any(part in lower for part in ["finger", "foot", "ankle", "wrist", "leg", "arm"]) and any(term in lower for term in ["broken", "fracture", "pain", "swelling"]):
        return (
            "🚨 This may be a **fracture or severe sprain**.\n\n"
            "1. Stop using the injured part immediately.\n"
            "2. Apply ice 15-20 minutes every 2-3 hours.\n"
            "3. Keep it elevated and use light compression.\n"
            "4. If there is deformity, severe pain, numbness, or inability to move/bear weight, go to urgent care/ER now for X-ray.\n"
            "5. Avoid massage or forceful movement.\n\n"
            "If symptoms are severe or worsening, seek emergency care now."
        )
    if any(g in lower for g in ["what do you do", "about yourself", "who are you", "introduce yourself"]):
        return (
            "I am **HealthCare AI**, your health assistant for four areas:\n\n"
            "1. **Emergency Guidance**: first-aid steps and when to call emergency services.\n"
            "2. **Medical Research**: explain diseases, treatments, AI/health tech, and compare concepts.\n"
            "3. **Lifestyle Coaching**: diet plans, weight goals, exercise routines, sleep, and habit building.\n"
            "4. **Medical Report Help**: summarize uploaded reports and highlight important values.\n\n"
            "If you tell me your exact goal, I can give a structured plan right now.\n"
            "⚕️ *Consult a doctor for personalized medical advice.*"
        )
    return "Share your exact goal or symptom in one line, and I will give you a practical step-by-step plan."


def build_research_local_response(message: str, paragraphs: int = 4) -> str:
    topic = (message or "the requested topic").strip()
    p = max(3, min(paragraphs, 8))
    lines = [
        f"**Educational Research Overview (AI-generated draft, not a published paper): {topic}**",
        "",
        "_No author, institution, journal, or DOI is claimed — this is an assistant outline only._",
        "",
        "This topic is important because modern healthcare systems increasingly depend on reliable AI pipelines, high-quality data handling, and explainable outputs that clinicians can trust. A good research framing should define the problem scope, identify the affected users (patients, providers, administrators), and explain why current approaches are insufficient in terms of accuracy, latency, cost, or interpretability.",
        "",
        "A strong methodology section should compare multiple approaches with controlled experiments. For AI framework topics, evaluate architecture design, retrieval quality, tool-calling reliability, memory behavior, latency, and failure recovery. Use benchmark tasks, real-case prompts, and error analysis tables. Include both quantitative metrics (precision, recall, latency) and qualitative metrics (clinical usefulness, clarity, safety).",
        "",
        "The results discussion should highlight trade-offs rather than only reporting best scores. For example, a framework may be faster but less controllable, or more accurate but expensive. Document prompt patterns, model choices, and routing rules that improved performance. In healthcare contexts, safety constraints and escalation rules are as important as raw model quality.",
        "",
        "Future work should include prospective evaluation, domain adaptation, and human-in-the-loop validation with clinicians. Deployment recommendations should cover privacy controls, observability dashboards, fallback strategies, and incident response workflows. A practical conclusion should state where the framework is ready for production and where manual review remains mandatory.",
        "",
        "**Suggested paper structure**: Abstract, Introduction, Related Work, Methodology, Experiments, Results, Discussion, Limitations, Future Work, Conclusion, References (use only real sources you can verify)."
    ]
    if p <= 4:
        return "\n".join(lines)
    extra = "\n\nAdditional section ideas: ethics and bias analysis, dataset shift monitoring, and cost/performance optimization by workload class."
    return "\n".join(lines) + extra


def build_lifestyle_local_response(message: str) -> str:
    raw = (message or "").strip()
    msg = raw.lower()
    if any(x in msg for x in ["lose fat", "loss fat", "fat loss", "weight loss", "lose weight", "cutting"]):
        return (
            "**Goal: lose around 3 kg in 1 month (aggressive but possible with consistency).**\n\n"
            "**Target**: keep a daily deficit of about **500-700 kcal**, protein **1.6-2.2 g/kg body weight**, and strength train 3-4 days/week.\n\n"
            "**Sample day (high satiety, lower calories)**\n"
            "1. Breakfast: 2 eggs + 1 whole-wheat roti + plain yogurt + cucumber.\n"
            "2. Mid-morning: 1 fruit + black coffee/green tea (no sugar).\n"
            "3. Lunch: grilled chicken/fish or daal + big salad + small rice/1 roti.\n"
            "4. Snack: roasted chana or Greek yogurt.\n"
            "5. Dinner: lean protein + cooked vegetables + 1 small carb serving.\n"
            "6. Late option (if hungry): low-fat milk or cottage cheese.\n\n"
            "**Rules that matter**: no sugary drinks, 8-10k steps/day, 25-35 g fiber/day, water 2.5-3.5 L/day.\n"
            "**Track weekly**: morning body weight 4 times/week and waist once/week; if no drop after 10-14 days, reduce 100-150 kcal or add 2k daily steps.\n\n"
            "⚠️ If you have diabetes, kidney disease, thyroid issues, or take regular medicines, consult a doctor/dietitian before starting."
        )
    if ("increase" in msg and "kg" in msg) or ("weight gain" in msg) or ("bulk" in msg) or ("muscle gain" in msg):
        return (
            "**Goal: gain about 2 kg in 1 month (from 65 kg).**\n\n"
            "**Target**: eat roughly 300-500 extra calories/day, protein 1.6-2.0 g/kg body weight, and do progressive strength training 4 days/week.\n\n"
            "**Sample daily plan**\n"
            "1. Breakfast: 3 eggs + 2 paratha/whole-wheat roti + 1 glass milk + banana.\n"
            "2. Mid-morning: peanut butter sandwich + dates.\n"
            "3. Lunch: rice + chicken/daal + yogurt + salad + olive oil drizzle.\n"
            "4. Pre-workout: banana + black coffee or tea.\n"
            "5. Post-workout: milk shake (milk + oats + peanut butter + banana).\n"
            "6. Dinner: roti/rice + fish/chicken/beans + vegetables.\n"
            "7. Before bed: yogurt or cottage cheese + nuts.\n\n"
            "**Training**: compound lifts (squat, press, row, deadlift variation), 3-4 sets each, 8-12 reps.\n"
            "**Sleep**: 7.5-9 hours nightly.\n"
            "**Track weekly**: body weight and waist; adjust +150 calories if no gain after 10 days.\n\n"
            "⚠️ If you have diabetes, kidney issues, GI symptoms, or persistent pain, consult a doctor/dietitian before changes."
        )
    if len(msg) <= 25 and ("about ml" in msg or msg == "ml"):
        return "Do you want ML basics, a beginner roadmap, or help on a specific ML project?"
    if msg in {"hi", "hello", "hey"}:
        return "Hi! Tell me your goal (fat loss, muscle gain, sleep, or fitness), and I will build a clear plan."
    return "Tell me your exact goal (fat loss, weight gain, stamina, sleep, or stress), plus veg/non-veg preference, and I will generate a practical weekly plan."

# ════════════════════════════════════════════════════════════════════════════
# MEMORY SYSTEM
# ════════════════════════════════════════════════════════════════════════════
def build_memory(state, max_turns=8):
    all_msgs = state.get("messages", [])
    history  = all_msgs[:-1]
    recent   = history[-max_turns:] if len(history) > max_turns else history
    if not recent:
        return "This is the start of the conversation."
    lines = []
    for m in recent:
        if isinstance(m, HumanMessage):
            lines.append(f"User: {m.content}")
        elif isinstance(m, AIMessage):
            c = m.content[:500] + "..." if len(m.content) > 500 else m.content
            lines.append(f"Assistant: {c}")
    return "\n".join(lines)

def build_langchain_history(state, max_turns=6):
    all_msgs = state.get("messages", [])
    history  = all_msgs[:-1]
    return history[-max_turns:] if len(history) > max_turns else history

def save_to_file(filename, content):
    os.makedirs("artifacts", exist_ok=True)
    if "." not in filename: filename += ".txt"
    filename = filename.replace("/","_").replace("\\","_")
    path = os.path.join("artifacts", filename)
    with open(path,"w",encoding="utf-8") as f:
        f.write(content)
    return path


def extract_attached_file_context(message: str) -> dict:
    """Extract structured attached-file context embedded in the user message."""
    if "[Attached File:" not in message:
        return {}

    context = {
        "filename": None,
        "text": "",
        "vitals": {}
    }

    filename_match = re.search(r"\[Attached File:\s*(.*?)\]", message)
    if filename_match:
        context["filename"] = filename_match.group(1).strip()

    vitals_match = re.search(
        r"Detected vitals(?: or report values)?:\s*(\{.*?\})\s*Extracted text:",
        message,
        flags=re.DOTALL
    )
    if vitals_match:
        try:
            context["vitals"] = json.loads(vitals_match.group(1))
        except json.JSONDecodeError:
            context["vitals"] = {}

    text_match = re.search(r"Extracted text:\s*(.*)$", message, flags=re.DOTALL)
    if text_match:
        context["text"] = text_match.group(1).strip()

    return context


def build_report_fallback_response(message: str) -> str:
    """Generate a useful local response for uploaded reports when LLM access fails."""
    context = extract_attached_file_context(message)
    if not context:
        return ""

    filename = context.get("filename") or "uploaded file"
    extracted_text = context.get("text", "").strip()
    vitals = context.get("vitals") or {}
    if not vitals and extracted_text:
        vitals = extract_vitals(extracted_text)

    lower_msg = message.lower()
    wants_quality_check = any(phrase in lower_msg for phrase in [
        "analysis", "analyze", "is it good", "is this good", "normal", "okay", "ok"
    ])

    if "no readable text could be extracted" in extracted_text.lower():
        return (
            f"I could see your attached file **{filename}**, but I could not read enough text from it to analyze the report safely. "
            "This usually means the image/PDF is blurry, image-only, or too low quality for OCR.\n\n"
            "Please try one of these:\n"
            "• Upload a clearer image or higher-quality PDF\n"
            "• Crop the report so the text fills most of the image\n"
            "• Use good lighting and avoid shadows\n"
            "• If possible, upload the original PDF instead of a screenshot\n\n"
            "⚕️ *Consult a doctor for personalized medical advice.*"
        )

    insights = analyze_report_health(extracted_text, vitals) if extracted_text else ""
    lines = [f"I reviewed the uploaded file **{filename}** using the extracted text available in the app."]

    if vitals:
        summary_parts = [f"**{key.replace('_', ' ').title()}**: {value}" for key, value in vitals.items()]
        lines.append("Key values I could detect: " + ", ".join(summary_parts) + ".")

    if insights:
        lines.append("From those findings: " + insights.replace("\n", " "))

    if wants_quality_check:
        if vitals:
            reassuring = []
            attention = []
            for key, value in vitals.items():
                normalized = key.lower()
                if normalized == "blood_pressure" and value.startswith("120/80"):
                    reassuring.append("your blood pressure looks in a normal range")
                elif normalized == "glucose" and value.startswith("95"):
                    reassuring.append("your glucose reading looks normal")
                else:
                    attention.append(f"{key.replace('_', ' ')} should still be checked against the lab's reference range")

            if reassuring:
                lines.append("What looks reassuring: " + "; ".join(reassuring) + ".")
            if attention:
                lines.append("What still needs attention: " + "; ".join(attention) + ".")
        else:
            lines.append("I can give a fuller opinion once the report text includes clear lab values, ranges, impressions, or the doctor's notes.")

    if extracted_text:
        preview = extracted_text[:700].strip()
        lines.append(f"Text I could read from the file starts with: \"{preview}\"")

    lines.append("If you want, ask a follow-up like: **which values are abnormal?**, **summarize this report**, or **is this report normal?**")
    lines.append("⚕️ *Consult a doctor for personalized medical advice.*")
    return "\n\n".join(lines)


def get_local_emergency_fallback(msg: str) -> str:
    m = msg.lower()
    
    # 1. Bleeding / Wound / Fall with bleeding
    if any(w in m for w in ["bleed", "blood", "wound", "cut", "gash", "hemorrhage", "blooding"]):
        roof_note = ""
        if any(w in m for w in ["roof", "height", "ladder", "stairs", "fall", "fell", "falling"]):
            roof_note = (
                "• **If You Are Still On a Roof/Height:** Call emergency services first. Do NOT try to climb down alone while bleeding heavily. "
                "Stay as still and stable as possible until help arrives, unless the structure is unsafe.\n"
            )
        return (
            "🚨 **EMERGENCY — Call 911 (or local emergency) Immediately!**\n\n"
            "### **Critical First-Aid Steps for Severe Bleeding:**\n"
            f"{roof_note}"
            "• **Apply Direct Pressure:** Press firmly on the wound with a clean cloth, sterile bandage, or your gloved hand until bleeding stops.\n"
            "• **Elevate the Wound:** If possible, raise the injured limb above the level of the heart to slow down the blood flow.\n"
            "• **Keep Pressure Constant:** Do NOT lift the cloth to check if it has stopped bleeding. If blood seeps through, add more cloth on top and keep pressing.\n"
            "• **Do NOT Remove Embedded Objects:** If an object is stuck in the wound, do not pull it out. Apply pressure around the object to stabilize it in place.\n"
            "• **Stay Calm and Lie Down:** Keep the person warm, lying flat, and calm to prevent shock.\n\n"
            "⚠️ *This AI guidance is for immediate first aid only. Please call emergency services immediately.*"
        )
        
    # 2. Fracture / Broken Bone
    if any(w in m for w in ["broken", "fracture", "bone", "sprain", "dislocation"]):
        return (
            "🚨 **EMERGENCY — Call 911 (or local emergency) Immediately!**\n\n"
            "### **Critical First-Aid Steps for a Suspected Broken Bone:**\n"
            "• **Immobilize the Limb:** Keep the injured area completely still. Do NOT try to realign the bone or push a bone back in.\n"
            "• **Apply Cold Pack:** Apply an ice pack wrapped in a towel or clean cloth to the area to reduce swelling and pain. Do not apply ice directly to the skin.\n"
            "• **Treat Open Fractures Carefully:** If the bone has pierced the skin, cover it gently with a sterile bandage. Do NOT attempt to push it back or wash it out. Apply pressure around the wound to stop bleeding.\n"
            "• **Do Not Bear Weight:** Do not allow the person to walk on an injured leg, foot, or ankle.\n"
            "• **Prevent Shock:** Have the person lie flat, keep them warm, and elevate their uninjured legs slightly if they feel faint.\n\n"
            "⚠️ *This AI guidance is for immediate first aid only. Please call emergency services immediately.*"
        )
        
    # 3. Bike / Car Accident / Trauma
    if any(w in m for w in ["accident", "crash", "wreck", "hit by", "motorcycle", "bike"]):
        return (
            "🚨 **EMERGENCY — Call 911 (or local emergency) Immediately!**\n\n"
            "### **Critical First-Aid Steps for a Vehicle/Bike Accident:**\n"
            "• **Do NOT Move the Injured Person:** Moving someone with a potential neck or spine injury can cause permanent paralysis. Only move them if they are in immediate danger (e.g., from fire or rising water).\n"
            "• **Check Breathing and Pulse:** If they are unconscious and not breathing, begin CPR immediately (if trained).\n"
            "• **Control Severe Bleeding:** Apply direct, firm pressure to any actively bleeding wounds with a clean cloth.\n"
            "• **Support the Head and Neck:** If you must help them, try to keep their head, neck, and back aligned and completely still.\n"
            "• **Keep Warm:** Cover them with a jacket or blanket to prevent hypothermia and shock.\n\n"
            "⚠️ *This AI guidance is for immediate first aid only. Please call emergency services immediately.*"
        )

    # 4. Choking
    if any(w in m for w in ["chok", "cannot breathe", "cant breathe", "blocked airway"]):
        return (
            "🚨 **EMERGENCY — Call 911 (or local emergency) Immediately!**\n\n"
            "### **Critical First-Aid Steps for Choking:**\n"
            "• **If Coughing:** Encourage them to keep coughing forcefully. Do NOT slap them on the back if they are coughing, as it may lodge the object deeper.\n"
            "• **If Cannot Breathe or Speak:** Perform the **Heimlich Maneuver**:\n"
            "  1. Stand behind the person, wrap your arms around their waist.\n"
            "  2. Make a fist with one hand and place the thumb-side slightly above their belly button.\n"
            "  3. Grasp your fist with your other hand and press into their abdomen with quick, upward thrusts.\n"
            "  4. Repeat until the object is expelled or they lose consciousness.\n"
            "• **If Unconscious:** Lower them to the floor, call 911 immediately, and begin CPR. Check the mouth for the object before giving breaths.\n\n"
            "⚠️ *This AI guidance is for immediate first aid only. Please call emergency services immediately.*"
        )

    # 5. Stroke
    if any(w in m for w in ["stroke", "slur", "numb", "droop", "paralyz", "cannot move"]):
        return (
            "🚨 **EMERGENCY — Call 911 (or local emergency) Immediately!**\n\n"
            "### **Critical First-Aid Steps for a Suspected Stroke (F.A.S.T.):**\n"
            "• **F - Face Drooping:** Ask the person to smile. Does one side of the face droop?\n"
            "• **A - Arm Weakness:** Ask them to raise both arms. Does one arm drift downward?\n"
            "• **S - Speech Difficulty:** Ask them to repeat a simple sentence. Is their speech slurred or strange?\n"
            "• **T - Time to Call 911:** If they show any of these signs, call 911 immediately! Note the exact time symptoms first started.\n"
            "• **Do NOT Give Food, Water, or Aspirin:** A stroke can impair swallowing and could be caused by bleeding in the brain. Giving aspirin could make it worse.\n"
            "• **Keep them Comfortable:** Lay the person down on their side (recovery position) if they are unconscious or vomiting, ensuring their airway is clear.\n\n"
            "⚠️ *This AI guidance is for immediate first aid only. Please call emergency services immediately.*"
        )

    # 6. Heart Attack / Chest Pain
    if any(w in m for w in ["chest pain", "heart attack", "chest tightness", "crushing pain"]):
        return (
            "🚨 **EMERGENCY — Call 911 (or local emergency) Immediately!**\n\n"
            "### **Critical First-Aid Steps for a Suspected Heart Attack:**\n"
            "• **Sit and Rest:** Have the person sit down, stay calm, and rest. Do not let them walk or exert themselves.\n"
            "• **Chew Aspirin:** Have the person chew and swallow a full aspirin (325mg) or 2-4 baby aspirins if they have no allergy or contraindications.\n"
            "• **Monitor Closely:** Be prepared to start CPR immediately if the person becomes unconscious and stops breathing.\n"
            "• **Do NOT Drive:** Wait for the ambulance to arrive. Paramedics can begin lifesaving treatment immediately upon arrival.\n\n"
            "⚠️ *This AI guidance is for immediate first aid only. Please call emergency services immediately.*"
        )

    # 7. General Fallback
    return (
        "🚨 **EMERGENCY — Call 911 (or local emergency) Immediately!**\n\n"
        "### **Critical First-Aid Steps While Waiting for Emergency Services:**\n"
        "• **Assess the Situation:** Ensure the area is safe for you and the victim before helping.\n"
        "• **Stay Calm and Reassure:** Help the person sit or lie down safely in a comfortable position.\n"
        "• **Loosen Clothing:** Loosen any tight clothing around the neck, chest, or waist.\n"
        "• **Do NOT Give Food or Water:** The patient may need surgery or lose consciousness; giving food/water poses a choking risk.\n"
        "• **Prepare for Paramedics:** Unlock your front door, turn on outside lights, and if someone is with you, have them wait outside to guide the ambulance.\n"
        "• **Perform CPR If Needed:** If they lose consciousness and stop breathing, begin hands-only CPR immediately.\n\n"
        "⚠️ *This AI guidance is for immediate first-aid only. Please call for professional help immediately.*"
    )

def generate_emergency_guidance(msg: str) -> str:
    system_prompt = (
        "You are an Emergency Medical Triage Assistant. The user is experiencing a life-threatening emergency. "
        "Provide extremely clear, direct, and medically precise first-aid steps in a bulleted list for their specific situation. "
        "Do NOT use conversational filler. Be brief, authoritative, and clear. "
        "Start immediately with '🚨 **EMERGENCY — Call 911 (or your local emergency services) Immediately!**' "
        "Follow with '### **Critical First-Aid Steps for [SITUATION]:**' (where [SITUATION] is replaced with their specific issue like Bleeding, Fractured Hand, Bike Accident, etc.) and then bullet points. "
        "End with: '⚠️ *Disclaimer: This AI advice is for immediate first-aid guidance only and cannot replace professional emergency medical services. Please call 911 immediately.*'"
    )
    try:
        from langchain_core.messages import SystemMessage, HumanMessage
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=msg)
        ]
        response = get_agent_llm("triage", 0.3).invoke(messages)
        content = response.content if hasattr(response, "content") else str(response)
        if content and len(content) > 50:
            return content
    except Exception as e:
        print(f"Emergency LLM generation failed: {e}")
    
    return get_local_emergency_fallback(msg)

# ════════════════════════════════════════════════════════════════════════════
# TRIAGE NODE
# ════════════════════════════════════════════════════════════════════════════
def triage_node(state):
    msg    = get_msg(state)
    intent = detect_intent(msg, state)
    state["intent"]      = intent
    state["last_intent"] = intent

    if intent == "emergency":
        r = generate_emergency_guidance(msg)
        state["messages"].append(AIMessage(content=r))
        state["response"] = r
    return state


# ════════════════════════════════════════════════════════════════════════════
# RESEARCHER NODE
# GPT/Claude level: 4 paragraphs default, user can request more
# Deep, academic, well-structured, uses real web data
# ════════════════════════════════════════════════════════════════════════════
def researcher_node(state):
    try:
        msg         = get_msg(state)
        memory      = build_memory(state)
        history     = build_langchain_history(state)
        should_save = any(w in msg.lower() for w in ["save","file","store","keep","download"])

        # Check if user requested specific paragraph count
        para_count  = extract_paragraph_count(msg)
        para_target = para_count if para_count > 0 else 4  # default: 4 paragraphs
        word_target = para_target * 80  # ~80 words per paragraph

        search1 = ""
        search2 = ""
        wiki = ""
        # Research agent always gathers live web context (Wikipedia + web).
        try:
            from healthcare.tools import wikipedia_search
            wiki = wikipedia_search(msg)
        except Exception as e:
            print(f"Wikipedia search failed: {e}")
        if ENABLE_CONTEXT_WEB_SEARCH:
            try:
                search1 = web_search(f"{msg} site:en.wikipedia.org OR medical research evidence")
                search2 = web_search(f"{msg} Mayo Clinic OR NIH OR CDC")
            except Exception as e:
                print(f"Research web search failed: {e}")

        system_prompt = f"""You are HealthCare AI Research Assistant — an educational helper that explains healthcare and AI topics clearly. You are NOT a real doctor, researcher, journal, or publishing institution.

--- CONVERSATION HISTORY ---
{memory}
----------------------------

LIVE WEB CONTEXT (use these facts; do not invent sources):
Wikipedia: {wiki[:1800]}
Web Source 1: {search1[:1200]}
Web Source 2: {search2[:800]}
----------------------------

CRITICAL ANTI-HALLUCINATION RULES (never break these):
- NEVER invent authors, degrees, job titles, institutions, universities, hospitals, journals, DOIs, PubMed IDs, URLs, publication dates, or citation lists.
- NEVER sign answers as "Dr. Ahmad", "Senior Medical Research Specialist", or any fake personal identity.
- NEVER present AI-generated text as a real published research paper.
- If the user asks to "write a research paper", provide an **educational overview / draft outline** and clearly label it as AI-generated educational content, not a peer-reviewed publication.
- Only cite sources that appear in the retrieved information above. If no real sources are available, say so and summarize established concepts without fake references.
- If unsure about a fact, say you are unsure rather than inventing details.

IMPORTANT INSTRUCTIONS FOR ATTACHED FILES:
If the user's message contains [Attached File: ...] and "Extracted text:", you MUST analyze the extracted text provided and answer questions about it.
- DO NOT say you can't access external files or PDFs — the text is already extracted and provided for you!
- Read the extracted text carefully
- Answer the user's question directly based on the extracted text
- If the extracted text mentions an error (like OCR failed or Tesseract not found), tell the user what dependencies they need to install to get text extraction working (like Tesseract OCR, pytesseract, Pillow, pdfplumber)

TASK:
Write a comprehensive, professional, and deeply informative response to the user's question. Your response must be thorough, accurate, well-structured, and genuinely helpful.

RESPONSE REQUIREMENTS:
- Write at least {para_target} full paragraphs
- Each paragraph must be 60-100 words minimum
- Start DIRECTLY with the topic heading or answer — no fake author/institution header block
- Use **bold** for important medical terms and key points
- Each paragraph should cover a distinct aspect
- For paper-style requests, use sections like Abstract, Introduction, Causes, Types, Mitigation, Limitations — without fake metadata

WRITING STYLE:
- Professional yet easy to understand
- Be specific where possible
- Connect ideas between paragraphs smoothly
- Avoid vague statements — be precise and actionable

IMPORTANT RULES:
- Do NOT give personal medical diagnosis
- Connect your answer to conversation history if this is a follow-up question

End with: **⚕️ Always consult a qualified healthcare professional for personalized medical advice. This is AI-generated educational content, not a published paper.**"""

        messages_to_send  = [SystemMessage(content=system_prompt)]
        messages_to_send += history
        messages_to_send.append(HumanMessage(content=msg))

        response = get_agent_llm("researcher", 0.5).invoke(messages_to_send)
        content  = response.content if hasattr(response,"content") else str(response)

        if should_save:
            name_match = re.search(r'save (?:it )?(?:as |to )?([\w\s]+?)(?:\.txt)?(?:\s|$)', msg.lower())
            filename   = (name_match.group(1).strip().replace(" ","_") + ".txt") if name_match \
                         else "_".join(msg.lower().split()[:4]).replace("?","") + ".txt"
            saved_path = save_to_file(filename, f"Research: {msg}\n\n{'='*50}\n\n{content}")
            content   += f"\n\n✅ **Saved to:** `{saved_path}`"

        state["messages"].append(AIMessage(content=content))
        state["response"] = content

    except Exception as e:
        print(f"ERROR in researcher_node: {e}")
        import traceback
        traceback.print_exc()

        report_fallback = build_report_fallback_response(get_msg(state))
        if report_fallback:
            state["messages"].append(AIMessage(content=report_fallback))
            state["response"] = report_fallback
            return state
        
        fallback_msg = get_msg(state)
        # Web search fallback
        try:
            search_results = web_search(fallback_msg)
            if search_results and "Search failed" not in search_results and "Search disabled" not in search_results:
                state["response"] = f"⚠️ **AI Connection Error (All models failed)**\n\nI was unable to connect to the AI engine to generate a professional assessment. However, I have performed a live web search for your query:\n\n{search_results}"
                return state
        except Exception as se:
            print(f"Researcher web search fallback failed: {se}")
        
        state["response"] = f"⚠️ **AI Connection Error**\n\nI understand you are asking a research question, but my connection to the AI engine is currently unavailable (Error: {str(e)[:50]}).\n\nPlease try again in a few moments."
    return state


# ════════════════════════════════════════════════════════════════════════════
# LIFESTYLE NODE
# Professional wellness coach — satisfying, practical, culturally aware
# ════════════════════════════════════════════════════════════════════════════
def lifestyle_node(state):
    try:
        msg         = get_msg(state)
        memory      = build_memory(state)
        history     = build_langchain_history(state)
        should_save = any(w in msg.lower() for w in ["save","file","store","keep"])

        search1 = ""
        search2 = ""
        if ENABLE_CONTEXT_WEB_SEARCH:
            search1 = web_search(f"{msg} fitness health advice 2025")
            search2 = web_search(f"{msg} wellness tips expert recommendation")

        system_prompt = f"""You are HealthCare AI Wellness Coach (educational persona only — not a licensed clinician). You are familiar with Pakistani culture, lifestyle, food, and daily routines. Give practical, actionable wellness advice — not generic tips. Never invent certifications, clinics, or personal medical credentials.

--- CONVERSATION HISTORY ---
{memory}
----------------------------

WELLNESS INFORMATION FOUND:
{search1[:1500]}
Additional: {search2[:600]}
----------------------------

IMPORTANT INSTRUCTIONS FOR ATTACHED FILES:
If the user's message contains [Attached File: ...] and "Extracted text:", you MUST analyze the extracted text provided and answer questions about it.
- DO NOT say you can't access external files or PDFs — the text is already extracted and provided for you!
- Read the extracted text carefully
- Answer the user's question directly based on the extracted text
- If the extracted text mentions an error (like OCR failed or Tesseract not found), tell the user what dependencies they need to install to get text extraction working (like Tesseract OCR, pytesseract, Pillow, pdfplumber)

TASK:
Give a thorough, professional, and genuinely satisfying wellness response. Your quality must match professional health platforms. The user deserves real expert advice, not surface-level tips.

RESPONSE STRUCTURE — write all sections:

**[Direct answer in one confident sentence]**

**Understanding Your Question:**
[2-3 sentences showing you understood the context and why this is a good question]

**The Science Behind It:**
[2-3 sentences explaining WHY — the biological/physiological reason. Be specific, not vague.]

**Your Complete Action Plan:**
• **[Action 1]:** Specific detail with timing/quantity
• **[Action 2]:** Specific detail with timing/quantity
• **[Action 3]:** Specific detail with timing/quantity
• **[Action 4]:** Specific detail with timing/quantity
• **[Action 5]:** Specific detail with timing/quantity

**Pakistani Lifestyle Tips:**
[2-3 tips using local context — Pakistani foods (doodh, dahi, dal, fruits, green tea), realistic schedules, budget-friendly options, seasonal considerations]

**What to Avoid:**
[2-3 common mistakes related to this topic]

**When to See a Doctor:**
[One clear sentence about warning signs]

TONE AND QUALITY:
- Sound like a real certified expert, not a chatbot
- Be specific with numbers: times, durations, quantities, frequencies
- Use **bold** for key terms and important points
- Give advice that actually works for Pakistani lifestyle
- Connect to conversation history if follow-up question
- Total length: 450-700 words for comprehensive, deeply professional, and detailed coverage

End with: ⚠️ *If symptoms persist or worsen, please consult a qualified doctor.*"""

        messages_to_send  = [SystemMessage(content=system_prompt)]
        messages_to_send += history
        messages_to_send.append(HumanMessage(content=msg))

        response = get_agent_llm("lifestyle", 0.75).invoke(messages_to_send)
        content  = response.content if hasattr(response,"content") else str(response)

        if should_save:
            filename   = "_".join(msg.lower().split()[:4]).replace("?","").replace(",","") + ".txt"
            saved_path = save_to_file(filename, f"Lifestyle: {msg}\n\n{'='*50}\n\n{content}")
            content   += f"\n\n✅ **Saved to:** `{saved_path}`"

        state["messages"].append(AIMessage(content=content))
        state["response"] = content

    except Exception as e:
        import traceback
        print(f"ERROR in lifestyle_node: {e}")
        traceback.print_exc()
        try:
            report_fallback = build_report_fallback_response(get_msg(state))
            if report_fallback:
                state["response"] = report_fallback
                return state
            
            # Web search fallback
            try:
                fallback_msg = get_msg(state)
                search_results = web_search(fallback_msg)
                if search_results and "Search failed" not in search_results and "Search disabled" not in search_results:
                    state["response"] = f"⚠️ **AI Connection Error (All models failed)**\n\nI was unable to connect to the AI engine to generate a professional assessment. However, I have performed a live web search for your query:\n\n{search_results}"
                    return state
            except Exception as se:
                print(f"Lifestyle web search fallback failed: {se}")
            
            # If it's an API error, inform the user clearly
            state["response"] = f"⚠️ **AI Connection Error**\n\nI understand you are asking about lifestyle/fitness, but my connection to the AI engine is currently unavailable (Error: {str(e)[:50]}).\n\nPlease try again in a few moments."
        except:
            state["response"] = "⚠️ **AI Connection Error**\n\nI understand your request, but I am experiencing temporary connection issues. Please try again shortly."
    return state


# ════════════════════════════════════════════════════════════════════════════
# GENERAL NODE
# Smart, professional, helpful — like GPT on general health topics
# ════════════════════════════════════════════════════════════════════════════
def general_node(state):
    try:
        msg     = get_msg(state)
        memory  = build_memory(state)
        history = build_langchain_history(state)

        system_prompt = f"""You are HealthCare AI — an intelligent, professional, and genuinely helpful health assistant. You respond with the depth and quality of ChatGPT or Claude — never shallow, always thoughtful. You are not a real doctor and must never invent authors, institutions, journals, DOIs, or claim published-paper authorship.

--- CONVERSATION HISTORY ---
{memory}
----------------------------

IMPORTANT INSTRUCTIONS FOR ATTACHED FILES:
If the user's message contains [Attached File: ...] and "Extracted text:", you MUST analyze the extracted text provided and answer questions about it.
- DO NOT say you can't access external files or PDFs — the text is already extracted and provided for you!
- Read the extracted text carefully
- Answer the user's question directly based on the extracted text
- If the extracted text mentions an error (like OCR failed or Tesseract not found), tell the user what dependencies they need to install to get text extraction working (like Tesseract OCR, pytesseract, Pillow, pdfplumber)

RESPONSE GUIDELINES:

FOR GREETINGS — respond warmly and clearly:
Hey! 👋 I am **HealthCare AI** — your intelligent health assistant!

Here is what I can help you with:
🚨 **Emergency Guidance** — First aid and urgent care advice
🔬 **Medical Research** — Diseases, treatments, AI in healthcare
🌿 **Wellness & Lifestyle** — Diet, exercise, sleep, daily habits
📄 **Medical Reports** — Analyze uploaded medical documents and reports

Just ask me anything about your health — I am here to help!

FOR HEALTH QUESTIONS — respond like a professional:
- Give a direct, confident answer in 150-200 words
- Use **bold** for key medical terms
- Be specific — include numbers, timeframes, practical steps
- Show empathy and understanding
- If complex topic → give overview + offer to go deeper
- Connect to previous conversation if follow-up

FOR UNCLEAR QUESTIONS:
- Make your best interpretation and answer it
- Offer 2-3 related things you could help with

QUALITY STANDARD:
- Every response must feel satisfying and complete
- Sound like a knowledgeable doctor friend, not a robot
- Never say "I am just an AI" — just help them

End health advice with: ⚕️ *Consult a doctor for personalized medical advice.*"""

        messages_to_send  = [SystemMessage(content=system_prompt)]
        messages_to_send += history
        messages_to_send.append(HumanMessage(content=msg))

        response = get_agent_llm("general", 0.65).invoke(messages_to_send)
        content  = response.content if hasattr(response,"content") else str(response)

        state["messages"].append(AIMessage(content=content))
        state["response"] = content

    except Exception as e:
        import traceback
        print(f"ERROR in general_node: {e}")
        traceback.print_exc()
        report_fallback = build_report_fallback_response(get_msg(state))
        if report_fallback:
            state["response"] = report_fallback
        else:
            # Web search fallback
            try:
                fallback_msg = get_msg(state)
                search_results = web_search(fallback_msg)
                if search_results and "Search failed" not in search_results and "Search disabled" not in search_results:
                    state["response"] = f"⚠️ **AI Connection Error (All models failed)**\n\nI was unable to connect to the AI engine to generate a professional assessment. However, I have performed a live web search for your query:\n\n{search_results}"
                    return state
            except Exception as se:
                print(f"General web search fallback failed: {se}")
            state["response"] = f"⚠️ **AI Connection Error**\n\nI understand your request, but my connection to the AI engine is currently unavailable (Error: {str(e)[:50]}).\n\nPlease try again in a few moments."
    return state


# ── Router ────────────────────────────────────────────────────────────────────
def router(state):
    intent = state.get("intent", "general")
    if intent == "emergency":   return "end"
    elif intent == "research":  return "researcher"
    elif intent == "lifestyle": return "lifestyle"
    return "general"
