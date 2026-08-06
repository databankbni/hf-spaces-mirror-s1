import gradio as gr

def tarot_reader(major):
    if "industrial" in major.lower():
        prediction = "By 2030, you will command smart factories where machines whisper efficiency secrets to you."
    elif "business" in major.lower():
        prediction = "By 2030, you will conjure strategies that turn markets into kingdoms."
    elif "art" in major.lower():
        prediction = "By 2030, your creativity will weave immersive worlds of light and sound."
    else:
        prediction = "By 2030, you will pioneer new paths where human ingenuity meets AI magic."
    return f"{prediction}\n\nYour fate is written in the stars of tomorrow — carry this vision with you as you step into 2030."

iface = gr.Interface(
    fn=tarot_reader,
    inputs=gr.Textbox(label="Welcome, seeker of destiny. Tell me your major or interest:"),
    outputs="text",
    title="AI Tarot Career Reader"
)

iface.launch()
