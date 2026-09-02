{{ config(materialized="view") }}

SELECT
    event_id,
    CASE 
        WHEN event_type = 'support_ticket_created' THEN 'ticket'
        WHEN event_type = 'incident_detected' THEN 'incident'
        WHEN event_type IN ('usability_complaint', 'feature_request', 'feature_praise') THEN 'product_event'
        WHEN event_type IN ('payment_failed', 'payment_method_expired', 'subscription_downgrade', 'overcharge_reported', 'invoice_dispute') THEN 'billing_event'
        ELSE event_type
    END AS event_type,
    source,
    COALESCE(tenant_id, 'system') AS tenant_id,
    customer_id,
    COALESCE(original_timestamp, timestamp, processed_at)::timestamp AS created_at,
    body,
    priority,
    COALESCE(reopen_count::integer, 0) AS reopen_count,
    false AS is_synthetic,
    
    -- Billing Specific Fields
    amount::double AS billing_amount,
    currency AS billing_currency,
    plan AS billing_plan,
    failure_code AS billing_failure_code,
    
    -- Product Specific Fields
    sentiment_score::double AS product_sentiment_score,
    satisfaction_rating::integer AS product_satisfaction_rating,
    
    -- Incident Specific Fields
    severity AS incident_severity,
    affected_service AS incident_affected_service,
    error_rate::double AS incident_error_rate
    
FROM {{ source('silver', 'silver_events') }}
