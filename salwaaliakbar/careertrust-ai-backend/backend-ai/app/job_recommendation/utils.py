import re
from typing import Optional

from sklearn.metrics.pairwise import cosine_similarity


def cosine_sim(vec1, vec2) -> float:
    """Compute cosine similarity between two vectors."""
    return float(cosine_similarity([vec1], [vec2])[0][0])


def normalize_skill(skill: str) -> str:
    """Normalize skill for comparison (lowercase, trim, remove special chars)."""
    return re.sub(r"[^\w\s]", "", skill.lower().strip())


def parse_experience(exp_text: str) -> Optional[float]:
    """
    Extract numeric experience from text.
    Examples: "3 years", "2-4 years", "5+ years" -> 3.0, 3.0, 5.0
    """
    if not exp_text:
        return None

    numbers = re.findall(r"\d+\.?\d*", str(exp_text))
    if not numbers:
        return None

    return float(numbers[0])
