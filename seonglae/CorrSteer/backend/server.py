import os
import torch
from flask import Flask, Response, request, jsonify
from transformers import AutoTokenizer, AutoModelForCausalLM, TextIteratorStreamer
from threading import Thread
from sae_lens import SAE
from flask_cors import CORS
from json import load

from config import datasets_config, models_config

# ------------------------------------
# Device setup
# ------------------------------------
device = "cuda" if torch.cuda.is_available() else "cpu"

# ------------------------------------
# Model loading
# ------------------------------------
tokenizer = AutoTokenizer.from_pretrained("gpt2")
if tokenizer.pad_token_id is None:
    tokenizer.pad_token_id = tokenizer.eos_token_id

original_model = AutoModelForCausalLM.from_pretrained("gpt2").to(device)
original_model.eval()

trained_model = AutoModelForCausalLM.from_pretrained("holistic-ai/gpt2-EMGSD").to(device)
trained_model.eval()

# ------------------------------------
# Steering hooks
# ------------------------------------
hooks = []


def generate_pre_hook(sae: SAE, index: int, coeff: float):
    def steering_hook(module, inputs):
        residual = inputs[0]
        steering_vector = sae.W_dec[index].to(device).unsqueeze(0).unsqueeze(0)
        residual = residual + coeff * steering_vector
        return (residual,)

    return steering_hook


def generate_post_hook(sae: SAE, index: int, coeff: float):
    def steering_hook(module, inputs, outputs):
        residual = outputs[0]
        steering_vector = sae.W_dec[index].to(device).unsqueeze(0).unsqueeze(0)
        residual = residual + coeff * steering_vector
        return (residual,) + outputs[1:]

    return steering_hook


def register_steering(model, model_key: str, gen_type: str, dataset_key: str, category_key: str):
    file_path = f"features/{model_key}.{dataset_key}.json"
    with open(file_path, "r") as f:
        feature_map = load(f)
        top_features = feature_map[category_key]

        # Pick top positive-correlation feature, use sign for direction
        pos_features = [f for f in top_features if f["correlation"] > 0]
        if not pos_features:
            pos_features = top_features
        top_feature = pos_features[0]

        # Amplify: +50, Mitigate: -150 (validated in emgsd-hermes)
        if "-" in gen_type:
            coeff = -150
        else:
            coeff = 50

        sae_hook_point = "blocks.11.hook_resid_post"
        block_idx = 11
        index = top_feature["feature_index"]

        sae, cfg_dict, sparsity = SAE.from_pretrained(
            models_config[model_key]["sae"],
            sae_hook_point,
            device=device,
        )

    # Use post-hook on transformer block (matches emgsd-hermes)
    module = model.transformer.h[block_idx]
    handle = module.register_forward_hook(generate_post_hook(sae, index, coeff))
    hooks.append(handle)


def remove_hooks():
    for h in hooks:
        h.remove()
    hooks.clear()


# ------------------------------------
# Streaming generation
# ------------------------------------
def stream_generate(model, prompt, max_new_tokens=60, temperature=1.0, repetition_penalty=1.2, seed=42):
    streamer = TextIteratorStreamer(tokenizer, skip_prompt=True, skip_special_tokens=True)
    inputs = tokenizer(prompt, return_tensors="pt").to(device)

    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed(seed)

    generation_kwargs = dict(
        **inputs,
        streamer=streamer,
        max_new_tokens=max_new_tokens,
        do_sample=True,
        temperature=temperature,
        top_p=0.9,
        pad_token_id=tokenizer.eos_token_id,
        repetition_penalty=repetition_penalty,
    )

    thread = Thread(target=model.generate, kwargs=generation_kwargs)
    thread.start()

    for new_text in streamer:
        yield new_text


# ------------------------------------
# Flask App
# ------------------------------------
app = Flask(__name__)
CORS(app)


@app.route("/api/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/api/generate", methods=["POST"])
def generate():
    """
    Expects JSON:
    {
      "model": "gpt2",
      "dataset": "emgsd",
      "category": "lgbtq+",
      "type": "original" | "origin+steer" | "trained" | "trained-steer"
    }
    Streams back generated text token by token.
    """
    data = request.json
    model_key = data.get("model", "gpt2")
    dataset_key = data.get("dataset", "emgsd")
    category_key = data.get("category", "lgbtq+")
    gen_type = data.get("type", "original")

    try:
        prompt_text = datasets_config[dataset_key]["category"][category_key]["prompt"]
    except KeyError:
        return Response("Invalid dataset/category combination.", status=400)

    if "trained" in gen_type:
        chosen_model = trained_model
    else:
        chosen_model = original_model

    remove_hooks()
    if "steer" in gen_type:
        register_steering(chosen_model, model_key, gen_type, dataset_key, category_key)

    def token_stream():
        for token in stream_generate(chosen_model, prompt_text):
            yield token
        remove_hooks()

    return Response(token_stream(), mimetype="text/event-stream")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    app.run(host="0.0.0.0", port=port)
