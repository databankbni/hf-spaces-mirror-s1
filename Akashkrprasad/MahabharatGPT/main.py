import os
import sys
from dotenv import load_dotenv

# Add the src directory to sys.path to ensure imports work correctly
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

from character_bot import MahabharataCharacter

load_dotenv()

def main():
    print("--------------------------------------------------")
    print("Welcome to the Mahabharata Character Chatbot")
    print("--------------------------------------------------")
    
    # Check for keys
    if not os.getenv("PINECONE_API_KEY"):
        print("\n⚠️  WARNING: PINECONE_API_KEY is missing in .env file.")
        print("You need to provide a Pinecone API key to ingest data and retrieve memories.")
        print("The chatbot might crash if you try to chat without the key.")
        print("--------------------------------------------------\n")

    while True:
        character_name = input("Enter the character name you want to talk to (e.g., Arjuna): ").strip()
        if character_name:
            break
            
    try:
        print(f"\nSummoning {character_name}...\n")
        bot = MahabharataCharacter(character_name)
        print(f"{character_name} is here. (Type 'quit' to exit)")
        print("-" * 50)
        
        while True:
            user_input = input("You: ")
            if user_input.lower() in ['quit', 'exit', 'bye']:
                print(f"{character_name}: Farewell.")
                break
                
            result = bot.chat(user_input)
            print(f"{character_name}: {result['response']}")
            if result.get("sources"):
                print(f"   [drawn from: {', '.join(result['sources'])}]")
            print("-" * 50)
            
    except Exception as e:
        print(f"\nAn error occurred: {e}")
        print("Please check your API keys and internet connection.")

if __name__ == "__main__":
    main()
