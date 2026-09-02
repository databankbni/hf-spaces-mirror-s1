import uuid

def generate_id(prefix: str) -> str:
    """Generates a random ID with a prefix, e.g., 'vs_12345678' or 'job_abcde'."""
    suffix = uuid.uuid4().hex[:12]
    return f"{prefix}_{suffix}"
