-- FinOps Optimizer MCP — Supabase Schema
-- Run this in Supabase SQL Editor if tables don't exist yet

-- Existing tables confirmed present in your stack:
-- finops_anomalies, finops_ai_insights, finops_savings,
-- finops_recommendations, finops_remediation_log

-- === finops_anomalies ===
CREATE TABLE IF NOT EXISTS finops_anomalies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    provider TEXT NOT NULL CHECK (provider IN ('azure','aws','gcp','openshift')),
    resource_id TEXT NOT NULL,
    resource_name TEXT,
    severity TEXT NOT NULL CHECK (severity IN ('critical','high','medium','low')),
    anomaly_type TEXT NOT NULL,
    cost_delta_usd NUMERIC(12,2),
    baseline_cost_usd NUMERIC(12,2),
    description TEXT,
    detected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_anomalies_provider ON finops_anomalies(provider);
CREATE INDEX IF NOT EXISTS idx_anomalies_severity ON finops_anomalies(severity);
CREATE INDEX IF NOT EXISTS idx_anomalies_resource ON finops_anomalies(resource_id);

-- === finops_recommendations ===
CREATE TABLE IF NOT EXISTS finops_recommendations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    provider TEXT NOT NULL CHECK (provider IN ('azure','aws','gcp','openshift')),
    resource_id TEXT NOT NULL,
    resource_name TEXT,
    category TEXT NOT NULL,  -- rightsizing | idle_resources | reserved_instances | storage
    title TEXT NOT NULL,
    description TEXT,
    estimated_savings_usd NUMERIC(12,2),
    effort_level TEXT CHECK (effort_level IN ('low','medium','high')),
    priority TEXT CHECK (priority IN ('high','medium','low')),
    current_config TEXT,
    recommended_config TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_recs_provider ON finops_recommendations(provider);
CREATE INDEX IF NOT EXISTS idx_recs_savings ON finops_recommendations(estimated_savings_usd DESC);
CREATE INDEX IF NOT EXISTS idx_recs_resource ON finops_recommendations(resource_id);

-- === finops_ai_insights ===
CREATE TABLE IF NOT EXISTS finops_ai_insights (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    provider TEXT NOT NULL,
    insight_type TEXT NOT NULL,  -- anomaly_explanation | optimization | forecast | trend
    title TEXT NOT NULL,
    summary TEXT,
    detailed_analysis TEXT,
    confidence_score NUMERIC(3,2) CHECK (confidence_score BETWEEN 0 AND 1),
    affected_resources JSONB,
    potential_savings_usd NUMERIC(12,2),
    generated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- === finops_savings ===
CREATE TABLE IF NOT EXISTS finops_savings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    provider TEXT NOT NULL,
    resource_id TEXT,
    saving_type TEXT NOT NULL,
    amount_usd NUMERIC(12,2),
    period TEXT,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- === finops_remediation_log ===
CREATE TABLE IF NOT EXISTS finops_remediation_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    recommendation_id TEXT NOT NULL,
    provider TEXT NOT NULL CHECK (provider IN ('azure','aws','gcp','openshift')),
    resource_id TEXT NOT NULL,
    action_type TEXT NOT NULL CHECK (action_type IN (
        'rightsize','stop_idle','switch_ri','delete_unattached','resize_storage'
    )),
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN (
        'pending','in_progress','completed','failed','skipped'
    )),
    executed_by TEXT NOT NULL DEFAULT 'finops_mcp',
    estimated_savings_usd NUMERIC(12,2),
    actual_savings_usd NUMERIC(12,2),
    notes TEXT,
    initiated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_rem_status ON finops_remediation_log(status);
CREATE INDEX IF NOT EXISTS idx_rem_resource ON finops_remediation_log(resource_id);
CREATE INDEX IF NOT EXISTS idx_rem_provider ON finops_remediation_log(provider);
