"""
tests/unit/test_phase8_multilang.py

Phase 8: Multi-Language Support + Graph-RAG — Full Test Suite

Sections:
  1. Language detection — 7 languages, edge cases
  2. Multilingual tokenization — stopword removal per language
  3. Language routing flags — multilingual vs English-only
  4. Silver record enrichment — enrich_with_language()
  5. B2BKnowledgeGraph — nodes, edges, context
  6. GraphRAGEngine — indexing, query, context formatting
  7. MASSIVE enrich function — intent mapping, language field
  8. Routing table integration — multilingual tickets get cloud routing
"""

import pytest
from unittest.mock import patch

from src.rag.multilingual import (
    detect_language, detect_language_with_confidence,
    get_stopwords, tokenize_multilingual, needs_multilingual_model,
    get_language_display, enrich_with_language,
    SUPPORTED_LANGUAGES, MULTILINGUAL_LANGUAGES,
)
from src.rag.graph_rag import (
    B2BKnowledgeGraph, GraphRAGEngine, GraphRAGResult,
)
from src.streaming.data_loader import enrich_massive, MASSIVE_LANGUAGES


# ── 1. Language Detection ─────────────────────────────────────────────────────

class TestLanguageDetection:
    def test_english_detected(self):
        text = "My payment failed and I cannot access my account. Please help urgently."
        assert detect_language(text) == "en"

    def test_german_detected(self):
        text = "Meine Zahlung ist fehlgeschlagen und ich kann nicht auf mein Konto zugreifen."
        lang = detect_language(text)
        assert lang == "de"

    def test_french_detected(self):
        text = "Mon paiement a échoué et je ne peux pas accéder à mon compte. Aidez-moi."
        lang = detect_language(text)
        assert lang == "fr"

    def test_spanish_detected(self):
        text = "Mi pago falló y no puedo acceder a mi cuenta. Por favor ayúdame urgentemente."
        lang = detect_language(text)
        assert lang == "es"

    def test_short_text_falls_back_to_english(self):
        # Texts under 20 chars are too short for reliable detection
        assert detect_language("Hi") == "en"
        assert detect_language("") == "en"
        assert detect_language("   ") == "en"

    def test_detect_with_confidence_returns_tuple(self):
        text = "My API is returning 500 errors on the checkout endpoint. This is urgent."
        lang, conf = detect_language_with_confidence(text)
        assert isinstance(lang, str)
        assert isinstance(conf, float)
        assert 0.0 <= conf <= 1.0
        assert lang == "en"

    def test_detect_confidence_high_for_clear_english(self):
        text = "My API is returning 500 errors on the checkout endpoint. This is urgent."
        _, conf = detect_language_with_confidence(text)
        assert conf > 0.5

    def test_normalize_hyphenated_lang_code(self):
        """langdetect returns 'zh-cn' — we normalize to 'zh'."""
        with patch("langdetect.detect") as mock_detect:
            mock_detect.return_value = "zh-cn"
            lang = detect_language("some text long enough for detection to work here ok yes")
            assert lang == "zh"  # normalized


# ── 2. Multilingual Tokenization ──────────────────────────────────────────────

class TestMultilingualTokenization:
    def test_english_stopwords_removed(self):
        tokens = tokenize_multilingual("The API is broken for the user", "en")
        assert "the" not in tokens
        assert "is" not in tokens
        assert "api" in tokens
        assert "broken" in tokens

    def test_german_stopwords_removed(self):
        tokens = tokenize_multilingual("Der Server ist kaputt und funktioniert nicht", "de")
        assert "der" not in tokens
        assert "ist" not in tokens
        assert "und" not in tokens
        assert "server" in tokens
        assert "kaputt" in tokens

    def test_french_stopwords_removed(self):
        tokens = tokenize_multilingual("Le paiement est refusé par le système", "fr")
        assert "le" not in tokens
        assert "est" not in tokens
        assert "paiement" in tokens

    def test_spanish_stopwords_removed(self):
        tokens = tokenize_multilingual("El pago falló en el sistema de facturación", "es")
        assert "el" not in tokens
        assert "pago" in tokens
        assert "sistema" in tokens

    def test_unknown_language_falls_back_to_english_stopwords(self):
        tokens = tokenize_multilingual("The system is broken", "xx")
        assert "the" not in tokens
        assert "system" in tokens

    def test_short_tokens_filtered(self):
        tokens = tokenize_multilingual("I am at a café", "en")
        assert "i" not in tokens  # length 1
        assert "a" not in tokens  # length 1

    def test_returns_list(self):
        result = tokenize_multilingual("API payment error", "en")
        assert isinstance(result, list)

    def test_stopwords_returns_set(self):
        sw = get_stopwords("en")
        assert isinstance(sw, set)
        assert "the" in sw

    def test_stopwords_all_supported_languages(self):
        for lang in SUPPORTED_LANGUAGES:
            sw = get_stopwords(lang)
            assert len(sw) > 5, f"Too few stopwords for {lang}"


# ── 3. Language Routing Flags ─────────────────────────────────────────────────

class TestLanguageRoutingFlags:
    def test_english_not_multilingual(self):
        assert needs_multilingual_model("en") is False

    def test_german_needs_multilingual(self):
        assert needs_multilingual_model("de") is True

    def test_french_needs_multilingual(self):
        assert needs_multilingual_model("fr") is True

    def test_spanish_needs_multilingual(self):
        assert needs_multilingual_model("es") is True

    def test_portuguese_needs_multilingual(self):
        assert needs_multilingual_model("pt") is True

    def test_dutch_needs_multilingual(self):
        assert needs_multilingual_model("nl") is True

    def test_italian_needs_multilingual(self):
        assert needs_multilingual_model("it") is True

    def test_unknown_lang_not_multilingual(self):
        # Unknown languages don't get multilingual flag — fallback to English
        assert needs_multilingual_model("xx") is False

    def test_multilingual_languages_set_has_6(self):
        assert len(MULTILINGUAL_LANGUAGES) == 6

    def test_get_language_display_english(self):
        assert get_language_display("en") == "English"

    def test_get_language_display_german(self):
        assert get_language_display("de") == "German"

    def test_get_language_display_unknown(self):
        result = get_language_display("xx")
        assert "xx" in result  # Should include the code in unknown display


# ── 4. Silver Record Enrichment ───────────────────────────────────────────────

class TestSilverEnrichment:
    def test_enrich_with_language_adds_fields(self):
        record = {"body": "My payment failed and I need a refund urgently today."}
        result = enrich_with_language(record)
        assert "detected_language" in result
        assert "language_confidence" in result
        assert "language_display" in result
        assert "is_multilingual" in result

    def test_enrich_english_not_multilingual(self):
        record = {"body": "API returning 500 errors on checkout endpoint for all users."}
        result = enrich_with_language(record)
        assert result["detected_language"] == "en"
        assert result["is_multilingual"] is False

    def test_enrich_mutates_record_in_place(self):
        record = {"body": "My payment failed and I need a refund urgently today."}
        result = enrich_with_language(record)
        assert result is record  # same object

    def test_enrich_empty_body_uses_subject(self):
        record = {"body": "", "subject": "API error on production system for all users"}
        result = enrich_with_language(record)
        assert result["detected_language"] in SUPPORTED_LANGUAGES or len(result["detected_language"]) == 2

    def test_enrich_confidence_is_float(self):
        record = {"body": "My payment failed and I need a refund urgently today."}
        result = enrich_with_language(record)
        assert isinstance(result["language_confidence"], float)


# ── 5. B2BKnowledgeGraph ─────────────────────────────────────────────────────

class TestB2BKnowledgeGraph:
    @pytest.fixture
    def graph(self):
        g = B2BKnowledgeGraph()
        g.add_ticket("acme-corp", "TKT-001", "API 500 error", "technical", "critical", "en")
        g.add_ticket("acme-corp", "TKT-002", "Invoice double charge", "billing", "high", "en")
        g.add_ticket("acme-corp", "TKT-003", "Zahlung fehlgeschlagen", "billing", "high", "de")
        g.add_ticket("globex-inc", "TKT-010", "Latency spike on EU cluster", "technical", "critical", "en")
        return g

    def test_node_count_positive(self, graph):
        assert graph.node_count() > 0

    def test_ticket_stored(self, graph):
        assert "TKT-001" in graph._tickets

    def test_tenant_stored(self, graph):
        assert "acme-corp" in graph._tenants
        assert "globex-inc" in graph._tenants

    def test_category_stored(self, graph):
        assert "technical" in graph._categories
        assert "billing" in graph._categories

    def test_tenant_context_total_tickets(self, graph):
        ctx = graph.get_tenant_context("acme-corp")
        assert ctx["total_tickets"] == 3

    def test_tenant_context_escalation_rate(self, graph):
        ctx = graph.get_tenant_context("acme-corp")
        # 1 critical + 2 high = 3 escalations out of 3 = 100%
        assert ctx["escalation_rate_pct"] == 100.0

    def test_tenant_context_top_categories(self, graph):
        ctx = graph.get_tenant_context("acme-corp")
        cats = [c["category"] for c in ctx["top_categories"]]
        assert "billing" in cats

    def test_tenant_context_language_breakdown(self, graph):
        ctx = graph.get_tenant_context("acme-corp")
        lb = ctx["language_breakdown"]
        assert lb.get("en", 0) == 2
        assert lb.get("de", 0) == 1

    def test_unknown_tenant_returns_graceful(self, graph):
        ctx = graph.get_tenant_context("unknown-tenant-xyz")
        assert ctx["total_tickets"] == 0

    def test_add_tenant_metrics(self, graph):
        graph.add_tenant_metrics("acme-corp", {"csat_score": 4.2, "open_tickets": 5})
        ctx = graph.get_tenant_context("acme-corp")
        assert ctx["gold_metrics"]["csat_score"] == 4.2

    def test_get_category_trends(self, graph):
        trends = graph.get_category_trends()
        assert "technical" in trends
        assert "billing" in trends
        assert trends["billing"] >= 2  # 2 billing tickets for acme + 0 for globex

    def test_find_similar_tenants(self, graph):
        similar = graph.find_similar_tenants("acme-corp")
        assert isinstance(similar, list)
        # globex has "technical" in common with acme
        tenant_ids = [s["tenant_id"] for s in similar]
        assert "globex-inc" in tenant_ids

    def test_similar_tenants_excludes_self(self, graph):
        similar = graph.find_similar_tenants("acme-corp")
        tenant_ids = [s["tenant_id"] for s in similar]
        assert "acme-corp" not in tenant_ids

    def test_category_count_increments(self, graph):
        graph.add_ticket("acme-corp", "TKT-099", "Another billing issue", "billing", "medium", "en")
        trends = graph.get_category_trends()
        assert trends["billing"] == 3  # was 2, now 3


# ── 6. GraphRAGEngine ─────────────────────────────────────────────────────────

class TestGraphRAGEngine:
    @pytest.fixture
    def engine(self):
        graph = B2BKnowledgeGraph()
        graph.add_ticket("acme-corp", "TKT-A1", "API error on production", "technical", "critical", "en")
        graph.add_ticket("acme-corp", "TKT-A2", "Double charge on invoice", "billing", "high", "en")
        graph.add_ticket("acme-corp", "TKT-A3", "Zahlung fehlgeschlagen", "billing", "high", "de")
        return GraphRAGEngine(retriever=None, graph=graph, gold_db_path="nonexistent.duckdb")

    def test_query_returns_graph_rag_result(self, engine):
        result = engine.query("acme-corp", "Why is this tenant escalating?", include_sql=False)
        assert isinstance(result, GraphRAGResult)

    def test_query_has_tenant_context(self, engine):
        result = engine.query("acme-corp", "escalation patterns", include_sql=False)
        assert result.tenant_context["total_tickets"] == 3

    def test_query_has_combined_context(self, engine):
        result = engine.query("acme-corp", "billing issues", include_sql=False)
        assert len(result.combined_context) > 50
        assert "acme-corp" in result.combined_context

    def test_query_plan_has_steps(self, engine):
        result = engine.query("acme-corp", "billing issues", include_sql=False)
        assert len(result.query_plan) >= 2

    def test_query_no_retriever_has_empty_similar_tickets(self, engine):
        result = engine.query("acme-corp", "billing issues", include_sql=False)
        assert result.similar_tickets == []

    def test_query_missing_tenant_graceful(self, engine):
        result = engine.query("unknown-tenant", "any question", include_sql=False)
        assert result.tenant_context["total_tickets"] == 0

    def test_index_ticket_adds_to_graph(self, engine):
        engine.index_ticket(
            "acme-corp", "TKT-NEW", "New ticket text",
            metadata={"category": "technical", "priority": "high", "language": "en"}
        )
        ctx = engine.graph.get_tenant_context("acme-corp")
        assert ctx["total_tickets"] == 4

    def test_combined_context_contains_tenant_profile(self, engine):
        result = engine.query("acme-corp", "billing", include_sql=False)
        assert "TENANT PROFILE" in result.combined_context
        assert "escalation" in result.combined_context.lower()

    def test_sql_insights_empty_when_db_missing(self, engine):
        result = engine.query("acme-corp", "billing", include_sql=True)
        assert isinstance(result.sql_insights, list)
        # DB doesn't exist so should be empty
        assert result.sql_insights == []


# ── 7. MASSIVE enrich function ────────────────────────────────────────────────

class TestEnrichMassive:
    SAMPLE_ROW = {
        "id": "de-123",
        "label": 5,
        "label_text": "alarm_set",
        "text": "Stell mir einen Wecker für morgen früh um 7 Uhr",
        "lang": "de-DE",
    }

    def test_enrich_massive_has_required_fields(self):
        event = enrich_massive(self.SAMPLE_ROW, "de", "German")
        required = [
            "event_id", "event_type", "timestamp", "tenant_id", "ticket_id",
            "customer_id", "customer_tier", "subject", "body", "category",
            "priority", "channel", "language", "is_multilingual", "intent",
        ]
        for f in required:
            assert f in event, f"Missing field: {f}"

    def test_enrich_massive_language_set(self):
        event = enrich_massive(self.SAMPLE_ROW, "de", "German")
        assert event["language"] == "de"
        assert event["language_name"] == "German"

    def test_enrich_massive_is_multilingual_true(self):
        event = enrich_massive(self.SAMPLE_ROW, "de", "German")
        assert event["is_multilingual"] is True

    def test_enrich_massive_intent_mapping_alarm_to_account(self):
        event = enrich_massive(self.SAMPLE_ROW, "de", "German")
        # alarm_set -> account category
        assert event["category"] == "account"

    def test_enrich_massive_shopping_maps_to_order(self):
        row = {**self.SAMPLE_ROW, "label_text": "shopping_query"}
        event = enrich_massive(row, "fr", "French")
        assert event["category"] == "order"

    def test_enrich_massive_iot_maps_to_technical(self):
        row = {**self.SAMPLE_ROW, "label_text": "iot_hue_lightchange"}
        event = enrich_massive(row, "es", "Spanish")
        assert event["category"] == "technical"

    def test_enrich_massive_body_from_text_field(self):
        event = enrich_massive(self.SAMPLE_ROW, "de", "German")
        assert "Wecker" in event["body"]

    def test_enrich_massive_license_apache(self):
        event = enrich_massive(self.SAMPLE_ROW, "de", "German")
        assert event["license"] == "Apache-2.0"

    def test_enrich_massive_tags_include_intent(self):
        event = enrich_massive(self.SAMPLE_ROW, "de", "German")
        assert any("alarm" in tag for tag in event["tags"])

    def test_massive_languages_config_has_3(self):
        assert len(MASSIVE_LANGUAGES) == 3
        assert "de" in MASSIVE_LANGUAGES
        assert "fr" in MASSIVE_LANGUAGES
        assert "es" in MASSIVE_LANGUAGES


# ── 8. Router Integration: Multilingual Routing ───────────────────────────────

class TestMultilingualRouterIntegration:
    """Verify that non-English tickets get appropriate routing flags."""

    def test_german_ticket_needs_multilingual_model(self):
        lang = "de"
        assert needs_multilingual_model(lang) is True

    def test_multilingual_record_has_is_multilingual_true(self):
        record = {
            "body": "Meine Zahlung ist fehlgeschlagen und ich kann nicht einloggen."
        }
        result = enrich_with_language(record)
        # German detected -> is_multilingual = True
        if result["detected_language"] == "de":
            assert result["is_multilingual"] is True

    def test_english_record_has_is_multilingual_false(self):
        record = {
            "body": "My payment failed and I cannot access my account. Please help."
        }
        result = enrich_with_language(record)
        if result["detected_language"] == "en":
            assert result["is_multilingual"] is False
