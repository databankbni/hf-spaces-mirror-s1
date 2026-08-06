import gradio as gr


with gr.Blocks(title="Gradio #13623 Column variants") as demo:
    gr.Markdown(
        """
        # Gradio #13623 — Column variants

        The **before** Space drops the `variant` prop before it reaches the
        base column, so the two layouts have no panel/compact styling. The
        **after** Space forwards the component props and restores both styles.
        """
    )
    with gr.Row():
        with gr.Column(variant="panel"):
            gr.Markdown("### Panel column")
            gr.Button("One")
            gr.Button("Two")
        with gr.Column(variant="compact"):
            gr.Markdown("### Compact column")
            gr.Button("Three")
            gr.Button("Four")

demo.launch()
