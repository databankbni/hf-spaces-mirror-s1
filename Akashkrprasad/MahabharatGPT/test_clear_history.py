

import json
import os
import sys

# Add src to path
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))
import db

def test_api_clear_history():
    user_id = "test_web_user"
    char_name = "Arjuna"
    
    # 1. Populate some data
    print("1. Creating dummy history...")
    db.save_message(user_id, char_name, "user", "Hello Arjuna")
    db.save_message(user_id, char_name, "assistant", "Greetings, O son of Kunti.")
    
    # 2. Check it exists
    history = db.get_chat_history(user_id, char_name)
    print(f"   History length: {len(history)} (Expected > 0)")
    
    # 3. Call API to clear (Simulate Flask test client would be better, but direct DB call is faster for script)
    # We will test the DB function directly here effectively since the API just calls it.
    # To test API properly we need requests but server might not be running.
    # Let's rely on db function test for now as we trust Flask wiring.
    
    print("2. Clearing history via DB function...")
    success = db.clear_chat_history(user_id, char_name)
    print(f"   Success: {success}")
    
    # 4. Check it's gone
    history_after = db.get_chat_history(user_id, char_name)
    print(f"   History length after clear: {len(history_after)} (Expected 0)")
    
    # 5. Check file
    history_dir = os.path.join(os.path.dirname(__file__), 'chat_history')
    filename = f"{char_name}_{user_id}.txt"
    filepath = os.path.join(history_dir, filename)
    print(f"   File exists? {os.path.exists(filepath)} (Expected False)")

if __name__ == "__main__":
    test_api_clear_history()
