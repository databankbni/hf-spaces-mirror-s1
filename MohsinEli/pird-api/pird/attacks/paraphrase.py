"""Paraphrase attack: rewrite AI text to evade detection. Supports recursive paraphrasing
(the hardest PADBen case). Used both to attack baselines and to augment PIRD's invariance training."""
from __future__ import annotations


class Paraphraser:
    def __init__(self, model_name: str = "humarin/chatgpt_paraphraser_on_T5_base",
                 device: str | None = None, max_tokens: int = 512, prefix: str = "paraphrase: "):
        import torch
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
        self.torch = torch
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.max_tokens = max_tokens
        self.prefix = prefix       # T5-style models need "paraphrase: "; BART/Pegasus use ""
        self.tok = AutoTokenizer.from_pretrained(model_name)
        self.model = AutoModelForSeq2SeqLM.from_pretrained(model_name).to(self.device).eval()

    def paraphrase(self, text: str, num_beams: int = 5, temperature: float = 0.7) -> str:
        ids = self.tok(f"{self.prefix}{text}", return_tensors="pt", truncation=True,
                       max_length=self.max_tokens).input_ids.to(self.device)
        with self.torch.no_grad():
            out = self.model.generate(ids, max_length=self.max_tokens, num_beams=num_beams,
                                      num_return_sequences=1, temperature=temperature, do_sample=True)
        return self.tok.decode(out[0], skip_special_tokens=True)

    def recursive(self, text: str, rounds: int = 3, **kw) -> str:
        for _ in range(rounds):
            text = self.paraphrase(text, **kw)
        return text

    def paraphrase_many(self, texts: list[str], rounds: int = 1, **kw) -> list[str]:
        fn = (lambda t: self.recursive(t, rounds=rounds, **kw)) if rounds > 1 else \
             (lambda t: self.paraphrase(t, **kw))
        return [fn(t) for t in texts]
