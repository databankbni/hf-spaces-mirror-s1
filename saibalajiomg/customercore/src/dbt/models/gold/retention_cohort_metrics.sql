{{ config(materialized="table") }}

WITH first_seen AS (
    SELECT
        customer_id,
        tenant_id,
        MIN(DATE(created_at)) AS cohort_date
    FROM {{ ref('stg_silver_events') }}
    WHERE customer_id IS NOT NULL
    GROUP BY 1, 2
),

activity AS (
    SELECT
        customer_id,
        tenant_id,
        DATE(created_at) AS active_date
    FROM {{ ref('stg_silver_events') }}
    WHERE customer_id IS NOT NULL
    GROUP BY 1, 2, 3
)

SELECT
    f.cohort_date,
    f.tenant_id,
    COUNT(DISTINCT f.customer_id) AS cohort_size,
    COUNT(DISTINCT CASE WHEN a.active_date <= f.cohort_date + INTERVAL '7' DAY
        THEN a.customer_id END) AS retained_d7,
    COUNT(DISTINCT CASE WHEN a.active_date <= f.cohort_date + INTERVAL '30' DAY
        THEN a.customer_id END) AS retained_d30
FROM first_seen f
LEFT JOIN activity a USING (customer_id, tenant_id)
GROUP BY 1, 2
