"""
Primer design using Primer3-py — the gold standard PCR primer designer.
"""

import primer3
from typing import Dict, Any, List
import logging

logger = logging.getLogger(__name__)


def design_primers_primer3(
    sequence: str,
    target_tm: float = 58.0,
    min_len: int = 18,
    max_len: int = 22,
    min_product: int = 150,
    max_product: int = 600,
    num_pairs: int = 10,
) -> Dict[str, Any]:
    """
    Design primers using Primer3 (the gold standard).
    """
    seq = sequence.upper().strip().replace(" ", "")

    if len(seq) < 100:
        raise ValueError("Sequence must be at least 100 bp for primer design")

    # Primer3 global args
    global_args = {
        "SEQUENCE_TEMPLATE": seq,
        "PRIMER_TASK": "generic",
        "PRIMER_PICK_LEFT_PRIMER": 1,
        "PRIMER_PICK_RIGHT_PRIMER": 1,
        "PRIMER_PICK_INTERNAL_OLIGO": 0,
        "PRIMER_OPT_SIZE": 20,
        "PRIMER_MIN_SIZE": min_len,
        "PRIMER_MAX_SIZE": max_len,
        "PRIMER_OPT_TM": target_tm,
        "PRIMER_MIN_TM": target_tm - 5,
        "PRIMER_MAX_TM": target_tm + 5,
        "PRIMER_MIN_GC": 40.0,
        "PRIMER_MAX_GC": 60.0,
        "PRIMER_PRODUCT_SIZE_RANGE": [[min_product, max_product]],
        "PRIMER_NUM_RETURN": num_pairs,
        "PRIMER_MAX_POLY_X": 4,
        "PRIMER_SALT_MONOVALENT": 50.0,
        "PRIMER_DNA_CONC": 50.0,
        "PRIMER_MAX_NS_ACCEPTED": 0,
        "PRIMER_EXPLAIN_FLAG": 1,
    }

    try:
        result = primer3.bindings.design_primers(global_args)
    except Exception as e:
        raise RuntimeError(f"Primer3 error: {e}")

    # Extract primer pairs
    pairs: List[Dict[str, Any]] = []
    num_returned = result.get("PRIMER_PAIR_NUM_RETURNED", 0)

    for i in range(num_returned):
        left_seq = result.get(f"PRIMER_LEFT_{i}_SEQUENCE", "")
        right_seq = result.get(f"PRIMER_RIGHT_{i}_SEQUENCE", "")
        left_tm = result.get(f"PRIMER_LEFT_{i}_TM", 0)
        right_tm = result.get(f"PRIMER_RIGHT_{i}_TM", 0)
        left_gc = result.get(f"PRIMER_LEFT_{i}_GC_PERCENT", 0)
        right_gc = result.get(f"PRIMER_RIGHT_{i}_GC_PERCENT", 0)
        product_size = result.get(f"PRIMER_PAIR_{i}_PRODUCT_SIZE", 0)
        left_pos = result.get(f"PRIMER_LEFT_{i}", (0, 0))
        right_pos = result.get(f"PRIMER_RIGHT_{i}", (0, 0))
        left_hairpin = result.get(f"PRIMER_LEFT_{i}_HAIRPIN_TH", 0)
        right_hairpin = result.get(f"PRIMER_RIGHT_{i}_HAIRPIN_TH", 0)
        left_self_dimer = result.get(f"PRIMER_LEFT_{i}_SELF_ANY_TH", 0)
        right_self_dimer = result.get(f"PRIMER_RIGHT_{i}_SELF_ANY_TH", 0)
        pair_compl = result.get(f"PRIMER_PAIR_{i}_COMPL_ANY_TH", 0)
        left_penalty = result.get(f"PRIMER_LEFT_{i}_PENALTY", 0)
        right_penalty = result.get(f"PRIMER_RIGHT_{i}_PENALTY", 0)

        tm_diff = abs(left_tm - right_tm)

        # Quality score
        score = 100
        score -= abs(left_tm - target_tm) * 2
        score -= abs(right_tm - target_tm) * 2
        score -= tm_diff * 5
        if left_hairpin > 47:
            score -= 10
        if right_hairpin > 47:
            score -= 10
        if pair_compl > 47:
            score -= 15
        score = max(0, min(100, round(score)))

        pairs.append({
            "rank": i + 1,
            "forward": {
                "sequence": left_seq,
                "tm": round(left_tm, 1),
                "gc": round(left_gc, 1),
                "length": len(left_seq),
                "position": left_pos[0] + 1 if isinstance(left_pos, (list, tuple)) else 0,
                "hairpin_th": round(left_hairpin, 1),
                "self_dimer_th": round(left_self_dimer, 1),
                "penalty": round(left_penalty, 2),
            },
            "reverse": {
                "sequence": right_seq,
                "tm": round(right_tm, 1),
                "gc": round(right_gc, 1),
                "length": len(right_seq),
                "position": right_pos[0] + 1 if isinstance(right_pos, (list, tuple)) else 0,
                "hairpin_th": round(right_hairpin, 1),
                "self_dimer_th": round(right_self_dimer, 1),
                "penalty": round(right_penalty, 2),
            },
            "amplicon_size": product_size,
            "tm_difference": round(tm_diff, 1),
            "pair_complementarity": round(pair_compl, 1),
            "score": score,
        })

    # Sort by score descending
    pairs.sort(key=lambda x: x["score"], reverse=True)

    return {
        "sequence_length": len(seq),
        "num_pairs": len(pairs),
        "pairs": pairs,
        "engine": "primer3-py",
        "explanation": {
            "left": result.get("PRIMER_LEFT_EXPLAIN", ""),
            "right": result.get("PRIMER_RIGHT_EXPLAIN", ""),
            "pair": result.get("PRIMER_PAIR_EXPLAIN", ""),
        },
    }
