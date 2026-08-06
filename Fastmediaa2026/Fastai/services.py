from openai import OpenAI
import os
import google.generativeai as genai


def get_openai_response(prompt, username, model="gpt-4o"):
    client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "user", "content": prompt}
        ]
    )

    return {
        "content": response.choices[0].message.content,
        "total_tokens": response.usage.total_tokens
    }


def get_gemini_response(prompt, username):
    try:
        genai.configure(api_key=os.environ.get("GOOGLE_API_KEY"))

        model_name = os.environ.get(
            "GEMINI_MODEL",
            "gemini-1.5-pro"
        )

        model = genai.GenerativeModel(model_name)

        response = model.generate_content(prompt)

        # Gemini أحياناً لا يرجع usage مباشرة
        tokens = 0

        try:
            tokens = response.usage_metadata.total_token_count
        except:
            pass

        return {
            "content": response.text,
            "total_tokens": tokens
        }

    except Exception as e:
        return {
            "content": f"Gemini Error: {str(e)}",
            "total_tokens": 0
        }