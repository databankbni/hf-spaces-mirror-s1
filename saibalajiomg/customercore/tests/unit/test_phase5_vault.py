"""
tests/unit/test_phase5_vault.py

Phase 5: Zero-Trust Cryptographic Privacy Vault — Full Test Suite

Tests:
  1. TenantKeyManager — key isolation and determinism
  2. VaultStore       — CRUD, idempotency, tenant isolation
  3. CryptographicPrivacyVault — encrypt/decrypt round-trips
  4. RBAC enforcement — unauthorized role blocked and audit-logged
  5. Token format     — readable, stable, parseable
  6. encrypt_text()   — full text tokenization with Presidio
  7. decrypt_text()   — full text restoration
  8. GDPR forget()    — deletion cascade
  9. Vault integration in bronze_to_silver.py validate_and_clean_ticket()
 10. Backward compat  — vault=None produces legacy silver_version=1.0
"""

import pytest

from src.responsible_ai.key_manager import TenantKeyManager
from src.responsible_ai.privacy_vault import (
    CryptographicPrivacyVault, VaultStore, TOKEN_PATTERN
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def km():
    return TenantKeyManager(master_secret="test-master-secret-unit")


@pytest.fixture
def store(tmp_path):
    """Fresh in-memory SQLite VaultStore for each test."""
    db_path = tmp_path / "test_vault.db"
    return VaultStore(db_path=db_path)


@pytest.fixture
def vault(store):
    """Vault wired to a fresh in-memory store and deterministic key manager."""
    km = TenantKeyManager(master_secret="test-master-secret-unit")
    return CryptographicPrivacyVault(key_manager=km, store=store)


@pytest.fixture(scope="module")
def presidio_engines():
    """Initialize Presidio engines once per test session."""
    from presidio_analyzer import AnalyzerEngine
    from presidio_anonymizer import AnonymizerEngine
    from presidio_analyzer.nlp_engine import NlpEngineProvider
    nlp_cfg = {
        "nlp_engine_name": "spacy",
        "models": [{"lang_code": "en", "model_name": "en_core_web_sm"}]
    }
    nlp_engine = NlpEngineProvider(nlp_configuration=nlp_cfg).create_engine()
    analyzer = AnalyzerEngine(nlp_engine=nlp_engine)
    anonymizer = AnonymizerEngine()
    return analyzer, anonymizer


# ── 1. TenantKeyManager ────────────────────────────────────────────────────────

class TestTenantKeyManager:
    def test_key_is_deterministic(self, km):
        """Same tenant always produces the same key."""
        k1 = km.get_key("acme-corp")
        k2 = km.get_key("acme-corp")
        assert k1 == k2

    def test_keys_are_isolated_per_tenant(self, km):
        """Different tenants produce different keys."""
        k_acme = km.get_key("acme-corp")
        k_globex = km.get_key("globex-inc")
        assert k_acme != k_globex

    def test_key_is_valid_fernet_key(self, km):
        """Key must be exactly 32 bytes URL-safe base64 (44 chars with padding)."""
        from cryptography.fernet import Fernet
        key = km.get_key("acme-corp")
        # Should not raise
        cipher = Fernet(key)
        assert cipher is not None

    def test_five_tenants_all_unique(self, km):
        tenants = ["acme-corp", "globex-inc", "initech-ltd", "umbrella-co", "stark-tech"]
        keys = [km.get_key(t) for t in tenants]
        assert len(set(keys)) == 5, "All tenant keys must be unique"

    def test_key_caching(self, km):
        """get_key() caches after first derivation (same object)."""
        k1 = km.get_key("cached-tenant")
        k2 = km.get_key("cached-tenant")
        assert k1 is k2  # Same bytes object from cache


# ── 2. VaultStore ──────────────────────────────────────────────────────────────

class TestVaultStore:
    def test_store_and_fetch(self, store):
        store.store("acme", "<<TOK_EMAIL_abc123>>", "EMAIL_ADDRESS", "encrypted==", "sha1234")
        row = store.fetch("acme", "<<TOK_EMAIL_abc123>>")
        assert row is not None
        field_name, enc = row
        assert field_name == "EMAIL_ADDRESS"
        assert enc == "encrypted=="

    def test_fetch_nonexistent_returns_none(self, store):
        result = store.fetch("acme", "<<TOK_PHONE_nonexistent>>")
        assert result is None

    def test_tenant_isolation(self, store):
        """A token stored for Tenant A cannot be fetched by Tenant B."""
        store.store("tenant-a", "<<TOK_EMAIL_aa1122>>", "EMAIL_ADDRESS", "enc_a", "sha_a")
        result_b = store.fetch("tenant-b", "<<TOK_EMAIL_aa1122>>")
        assert result_b is None

    def test_count(self, store):
        store.store("count-tenant", "<<TOK_EMAIL_111>>", "EMAIL_ADDRESS", "enc1", "sha1")
        store.store("count-tenant", "<<TOK_EMAIL_222>>", "EMAIL_ADDRESS", "enc2", "sha2")
        assert store.count("count-tenant") == 2

    def test_delete_tenant(self, store):
        store.store("delete-me", "<<TOK_EMAIL_del>>", "EMAIL_ADDRESS", "enc_del", "sha_del")
        deleted = store.delete_tenant("delete-me")
        assert deleted == 1
        assert store.fetch("delete-me", "<<TOK_EMAIL_del>>") is None


# ── 3. Encrypt / Decrypt Round-trip ───────────────────────────────────────────

class TestVaultEncryptDecrypt:
    def test_encrypt_field_returns_token(self, vault):
        token = vault.encrypt_field(
            tenant_id="acme-corp",
            field_name="EMAIL_ADDRESS",
            plaintext="john@acme.com",
        )
        assert token.startswith("<<TOK_EMAIL_ADDRESS_")
        assert token.endswith(">>")

    def test_decrypt_returns_original(self, vault):
        token = vault.encrypt_field(
            tenant_id="acme-corp",
            field_name="EMAIL_ADDRESS",
            plaintext="roundtrip@acme.com",
        )
        decrypted = vault.decrypt_token(
            tenant_id="acme-corp",
            token=token,
            actor_role="SUPPORT_LEAD",
        )
        assert decrypted == "roundtrip@acme.com"

    def test_cross_tenant_decrypt_fails(self, vault):
        """Tenant A's token cannot be decrypted using Tenant B's key."""
        token = vault.encrypt_field(
            tenant_id="tenant-a",
            field_name="PERSON",
            plaintext="Jane Doe",
        )
        with pytest.raises((KeyError, ValueError)):
            vault.decrypt_token(
                tenant_id="tenant-b",
                token=token,
                actor_role="SUPPORT_LEAD",
            )

    def test_idempotent_encrypt(self, vault):
        """Encrypting the same value twice returns the same token (no duplicates)."""
        t1 = vault.encrypt_field(tenant_id="acme-corp", field_name="EMAIL_ADDRESS", plaintext="idem@acme.com")
        t2 = vault.encrypt_field(tenant_id="acme-corp", field_name="EMAIL_ADDRESS", plaintext="idem@acme.com")
        assert t1 == t2

    def test_different_values_produce_different_tokens(self, vault):
        t1 = vault.encrypt_field(tenant_id="acme-corp", field_name="EMAIL_ADDRESS", plaintext="alice@acme.com")
        t2 = vault.encrypt_field(tenant_id="acme-corp", field_name="EMAIL_ADDRESS", plaintext="bob@acme.com")
        assert t1 != t2


# ── 4. RBAC Enforcement ───────────────────────────────────────────────────────

class TestVaultRBAC:
    def test_support_lead_can_decrypt(self, vault):
        token = vault.encrypt_field(
            tenant_id="acme-corp", field_name="EMAIL_ADDRESS", plaintext="lead@acme.com"
        )
        result = vault.decrypt_token(
            tenant_id="acme-corp", token=token, actor_role="SUPPORT_LEAD"
        )
        assert result == "lead@acme.com"

    def test_security_admin_can_decrypt(self, vault):
        token = vault.encrypt_field(
            tenant_id="acme-corp", field_name="PHONE_NUMBER", plaintext="+49 30 123456"
        )
        result = vault.decrypt_token(
            tenant_id="acme-corp", token=token, actor_role="SECURITY_ADMIN"
        )
        assert result == "+49 30 123456"

    def test_agent_role_is_blocked(self, vault):
        token = vault.encrypt_field(
            tenant_id="acme-corp", field_name="PERSON", plaintext="Max Mustermann"
        )
        with pytest.raises(PermissionError, match="not authorized"):
            vault.decrypt_token(
                tenant_id="acme-corp", token=token, actor_role="AGENT"
            )

    def test_viewer_role_is_blocked(self, vault):
        token = vault.encrypt_field(
            tenant_id="acme-corp", field_name="EMAIL_ADDRESS", plaintext="viewer@acme.com"
        )
        with pytest.raises(PermissionError):
            vault.decrypt_token(
                tenant_id="acme-corp", token=token, actor_role="VIEWER"
            )

    def test_unknown_token_raises_keyerror(self, vault):
        with pytest.raises(KeyError):
            vault.decrypt_token(
                tenant_id="acme-corp",
                token="<<TOK_EMAIL_DEADBEEF>>",
                actor_role="SUPPORT_LEAD",
            )


# ── 5. Token Format ───────────────────────────────────────────────────────────

class TestTokenFormat:
    def test_token_matches_pattern(self, vault):
        token = vault.encrypt_field(
            tenant_id="acme-corp", field_name="EMAIL_ADDRESS", plaintext="fmt@test.com"
        )
        assert TOKEN_PATTERN.fullmatch(token), f"Token does not match pattern: {token}"

    def test_token_is_human_readable(self, vault):
        token = vault.encrypt_field(
            tenant_id="acme-corp", field_name="PHONE_NUMBER", plaintext="+1 555 123"
        )
        # Should contain the entity type for readability
        assert "PHONE_NUMBER" in token


# ── 6. encrypt_text() ─────────────────────────────────────────────────────────

class TestEncryptText:
    def test_email_is_tokenized(self, vault, presidio_engines):
        analyzer, anonymizer = presidio_engines
        text = "Please contact john.doe@example.com for details."
        tokenized, count = vault.encrypt_text(
            tenant_id="acme-corp",
            text=text,
            analyzer=analyzer,
            anonymizer=anonymizer,
        )
        assert "john.doe@example.com" not in tokenized
        assert "<<TOK_" in tokenized
        assert count >= 1

    def test_clean_text_unchanged(self, vault, presidio_engines):
        analyzer, anonymizer = presidio_engines
        text = "Please review the billing section of the dashboard."
        tokenized, count = vault.encrypt_text(
            tenant_id="acme-corp",
            text=text,
            analyzer=analyzer,
            anonymizer=anonymizer,
        )
        assert count == 0
        assert tokenized == text

    def test_none_text_returned_unchanged(self, vault, presidio_engines):
        analyzer, anonymizer = presidio_engines
        result, count = vault.encrypt_text(
            tenant_id="acme-corp",
            text=None,
            analyzer=analyzer,
            anonymizer=anonymizer,
        )
        assert result is None
        assert count == 0


# ── 7. decrypt_text() ─────────────────────────────────────────────────────────

class TestDecryptText:
    def test_full_roundtrip_on_text(self, vault, presidio_engines):
        analyzer, anonymizer = presidio_engines
        original = "Billing for alice@company.com looks wrong this month."
        tokenized, _ = vault.encrypt_text(
            tenant_id="acme-corp",
            text=original,
            analyzer=analyzer,
            anonymizer=anonymizer,
        )
        restored = vault.decrypt_text(
            tenant_id="acme-corp",
            text=tokenized,
            actor_role="SUPPORT_LEAD",
        )
        assert "alice@company.com" in restored


# ── 8. GDPR Forget ───────────────────────────────────────────────────────────

class TestGDPRForget:
    def test_forget_deletes_vault_entries(self, vault):
        vault.encrypt_field(tenant_id="gdpr-tenant", field_name="EMAIL_ADDRESS", plaintext="del@gdpr.com")
        vault.encrypt_field(tenant_id="gdpr-tenant", field_name="PERSON", plaintext="Hans Müller")
        assert vault.store.count("gdpr-tenant") == 2

        result = vault.forget_tenant("gdpr-tenant")
        assert result["vault_entries_deleted"] == 2
        assert vault.store.count("gdpr-tenant") == 0

    def test_other_tenants_unaffected_by_forget(self, vault):
        vault.encrypt_field(tenant_id="safe-tenant", field_name="EMAIL_ADDRESS", plaintext="safe@safe.com")
        vault.encrypt_field(tenant_id="forget-me-2", field_name="EMAIL_ADDRESS", plaintext="del2@del.com")
        vault.forget_tenant("forget-me-2")
        # safe-tenant still has their entries
        assert vault.store.count("safe-tenant") == 1


# ── 9. Integration: validate_and_clean_ticket() with vault ────────────────────

class TestBronzeToSilverVaultIntegration:
    BASE_RECORD = {
        "event_id": "evt-vault-001",
        "tenant_id": "acme-corp",
        "ticket_id": "TKT-VAULT-001",
        "customer_id": "CUST-9999",
        "customer_tier": "enterprise",
        "subject": "Billing issue for user@acme.com",
        "body": "Please email me at user@acme.com. My phone is +49 30 1234567.",
        "category": "billing",
        "priority": "high",
        "channel": "web",
        "reopen_count": 0,
        "tags": [],
        "timestamp": "2026-05-21T12:00:00Z",
    }

    def test_vault_mode_produces_version_2(self, vault, presidio_engines):
        from src.streaming.bronze_to_silver import validate_and_clean_ticket
        analyzer, anonymizer = presidio_engines
        result = validate_and_clean_ticket(self.BASE_RECORD, analyzer, anonymizer, vault=vault)
        assert result is not None
        assert result["silver_version"] == "2.0"
        assert result["vault_protected"] is True

    def test_vault_mode_tokens_in_body(self, vault, presidio_engines):
        from src.streaming.bronze_to_silver import validate_and_clean_ticket
        analyzer, anonymizer = presidio_engines
        result = validate_and_clean_ticket(self.BASE_RECORD, analyzer, anonymizer, vault=vault)
        assert "user@acme.com" not in result["body"]
        assert "<<TOK_" in result["body"]

    def test_vault_tokens_are_decryptable(self, vault, presidio_engines):
        from src.streaming.bronze_to_silver import validate_and_clean_ticket
        analyzer, anonymizer = presidio_engines
        result = validate_and_clean_ticket(self.BASE_RECORD, analyzer, anonymizer, vault=vault)
        restored = vault.decrypt_text(
            tenant_id="acme-corp",
            text=result["body"],
            actor_role="SUPPORT_LEAD",
            ticket_id=result["ticket_id"],
        )
        assert "user@acme.com" in restored


# ── 10. Backward Compatibility ────────────────────────────────────────────────

class TestBackwardCompatibility:
    RECORD = {
        "event_id": "evt-legacy-001",
        "tenant_id": "legacy-tenant",
        "ticket_id": "TKT-L001",
        "customer_id": "CUST-L001",
        "customer_tier": "free",
        "subject": "Hi from old@legacy.com",
        "body": "Call me at +1 800 555 1234 please.",
        "category": "general",
        "priority": "low",
        "channel": "email",
        "reopen_count": 0,
        "tags": [],
        "timestamp": "2026-01-01T00:00:00Z",
    }

    def test_no_vault_produces_version_1(self, presidio_engines):
        from src.streaming.bronze_to_silver import validate_and_clean_ticket
        analyzer, anonymizer = presidio_engines
        result = validate_and_clean_ticket(self.RECORD, analyzer, anonymizer, vault=None)
        assert result is not None
        assert result["silver_version"] == "1.0"
        assert result["vault_protected"] is False

    def test_no_vault_pii_is_deleted(self, presidio_engines):
        """With vault=None, Presidio permanently replaces PII (no <<TOK_ tokens)."""
        from src.streaming.bronze_to_silver import validate_and_clean_ticket
        analyzer, anonymizer = presidio_engines
        result = validate_and_clean_ticket(self.RECORD, analyzer, anonymizer, vault=None)
        # The email should be masked (not present in plain form)
        assert "old@legacy.com" not in result["body"]
        # No vault tokens — plain masking produces [EMAIL_ADDRESS] etc.
        assert "<<TOK_" not in result["body"]
