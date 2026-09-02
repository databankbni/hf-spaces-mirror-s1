import gradio as gr
from gradio_client import Client

# Free hosted AI image generator
client = Client("mrfakename/Z-Image-Turbo")


def generate_image(prompt):
    if not prompt or not prompt.strip():
        raise gr.Error("Please write an image prompt.")

    try:
        result = client.predict(
            prompt.strip(),
            1024,   # height
            1024,   # width
            9,      # steps
            42,     # seed
            True,   # random seed
            api_name="/generate_image"
        )

        return result[0]

    except Exception as e:
        raise gr.Error(f"Generation failed: {str(e)}")


with gr.Blocks(title="My AI Creative Studio") as app:

    gr.Markdown(
        """
        # 🎨 My AI Creative Studio
        ### Create amazing images from your text
        """
    )

    prompt = gr.Textbox(
        label="✨ Describe your image",
        placeholder="Example: A cute orange cat wearing a pink dress, cinematic lighting, highly detailed",
        lines=5
    )

    generate = gr.Button(
        "🎨 Generate Image",
        variant="primary"
    )

    output = gr.Image(
        label="🖼️ Your Generated Image",
        type="filepath"
    )

    generate.click(
        generate_image,
        inputs=prompt,
        outputs=output
    )

    gr.Markdown(
        "💡 Tip: Describe the subject, clothes, background, lighting and style for better results."
    )


app.launch()