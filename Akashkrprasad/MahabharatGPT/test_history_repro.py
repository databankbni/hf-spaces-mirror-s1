
import os
import sys
import shutil

# Add src to path
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))
import db

def test_history_persistence():
    user_id = "test_user"
    char_name = "TestChar"
    
    # Ensure clean state
    history_dir = os.path.join(os.path.dirname(__file__), 'chat_history')
    if not os.path.exists(history_dir):
        os.makedirs(history_dir)
        
    file_path = os.path.join(history_dir, f"{char_name}_{user_id}.txt")
    if os.path.exists(file_path):
        os.remove(file_path)
        
    print(f"1. Initial state: File exists? {os.path.exists(file_path)}")
    print(f"   History from DB: {db.get_chat_history(user_id, char_name)}")
    
    # Write message
    print("2. Saving message...")
    db.save_message(user_id, char_name, "user", "Hello")
    
    print(f"   File exists? {os.path.exists(file_path)}")
    print(f"   History from DB: {db.get_chat_history(user_id, char_name)}")
    
    # Delete file
    print("3. Deleting file...")
    os.remove(file_path)
    
    print(f"   File exists? {os.path.exists(file_path)}")
    print(f"   History from DB: {db.get_chat_history(user_id, char_name)}")
    
if __name__ == "__main__":
    test_history_persistence()
