"""Security utilities — bcrypt hashing (direct)."""
import bcrypt
import secrets
import string

def hash_password(password: str) -> str:
    """Hash a password with bcrypt, truncating to 72 bytes."""
    # bcrypt has a 72-byte limit — truncate to 72 characters (UTF‑8 safe)
    truncated = password[:72].encode('utf-8')
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(truncated, salt).decode('utf-8')

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain password against a bcrypt hash."""
    truncated = plain_password[:72].encode('utf-8')
    return bcrypt.checkpw(truncated, hashed_password.encode('utf-8'))

def generate_referral_code(length: int = 8) -> str:
    """Generate a random referral code."""
    alphabet = string.ascii_uppercase + string.digits
    return "REF-" + ''.join(secrets.choice(alphabet) for _ in range(length))

def generate_slug(name: str) -> str:
    """Generate a URL slug from a business name."""
    slug = name.lower().strip()
    slug = "".join(c for c in slug if c.isalnum() or c == " ")
    slug = slug.replace(" ", "-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    if len(slug) > 30:
        slug = slug[:30]
    slug = slug.rstrip("-")
    return slug or "shop"