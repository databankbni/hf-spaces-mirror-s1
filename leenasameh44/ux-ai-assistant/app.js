import { pipeline } from "https://cdn.jsdelivr.net/npm/@huggingface/transformers@3.8.1";

const MODEL = "HuggingFaceTB/SmolVLM-256M-Instruct";

let model = null;
let selectedImage = null;

const DAILY_LIMIT = 5;

const status = document.getElementById("status");
const analyzeButton = document.getElementById("analyzeButton");

const imageInput = document.getElementById("imageInput");
const preview = document.getElementById("preview");
const previewContainer = document.getElementById("previewContainer");


// =========================
// DAILY LIMIT
// =========================

function getUsage() {
    const today = new Date().toISOString().split("T")[0];

    let saved;

    try {
        saved = JSON.parse(
            localStorage.getItem("ux_usage") || "{}"
        );
    } catch {
        saved = {};
    }

    if (saved.date !== today) {
        return {
            date: today,
            count: 0
        };
    }

    return saved;
}


function canAnalyze() {
    const usage = getUsage();

    return usage.count < DAILY_LIMIT;
}


function increaseUsage() {
    const usage = getUsage();

    usage.count += 1;

    localStorage.setItem(
        "ux_usage",
        JSON.stringify(usage)
    );
}


function updateStatusWithLimit() {
    const usage = getUsage();

    const remaining =
        DAILY_LIMIT - usage.count;

    if (remaining <= 0) {
        status.textContent =
            "You reached your daily limit of 5 analyses.";
    } else {
        status.textContent =
            `AI ready ✓ ${remaining} analyses remaining today.`;
    }
}


// =========================
// BUTTON
// =========================

function updateButton() {
    analyzeButton.disabled =
        !selectedImage ||
        !model ||
        !canAnalyze();
}


// =========================
// LOAD MODEL
// =========================

async function loadModel() {

    status.textContent =
        "Loading AI model... This may take a while the first time.";

    try {

        model = await pipeline(
            "image-text-to-text",
            MODEL,
            {
                device: "webgpu",
                dtype: {
                    embed_tokens: "fp32",
                    vision_encoder: "q4",
                    decoder_model_merged: "q4"
                }
            }
        );

        updateStatusWithLimit();
        updateButton();

    } catch (webgpuError) {

        console.error(
            "WebGPU failed:",
            webgpuError
        );

        status.textContent =
            "WebGPU failed. Trying CPU...";

        try {

            model = await pipeline(
                "image-text-to-text",
                MODEL,
                {
                    dtype: "q8"
                }
            );

            updateStatusWithLimit();
            updateButton();

        } catch (cpuError) {

            console.error(
                "CPU failed:",
                cpuError
            );

            status.textContent =
                "Could not load the AI model. Please use a modern Chrome or Edge browser.";
        }
    }
}


// =========================
// IMAGE UPLOAD
// =========================

imageInput.addEventListener(
    "change",
    (event) => {

        const file =
            event.target.files[0];

        if (!file) {
            return;
        }

        selectedImage = file;

        preview.src =
            URL.createObjectURL(file);

        previewContainer
            .classList
            .remove("hidden");

        updateButton();
    }
);


// =========================
// UX PROMPT
// =========================

function buildPrompt(problem) {

    return `
You are an expert UX/UI designer and usability analyst.

Analyze the provided application screenshot.

Look specifically for:

- Visual hierarchy
- Navigation
- Layout
- Spacing
- Typography
- Color contrast
- CTA visibility
- Forms
- Accessibility
- Consistency
- Cognitive load

Identify ONLY problems that can actually
be observed in the screenshot.

For every problem provide:

Severity:
High, Medium, or Low

Category:

Problem:

Why it is a UX problem:

Recommendation:

Also provide an overall UX score from 0 to 100.

User's reported problem:
${problem || "No specific problem provided."}

Give a concise and practical UX report.
`;
}


// =========================
// ANALYZE
// =========================

analyzeButton.addEventListener(
    "click",
    analyzeUX
);


async function analyzeUX() {

    if (!model || !selectedImage) {
        return;
    }

    // Check daily limit
    if (!canAnalyze()) {

        status.textContent =
            "You reached your daily limit of 5 analyses.";

        updateButton();

        return;
    }

    analyzeButton.disabled = true;

    status.textContent =
        "Analyzing your UI...";

    const problem =
        document
            .getElementById("problemInput")
            .value
            .trim();

    const prompt =
        buildPrompt(problem);

    try {

        const result = await model(
            [
                {
                    role: "user",
                    content: [
                        {
                            type: "image",
                            image: selectedImage
                        },
                        {
                            type: "text",
                            text: prompt
                        }
                    ]
                }
            ],
            {
                max_new_tokens: 500
            }
        );

        displayResult(result);

        // Count only successful analyses
        increaseUsage();

        status.textContent =
            "Analysis completed ✓";

    } catch (error) {

        console.error(
            "Analysis error:",
            error
        );

        status.textContent =
            "Something went wrong while analyzing the screenshot.";
    }

    updateButton();
}


// =========================
// DISPLAY RESULT
// =========================

function displayResult(result) {

    const resultSection =
        document.getElementById("result");

    const resultContent =
        document.getElementById("resultContent");

    let text = "";

    if (Array.isArray(result)) {

        text = result
            .map(
                item =>
                    item.generated_text || ""
            )
            .join("\n");

    } else {

        text =
            JSON.stringify(
                result,
                null,
                2
            );
    }

    resultContent.innerText =
        text;

    resultSection
        .classList
        .remove("hidden");
}


// =========================
// START
// =========================

loadModel();