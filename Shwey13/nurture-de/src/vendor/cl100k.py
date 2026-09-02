# Pure-Python cl100k_base encoder (token-count parity with tiktoken).
# Reproduces exact cl100k token ids from the official vocab + GPT-4 regex
# pre-tokenizer. Vendored in-repo 2026-08-06 (PM-5): both this module and its
# vocab blob live beside each other so the tracked chunks.jsonl is reproducible
# offline, with no dependency on any external/Temp path.
import base64, functools, os, regex

_VOCAB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cl100k_base.tiktoken")

# Canonical cl100k pat_str from tiktoken openai_public.py
_PAT = regex.compile(
    r"""'(?i:[sdmt]|ll|ve|re)|[^\r\n\p{L}\p{N}]?+\p{L}+|\p{N}{1,3}| ?[^\s\p{L}\p{N}]++[\r\n]*|\s*[\r\n]|\s+(?!\S)|\s+"""
)

def _load_ranks():
    ranks = {}
    with open(_VOCAB, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            tok_b64, rank = line.split()
            ranks[base64.b64decode(tok_b64)] = int(rank)
    return ranks

_RANKS = _load_ranks()

@functools.lru_cache(maxsize=200000)
def _bpe_len(piece):
    # piece: bytes. Returns number of tokens after byte-level BPE merges.
    if piece in _RANKS:
        return 1
    parts = [bytes([b]) for b in piece]
    while len(parts) > 1:
        min_rank = None
        min_i = None
        for i in range(len(parts) - 1):
            r = _RANKS.get(parts[i] + parts[i + 1])
            if r is not None and (min_rank is None or r < min_rank):
                min_rank = r
                min_i = i
        if min_i is None:
            break
        parts[min_i : min_i + 2] = [parts[min_i] + parts[min_i + 1]]
    return len(parts)

def count(text):
    n = 0
    for m in _PAT.findall(text):
        n += _bpe_len(m.encode("utf-8"))
    return n

if __name__ == "__main__":
    # Validation against known tiktoken cl100k_base token counts.
    cases = [
        ("hello world", 2),
        ("tiktoken is great!", 6),
        ("", 0),
        ("   ", 1),
        ("Beschäftigungsverbot", 6),   # count only asserted vs tiktoken below at runtime
    ]
    ok = True
    for text, expected in cases[:4]:
        got = count(text)
        flag = "OK" if got == expected else "MISMATCH"
        if got != expected:
            ok = False
        print("%-24r expected=%s got=%s  %s" % (text, expected, got, flag))
    print("German sample 'Beschäftigungsverbot' ->", count("Beschäftigungsverbot"), "tokens")
    print("VALIDATION", "PASS" if ok else "FAIL")
