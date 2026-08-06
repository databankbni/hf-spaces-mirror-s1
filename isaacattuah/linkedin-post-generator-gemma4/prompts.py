"""Prompt construction for the LinkedIn Post Generator.

Shared by both the hosted (Hugging Face) and local (Ollama) versions.
"""

TONE_INSTRUCTIONS = {
    "Professional": (
        "Write in a polished, business-appropriate voice. "
        "Use precise language. Avoid slang and excessive enthusiasm."
    ),
    "Conversational": (
        "Write like you're talking to a smart colleague over coffee. "
        "Use contractions, short sentences, and a natural rhythm."
    ),
    "Inspirational": (
        "Write to motivate. Lead with a personal insight or turning point. "
        "Build toward a lesson the reader can apply. Avoid empty platitudes."
    ),
    "Educational": (
        "Write to teach. Define terms plainly, use concrete examples, "
        "and structure the post so a newcomer can follow it end to end."
    ),
}

LENGTH_TARGETS = {
    "Short (~150 words)": 150,
    "Medium (~300 words)": 300,
    "Long (~500 words)": 500,
}


def build_prompt(topic: str, tone: str, length: str) -> str:
    word_target = LENGTH_TARGETS[length]
    tone_guidance = TONE_INSTRUCTIONS[tone]

    return f"""You are an expert LinkedIn ghostwriter.

Write a LinkedIn post about the following topic:

{topic}

TONE
{tone_guidance}

LENGTH
Approximately {word_target} words.

RULES
- Open with a hook in the first line. LinkedIn truncates after roughly
  two lines, so the first line must earn the click.
- Use short paragraphs. One to three sentences each.
- Include one clear takeaway the reader can act on.
- End with a question or call to action that invites comments.
- Add 3 to 5 relevant hashtags on the final line.
- Do not use markdown headers or bold formatting. LinkedIn renders plain text.
- Do not include a preamble. Output only the post itself.

Write the post now."""