
import gradio as gr
import data_server as ds

invObj = ds.investmentRecords()

# This targets the table cells (td) and headers (th) specifically
css = """
/* 1. Body Cells: Standard centering */
.gradio-container table td {
    text-align: center !important;
    vertical-align: middle !important; /* Use 'middle' for vertical, not 'center' */
}

/* 2. Headers: Target the wrapper DIV specifically */
/* This centers the text without collapsing the column structure */
.gradio-container table th > div {
    display: flex !important;
    justify-content: center !important; /* Horizontally center */
    align-items: center !important;     /* Vertically center */
    text-align: center !important;
    width: 100% !important;
}

/* 3. Ensure the text span itself doesn't fight the centering */
.gradio-container table th span {
    display: inline-block !important;
    text-align: center !important;
}
"""

def update_chart_display(selected_chart):
    new_table_value, new_table_label = invObj.serve_selected_chart(selected_chart)
    return gr.update(value=new_table_value, label=new_table_label)


with gr.Blocks() as dashboard:
    # The wrapper for everything in the launched demo.

    gr.Markdown("# FAANG Robotrader - *Pursuit of Wealth by 4 Virtual Investors*")

    gr.Markdown("""### <p align="center"><a href="https://huggingface.co/spaces/ML-Owl/FAANG-Robotrader/blob/main/README.md" target="_blank">Read the documentation</a> to learn more about the Robotrader and the investors' strategies.</p>""")

    gr.Markdown("""### Watch how well the following investors each with $500K budget perform in the real world using my Robotrader based on <a href="https://huggingface.co/spaces/ML-Owl/FAANG-Pulse-AI" target="_blank">FAANG Pulse AI !</a>""")
    
    gr.Markdown("""- **Safe Sam -** Precision over participation""")
    gr.Markdown("""- **Optimal Owen -** Model-calibrated balance""")
    gr.Markdown("""- **Brave Beth -** Participation over precision""")
    gr.Markdown("""- **Random Randy -** Chance-based benchmark""")

    ### 📣 Stay tuned for updates!!!""")
    
    # Performance chart dropdown rowread the documentation to understand how the Robotrader works and how the 4 investors use it.
    with gr.Row():
        gr.Column(scale=2)  # empty column on row for left spacing
        with gr.Column(scale=1):  # 20% of full width
            with gr.Group():
                gr.Markdown("### 📉📈 PERFORMANCE CHARTS:")
                charts_dropdown = gr.Dropdown(
                    label="Pick a chart to analyze.",
                    value=invObj.selected_chart,  # object defauls set as dropdown value
                    choices=invObj.get_available_charts()
                )
        gr.Column(scale=2)  # empty column on row for right spacing

    # Table charts row
    with gr.Row():
        chart_display = gr.DataFrame(
            value=invObj.selected_chart_df,
            label=f"{invObj.selected_chart}",
            wrap=True,
            interactive=False  # pandas Data Frames apply ONLY when the table is NOT interactive!
        )

    ###### EVENT LISTENERS FOLLOW

    charts_dropdown.change(
        fn=update_chart_display,
        inputs=[charts_dropdown],
        outputs=chart_display,  # Display as table in the GUI
        api_name="update_selected_chart",
        api_visibility="private"  # not exposed as public API
    )

    dashboard.launch(theme=gr.themes.Soft(), css=css, ssr_mode=False)

