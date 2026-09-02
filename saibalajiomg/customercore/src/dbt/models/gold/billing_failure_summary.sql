{{ config(materialized="table") }}

SELECT
    tenant_id,
    DATE(created_at) AS event_date,
    priority,
    COUNT(*) AS billing_event_count,
    SUM(CASE WHEN body LIKE '%payment_failed%' THEN 1 ELSE 0 END) AS payment_failures,
    SUM(CASE WHEN body LIKE '%cancelled%' THEN 1 ELSE 0 END)      AS cancellations
FROM {{ ref('stg_silver_events') }}
WHERE event_type = 'billing_event'
GROUP BY 1, 2, 3
