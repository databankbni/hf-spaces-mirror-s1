"""LLM-based humanizer attack: rewrite AI text with an instruction-tuned LLM prompted to sound like
a casual human, preserving meaning. A stronger, more natural evasion than seq2seq paraphrasers,
closer to how a real user would obfuscate AI text. Default Qwen2.5-1.5B-Instruct (Colab-friendly)."""
from __future__ import annotations


class LLMHumanizer:
    name = "llm-humanizer"

    def __init__(self, model_name: str = "Qwen/Qwen2.5-1.5B-Instruct",
                 device: str | None = None, max_new_tokens: int = 400):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
        self.torch = torch
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.max_new_tokens = max_new_tokens
        self.tok = AutoTokenizer.from_pretrained(model_name)
        dtype = torch.float16 if self.device == "cuda" else torch.float32
        self.model = AutoModelForCausalLM.from_pretrained(
            model_name, torch_dtype=dtype).to(self.device).eval()

    def humanize(self, text: str, temperature: float = 0.9) -> str:
        msg = [
            {"role": "system", "content": "You rewrite text so it reads like a casual human wrote "
             "it, preserving the original meaning and approximate length. Output only the rewrite."},
            {"role": "user", "content": f"Rewrite this:\n\n{text}"},
        ]
        prompt = self.tok.apply_chat_template(msg, tokenize=False, add_generation_prompt=True)
        ids = self.tok(prompt, return_tensors="pt", truncation=True, max_length=2048).to(self.device)
        with self.torch.no_grad():
            out = self.model.generate(**ids, max_new_tokens=self.max_new_tokens,
                                      do_sample=True, temperature=temperature, top_p=0.95)
        gen = out[0][ids["input_ids"].shape[1]:]
        return self.tok.decode(gen, skip_special_tokens=True).strip()

    def humanize_many(self, texts: list[str]) -> list[str]:
        out = []
        for i, t in enumerate(texts):
            out.append(self.humanize(t))
            if (i + 1) % 25 == 0:
                print(f"  humanized {i+1}/{len(texts)}")
        return out
