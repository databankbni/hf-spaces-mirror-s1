import gradio as gr
from apscheduler.schedulers.background import BackgroundScheduler

from src.data import filter_dataframe, load_evaluation_results
from src.settings import LB_ALLOWED_DATASETS, LB_ALLOWED_MODELS, LB_DEFAULT_MODELS, LOCAL_RESULTS_DIR
from src.textual_content import CITATION_TEXT, INTRO_TEXT, MOTIVATION_TEXT, SUBMISSION_INSTRUCTIONS, TITLE
from src.utils import create_interactive_leaderboard_plot, generate_detail_panel_html, get_leaderboard_css, restart_space

# Load dataframe file with results
print("Loading results...")
results_df = load_evaluation_results(LOCAL_RESULTS_DIR, pretty_method_names=True)

# Filter the dataframe according to the settings in settings.py
results_df = filter_dataframe(results_df, selected_datasets=LB_ALLOWED_DATASETS, selected_models=LB_ALLOWED_MODELS)

# Get available methods and models from filtered data
method_options = results_df["method"].unique().tolist()
# Full list for consistent color assignment
all_methods_for_colors = sorted([m for m in method_options if m != "No Compression"])

# Get default models for initial display
default_models = LB_DEFAULT_MODELS or LB_ALLOWED_MODELS

print("Initializing leaderboard...")
demo = gr.Blocks(theme=gr.themes.Default(primary_hue="green", secondary_hue="green"))
with demo:

    gr.HTML(TITLE)
    gr.Image(value="https://raw.githubusercontent.com/NVIDIA/kvpress/refs/heads/main/kvpress.jpg", width=600)
    gr.Markdown(INTRO_TEXT)
    gr.Markdown(MOTIVATION_TEXT)

    with gr.Tabs(elem_classes="tab-buttons") as tabs:

        #### Leaderboard & Plot ####
        with gr.TabItem("🏅 Benchmark"):
            # Inject custom CSS
            gr.HTML(get_leaderboard_css())

            with gr.Column():
                # Create plot
                with gr.Row():
                    # Filter dataframe for initial plot display using default models
                    initial_plot_df = filter_dataframe(results_df, selected_models=default_models, selected_methods=method_options)
                    lb_plot = gr.Plot(
                        value=create_interactive_leaderboard_plot(
                            initial_plot_df, title="KVPress Leaderboard - RULER 4k", all_methods=all_methods_for_colors
                        ),
                        container=True,
                    )

                # Model selector (always visible)
                available_models = LB_ALLOWED_MODELS or results_df["model"].unique().tolist()

                model_checkboxes = gr.CheckboxGroup(
                    choices=available_models,
                    label="Select Models",
                    value=default_models,
                )

                # Method Selection + Detail Panel Layout
                with gr.Row(equal_height=False):
                    # Left: Method Selection (compact)
                    with gr.Column(scale=1, min_width=220):
                        gr.Markdown("### 📊 Methods")

                        # Use Radio for reliable selection, styled as a list
                        method_selector = gr.Radio(
                            choices=sorted(method_options),
                            label="",
                            value=None,
                            elem_id="method-selector-radio",
                        )

                    # Right: Detail Panel
                    with gr.Column(scale=2, min_width=400):
                        gr.Markdown("### 📋 Method Details")
                        detail_panel = gr.HTML(
                            value=generate_detail_panel_html(results_df, None, full_df=results_df),
                            elem_id="detail-panel",
                        )

                # Update detail panel when method is selected
                def update_detail_panel(method_name, model_list):
                    if not method_name:
                        return generate_detail_panel_html(results_df, None, full_df=results_df)
                    filtered = filter_dataframe(
                        results_df,
                        selected_models=model_list,
                        selected_methods=method_options,
                    )
                    return generate_detail_panel_html(filtered, method_name, full_df=results_df)

                method_selector.change(
                    fn=update_detail_panel,
                    inputs=[method_selector, model_checkboxes],
                    outputs=[detail_panel],
                )

                # Update plot and detail panel when model selection changes
                def update_leaderboard(models, method_name):
                    # Update plot
                    filtered_df_plot = filter_dataframe(
                        results_df,
                        selected_models=models,
                        selected_methods=method_options,
                        apply_clickable=False,
                    )
                    updated_plot = create_interactive_leaderboard_plot(
                        filtered_df_plot, title="KVPress Leaderboard", all_methods=all_methods_for_colors
                    )
                    # Update detail panel
                    updated_detail = update_detail_panel(method_name, models)
                    return updated_plot, updated_detail

                model_checkboxes.change(
                    fn=update_leaderboard,
                    inputs=[model_checkboxes, method_selector],
                    outputs=[lb_plot, detail_panel],
                )

        #### Submission instructions ####
        with gr.TabItem("🚀 Submit here!"):
            with gr.Column():
                gr.Markdown(SUBMISSION_INSTRUCTIONS)

        #### Citation ####
        with gr.TabItem("📙 Citation"):
            with gr.Column():
                gr.Markdown(CITATION_TEXT)


# Launch the app
scheduler = BackgroundScheduler()
scheduler.add_job(restart_space, "interval", hours=12)
scheduler.start()
demo.queue(default_concurrency_limit=40).launch(ssr_mode=False)
print("App launched")
