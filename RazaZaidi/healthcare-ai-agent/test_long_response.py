import sys
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from healthcare.graph import chat

try:
    print("Testing LONG response in chat (Verification)...")
    
    # We query the research agent which is triggered by words like "literature review" or "research paper"
    query = "Write a comprehensive medical literature review on the metabolic changes during 14 days of fasting."
    response = chat(query, [])
    
    print(f"\nResponse received! Length: {len(response)} characters.")
    print("Writing response to long_response_output.txt to verify...")
    with open("long_response_output.txt", "w", encoding="utf-8") as f:
        f.write(response)
    print("Verification complete!")
except Exception as e:
    import traceback
    traceback.print_exc()
