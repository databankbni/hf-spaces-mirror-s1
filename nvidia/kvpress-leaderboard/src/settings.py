import os

from gradio.themes.utils import colors
from huggingface_hub import HfApi


### General settings ###
LINKS_COLOR = colors.green.c500
TOKEN = os.environ.get("HF_TOKEN")
OWNER = "NVIDIA"
REPO_ID = f"{OWNER}/kvpress-leaderboard"

LOCAL_RESULTS_DIR = "./benchmark/"  # local dir to store results

API = HfApi(token=TOKEN)

### Leaderboard table settings ###
LB_ALLOWED_MODELS = [
    "Qwen/Qwen3-8B",
    "meta-llama/Llama-3.1-8B-Instruct",
]  # models to show in the leaderboard table
LB_DEFAULT_MODELS = [
    "Qwen/Qwen3-8B",
]  # models to show by default in the leaderboard and plot, set to None to show all allowed models
LB_ALLOWED_DATASETS = None  # ["ruler"]  # datasets to show in the leaderboard table, set to None to show all datasets
LB_DEFAULT_COLUMNS = [
    "dataset",
    "data_dir",
    "model",
    "method",
    "compression_ratio",
    "score",
]  # columns to show in the leaderboard table
LB_HIDE_COLUMNS = ["filename"]  # columns to hide in the leaderboard table
LB_MARKDOWN_COLUMNS = ["dataset", "model"]  # columns to show in the leaderboard table as markdown
LB_HTML_COLUMNS = ["method"]  # columns to show in the leaderboard table as html


### Mapping from method name to pretty method name ###
METHOD_TO_PRETTY_NAME = {
    "knorm": "Knorm",
    "random": "Random",
    "snapkv": "SnapKV",
    "expected_attention": "ExpectedAttention",
    "streaming_llm": "StreamingLLM",
    "tova": "TOVA",
    "observed_attention": "ObservedAttention",
    "qfilter": "QFilter",
    "pyramidkv": "PyramidKV",
    "lagkv": "LagKV",
    "keydiff": "KeyDiff",
    "think": "ThinK",
    "simlayerkv": "SimLayerKV",
    "duo_attention": "DuoAttention",
    "finch": "Finch",
    "adasnapkv": "AdaKV",
    "chunkkv": "ChunkKV",
    "ChunkPress": "Chunk",
    "criti_snapkv": "CriticalKV",
    "block_keydiff": "Block",
    "no_press": "No Compression",
    # Query-aware methods (question included during compression)
    "snapkv_query_aware": "SnapKV (query-aware)",
    "finch_query_aware": "Finch (query-aware)",
    "chunkkv_query_aware": "ChunkKV (query-aware)",
    "adakv_snapkv_query_aware": "AdaSnapKV (query-aware)",
    # Other methods
    "adakv_expected_attention_e2": "AdaKVExpectedAttention",
    "adakv_compactor": "AdaKVCompactor",
    "adakv_snapkv": "AdaSnapKV",
    "duo_attention_on_the_fly": "DuoAttentionOnTheFly",
    "kvzip": "KVzip",
    "fastkvzip": "FastKVzip",
    "kvzap_linear": "KVzap (linear)",
    "kvzap_mlp": "KVzap (MLP)",
    # New presses
    "cur": "CUR",
    "compose": "Compose",
    "dms": "DMS",
    # Additional presses from README
    "compactor": "Compactor",
    "merging_knorm": "MergingKnorm",
    # Recently added presses
    "kvcompose": "KVCompose",
    "kvcompose_unstructured": "KVCompose (unstructured)",
    "lukv": "LUKV",
    "RestoreKV": "RestoreKV",
    "RestoreKV_plus": "RestoreKV+",
}

### Mapping from pretty method name to method paper link and implementation link ###
PRETTY_NAME_TO_PAPER_LINK = {
    "Knorm": f"KnormPress (<a href='https://github.com/NVIDIA/kvpress/blob/main/kvpress/presses/knorm_press.py' style='color: {LINKS_COLOR};'>source</a>, <a href='https://arxiv.org/abs/2406.11430' style='color: {LINKS_COLOR};'>paper</a>)",
    "Random": f"RandomPress (<a href='https://github.com/NVIDIA/kvpress/blob/main/kvpress/presses/random_press.py' style='color: {LINKS_COLOR};'>source</a>)",
    "SnapKV": f"SnapKVPress (<a href='https://github.com/NVIDIA/kvpress/blob/main/kvpress/presses/snapkv_press.py' style='color: {LINKS_COLOR};'>source</a>, <a href='https://arxiv.org/abs/2404.14469' style='color: {LINKS_COLOR};'>paper</a>)",
    "ExpectedAttention": f"ExpectedAttentionPress (<a href='https://github.com/NVIDIA/kvpress/blob/main/kvpress/presses/expected_attention_press.py' style='color: {LINKS_COLOR};'>source</a>, <a href='notebooks/expected_attention.ipynb' style='color: {LINKS_COLOR};'>notebook</a>)",
    "StreamingLLM": f"StreamingLLMPress (<a href='https://github.com/NVIDIA/kvpress/blob/main/kvpress/presses/streaming_llm_press.py' style='color: {LINKS_COLOR};'>source</a>, <a href='https://arxiv.org/abs/2309.17453' style='color: {LINKS_COLOR};'>paper</a>)",
    "TOVA": f"TOVAPress (<a href='https://github.com/NVIDIA/kvpress/blob/main/kvpress/presses/tova_press.py' style='color: {LINKS_COLOR};'>source</a>, <a href='https://arxiv.org/abs/2401.06104' style='color: {LINKS_COLOR};'>paper</a>)",
    "ObservedAttention": f"ObservedAttentionPress (<a href='https://github.com/NVIDIA/kvpress/blob/main/kvpress/presses/observed_attention_press.py' style='color: {LINKS_COLOR};'>source</a>, <a href='https://arxiv.org/abs/2306.14048' style='color: {LINKS_COLOR};'>paper</a>)",
    "QFilter": f"QFilterPress (<a href='https://github.com/NVIDIA/kvpress/blob/main/kvpress/presses/qfilter_press.py' style='color: {LINKS_COLOR};'>source</a>, <a href='https://arxiv.org/abs/2503.02812' style='color: {LINKS_COLOR};'>paper</a>)",
    "PyramidKV": f"PyramidKVPress (<a href='https://github.com/NVIDIA/kvpress/blob/main/kvpress/presses/pyramidkv_press.py' style='color: {LINKS_COLOR};'>source</a>, <a href='https://arxiv.org/abs/2406.02069' style='color: {LINKS_COLOR};'>paper</a>)",
    "LagKV": f"LagKVPress (<a href='https://github.com/NVIDIA/kvpress/blob/main/kvpress/presses/lagkv_press.py' style='color: {LINKS_COLOR};'>source</a>, <a href='https://arxiv.org/abs/2504.04704' style='color: {LINKS_COLOR};'>paper</a>)",
    "KeyDiff": f"KeyDiffPress (<a href='https://github.com/NVIDIA/kvpress/blob/main/kvpress/presses/keydiff_press.py' style='color: {LINKS_COLOR};'>source</a>, <a href='https://arxiv.org/abs/2504.15364' style='color: {LINKS_COLOR};'>paper</a>)",
    "ThinK": f"ThinKPress (<a href='https://github.com/NVIDIA/kvpress/blob/main/kvpress/presses/think_press.py' style='color: {LINKS_COLOR};'>source</a>, <a href='https://arxiv.org/pdf/2407.21018' style='color: {LINKS_COLOR};'>paper</a>)",
    "SimLayerKV": f"SimLayerKVPress (<a href='https://github.com/NVIDIA/kvpress/blob/main/kvpress/presses/simlayerkv_press.py' style='color: {LINKS_COLOR};'>source</a>, <a href='https://arxiv.org/abs/2410.13846' style='color: {LINKS_COLOR};'>paper</a>)",
    "DuoAttention": f"DuoAttentionPress (<a href='https://github.com/NVIDIA/kvpress/blob/main/kvpress/presses/duo_attention_press.py' style='color: {LINKS_COLOR};'>source</a>, <a href='https://arxiv.org/abs/2410.10819' style='color: {LINKS_COLOR};'>paper</a>)",
    "DuoAttentionOnTheFly": f"DuoAttentionOnTheFlyPress (<a href='https://github.com/NVIDIA/kvpress/blob/main/kvpress/presses/duo_attention_on_the_fly_press.py' style='color: {LINKS_COLOR};'>source</a>, <a href='https://arxiv.org/abs/2410.10819' style='color: {LINKS_COLOR};'>paper</a>)",
    "Finch": f"FinchPress (<a href='https://github.com/NVIDIA/kvpress/blob/main/kvpress/presses/finch_press.py' style='color: {LINKS_COLOR};'>source</a>, <a href='https://direct.mit.edu/tacl/article/doi/10.1162/tacl_a_00716/125280' style='color: {LINKS_COLOR};'>paper</a>)",
    "AdaKV": f"AdaKVPress (<a href='https://github.com/NVIDIA/kvpress/blob/main/kvpress/presses/adakv_press.py' style='color: {LINKS_COLOR};'>source</a>, <a href='https://arxiv.org/abs/2407.11550' style='color: {LINKS_COLOR};'>paper</a>)",
    "AdaKVCompactor": f"AdaKVCompactorPress (<a href='https://github.com/NVIDIA/kvpress/blob/main/kvpress/presses/adakv_press.py' style='color: {LINKS_COLOR};'>source</a>, <a href='https://arxiv.org/abs/2407.11550' style='color: {LINKS_COLOR};'>paper</a>)",
    "AdaSnapKV": f"AdaSnapKVPress (<a href='https://github.com/NVIDIA/kvpress/blob/main/kvpress/presses/adakv_press.py' style='color: {LINKS_COLOR};'>source</a>, <a href='https://arxiv.org/abs/2407.11550' style='color: {LINKS_COLOR};'>paper</a>)",
    "ChunkKV": f"ChunkKVPress (<a href='https://github.com/NVIDIA/kvpress/blob/main/kvpress/presses/chunkkv_press.py' style='color: {LINKS_COLOR};'>source</a>, <a href='https://arxiv.org/abs/2502.00299' style='color: {LINKS_COLOR};'>paper</a>)",
    "Chunk": f"ChunkPress (<a href='https://github.com/NVIDIA/kvpress/blob/main/kvpress/presses/chunk_press.py' style='color: {LINKS_COLOR};'>source</a>, <a href='https://direct.mit.edu/tacl/article/doi/10.1162/tacl_a_00716/125280' style='color: {LINKS_COLOR};'>paper</a>)",
    "CriticalKV": f"CriticalKVPress (<a href='https://github.com/NVIDIA/kvpress/blob/main/kvpress/presses/criticalkv_press.py' style='color: {LINKS_COLOR};'>source</a>, <a href='https://arxiv.org/abs/2502.03805' style='color: {LINKS_COLOR};'>paper</a>)",
    "Block": f"BlockPress (<a href='https://github.com/NVIDIA/kvpress/blob/main/kvpress/presses/block_press.py' style='color: {LINKS_COLOR};'>source</a>, <a href='https://arxiv.org/abs/2504.15364' style='color: {LINKS_COLOR};'>paper</a>)",
    # Query-aware methods (question included during compression)
    "SnapKV (query-aware)": f"SnapKVPress - query-aware (<a href='https://github.com/NVIDIA/kvpress/blob/main/kvpress/presses/snapkv_press.py' style='color: {LINKS_COLOR};'>source</a>, <a href='https://arxiv.org/abs/2404.14469' style='color: {LINKS_COLOR};'>paper</a>)",
    "Finch (query-aware)": f"FinchPress - query-aware (<a href='https://github.com/NVIDIA/kvpress/blob/main/kvpress/presses/finch_press.py' style='color: {LINKS_COLOR};'>source</a>, <a href='https://direct.mit.edu/tacl/article/doi/10.1162/tacl_a_00716/125280' style='color: {LINKS_COLOR};'>paper</a>)",
    "ChunkKV (query-aware)": f"ChunkKVPress - query-aware (<a href='https://github.com/NVIDIA/kvpress/blob/main/kvpress/presses/chunkkv_press.py' style='color: {LINKS_COLOR};'>source</a>, <a href='https://arxiv.org/abs/2502.00299' style='color: {LINKS_COLOR};'>paper</a>)",
    "AdaSnapKV (query-aware)": f"AdaSnapKVPress - query-aware (<a href='https://github.com/NVIDIA/kvpress/blob/main/kvpress/presses/adakv_press.py' style='color: {LINKS_COLOR};'>source</a>, <a href='https://arxiv.org/abs/2407.11550' style='color: {LINKS_COLOR};'>paper</a>)",
    "AdaKVExpectedAttention": f"AdaKVExpectedAttentionPress (<a href='https://github.com/NVIDIA/kvpress/blob/main/kvpress/presses/expected_attention_press.py' style='color: {LINKS_COLOR};'>source</a>, <a href='notebooks/expected_attention.ipynb' style='color: {LINKS_COLOR};'>notebook</a>)",
    "KVzip": f"KVzipPress (<a href='https://github.com/NVIDIA/kvpress/blob/main/kvpress/presses/kvzip_press.py' style='color: {LINKS_COLOR};'>source</a>, <a href='https://arxiv.org/abs/2505.23416' style='color: {LINKS_COLOR};'>paper</a>)",
    "FastKVzip": f"FastKVzipPress (<a href='https://github.com/NVIDIA/kvpress/blob/main/kvpress/presses/fastkvzip_press.py' style='color: {LINKS_COLOR};'>source</a>, <a href='https://arxiv.org/abs/2601.17668' style='color: {LINKS_COLOR};'>paper</a>)",
    "KVzap (linear)": f"KVzapPress - linear (<a href='https://github.com/NVIDIA/kvpress/blob/main/kvpress/presses/kvzap/kvzap_press.py' style='color: {LINKS_COLOR};'>source</a>, <a href='https://arxiv.org/abs/2601.07891' style='color: {LINKS_COLOR};'>paper</a>)",
    "KVzap (MLP)": f"KVzapPress - MLP (<a href='https://github.com/NVIDIA/kvpress/blob/main/kvpress/presses/kvzap/kvzap_press.py' style='color: {LINKS_COLOR};'>source</a>, <a href='https://arxiv.org/abs/2601.07891' style='color: {LINKS_COLOR};'>paper</a>)",
    # New presses
    "CUR": f"CURPress (<a href='https://github.com/NVIDIA/kvpress/blob/main/kvpress/presses/cur_press.py' style='color: {LINKS_COLOR};'>source</a>, <a href='https://arxiv.org/abs/2509.15038' style='color: {LINKS_COLOR};'>paper</a>)",
    "Compose": f"ComposePress (<a href='https://github.com/NVIDIA/kvpress/blob/main/kvpress/presses/compose_press.py' style='color: {LINKS_COLOR};'>source</a>)",
    "DMS": f"DMSPress (<a href='https://github.com/NVIDIA/kvpress/blob/main/kvpress/presses/dms_press.py' style='color: {LINKS_COLOR};'>source</a>, <a href='https://arxiv.org/abs/2506.05345' style='color: {LINKS_COLOR};'>paper</a>)",
    # Additional presses from README
    "Compactor": f"CompactorPress (<a href='https://github.com/NVIDIA/kvpress/blob/main/kvpress/presses/compactor_press.py' style='color: {LINKS_COLOR};'>source</a>, <a href='https://arxiv.org/abs/2507.08143' style='color: {LINKS_COLOR};'>paper</a>)",
    "MergingKnorm": f"MergingPress wrapping KnormPress (<a href='https://github.com/NVIDIA/kvpress/blob/main/kvpress/presses/merging_press.py' style='color: {LINKS_COLOR};'>source</a>)",
    # Recently added presses
    "KVCompose": f"KVComposePress (<a href='https://github.com/NVIDIA/kvpress/blob/main/kvpress/presses/kvcompose_press.py' style='color: {LINKS_COLOR};'>source</a>, <a href='https://arxiv.org/abs/2509.05165' style='color: {LINKS_COLOR};'>paper</a>)",
    "KVCompose (unstructured)": f"KVComposePress - unstructured (<a href='https://github.com/NVIDIA/kvpress/blob/main/kvpress/presses/kvcompose_press.py' style='color: {LINKS_COLOR};'>source</a>, <a href='https://arxiv.org/abs/2509.05165' style='color: {LINKS_COLOR};'>paper</a>)",
    "LUKV": f"LUKVPress (<a href='https://github.com/NVIDIA/kvpress/blob/main/kvpress/presses/lukv_press.py' style='color: {LINKS_COLOR};'>source</a>, <a href='https://arxiv.org/abs/2602.08585' style='color: {LINKS_COLOR};'>paper</a>)",
    "RestoreKV": f"RestoreKVPress (<a href='https://github.com/NVIDIA/kvpress/blob/main/kvpress/presses/restorekv_press.py' style='color: {LINKS_COLOR};'>source</a>, <a href='https://arxiv.org/abs/2608.01247' style='color: {LINKS_COLOR};'>paper</a>)",
    "RestoreKV+": f"RestoreKVPress - plus variant (<a href='https://github.com/NVIDIA/kvpress/blob/main/kvpress/presses/restorekv_press.py' style='color: {LINKS_COLOR};'>source</a>, <a href='https://arxiv.org/abs/2608.01247' style='color: {LINKS_COLOR};'>paper</a>)",
    "No Compression": "No Compression",
}


PRETTY_NAME_TO_ADDITIONAL_INFO = {k: "" for k, _ in PRETTY_NAME_TO_PAPER_LINK.items()}
PRETTY_NAME_TO_ADDITIONAL_INFO["KVzip"] = "⚠️ KVzip requires multiple forward passes."
PRETTY_NAME_TO_ADDITIONAL_INFO["KVCompose"] = "⚠️ KVCompose requires multiple forward passes."
PRETTY_NAME_TO_ADDITIONAL_INFO["KVCompose (unstructured)"] = "⚠️ KVCompose requires multiple forward passes."


### Mapping from dataset name to dataset paper link ###
DATASET_PAPER_LINK = {"ruler": "[Ruler](https://github.com/NVIDIA/RULER)"}


### Method descriptions for detail panel ###
METHOD_DESCRIPTIONS: dict[str, str] = {
    "SnapKV": "Identifies important KV pairs by observing attention patterns on recent tokens (observation window). Keeps tokens that receive the most attention.",
    "Knorm": "Prunes keys based on their L2 norm. Keys with smaller norms are removed first, as they tend to have less impact on attention.",
    "Random": "Randomly samples KV pairs to keep. Simple baseline that doesn't use any learned patterns.",
    "ExpectedAttention": "Uses expected attention weights computed from key norms and query-key relationships to score importance.",
    "StreamingLLM": "Keeps only the initial tokens (attention sinks) and recent tokens, discarding the middle context.",
    "TOVA": "Token Omission Via Attention - removes tokens based on accumulated attention scores over generation steps.",
    "ObservedAttention": "Tracks actual attention patterns during forward pass and keeps tokens that received the most attention.",
    "QFilter": "Query-aware filtering that uses the query to determine which key-value pairs are most relevant.",
    "PyramidKV": "Applies different compression ratios at different layers, using more compression in lower layers.",
    "LagKV": "Uses lagged attention scores from previous tokens to predict importance of current tokens.",
    "KeyDiff": "Computes differences between consecutive keys and keeps tokens with high key variation.",
    "ThinK": "Thins the KV cache by analyzing channel-wise importance and pruning less important dimensions.",
    "SimLayerKV": "Exploits layer similarity to share KV cache across similar layers, reducing redundancy.",
    "DuoAttention": "Learns attention patterns offline to identify which heads need full attention vs sparse attention.",
    "Finch": "Fast Inference with Chunked Attention - processes context in chunks with efficient memory patterns.",
    "AdaKV": "Adaptive KV compression that adjusts compression per-head based on attention entropy.",
    "AdaSnapKV": "Combines AdaKV's adaptive per-head compression with SnapKV's attention-based scoring.",
    "ChunkKV": "Processes KV cache in chunks, keeping representative tokens from each chunk.",
    "Chunk": "Fixed-size chunking strategy that divides context into blocks.",
    "CriticalKV": "Identifies critical tokens that are essential for maintaining model accuracy.",
    "Block": "Block-wise compression using key differences to identify important blocks.",
    "No Compression": "Baseline with no KV cache compression applied. Uses full context.",
    # Query-aware methods
    "SnapKV (query-aware)": "SnapKV with the query included during compression, allowing the method to see the question when selecting important tokens.",
    "Finch (query-aware)": "Finch with query-aware compression - uses the question to guide which chunks to retain.",
    "ChunkKV (query-aware)": "ChunkKV with query-aware selection of representative tokens per chunk.",
    "AdaSnapKV (query-aware)": "AdaSnapKV with query included during compression for better question-relevant token selection.",
    # Other variants
    "AdaKVExpectedAttention": "Combines AdaKV's adaptive compression with expected attention scoring.",
    "AdaKVCompactor": "AdaKV variant using compactor-based compression strategy.",
    "DuoAttentionOnTheFly": "DuoAttention without pre-computed patterns, computing attention requirements dynamically.",
    "KVzip": "Compresses KV cache using learned compression patterns. Requires multiple forward passes.",
    "FastKVzip": "Approximates KVzip through a lightweight gating mechanism trained on KVzip scores. Achieves high compression with negligible computational cost.",
    "KVzap (linear)": "Approximates KVzip+ using a fast linear surrogate model. Used with DMSPress.",
    "KVzap (MLP)": "Approximates KVzip+ using a fast MLP surrogate model. Used with DMSPress.",
    "CUR": "Prunes keys and values based on the CUR decomposition using approximate leverage scores.",
    "Compose": "Composes multiple compression strategies together.",
    "DMS": "Evicts keys and values with scores below a given threshold of any ScorerPress instead of relying on top-k scores. Supports both prefilling and decoding.",
    # Additional presses from README
    "MergingKnorm": "Wraps KnormPress with merge-on-evict: instead of discarding low-scoring tokens, merges their values into the most similar surviving token via cosine-similarity routing. Zero extra parameters.",
    "Compactor": "Blends non-causal chunked attention scores and approximate statistical leverage based on the compression ratio.",
    # Recently added presses
    "KVCompose": "Structured KV cache compression that aggregates attention scores across heads to form a composite importance signal, then keeps a globally aligned subset of tokens compatible with standard inference pipelines.",
    "KVCompose (unstructured)": "Unstructured variant of KVCompose where each head selects its retained tokens independently. Typically stronger than the structured variant but requires attention-mechanism support for non-aligned KV layouts.",
    "LUKV": "Head-wise budget allocation around a scoring press. Uses a pre-computed per-layer/per-head budget curve to allocate different token budgets across attention heads before scoring.",
    "RestoreKV": "Learned restoration on top of KVzip. Before eviction, 8 restore tokens attend to the full KV cache in a single LoRA-adapted pass, producing a context-conditioned restore cache that fills part of the budget while the base evictor fills the rest (budget-matched). Only the restore embeddings and LoRA (~0.4% of params) are trained via self-distillation from the full-cache teacher.",
    "RestoreKV+": "RestoreKV with KVzip-plus normalization enabled on the restoration pass.",
}
