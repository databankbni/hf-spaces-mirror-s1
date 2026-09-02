{{ config(materialized="table") }}

SELECT
    tenant_id,
    customer_id,
    DATE(created_at) AS event_date,
    COUNT(*)         AS total_product_events,
    COUNT(DISTINCT DATE(created_at)) AS active_days
FROM {{ ref('stg_silver_events') }}
WHERE event_type = 'product_event'
GROUP BY 1, 2, 3
