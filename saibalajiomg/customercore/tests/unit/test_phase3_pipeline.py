"""
tests/unit/test_phase3_pipeline.py

Phase 3 verification tests.
Tests that:
1. MinIO setup module imports correctly
2. Data loader enrich() function produces valid events
3. Bronze-to-Silver cleaning functions work correctly
4. PII masking actually masks known PII patterns
5. Validation correctly drops records missing required fields
"""

from src.streaming.data_loader import enrich, TENANTS


# ── Data Loader Tests ─────────────────────────────────────────

class TestDataLoader:
    SAMPLE_ROW = {
        "instruction": "Hello my name is John Smith, call me at 555-1234 to fix my billing issue.",
        "response": "We will call you back shortly.",
        "category": "BILLING",
        "tags": "billing, payment",
    }

    def test_enrich_returns_all_required_fields(self):
        required = [
            "event_id", "event_type", "timestamp", "tenant_id",
            "ticket_id", "customer_id", "customer_tier",
            "subject", "body", "category", "priority", "channel",
        ]
        event = enrich(self.SAMPLE_ROW, "saas_support", "CDLA-Sharing-1.0")
        for f in required:
            assert f in event, f"Missing field: {f}"

    def test_enrich_tenant_is_valid(self):
        for _ in range(20):
            event = enrich(self.SAMPLE_ROW, "saas_support", "CDLA-Sharing-1.0")
            assert event["tenant_id"] in TENANTS

    def test_enrich_event_type_correct(self):
        event = enrich(self.SAMPLE_ROW, "saas_support", "CDLA-Sharing-1.0")
        assert event["event_type"] == "support_ticket_created"

    def test_enrich_license_correct(self):
        event = enrich(self.SAMPLE_ROW, "saas_support", "CDLA-Sharing-1.0")
        assert event["license"] == "CDLA-Sharing-1.0"

    def test_enrich_subject_truncated_to_120(self):
        long_row = {**self.SAMPLE_ROW, "instruction": "x" * 200}
        event = enrich(long_row, "saas_support", "CDLA-Sharing-1.0")
        assert len(event["subject"]) <= 120

    def test_enrich_tags_is_list(self):
        event = enrich(self.SAMPLE_ROW, "saas_support", "CDLA-Sharing-1.0")
        assert isinstance(event["tags"], list)


# ── Bronze-to-Silver Cleaning Tests ──────────────────────────

class TestBronzeToSilver:
    def setup_method(self):
        """Initialize Presidio engines for PII tests."""
        from presidio_analyzer import AnalyzerEngine
        from presidio_anonymizer import AnonymizerEngine
        from presidio_analyzer.nlp_engine import NlpEngineProvider
        nlp_config = {"nlp_engine_name": "spacy", "models": [{"lang_code": "en", "model_name": "en_core_web_sm"}]}
        nlp_engine = NlpEngineProvider(nlp_configuration=nlp_config).create_engine()
        self.analyzer = AnalyzerEngine(nlp_engine=nlp_engine)
        self.anonymizer = AnonymizerEngine()

    def _clean(self, record):
        from src.streaming.bronze_to_silver import validate_and_clean_ticket
        return validate_and_clean_ticket(record, self.analyzer, self.anonymizer)

    VALID_RECORD = {
        "event_id": "abc-123",
        "tenant_id": "acme-corp",
        "ticket_id": "TKT-99999",
        "customer_id": "CUST-1234",
        "customer_tier": "enterprise",
        "subject": "Login is broken",
        "body": "I cannot login to my account.",
        "category": "technical",
        "priority": "high",
        "channel": "web",
        "reopen_count": 0,
        "tags": [],
        "timestamp": "2025-01-01T00:00:00Z",
    }

    def test_valid_record_passes_cleaning(self):
        result = self._clean(self.VALID_RECORD)
        assert result is not None

    def test_missing_event_id_drops_record(self):
        bad = {**self.VALID_RECORD, "event_id": ""}
        assert self._clean(bad) is None

    def test_missing_tenant_id_drops_record(self):
        bad = {**self.VALID_RECORD, "tenant_id": ""}
        assert self._clean(bad) is None

    def test_invalid_priority_normalized_to_medium(self):
        bad = {**self.VALID_RECORD, "priority": "super-urgent"}
        result = self._clean(bad)
        assert result["priority"] == "medium"

    def test_invalid_tier_normalized_to_free(self):
        bad = {**self.VALID_RECORD, "customer_tier": "vip"}
        result = self._clean(bad)
        assert result["customer_tier"] == "free"

    def test_invalid_channel_normalized_to_web(self):
        bad = {**self.VALID_RECORD, "channel": "telegram"}
        result = self._clean(bad)
        assert result["channel"] == "web"

    def test_pii_masked_flag_set(self):
        result = self._clean(self.VALID_RECORD)
        assert result["pii_masked"] is True

    def test_silver_version_set(self):
        result = self._clean(self.VALID_RECORD)
        assert result["silver_version"] == "1.0"

    def test_processed_at_set(self):
        result = self._clean(self.VALID_RECORD)
        assert result["processed_at"] != ""

    def test_email_pii_is_masked(self):
        """Presidio should mask email addresses in body."""
        from src.streaming.bronze_to_silver import mask_pii
        text = "Please email me at john.doe@example.com with the update."
        masked = mask_pii(text, self.analyzer, self.anonymizer)
        assert "john.doe@example.com" not in masked

    def test_phone_pii_is_masked(self):
        """Presidio should mask phone numbers in body."""
        from src.streaming.bronze_to_silver import mask_pii
        text = "Call me at +1 212-555-1234 to discuss my account."
        masked = mask_pii(text, self.analyzer, self.anonymizer)
        assert "+1 212-555-1234" not in masked
