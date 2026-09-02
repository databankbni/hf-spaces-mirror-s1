{{ config(materialized="table") }}

SELECT
    tenant_id,
    DATE_TRUNC('hour', CAST(created_at AS TIMESTAMP)) AS incident_hour,
    priority AS severity,
    COUNT(*)  AS incident_count,
    COUNT(DISTINCT customer_id) AS affected_customers
FROM {{ ref('stg_silver_events') }}
WHERE event_type = 'incident'
GROUP BY 1, 2, 3
