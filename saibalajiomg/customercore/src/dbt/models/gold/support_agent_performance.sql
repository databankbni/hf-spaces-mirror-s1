{{ config(materialized="table") }}

SELECT
    tenant_id,
    source,
    DATE(created_at)  AS report_date,
    priority,
    COUNT(*)          AS tickets_created,
    COUNT(DISTINCT customer_id) AS unique_customers_served,
    AVG(LENGTH(body)) AS avg_body_length
FROM {{ ref('stg_silver_events') }}
WHERE event_type = 'ticket'
GROUP BY 1, 2, 3, 4
