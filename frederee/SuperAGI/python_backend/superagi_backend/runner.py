import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path


MODEL_OPTIONS = ("SuperAGI 0.2",)
DEFAULT_MODEL = MODEL_OPTIONS[-1]
PYTHON_BACKEND_ROOT = Path(__file__).resolve().parents[1]
BUNDLED_SUPERAGI_REPO_PATH = PYTHON_BACKEND_ROOT / "vendor" / "SuperAGI"
BUNDLED_MODEL_CHECKPOINT_PATHS = {
    "SuperAGI 0.2": PYTHON_BACKEND_ROOT / "models" / "superagi" / "superagi-0.3.pt",
}


class PlaceholderModelRunner:
    def __init__(self, model=DEFAULT_MODEL):
        self.model = model

    def generate(self, *, prompt, model):
        return (
            f"SuperAGI backend received your message using model {model}. "
            "Set SUPERAGI_REPO_PATH and SUPERAGI_CHECKPOINT_PATH to use the trained checkpoint."
        )

    def describe(self):
        return {
            "model": self.model,
            "runner": "placeholder",
            "ready": True
        }


class ModelRouter:
    def __init__(self, *, runners, default_model=DEFAULT_MODEL, aliases=None, model_options=MODEL_OPTIONS):
        self.runners = dict(runners)
        self.default_model = default_model
        self.aliases = dict(aliases or {})
        self.model_options = tuple(model_options)

    def generate(self, *, prompt, model):
        target_model = self.resolve_model(model)
        runner = self.runners.get(target_model)
        if runner is None:
            raise RuntimeError(f"Model {model} is not configured")

        return runner.generate(prompt=prompt, model=target_model)

    def describe(self):
        models = [self._describe_model(model) for model in self.model_options]
        default_description = self._describe_model(self.default_model)
        return {
            "model": self.default_model,
            "runner": "model-router",
            "ready": default_description["ready"],
            "served_by": default_description["served_by"],
            "models": models
        }

    def supports(self, model):
        return normalize_model_label(model) in self.model_options

    def supported_models(self):
        return self.model_options

    def resolve_model(self, model):
        model = normalize_model_label(model)
        if model not in self.model_options:
            return self.default_model
        return self.aliases.get(model, model)

    def _describe_model(self, model):
        target_model = self.resolve_model(model)
        runner = self.runners.get(target_model)
        if runner is None:
            return {
                "model": model,
                "served_by": target_model,
                "runner": "missing",
                "ready": False
            }

        description = dict(runner.describe())
        description["model"] = model
        description["served_by"] = target_model
        return description


class SuperAGICheckpointRunner:
    def __init__(
        self,
        *,
        repo_path,
        checkpoint_path,
        model=DEFAULT_MODEL,
        device="auto",
        max_new_tokens=120,
        temperature=0.5,
        top_k=20,
        repetition_penalty=1.25,
        repetition_window=128
    ):
        self.repo_path = Path(repo_path)
        self.checkpoint_path = Path(checkpoint_path)
        self.model = model
        self.device = device
        self.max_new_tokens = max_new_tokens
        self.temperature = temperature
        self.top_k = top_k
        self.repetition_penalty = repetition_penalty
        self.repetition_window = repetition_window
        self._checkpoint = None
        self._torch = None
        self._extract_chat_reply = None

    def generate(self, *, prompt, model):
        checkpoint = self._load_checkpoint()
        torch = self._torch
        extract_chat_reply = self._extract_chat_reply
        torch_device = self._resolve_device(torch)
        checkpoint.model.to(torch_device)

        prompt_ids = checkpoint.tokenizer.encode(prompt)
        if not prompt_ids:
            return ""

        input_ids = torch.tensor([prompt_ids], dtype=torch.long, device=torch_device)
        generated = checkpoint.model.generate(
            input_ids=input_ids,
            max_new_tokens=self.max_new_tokens,
            temperature=self.temperature,
            top_k=self.top_k,
            repetition_penalty=self.repetition_penalty,
            repetition_window=self.repetition_window
        )
        generated_text = checkpoint.tokenizer.decode(generated[0].cpu().tolist())
        if extract_chat_reply is not None:
            return extract_chat_reply(prompt, generated_text)
        if generated_text.startswith(prompt):
            return generated_text[len(prompt) :].strip()
        return generated_text.strip()

    def describe(self):
        return {
            "model": self.model,
            "runner": "superagi-checkpoint",
            "ready": self.checkpoint_path.exists(),
            "checkpoint_path": str(self.checkpoint_path),
            "device": self.device,
            "max_new_tokens": self.max_new_tokens,
            "temperature": self.temperature,
            "top_k": self.top_k,
            "repetition_penalty": self.repetition_penalty,
            "repetition_window": self.repetition_window
        }

    def _load_checkpoint(self):
        if self._checkpoint is not None:
            return self._checkpoint

        src_path = self.repo_path / "src"
        if not src_path.exists():
            raise RuntimeError(f"SuperAGI source directory not found: {src_path}")
        if not self.checkpoint_path.exists():
            raise RuntimeError(f"SuperAGI checkpoint not found: {self.checkpoint_path}")

        src_path_text = str(src_path)
        if src_path_text not in sys.path:
            sys.path.insert(0, src_path_text)

        import torch
        from superagi.chat.session import extract_chat_reply
        from superagi.model.checkpoint import load_checkpoint

        self._torch = torch
        self._extract_chat_reply = extract_chat_reply
        self._checkpoint = load_checkpoint(self.checkpoint_path, map_location="cpu")
        return self._checkpoint

    def _resolve_device(self, torch):
        if self.device != "auto":
            return torch.device(self.device)
        if torch.cuda.is_available():
            return torch.device("cuda")
        mps = getattr(torch.backends, "mps", None)
        if mps is not None and mps.is_available():
            return torch.device("mps")
        return torch.device("cpu")


class RunPodModelRunner:
    def __init__(
        self,
        *,
        endpoint_id,
        api_key,
        model=DEFAULT_MODEL,
        base_url="https://api.runpod.ai/v2",
        timeout_seconds=180,
        max_new_tokens=120,
        temperature=0.5,
        top_k=20,
        repetition_penalty=1.25,
        repetition_window=128
    ):
        self.endpoint_id = endpoint_id.strip()
        self.api_key = api_key.strip()
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.max_new_tokens = max_new_tokens
        self.temperature = temperature
        self.top_k = top_k
        self.repetition_penalty = repetition_penalty
        self.repetition_window = repetition_window

    def generate(self, *, prompt, model):
        request = urllib.request.Request(
            f"{self.base_url}/{self.endpoint_id}/runsync",
            data=json.dumps(
                {
                    "input": {
                        "prompt": prompt,
                        "model": model,
                        "max_new_tokens": self.max_new_tokens,
                        "temperature": self.temperature,
                        "top_k": self.top_k,
                        "repetition_penalty": self.repetition_penalty,
                        "repetition_window": self.repetition_window,
                    }
                }
            ).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as error:
            raise RuntimeError(_runpod_http_error_message(error)) from error
        except urllib.error.URLError as error:
            raise RuntimeError(f"RunPod request failed: {error.reason}") from error
        except json.JSONDecodeError as error:
            raise RuntimeError("RunPod response was not valid JSON") from error

        return _extract_runpod_text(payload)

    def describe(self):
        return {
            "model": self.model,
            "runner": "runpod-serverless",
            "ready": bool(self.endpoint_id and self.api_key),
            "endpoint_id": self.endpoint_id,
            "base_url": self.base_url,
            "timeout_seconds": self.timeout_seconds,
            "max_new_tokens": self.max_new_tokens,
            "temperature": self.temperature,
            "top_k": self.top_k,
            "repetition_penalty": self.repetition_penalty,
            "repetition_window": self.repetition_window
        }


def build_prompt(messages):
    lines = []
    for message in messages:
        if message["role"] == "assistant":
            lines.append(f"AGI: {message['text']}")
        else:
            lines.append(f"User: {message['text']}")
    lines.append("AGI:")
    return "\n".join(lines)


def create_model_runner_from_env():
    default_model = normalize_model_label(
        os.environ.get("SUPERAGI_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
    )
    if default_model not in MODEL_OPTIONS:
        default_model = DEFAULT_MODEL

    runpod_runner = _create_runpod_runner_from_env(default_model)
    if runpod_runner is not None:
        aliases = {
            model: default_model
            for model in MODEL_OPTIONS
            if model != default_model
        }
        return ModelRouter(
            runners={default_model: runpod_runner},
            default_model=default_model,
            aliases=aliases,
        )

    runners = {}
    for model in MODEL_OPTIONS:
        runners[model], _has_checkpoint = _create_runner_for_model(model)

    return ModelRouter(runners=runners, default_model=default_model)


def _create_runner_for_model(model):
    repo_path = _get_model_env(model, "REPO_PATH") or os.environ.get("SUPERAGI_REPO_PATH", "").strip()
    checkpoint_path = (
        _get_model_env(model, "CHECKPOINT_PATH")
        or os.environ.get("SUPERAGI_CHECKPOINT_PATH", "").strip()
    )

    if not repo_path and BUNDLED_SUPERAGI_REPO_PATH.exists():
        repo_path = str(BUNDLED_SUPERAGI_REPO_PATH)
    bundled_checkpoint_path = BUNDLED_MODEL_CHECKPOINT_PATHS.get(model)
    if not checkpoint_path and bundled_checkpoint_path and bundled_checkpoint_path.exists():
        checkpoint_path = str(bundled_checkpoint_path)
    if not repo_path or not checkpoint_path:
        return PlaceholderModelRunner(model=model), False

    top_k = os.environ.get("SUPERAGI_TOP_K", "").strip()
    repetition_window = os.environ.get("SUPERAGI_REPETITION_WINDOW", "").strip()
    return SuperAGICheckpointRunner(
        repo_path=repo_path,
        checkpoint_path=checkpoint_path,
        model=model,
        device=os.environ.get("SUPERAGI_DEVICE", "auto"),
        max_new_tokens=int(os.environ.get("SUPERAGI_MAX_NEW_TOKENS", "120")),
        temperature=float(os.environ.get("SUPERAGI_TEMPERATURE", "0.5")),
        top_k=int(top_k) if top_k else 20,
        repetition_penalty=float(os.environ.get("SUPERAGI_REPETITION_PENALTY", "1.25")),
        repetition_window=int(repetition_window) if repetition_window else 128
    ), True


def _create_runpod_runner_from_env(default_model):
    endpoint_id = os.environ.get("RUNPOD_ENDPOINT_ID", "").strip()
    api_key = os.environ.get("RUNPOD_API_KEY", "").strip()
    if not endpoint_id or not api_key:
        return None

    top_k = os.environ.get("SUPERAGI_TOP_K", "").strip()
    repetition_window = os.environ.get("SUPERAGI_REPETITION_WINDOW", "").strip()
    timeout_seconds = os.environ.get("RUNPOD_TIMEOUT_SECONDS", "").strip()
    return RunPodModelRunner(
        endpoint_id=endpoint_id,
        api_key=api_key,
        model=default_model,
        base_url=os.environ.get("RUNPOD_BASE_URL", "https://api.runpod.ai/v2"),
        timeout_seconds=int(timeout_seconds) if timeout_seconds else 180,
        max_new_tokens=int(os.environ.get("SUPERAGI_MAX_NEW_TOKENS", "120")),
        temperature=float(os.environ.get("SUPERAGI_TEMPERATURE", "0.5")),
        top_k=int(top_k) if top_k else 20,
        repetition_penalty=float(os.environ.get("SUPERAGI_REPETITION_PENALTY", "1.25")),
        repetition_window=int(repetition_window) if repetition_window else 128
    )


def _get_model_env(model, suffix):
    for candidate in _model_env_candidates(model):
        value = os.environ.get(f"{_model_env_prefix(candidate)}_{suffix}", "").strip()
        if value:
            return value
    return ""


def normalize_model_label(model):
    return model


def _model_env_candidates(model):
    model = normalize_model_label(model)
    candidates = [model]
    if model == "SuperAGI 0.2":
        candidates.append("SuperAGI 0.3")
    return candidates


def _model_env_prefix(model):
    return "".join(character if character.isalnum() else "_" for character in model.upper()).strip("_")


def _extract_runpod_text(payload):
    if not isinstance(payload, dict):
        raise RuntimeError("RunPod response must be a JSON object")

    if payload.get("error"):
        raise RuntimeError(f"RunPod request failed: {payload['error']}")

    status = str(payload.get("status", "")).upper()
    if status in {"FAILED", "CANCELLED", "TIMED_OUT"}:
        message = payload.get("error") or payload.get("message") or status.lower()
        raise RuntimeError(f"RunPod request failed: {message}")

    output = payload.get("output")
    if isinstance(output, str):
        return output.strip()
    if isinstance(output, dict):
        if output.get("error"):
            raise RuntimeError(f"RunPod request failed: {output['error']}")
        for key in ("text", "reply", "message", "response", "generated_text"):
            value = output.get(key)
            if isinstance(value, str):
                return value.strip()

    raise RuntimeError("RunPod response did not include generated text")


def _runpod_http_error_message(error):
    try:
        payload = json.loads(error.read().decode("utf-8") or "{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        payload = {}

    message = payload.get("error") or payload.get("message") or error.reason
    return f"RunPod request failed with HTTP {error.code}: {message}"
