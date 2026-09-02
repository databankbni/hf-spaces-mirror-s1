import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
import json
import os
from dotenv import load_dotenv

load_dotenv()

QWEN_MODEL_ID = os.getenv("QWEN_MODEL_ID", "Qwen/Qwen2.5-3B-Instruct")
_llm_tokenizer = AutoTokenizer.from_pretrained(QWEN_MODEL_ID)
_llm_model = AutoModelForCausalLM.from_pretrained(
    QWEN_MODEL_ID,
    torch_dtype=torch.float16,
    device_map="auto"
)

# Mock dropdowns
from database import get_all_dropdowns
dropdowns = get_all_dropdowns()

transcript = "This is a UA observation for Apex Engineering Ltd. on August 5th, 2026 for the AlphaCore Systems service at Adani Solar Park Development in Amravati zone Loc 1. The department is Admin and the contractor is Alpha Contractor. The violator is Rajesh Kumar with ID EMP1042. Rajesh was performing Arc Welding without face protection which is a sub-activity under Activity 1. This is a High risk level hazard of Arc Flash with Airborne Dust. The control measure violation is Acid-resistant flooring and spill kit because the worker did not wear the mandatory face protection while welding. The safety rule violated was Area Inspection. The observation is assigned to Ajay Mohod to resolve by August 12th, 2026."

from main import build_prompt
prompt = build_prompt(transcript, dropdowns)
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
        do_sample=False
    )

generated = _llm_tokenizer.decode(
    output[0][inputs.input_ids.shape[-1] :], skip_special_tokens=True
)

print("Generated LLM Output Raw:")
print(generated)

start = generated.find("{")
end = generated.rfind("}")
data = json.loads(generated[start : end + 1])
print("Parsed raw JSON from LLM:")
print(json.dumps(data, indent=2))

from main import fuzzy_match
dropdown_fields = [
    "Company", "Service", "PlantProjectClient", "Department", "Contractor",
    "UAUCType", "Activity", "SubActivity", "RiskLevel", "Hazard", "SubHazard",
    "ControlMeasureViolations", "ResolveRights", "SourceRules", "Location", "Zone",
]
for field in dropdown_fields:
    options = dropdowns.get(field, [])
    if options:
        val = data.get(field, "")
        matched = fuzzy_match(val, options)
        print(f"Field: {field} | Raw: '{val}' -> Matched: '{matched}'")
