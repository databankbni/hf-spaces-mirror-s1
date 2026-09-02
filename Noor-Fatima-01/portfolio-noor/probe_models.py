import os
from groq import Groq
from dotenv import load_dotenv

load_dotenv()
client = Groq(api_key=os.getenv('GROQ_API_KEY', ''))
models = [
    'groq/compound',
    'groq/compound-mini',
    'openai/gpt-oss-20b',
    'openai/gpt-oss-120b',
    'qwen/qwen3.6-27b',
    'allam-2-7b',
    'canopylabs/orpheus-v1-english',
]

print('API KEY SET:', bool(os.getenv('GROQ_API_KEY', '')))
print('LISTED MODELS:')
for m in client.models.list().data[:20]:
    print('-', m.id)

print('\nCHAT TESTS:')
for model in models:
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{'role': 'user', 'content': 'Say OK'}],
            max_tokens=5,
        )
        print('OK', model, '->', resp.choices[0].message.content)
    except Exception as exc:
        print('FAIL', model, type(exc).__name__, exc)
