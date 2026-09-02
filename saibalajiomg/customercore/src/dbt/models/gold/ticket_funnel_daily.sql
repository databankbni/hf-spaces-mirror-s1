{{ config(materialized="table") }}

SELECT
    tenant_id,
    event_type,
    priority,
    source,
    DATE(created_at)       AS event_date,
    COUNT(*)               AS event_count,
    COUNT(DISTINCT customer_id) AS unique_customers
FROM {{ ref('stg_silver_events') }}
WHERE event_type = 'ticket'
GROUP BY 1, 2, 3, 4, 5
