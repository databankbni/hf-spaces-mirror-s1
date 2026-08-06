import gradio as gr
import torch
import re
from transformers import pipeline

# ---------------------------------------------------------
# Model Configuration & Loading
# ---------------------------------------------------------
MODEL_NAME = "Qwen/Qwen2.5-0.5B-Instruct"

print(f"Starting model load: {MODEL_NAME}...")
try:
    dtype = torch.float16 if torch.cuda.is_available() else torch.float32
    device = 0 if torch.cuda.is_available() else -1

    generator = pipeline(
        "text-generation",
        model=MODEL_NAME,
        torch_dtype=dtype,
        device=device
    )
    MODEL_LOADED = True
    print("Model loaded successfully!")
except Exception as e:
    print(f"Error loading model: {e}")
    MODEL_LOADED = False

# ---------------------------------------------------------
# Processing & Robust Parsing Function
# ---------------------------------------------------------
def process_prompt(user_input, task):
    """
    Evaluates, scores, and rewrites the user's prompt by forcing a strict
    Persona and Structure using clear few-shot examples for the small model.
    """
    if not user_input or not user_input.strip():
        return "N/A", "Please enter a prompt.", "No input provided."
    
    if not MODEL_LOADED:
        return (
            "Error",
            "Error: Model failed to load offline.", 
            "Please check the server logs or try a different lightweight model."
        )

    # Injecting strict rules & a powerful Few-Shot Example to guide the 0.5B model
    system_message = (
        "You are an expert Prompt Engineer. Your task is to critically evaluate the user's prompt, "
        "give it an honest and strict quality score out of 100, and rewrite it into a highly effective prompt.\n\n"
        "CRITICAL RULES:\n"
        "1. Assign a Persona/Role: The rewritten prompt MUST start immediately by defining an expert role for the AI "
        "(e.g., 'Act as an expert [Role]...', 'You are a professional [Role]...').\n"
        "2. Add Structure & Details: Expand the prompt by adding specific guidelines, constraints, and target output format.\n"
        "3. Strict Scoring: Be very critical. Vague or single-sentence prompts (e.g., 'explain quantum physics', 'write a story') "
        "are extremely weak and MUST get a low score between 15 and 45. Only highly structured prompts with roles get 80+.\n\n"
        "You MUST format your output EXACTLY like this template. Do not add any extra intro or outro text:\n"
        "[SCORE]\n<numerical score only, e.g., 30>\n"
        "[IMPROVED]\n<The complete rewritten prompt starting with the Persona/Role>\n"
        "[EXPLANATION]\n<Short bullet points explaining the improvements>\n\n"
        "--- EXAMPLE OF EXPECTED BEHAVIOR ---\n"
        "User Input: write a blog about AI\n"
        "Output:\n"
        "[SCORE]\n"
        "30\n"
        "[IMPROVED]\n"
        "Act as an expert technology copywriter. Write a highly engaging 600-word blog post about how generative AI tools are changing daily office productivity. Use an informative yet professional tone. Structure the post with a compelling hook in the introduction, three practical use-cases with bullet points, and a forward-looking conclusion.\n"
        "[EXPLANATION]\n"
        "- Assigned the role of an expert tech copywriter to give the AI context.\n"
        "- Added specific constraints (600 words) and tone instruction (professional).\n"
        "- Outlined a clear structure (introduction, use-cases, conclusion) to ensure organized output."
    )
    
    user_message = f"Task: {task}\nOriginal Prompt: {user_input}"

    messages = [
        {"role": "system", "content": system_message},
        {"role": "user", "content": user_message}
    ]

    try:
        # Format the chat template
        prompt_text = generator.tokenizer.apply_chat_template(
            messages, 
            tokenize=False, 
            add_generation_prompt=True
        )
        
        # Generate the response
        outputs = generator(
            prompt_text,
            max_new_tokens=350,
            temperature=0.4, # Lower temperature for more focused instruction following
            do_sample=True,
            return_full_text=False
        )
        
        response = outputs[0]["generated_text"].strip()
        
        # Robust Splitting based on tags
        parts = re.split(r'\[SCORE\]|\[IMPROVED\]|\[EXPLANATION\]', response, flags=re.IGNORECASE)
        
        score = "⭐ N/A"
        improved_text = ""
        explanation_text = ""

        if len(parts) >= 4:
            score_num = parts[1].strip()
            # Handle case if model wrote text instead of just number
            score_clean = re.search(r'\d+', score_num)
            score = f"⭐ {score_clean.group(0) if score_clean else score_num} / 100"
            
            improved_text = parts[2].strip()
            explanation_text = parts[3].strip()
        else:
            # Fallback if splitting fails
            score_match = re.search(r'(?:SCORE:?)\s*(\d+)', response, re.IGNORECASE)
            score = f"⭐ {score_match.group(1)} / 100" if score_match else "⭐ 35 / 100"
            
            if "[IMPROVED]" in response.upper():
                temp = re.split(r'\[IMPROVED\]', response, flags=re.IGNORECASE)[1]
                if "[EXPLANATION]" in temp.upper():
                    improved_text = re.split(r'\[EXPLANATION\]', temp, flags=re.IGNORECASE)[0].strip()
                    explanation_text = re.split(r'\[EXPLANATION\]', temp, flags=re.IGNORECASE)[1].strip()
                else:
                    improved_text = temp.strip()
                    explanation_text = "Prompt restructured with role and context."
            else:
                improved_text = response
                explanation_text = "Prompt successfully optimized."
            
        return score, improved_text, explanation_text

    except Exception as e:
        return "Error", f"Generation Error: {str(e)}", "An error occurred during inference."


# ---------------------------------------------------------
# Gradio UI Definition
# ---------------------------------------------------------
custom_theme = gr.themes.Soft(primary_hue="blue")

with gr.Blocks(title="Prompt Assistant") as app:
    
    # Header Section
    gr.Markdown(
        """
        # 🚀 Prompt Assistant
        ### Your personal AI Prompt Engineer
        Welcome to the **Prompt Assistant**! This tool helps students, developers, and researchers write better, clearer, and more structured prompts for Large Language Models. 
        Select a task, enter your raw idea, and let the assistant craft a professional prompt for you.
        """
    )
    
    with gr.Row():
        with gr.Column(scale=1):
            # Input Section
            task_selector = gr.Dropdown(
                choices=[
                    "Improve Prompt", 
                    "Make More Detailed", 
                    "Summarize Prompt", 
                    "Translate Prompt", 
                    "Generate Better Version", 
                    "Explain Improvements"
                ],
                value="Improve Prompt",
                label="What would you like to do?",
                interactive=True
            )
            user_prompt_input = gr.Textbox(
                lines=6, 
                label="Your Original Prompt", 
                placeholder="Type your basic prompt or idea here... (e.g., 'write an email to my boss about a vacation')"
            )
            
            with gr.Row():
                clear_btn = gr.Button("Clear", variant="secondary")
                generate_btn = gr.Button("Generate", variant="primary")
                
        with gr.Column(scale=1):
            # Output Section
            score_output = gr.Textbox(
                label="Original Prompt Quality Score",
                value="N/A",
                interactive=False
            )
            improved_prompt_output = gr.Textbox(
                lines=5, 
                label="Ready-to-Use Prompt (With Persona & Context)", 
                buttons=["copy"],
                interactive=False
            )
            explanation_output = gr.Textbox(
                lines=3, 
                label="Improvements & Explanation", 
                interactive=False
            )

    # Examples Section
    gr.Markdown("### 💡 Ready-to-use Examples")
    gr.Examples(
        examples=[
            ["write a blog about AI", "Make More Detailed"],
            ["explain quantum physics", "Improve Prompt"],
            ["give me python code for a calculator", "Generate Better Version"],
        ],
        inputs=[user_prompt_input, task_selector],
        outputs=[score_output, improved_prompt_output, explanation_output],
        fn=process_prompt,
        cache_examples=False
    )
    
    # Footer Section
    gr.Markdown(
        """
        ---
        **Prompt Assistant** | Built for Educational AI Bootcamps | *Powered by open-source models on Hugging Face*
        """
    )
    
    # Event Listeners
    generate_btn.click(
        fn=process_prompt, 
        inputs=[user_prompt_input, task_selector], 
        outputs=[score_output, improved_prompt_output, explanation_output]
    )
    
    clear_btn.click(
        fn=lambda: ("", "N/A", "", "", "Improve Prompt"),
        inputs=None,
        outputs=[user_prompt_input, score_output, improved_prompt_output, explanation_output, task_selector]
    )

# ---------------------------------------------------------
# Entry Point
# ---------------------------------------------------------
if __name__ == "__main__":
    app.launch(theme=custom_theme)