---
title: Mahabharata Character Chatbot
emoji: 🏹
colorFrom: yellow
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
---

# Mahabharata Character Chatbot

Talk to the heroes, villains, sages, and queens of the Mahabharata. This app lets you have a conversation with characters like Krishna, Arjuna, Karna, Draupadi, and 23 others — each one speaking in first person, staying in character, and drawing on memories of their own life.

Under the hood, every reply is grounded in a curated set of character "memories" so the answers feel personal and consistent with who that character is, rather than generic.

## What it does

- **27 playable characters** — including Krishna, Yudhisthira, Bhima, Arjuna, Nakula, Sahadeva, Duryodhana, Karna, Draupadi, Kunti, Gandhari, Bhishma, Drona, Vidura, Shakuni, Ashwatthama, Abhimanyu, Ekalavya, and more.
- **Stays in character** — each character has its own personality, speaking style, and values. Arjuna is disciplined and warrior-like; Krishna is philosophical and playful; Bhima is loud and passionate.
- **Remembers your conversation** — your chat with each character is saved, so you can leave and come back and pick up where you left off.
- **Web chat interface** — a simple browser UI for picking a character and chatting.

## Requirements

Before you start you'll need:

1. **Python 3.9+** installed on your computer.
2. **Two free API keys:**
   - A **Groq** API key (powers the character's responses) — get one at [console.groq.com](https://console.groq.com).
   - A **Pinecone** API key (stores and searches the character memories) — get one at [app.pinecone.io](https://app.pinecone.io).

Both have free tiers that are plenty for personal use.

## Setup

Run these steps once from inside the project folder.

**1. Install the dependencies**

```bash
pip install -r requirements.txt
```

(Optional but recommended — create an isolated environment first:)

```bash
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # Mac/Linux
```

**2. Add your API keys**

Create a file named `.env` in the project folder and paste in your keys:

```
GROQ_API_KEY=your_groq_key_here
PINECONE_API_KEY=your_pinecone_key_here
```

**3. Load the character memories (one-time)**

This uploads the character data so the bots can recall their memories. It also downloads a small AI model the first time, so give it a minute.

```bash
python src/ingest.py
```

You only need to do this once (or again if you edit the memory files in the `data` folder).

## Using the app

**Web version (recommended)**

```bash
python app.py
```

Then open your browser to **http://localhost:5000**. Pick a character, type a message, and start chatting. Your conversation is saved automatically, and there's a button to clear history if you want a fresh start.

**Command-line version**

If you prefer the terminal:

```bash
python main.py
```

Type the name of a character (e.g. `Arjuna`), then chat. Type `quit`, `exit`, or `bye` to leave.

## Tips for a good conversation

- Ask characters about their own lives — their battles, regrets, relationships, and choices. For example, ask Karna about his loyalty to Duryodhana, or Draupadi about the dice game.
- Each character knows their own story best, so questions in first person ("How did you feel when...") tend to give the richest answers.
- Try the same question with different characters to see how their personalities and loyalties color the answer.

## Troubleshooting

- **"GROQ_API_KEY not found" / "PINECONE_API_KEY not found"** — make sure your `.env` file exists in the project folder and the key names are spelled exactly as above.
- **The character doesn't seem to recall anything** — make sure you ran `python src/ingest.py` successfully before chatting.
- **Errors mentioning the network or model download** — the first run needs an internet connection to download the embedding model and reach the APIs.

## Project layout

```
app.py            Web app (Flask)
main.py           Command-line version
src/              Core logic (character bot, database, data ingestion)
data/             Character memories (*.txt) and personality config
templates/        Web page
static/           Styles and scripts
Books/            Reference source material (not used at runtime)
```

## A note on the source material

The `Books` folder contains novels and retellings of the Mahabharata used as background reference for shaping the characters. They are not read by the app while it runs — the character knowledge lives in the `data` folder.
