import gradio as gr

from public_demo.demo_service import answer_question, check_eligibility, build_pathway


TITLE = "Verified Student Pathway Agent"
SUBTITLE = "Evidence-backed course guidance, eligibility checks and safer study pathways"


def app_header():
    return f"""
    <section class='hero'>
      <div class='eyebrow'>VERIFIED KNOWLEDGE AGENT · PUBLIC DEMO</div>
      <h1>{TITLE}</h1>
      <p class='subtitle'>{SUBTITLE}</p>
      <p class='intro'>Explore courses, check published entry conditions and understand a possible next step—without treating an AI response as an admission decision.</p>
      <div class='badges'><span>Official-source citations</span><span>Deterministic rule checks</span><span>Human-review boundaries</span></div>
    </section>
    """


CSS = """
.gradio-container {max-width: 1180px !important; background: #f5f7fb;}
.hero {padding: 28px 32px; border-radius: 18px; color: white; background: linear-gradient(125deg,#12253f,#176b78); margin-bottom: 16px; box-shadow: 0 10px 25px #15324a26;}
.hero h1 {font-size: 2.25rem; margin: 5px 0 2px; color:#ffffff !important; text-shadow:0 1px 2px #06152180;}
.hero .subtitle {font-size: 1.18rem; font-weight: 650; color: #d5fbf4 !important; margin: 0 0 10px;}
.hero .intro {max-width: 850px; color: #eaf2f7 !important;}
.hero .eyebrow {font-size: .74rem; letter-spacing: .12em; color: #91eadc !important; font-weight: 700;}
.badges {display:flex; flex-wrap:wrap; gap:8px; margin-top:14px;}
.badges span {padding:7px 11px; border:1px solid #b9eee5; border-radius:999px; background:#eefcf9; color:#123d4a !important; font-size:.80rem; font-weight:700; box-shadow:0 1px 3px #071d2b24;}
.panel {border-radius: 14px !important;}
.footer-note {font-size:.83rem; color:#536273; padding:10px 4px 22px;}
"""


with gr.Blocks(title=TITLE, css=CSS, theme=gr.themes.Soft(primary_hue="teal")) as demo:
    gr.HTML(app_header())

    with gr.Tabs():
        with gr.Tab("Ask about a course"):
            gr.Markdown("### Get a sourced answer\nAsk about duration, delivery mode, entry requirements or fees in the demonstration catalogue.")
            with gr.Row():
                with gr.Column(scale=2, elem_classes="panel"):
                    q = gr.Textbox(label="Your question", value="Can I study the Bachelor of Applied Computing part-time?", lines=3)
                    ask_btn = gr.Button("Check official information", variant="primary")
                    gr.Examples(
                        examples=[
                            ["Can I study the Bachelor of Applied Computing part-time?"],
                            ["What English evidence is required for international applicants?"],
                            ["How long is the Diploma of Information Technology?"],
                            ["What are the published fees for the Applied Computing degree?"],
                        ], inputs=q
                    )
                with gr.Column(scale=3, elem_classes="panel"):
                    ans = gr.Markdown(label="Verified answer")
            ask_btn.click(answer_question, q, ans)

        with gr.Tab("Check eligibility"):
            gr.Markdown("### Check published conditions\nThis is a preliminary rule check—not an admission decision.")
            with gr.Row():
                with gr.Column(scale=2):
                    target = gr.Dropdown(["Bachelor of Applied Computing", "Diploma of Information Technology"], value="Bachelor of Applied Computing", label="Target course")
                    applicant = gr.Radio(["Domestic", "International"], value="Domestic", label="Applicant type")
                    qualification = gr.Dropdown(["Year 12", "Certificate IV", "Diploma", "Bachelor degree", "Other / overseas qualification"], value="Diploma", label="Highest qualification")
                    relevant = gr.Checkbox(value=True, label="Qualification is in IT or a related field")
                    experience = gr.Slider(0, 10, value=2, step=1, label="Relevant work experience (years)")
                    english = gr.Radio(["Not provided", "Published requirement met", "Needs individual assessment"], value="Not provided", label="English-language evidence")
                    elig_btn = gr.Button("Run verified check", variant="primary")
                with gr.Column(scale=3):
                    elig_out = gr.Markdown()
            elig_btn.click(check_eligibility, [target, applicant, qualification, relevant, experience, english], elig_out)

        with gr.Tab("Build a pathway"):
            gr.Markdown("### Find a safer next step\nOnly pathways supported by the demonstration knowledge set are shown.")
            with gr.Row():
                current = gr.Dropdown(["Year 12", "Certificate IV", "Diploma of Information Technology", "Unrecognised / unclear qualification"], value="Certificate IV", label="Current position")
                goal = gr.Dropdown(["Bachelor of Applied Computing"], value="Bachelor of Applied Computing", label="Study goal")
            path_btn = gr.Button("Build verified pathway", variant="primary")
            path_out = gr.Markdown()
            path_btn.click(build_pathway, [current, goal], path_out)

        with gr.Tab("About & safety"):
            gr.Markdown("""
## What this demo does

It helps prospective students find course facts, compare their circumstances with **published** entry conditions, and identify a possible study pathway. Each material conclusion is paired with a source reference or a clear human-review boundary.

## Who it is for

Prospective students, career changers, education advisers and institutions exploring a safer digital enquiry experience.

## Inputs and outputs

- **Input:** a course question or a small set of applicant details.
- **Output:** a sourced answer, preliminary condition check, missing information, a possible next step and a compact 4C verification summary.

## Safety boundary

This public demonstration uses fictional course data for **Example Institute Australia**. It does not make admission decisions, approve credit, give visa advice, promise employment outcomes or store submitted personal information. Ambiguous and exceptional cases are referred for human assessment.

## Public demo and protected platform

The Space demonstrates the user experience and selected verification outputs. Production capabilities—document ingestion, LLM Wiki construction, provenance management, rule extraction, constraint services, full audit logging, evaluation dashboards, approval workflows and deployment templates—belong to a separate protected platform and are not included in this public release.
            """)

    gr.HTML("<div class='footer-note'><b>Important:</b> LLM-generated explanations, when enabled, are auxiliary. Deterministic rule status and cited source records remain authoritative within the demo.</div>")


if __name__ == "__main__":
    demo.launch()
