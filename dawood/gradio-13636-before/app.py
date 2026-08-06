import gradio as gr


with gr.Blocks(title="Gradio #13636 launch JavaScript") as demo:
    gr.Markdown(
        """
        # Gradio #13636 — `Blocks.launch(js=...)`

        The launch hook below sets the browser title to **LAUNCH-JS-RAN**.
        The **before** Space remains titled “Gradio”; the **after** Space runs
        the function after the Blocks tree is ready.
        """
    )

demo.launch(js="() => { document.title = 'LAUNCH-JS-RAN'; }")
