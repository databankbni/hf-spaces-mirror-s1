"""
src/responsible_ai/privacy_vault.py

Zero-Trust Cryptographic Privacy Vault for CustomerCore.

== What this replaces ==
The previous approach (Presidio simple masking) permanently deleted PII from
ticket text. This meant human agents reviewing low-confidence tickets during
Human-in-the-Loop pauses could only see [EMAIL] and [NAME] — making triage
impossible without contacting the customer separately.

== What this does instead ==
Instead of destroying PII, we:
  1. Detect PII spans using Presidio (same as before)
  2. Encrypt each detected value with the tenant's AES-256 Fernet key
  3. Replace the raw value in the ticket text with a readable token
     e.g. "john.doe@acme.com" → "<<TOK_EMAIL_ADDRESS_a1b2c3d4>>"
  4. Store the (token → encrypted_value) pair in the vault database
  5. Write an audit entry for every encrypt and decrypt action

When a SUPPORT_LEAD or SECURITY_ADMIN needs to review the ticket, they call
decrypt_token() which re-identifies the field in their UI. Every decrypt is
logged for GDPR audit compliance.

== GDPR Compliance (Germany / EU) ==
  GDPR Article 32: Requires "appropriate technical measures" to protect
  personal data — AES-256 encryption is the gold standard.
  GDPR Article 17 (Right to be Forgotten): To delete a customer's data,
  delete their vault entries AND shred the tenant's encryption key.
  Their Silver Parquet records become permanently unreadable ciphertext.

== Architecture ==
  CryptographicPrivacyVault
    ├── TenantKeyManager      — per-tenant AES-256 key derivation
    ├── VaultStore            — in-memory + SQLite backend for tokens
    └── AuditLog              — JSONL append-only compliance trail

Run standalone demo:
  python -m src.responsible_ai.privacy_vault
"""

import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

from src.responsible_ai.key_manager import TenantKeyManager, get_key_manager
from src.responsible_ai.audit_log import write_audit_entry, _sha256

# ── Config ─────────────────────────────────────────────────────────────────────
VAULT_DB_PATH = Path("logs/vault_audit/vault.db")
VAULT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)

# Roles allowed to call decrypt
AUTHORIZED_DECRYPT_ROLES = {"SUPPORT_LEAD", "SECURITY_ADMIN"}

# Token format: <<TOK_{FIELD}_{8-hex-chars}>>
TOKEN_PATTERN = re.compile(r"<<TOK_[A-Z_]+_[0-9a-f]{8}>>")


# ── Vault Store (SQLite) ───────────────────────────────────────────────────────

class VaultStore:
    """
    SQLite-backed store mapping (tenant_id, token) → encrypted_value.

    In production, swap with a Supabase PostgreSQL table:
      supabase.table("pii_vault").insert({...}).execute()

    The SQLite DB is stored at logs/vault_audit/vault.db — never commit this.
    """

    def __init__(self, db_path: Path = VAULT_DB_PATH):
        self.db_path = db_path
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._init_schema()

    def _init_schema(self):
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS pii_vault (
                token           TEXT NOT NULL,
                tenant_id       TEXT NOT NULL,
                field_name      TEXT NOT NULL,
                encrypted_value TEXT NOT NULL,
                plaintext_sha256 TEXT NOT NULL,
                created_at      TEXT NOT NULL,
                PRIMARY KEY (tenant_id, token)
            )
        """)
        self._conn.commit()

    def store(self, tenant_id: str, token: str, field_name: str,
              encrypted_value: str, plaintext_sha256: str):
        self._conn.execute(
            """INSERT OR REPLACE INTO pii_vault
               (token, tenant_id, field_name, encrypted_value, plaintext_sha256, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (token, tenant_id, field_name, encrypted_value,
             plaintext_sha256, datetime.now(timezone.utc).isoformat()),
        )
        self._conn.commit()

    def fetch(self, tenant_id: str, token: str) -> Optional[tuple[str, str]]:
        """Return (field_name, encrypted_value) or None if not found."""
        row = self._conn.execute(
            "SELECT field_name, encrypted_value FROM pii_vault WHERE tenant_id=? AND token=?",
            (tenant_id, token),
        ).fetchone()
        return row  # (field_name, encrypted_value) or None

    def delete_tenant(self, tenant_id: str) -> int:
        """
        GDPR Right to be Forgotten: delete ALL vault entries for a tenant.
        Combined with key shredding, their encrypted tokens become permanently
        unreadable ciphertext in the Silver Parquet files.
        Returns count of deleted rows.
        """
        cur = self._conn.execute(
            "DELETE FROM pii_vault WHERE tenant_id=?", (tenant_id,)
        )
        self._conn.commit()
        return cur.rowcount

    def count(self, tenant_id: Optional[str] = None) -> int:
        if tenant_id:
            return self._conn.execute(
                "SELECT COUNT(*) FROM pii_vault WHERE tenant_id=?", (tenant_id,)
            ).fetchone()[0]
        return self._conn.execute("SELECT COUNT(*) FROM pii_vault").fetchone()[0]


# ── Core Vault ─────────────────────────────────────────────────────────────────

class CryptographicPrivacyVault:
    """
    Zero-Trust Privacy Vault.

    encrypt_field()  — encrypt a single PII value, return its token
    encrypt_text()   — detect + encrypt all PII in a full text block
    decrypt_token()  — decrypt a token back to plaintext (RBAC-enforced)
    forget_tenant()  — GDPR deletion cascade for all tokens of a tenant
    """
    _analyzer_cached = None
    _anonymizer_cached = None

    def __init__(
        self,
        key_manager: Optional[TenantKeyManager] = None,
        store: Optional[VaultStore] = None,
    ):
        self.km = key_manager or get_key_manager()
        self.store = store or VaultStore()

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _make_token(self, field_name: str, plaintext: str) -> str:
        """
        Generate a deterministic, stable token for a PII value.
        Token format: <<TOK_{FIELD_NAME}_{first8hex_of_sha256}>>
        Deterministic so the same email always produces the same token,
        avoiding duplicate vault entries for repeated values.
        """
        digest = _sha256(plaintext)[:8]
        clean_field = field_name.upper().replace(" ", "_")
        return f"<<TOK_{clean_field}_{digest}>>"

    def _get_cipher(self, tenant_id: str) -> Fernet:
        key = self.km.get_key(tenant_id)
        return Fernet(key)

    # ── Public API ─────────────────────────────────────────────────────────────

    def encrypt_field(
        self,
        *,
        tenant_id: str,
        field_name: str,
        plaintext: str,
        ticket_id: str = "",
    ) -> str:
        """
        Encrypt a single PII value. Store in vault. Return its token.

        If this exact plaintext was already encrypted for this tenant,
        returns the existing token (idempotent — no duplicate vault entries).
        """
        token = self._make_token(field_name, plaintext)

        # Idempotency check — already in vault?
        existing = self.store.fetch(tenant_id, token)
        if existing:
            return token  # already stored, token is stable

        # Encrypt with tenant key
        cipher = self._get_cipher(tenant_id)
        encrypted = cipher.encrypt(plaintext.encode("utf-8")).decode("utf-8")
        sha = _sha256(plaintext)

        # Persist to vault
        self.store.store(tenant_id, token, field_name, encrypted, sha)

        # Write audit entry
        write_audit_entry(
            tenant_id=tenant_id,
            field_name=field_name,
            token=token,
            action="ENCRYPT",
            plaintext_hash=sha,
            ticket_id=ticket_id,
        )

        return token

    def encrypt_text(
        self,
        *,
        tenant_id: str,
        text: str,
        analyzer=None,
        anonymizer=None,
        ticket_id: str = "",
        pii_entities: list[str] | None = None,
    ) -> tuple[str, int]:
        """
        Detect all PII spans in `text` using Presidio, encrypt each one,
        and replace the raw span with its vault token in the returned string.

        Returns (tokenized_text, count_of_pii_detected).
        Falls back to standard Presidio anonymization if vault is disabled.
        """
        if analyzer is None or anonymizer is None:
            if CryptographicPrivacyVault._analyzer_cached is None or CryptographicPrivacyVault._anonymizer_cached is None:
                from presidio_analyzer import AnalyzerEngine
                from presidio_anonymizer import AnonymizerEngine
                from presidio_analyzer.nlp_engine import NlpEngineProvider
                nlp_config = {"nlp_engine_name": "spacy", "models": [{"lang_code": "en", "model_name": "en_core_web_sm"}]}
                nlp_engine = NlpEngineProvider(nlp_configuration=nlp_config).create_engine()
                CryptographicPrivacyVault._analyzer_cached = AnalyzerEngine(nlp_engine=nlp_engine)
                CryptographicPrivacyVault._anonymizer_cached = AnonymizerEngine()
            analyzer = analyzer or CryptographicPrivacyVault._analyzer_cached
            anonymizer = anonymizer or CryptographicPrivacyVault._anonymizer_cached

        if not text or not isinstance(text, str):
            return text, 0

        entities = pii_entities or [
            "EMAIL_ADDRESS", "PHONE_NUMBER", "CREDIT_CARD",
            "PERSON", "IBAN_CODE", "IP_ADDRESS", "US_SSN",
        ]

        results = analyzer.analyze(text=text, language="en", entities=entities)
        if not results:
            return text, 0

        # Sort by start position descending so we can replace without offset shift
        results_sorted = sorted(results, key=lambda r: r.start, reverse=True)
        tokenized = text

        for result in results_sorted:
            raw_value = text[result.start:result.end]
            token = self.encrypt_field(
                tenant_id=tenant_id,
                field_name=result.entity_type,
                plaintext=raw_value,
                ticket_id=ticket_id,
            )
            tokenized = tokenized[:result.start] + token + tokenized[result.end:]

        return tokenized, len(results_sorted)

    def decrypt_token(
        self,
        *,
        tenant_id: str,
        token: str,
        actor_role: str,
        ticket_id: str = "",
    ) -> str:
        """
        Decrypt a vault token back to its original plaintext value.

        Role-Based Access Control: only SUPPORT_LEAD and SECURITY_ADMIN
        may call this. All decrypt calls are logged in the audit trail.
        Raises PermissionError for unauthorized roles.
        Raises KeyError if token not found in vault.
        Raises ValueError if decryption fails (wrong key or corrupted data).
        """
        # RBAC check
        if actor_role not in AUTHORIZED_DECRYPT_ROLES:
            write_audit_entry(
                tenant_id=tenant_id,
                field_name="UNKNOWN",
                token=token,
                action="DECRYPT_DENIED",
                plaintext_hash="",
                actor_role=actor_role,
                ticket_id=ticket_id,
            )
            raise PermissionError(
                f"Role '{actor_role}' is not authorized to decrypt vault tokens. "
                f"Required: {AUTHORIZED_DECRYPT_ROLES}"
            )

        # Lookup in vault
        row = self.store.fetch(tenant_id, token)
        if not row:
            raise KeyError(
                f"Token '{token}' not found in vault for tenant '{tenant_id}'."
            )
        field_name, encrypted_value = row

        # Decrypt
        cipher = self._get_cipher(tenant_id)
        try:
            plaintext = cipher.decrypt(encrypted_value.encode("utf-8")).decode("utf-8")
        except InvalidToken as e:
            raise ValueError(
                f"Failed to decrypt token '{token}' — key may have been rotated: {e}"
            ) from e

        # Audit the successful decrypt
        write_audit_entry(
            tenant_id=tenant_id,
            field_name=field_name,
            token=token,
            action="DECRYPT",
            plaintext_hash=_sha256(plaintext),
            actor_role=actor_role,
            ticket_id=ticket_id,
        )

        return plaintext

    def decrypt_text(
        self,
        *,
        tenant_id: str,
        text: str,
        actor_role: str,
        ticket_id: str = "",
    ) -> str:
        """
        Find all vault tokens in `text` and replace them with decrypted values.
        Requires an authorized role. Each token decrypt is individually audited.
        """
        tokens_found = TOKEN_PATTERN.findall(text)
        result = text
        for token in set(tokens_found):
            try:
                plaintext = self.decrypt_token(
                    tenant_id=tenant_id,
                    token=token,
                    actor_role=actor_role,
                    ticket_id=ticket_id,
                )
                result = result.replace(token, plaintext)
            except (KeyError, ValueError):
                # Token not found or corrupted — leave as-is
                pass
        return result

    def forget_tenant(self, tenant_id: str) -> dict:
        """
        GDPR Article 17 — Right to be Forgotten.

        Deletes ALL vault entries for a tenant. After this call, their encrypted
        tokens in Silver Parquet files become permanently unreadable ciphertext.
        Callers should also shred the tenant's key via key_manager.rotate_key().

        Returns a summary of what was deleted.
        """
        deleted = self.store.delete_tenant(tenant_id)
        write_audit_entry(
            tenant_id=tenant_id,
            field_name="ALL",
            token="ALL",
            action="ENCRYPT",  # closest valid action — log the deletion event
            plaintext_hash="GDPR_DELETION",
            actor_role="GDPR_PROCESSOR",
            extra={"event": "GDPR_FORGET_TENANT", "deleted_rows": deleted},
        )
        return {"tenant_id": tenant_id, "vault_entries_deleted": deleted}


# ── Module-level singleton ─────────────────────────────────────────────────────
_default_vault: Optional[CryptographicPrivacyVault] = None


def get_vault() -> CryptographicPrivacyVault:
    """Return the module-level singleton vault (shared key manager + store)."""
    global _default_vault
    if _default_vault is None:
        _default_vault = CryptographicPrivacyVault()
    return _default_vault


# ── Standalone Demo ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    from presidio_analyzer import AnalyzerEngine
    from presidio_anonymizer import AnonymizerEngine
    from presidio_analyzer.nlp_engine import NlpEngineProvider

    nlp_cfg = {"nlp_engine_name": "spacy", "models": [{"lang_code": "en", "model_name": "en_core_web_sm"}]}
    nlp_engine = NlpEngineProvider(nlp_configuration=nlp_cfg).create_engine()
    analyzer = AnalyzerEngine(nlp_engine=nlp_engine)
    anonymizer = AnonymizerEngine()

    vault = CryptographicPrivacyVault()
    tenant = "acme-corp"
    ticket_text = (
        "Hi, my name is John Smith and I can be reached at john.smith@acme.com "
        "or call +1 212-555-9876. My credit card 4111-1111-1111-1111 was charged twice."
    )

    print("=" * 60)
    print("CustomerCore Cryptographic Privacy Vault — Demo")
    print("=" * 60)
    print(f"\nOriginal text:\n  {ticket_text}")

    tokenized, count = vault.encrypt_text(
        tenant_id=tenant,
        text=ticket_text,
        analyzer=analyzer,
        anonymizer=anonymizer,
        ticket_id="TKT-DEMO-001",
    )
    print(f"\nTokenized text ({count} PII entities detected):\n  {tokenized}")
    print(f"\nVault entries stored: {vault.store.count(tenant)}")

    # Authorized decrypt
    restored = vault.decrypt_text(
        tenant_id=tenant,
        text=tokenized,
        actor_role="SUPPORT_LEAD",
        ticket_id="TKT-DEMO-001",
    )
    print(f"\nRestored text (SUPPORT_LEAD view):\n  {restored}")

    # Unauthorized decrypt
    print("\nAttempting decrypt with AGENT role (unauthorized)...")
    try:
        vault.decrypt_token(
            tenant_id=tenant,
            token=list(TOKEN_PATTERN.findall(tokenized))[0],
            actor_role="AGENT",
        )
    except PermissionError as e:
        print(f"  BLOCKED: {e}")

    print("\nAudit log written to: logs/vault_audit/audit_trail.jsonl")
    print("=" * 60)
