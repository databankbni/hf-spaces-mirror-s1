import gradio as gr


launch_js = """() => {
    document.title = "LAUNCH-JS-RAN";
    const status = document.querySelector("#launch-js-status");
    if (status) {
        status.textContent = "Status: launch(js=...) ran";
        status.dataset.executed = "true";
    }

    const animation = document.querySelector("#launch-animation");
    const animationLabel = document.querySelector("#launch-animation-label");
    if (animation) {
        animation.dataset.animated = "true";
        animation.classList.add("launch-animation-ran");
    }
    if (animationLabel) {
        animationLabel.textContent = "Animation ran — launch(js=...) executed";
    }
};"""


with gr.Blocks(title="Gradio #13636 launch JavaScript") as demo:
    gr.Markdown(
        """
        # Gradio #13636 — `Blocks.launch(js=...)`

        The launch hook should set the browser title to **LAUNCH-JS-RAN** and
        play the quick animation below. The **before** Space keeps its configured
        title and leaves the pulse parked; the **after** Space runs the function
        after the Blocks tree is ready.
        """
    )
    gr.HTML(
        """
        <style>
            #launch-animation {
                box-sizing: border-box;
                margin: 1rem 0;
                padding: 1rem;
                border: 1px solid var(--border-color-primary);
                border-radius: 0.9rem;
                background: linear-gradient(135deg, #f8fafc, #eef2ff);
                overflow: hidden;
            }
            #launch-animation-track {
                position: relative;
                height: 3rem;
                border-radius: 999px;
                background: #dbe4f0;
                box-shadow: inset 0 1px 3px rgb(15 23 42 / 15%);
            }
            #launch-animation-pulse {
                position: absolute;
                top: 0.5rem;
                left: 0.5rem;
                display: grid;
                width: 2rem;
                height: 2rem;
                place-items: center;
                border-radius: 50%;
                background: #64748b;
                color: white;
                box-shadow: 0 4px 12px rgb(15 23 42 / 25%);
            }
            #launch-animation-label {
                margin-top: 0.65rem;
                color: #475569;
                font-weight: 600;
                text-align: center;
            }
            #launch-animation.launch-animation-ran {
                animation: launch-card-pop 500ms ease-out;
            }
            #launch-animation.launch-animation-ran #launch-animation-track {
                animation: launch-track-glow 1.2s ease-out forwards;
            }
            #launch-animation.launch-animation-ran #launch-animation-pulse {
                animation: launch-pulse-flight 1.2s cubic-bezier(0.22, 1, 0.36, 1)
                    forwards;
                background: #16a34a;
            }
            #launch-animation.launch-animation-ran #launch-animation-label {
                color: #15803d;
            }
            @keyframes launch-card-pop {
                0% { transform: scale(0.98); opacity: 0.75; }
                100% { transform: scale(1); opacity: 1; }
            }
            @keyframes launch-track-glow {
                0% { background: #dbe4f0; }
                45% { background: #bfdbfe; }
                100% { background: #dcfce7; }
            }
            @keyframes launch-pulse-flight {
                0% { left: 0.5rem; transform: scale(0.85); }
                55% { transform: scale(1.25) rotate(180deg); }
                100% { left: calc(100% - 2.5rem); transform: scale(1) rotate(360deg); }
            }
            @media (prefers-reduced-motion: reduce) {
                #launch-animation.launch-animation-ran,
                #launch-animation.launch-animation-ran #launch-animation-track,
                #launch-animation.launch-animation-ran #launch-animation-pulse {
                    animation-duration: 1ms;
                }
            }
        </style>
        <div id="launch-animation" data-animated="false" aria-live="polite">
            <div id="launch-animation-track" aria-hidden="true">
                <span id="launch-animation-pulse">⚡</span>
            </div>
            <div id="launch-animation-label">
                Waiting for launch(js=...) animation
            </div>
        </div>
        """
    )
    gr.HTML(
        '<div id="launch-js-status" data-executed="false">'
        "Status: launch(js=...) did not run</div>"
    )

demo.launch(js=launch_js)
