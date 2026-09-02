import os
import gradio as gr
from groq import Groq

# Initialize client
client = Groq(api_key=os.getenv("GROQ_API_KEY"))

def get_city_guide(city):
    # Updated prompt to include historical context
    prompt = f"""
You are a travel expert.

For the city {city}, provide:

1. **Brief History**: A 3-4 line historical overview highlighting the city's origins and its significance today.
2. **Top 5 Tourist Places**: List with short, engaging descriptions.
3. **Top 5 Places to Eat**: Mention specific restaurants or famous street food spots.
4. **Top 5 Places to Stay**: Suggest a mix of luxury and boutique hotels.

Format the response clearly with Markdown headings and bullet points.
"""

    try:
        completion = client.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=[
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=1000 # Increased slightly to accommodate the extra history text
        )

        return completion.choices[0].message.content

    except Exception as e:
        return f"Error: {str(e)}"

#GRADIO
# Gradio UI
demo = gr.Interface(
    fn=get_city_guide,
    inputs=gr.Textbox(placeholder="e.g. Rome, Tokyo, Paris...", label="Enter City Name"),
    outputs=gr.Markdown(label="Travel Guide"),
    title="🌍 City Travel Guide AI",
    description="Get a historical overview and top recommendations using Groq LLM."
)

if __name__ == "__main__":
    demo.launch()