import sys
import os

from dotenv import load_dotenv

# Add src to path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))

load_dotenv()

from character_bot import MahabharataCharacter

def test_bot():
    print("Initializing Arjuna...")
    try:
        bot = MahabharataCharacter("Arjuna")
        question = "What happened during Dronacharya's test with the bird?"
        print(f"\nQuestion: {question}")
        result = bot.chat(question)
        print(f"\nResponse:\n{result['response']}")
        if result.get("sources"):
            print(f"\nSources: {', '.join(result['sources'])}")
        
    except Exception as e:
        print(f"Error during test: {e}")

if __name__ == "__main__":
    test_bot()
