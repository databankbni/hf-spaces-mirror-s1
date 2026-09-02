-- ============================================================
-- CustomerCore — Phase 12: Supabase Schema + Row Level Security
-- Run this in: Supabase Dashboard → SQL Editor → New Query
-- ============================================================

-- Enable pgcrypto for UUID generation
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ────────────────────────────────────────────────────────────
-- 1. TENANTS
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS tenants (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    slug            TEXT        UNIQUE NOT NULL,          -- e.g. 'acme-corp'
    name            TEXT        NOT NULL,
    tier            TEXT        NOT NULL DEFAULT 'growth'
                                CHECK (tier IN ('free','growth','enterprise','vip')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE tenants IS 'One row per B2B customer organisation using CustomerCore.';

-- ────────────────────────────────────────────────────────────
-- 2. TICKETS
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS tickets (
    id                      UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id               UUID        NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    external_ticket_id      TEXT,                         -- caller-supplied ID (idempotency)
    customer_id             TEXT        NOT NULL,
    customer_tier           TEXT        NOT NULL DEFAULT 'free'
                                        CHECK (customer_tier IN ('free','starter','growth','enterprise','vip')),
    channel                 TEXT        NOT NULL DEFAULT 'api'
                                        CHECK (channel IN ('email','chat','api','phone','portal')),
    raw_text                TEXT        NOT NULL,          -- original ticket body (stored encrypted)
    masked_text             TEXT,
    detected_language       TEXT,
    status                  TEXT        NOT NULL DEFAULT 'pending'
                                        CHECK (status IN ('pending','processing','complete','hitl','failed')),
    priority                TEXT        CHECK (priority IN ('critical','high','medium','low')),
    category                TEXT,
    sub_category            TEXT,
    sentiment               TEXT        CHECK (sentiment IN ('angry','frustrated','neutral','satisfied','positive')),
    churn_risk_score        NUMERIC(4,3),                 -- 0.000–1.000
    constitutional_score    NUMERIC(4,3),                 -- 0.000–1.000
    constitutional_passed   BOOLEAN     DEFAULT TRUE,
    hitl_required           BOOLEAN     DEFAULT FALSE,
    hitl_reason             TEXT,
    hitl_resolved_at        TIMESTAMPTZ,
    hitl_resolved_by        TEXT,
    suggested_resolution    TEXT,
    resolution_quality      NUMERIC(4,3),
    rag_grounding_score     NUMERIC(4,3),
    llm_model_used          TEXT,
    llm_cost_usd            NUMERIC(10,6),
    llm_tokens_total        INTEGER,
    langfuse_trace_id       TEXT,                         -- link back to Langfuse
    error_message           TEXT,
    processing_started_at   TIMESTAMPTZ,
    processing_completed_at TIMESTAMPTZ,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT uq_tenant_external UNIQUE (tenant_id, external_ticket_id)
);
COMMENT ON TABLE tickets IS 'Persistent store for all triage requests and their AI-generated outcomes.';
CREATE INDEX IF NOT EXISTS idx_tickets_tenant_status  ON tickets (tenant_id, status);
CREATE INDEX IF NOT EXISTS idx_tickets_tenant_created ON tickets (tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tickets_priority        ON tickets (priority) WHERE priority IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_tickets_hitl            ON tickets (hitl_required) WHERE hitl_required = TRUE;

-- ────────────────────────────────────────────────────────────
-- 3. CONSTITUTIONAL VIOLATIONS LOG
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS constitutional_violations (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    ticket_id       UUID        NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
    tenant_id       UUID        NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    rule_id         TEXT        NOT NULL,    -- e.g. 'PII_PROTECTION'
    severity        TEXT        NOT NULL,    -- 'critical' | 'violation' | 'warning'
    action_taken    TEXT        NOT NULL,    -- 'block' | 'redact' | 'regenerate' | 'warn'
    evidence        TEXT,                   -- the triggering text (max 200 chars)
    explanation     TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE constitutional_violations IS 'Audit log: every constitutional rule violation with evidence and remediation.';
CREATE INDEX IF NOT EXISTS idx_violations_tenant ON constitutional_violations (tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_violations_rule   ON constitutional_violations (rule_id);

-- ────────────────────────────────────────────────────────────
-- 4. KB ARTICLES (for RAG grounding)
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS kb_articles (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID        NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    external_id     TEXT        NOT NULL,   -- e.g. 'KB-billing-001'
    title           TEXT        NOT NULL,
    content         TEXT        NOT NULL,
    category        TEXT,
    tags            TEXT[],
    active          BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_kb_tenant_external UNIQUE (tenant_id, external_id)
);
CREATE INDEX IF NOT EXISTS idx_kb_tenant_active ON kb_articles (tenant_id, active);

-- ────────────────────────────────────────────────────────────
-- 5. AUDIT LOG (immutable — no UPDATE/DELETE)
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS audit_log (
    id              BIGSERIAL   PRIMARY KEY,
    tenant_id       UUID        REFERENCES tenants(id),
    ticket_id       UUID        REFERENCES tickets(id),
    actor           TEXT,                   -- user_id, 'system', 'ai'
    action          TEXT        NOT NULL,   -- 'ticket.created', 'hitl.approved', etc.
    resource_type   TEXT,
    resource_id     TEXT,
    details         JSONB,
    ip_address      INET,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE audit_log IS 'Append-only audit trail. No DELETE/UPDATE permitted (enforced by RLS).';
CREATE INDEX IF NOT EXISTS idx_audit_tenant   ON audit_log (tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_ticket   ON audit_log (ticket_id);
CREATE INDEX IF NOT EXISTS idx_audit_action   ON audit_log (action);

-- ────────────────────────────────────────────────────────────
-- 6. ROW LEVEL SECURITY
-- Tenants can ONLY see their own rows. This is enforced at the
-- database level — even a buggy application cannot leak data.
-- ────────────────────────────────────────────────────────────

-- Enable RLS on every tenant-scoped table
ALTER TABLE tickets                 ENABLE ROW LEVEL SECURITY;
ALTER TABLE constitutional_violations ENABLE ROW LEVEL SECURITY;
ALTER TABLE kb_articles             ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_log               ENABLE ROW LEVEL SECURITY;

-- RLS policy: service role bypasses (for backend API)
-- Application uses SUPABASE_SERVICE_ROLE_KEY → full access
-- Public anon key → restricted by these policies

-- tickets: tenant isolation
CREATE POLICY tenant_isolation_tickets ON tickets
    USING (tenant_id::text = current_setting('app.tenant_id', TRUE));

-- constitutional_violations: tenant isolation
CREATE POLICY tenant_isolation_violations ON constitutional_violations
    USING (tenant_id::text = current_setting('app.tenant_id', TRUE));

-- kb_articles: tenant isolation (read their own KB, not others')
CREATE POLICY tenant_isolation_kb ON kb_articles
    USING (tenant_id::text = current_setting('app.tenant_id', TRUE));

-- audit_log: tenant can read own entries, cannot write directly
CREATE POLICY tenant_read_audit ON audit_log
    FOR SELECT
    USING (tenant_id::text = current_setting('app.tenant_id', TRUE));

-- Prevent any direct INSERT/UPDATE/DELETE on audit_log from non-service roles
CREATE POLICY audit_log_insert_service_only ON audit_log
    FOR INSERT
    WITH CHECK (current_setting('role', TRUE) = 'service_role');

-- ────────────────────────────────────────────────────────────
-- 7. auto-update updated_at trigger
-- ────────────────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_tickets_updated_at
    BEFORE UPDATE ON tickets
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER trg_tenants_updated_at
    BEFORE UPDATE ON tenants
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER trg_kb_updated_at
    BEFORE UPDATE ON kb_articles
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- ────────────────────────────────────────────────────────────
-- 8. Seed: demo tenant
-- ────────────────────────────────────────────────────────────
INSERT INTO tenants (id, slug, name, tier)
VALUES (
    'a0000000-0000-0000-0000-000000000001',
    'acme-corp',
    'Acme Corporation',
    'enterprise'
) ON CONFLICT (slug) DO NOTHING;
