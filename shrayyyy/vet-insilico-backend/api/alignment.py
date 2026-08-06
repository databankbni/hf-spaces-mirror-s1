"""
Sequence alignment using BioPython — Needleman-Wunsch and Smith-Waterman.
"""

from Bio import pairwise2
from Bio.SubsMat import MatrixInfo as matlist
from typing import Dict, Any
import logging

logger = logging.getLogger(__name__)


def align_sequences(seq_a: str, seq_b: str, seq_type: str = "protein", algorithm: str = "needleman-wunsch") -> Dict[str, Any]:
    """
    Real sequence alignment using BioPython.
    """
    seq_a = seq_a.upper().strip()
    seq_b = seq_b.upper().strip()

    if len(seq_a) < 2 or len(seq_b) < 2:
        raise ValueError("Sequences must be at least 2 characters")

    # Scoring
    if seq_type == "protein":
        matrix = matlist.blosum62
        gap_open = -10
        gap_extend = -0.5
    else:
        # DNA: match=2, mismatch=-1
        matrix = None
        gap_open = -10
        gap_extend = -0.5

    # Perform alignment
    if algorithm == "smith-waterman":
        # Local alignment
        if matrix:
            alignments = pairwise2.align.localds(seq_a, seq_b, matrix, gap_open, gap_extend)
        else:
            alignments = pairwise2.align.localms(seq_a, seq_b, 2, -1, gap_open, gap_extend)
    else:
        # Global alignment (Needleman-Wunsch)
        if matrix:
            alignments = pairwise2.align.globalds(seq_a, seq_b, matrix, gap_open, gap_extend)
        else:
            alignments = pairwise2.align.globalms(seq_a, seq_b, 2, -1, gap_open, gap_extend)

    if not alignments:
        raise ValueError("No alignment found")

    # Take best alignment
    best = alignments[0]
    aligned_a = best.seqA
    aligned_b = best.seqB
    score = best.score

    # Calculate identity, similarity, gaps
    length = len(aligned_a)
    identical = 0
    similar = 0
    gaps = 0

    for i in range(length):
        a = aligned_a[i]
        b = aligned_b[i]
        if a == "-" or b == "-":
            gaps += 1
        elif a == b:
            identical += 1
            similar += 1
        elif seq_type == "protein":
            # Check BLOSUM62 similarity
            try:
                pair_score = matrix.get((a, b), matrix.get((b, a), -4))
                if pair_score > 0:
                    similar += 1
            except Exception:
                pass

    identity = (identical / length * 100) if length > 0 else 0
    similarity = (similar / length * 100) if length > 0 else 0

    # Build match line
    match_line = ""
    for i in range(length):
        a = aligned_a[i]
        b = aligned_b[i]
        if a == "-" or b == "-":
            match_line += " "
        elif a == b:
            match_line += "|"
        elif seq_type == "protein":
            try:
                pair_score = matrix.get((a, b), matrix.get((b, a), -4))
                match_line += ":" if pair_score > 0 else "."
            except Exception:
                match_line += "."
        else:
            match_line += "."

    return {
        "aligned_a": aligned_a,
        "aligned_b": aligned_b,
        "match_line": match_line,
        "score": round(score, 1),
        "identity": round(identity, 1),
        "similarity": round(similarity, 1),
        "gaps": gaps,
        "length": length,
        "algorithm": algorithm,
        "seq_type": seq_type,
    }
