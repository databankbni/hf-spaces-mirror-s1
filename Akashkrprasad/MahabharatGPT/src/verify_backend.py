import sys
import os
from dotenv import load_dotenv

# Add src to path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))
load_dotenv()

from character_bot import MahabharataCharacter
import db

def test_persistence():
    print("--- Test 1: Persistence ---")
    user_id = "test_user_001"
    char_name = "Krishna"
    
    # Session 1
    print("\n[Session 1] Initializing Krishna...")
    bot1 = MahabharataCharacter(char_name, user_id=user_id)
    response1 = bot1.chat("Who are you?")
    print(f"You: Who are you?\nKrishna: {response1['response']}")
    
    # Session 2 (New Instance)
    print("\n[Session 2] Re-initializing Krishna (simulating server restart)...")
    bot2 = MahabharataCharacter(char_name, user_id=user_id)
    history = bot2._get_history_string()
    
    if "Who are you?" in history:
        print("SUCCESS: History retrieved from database.")
        print(f"History snippet:\n{history}")
    else:
        print("FAILURE: Could not retrieve history.")

def test_dynamic_config():
    print("\n--- Test 2: Dynamic Config ---")
    
    # Test Duryodhana (should be arrogant)
    print("\nInitializing Duryodhana...")
    duryodhana = MahabharataCharacter("Duryodhana", user_id="test_user_002")
    print(f"Traits loaded: {duryodhana.traits}")
    
    if "envy" in duryodhana.traits.lower() or "proud" in duryodhana.traits.lower():
        print("SUCCESS: Duryodhana's specific traits loaded.")
    else:
        print("FAILURE: Default traits loaded instead of Duryodhana's.")

if __name__ == "__main__":
    test_persistence()
    test_dynamic_config()
