import os

# أسماء المتغيرات كما هي في الـ Secrets
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

# إعدادات النماذج
GEMINI_MODEL = "gemini-1.5-pro"
OPENAI_MODEL = "gpt-4o-mini"