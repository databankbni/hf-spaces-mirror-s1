{{ config(
    materialized="table",
    unique_key="customer_id || '|' || tenant_id || '|' || snapshot_date"
) }}

WITH tickets AS (
    SELECT
        customer_id,
        tenant_id,
        COUNT(*) AS open_ticket_count,
        AVG(CASE priority
            WHEN 'critical' THEN 4
            WHEN 'high'     THEN 3
            WHEN 'medium'   THEN 2
            ELSE 1 END) AS avg_priority_score,
        SUM(CASE WHEN priority IN ('critical','high') THEN 1 ELSE 0 END) AS high_priority_count
    FROM {{ ref('stg_silver_events') }}
    WHERE event_type = 'ticket'
      AND created_at >= CURRENT_DATE - INTERVAL '30' DAY
    GROUP BY 1, 2
),

billing AS (
    SELECT
        customer_id,
        tenant_id,
        COUNT(*) FILTER (WHERE body LIKE '%payment_failed%') AS payment_failures_30d,
        MAX(created_at) AS last_billing_event
    FROM {{ ref('stg_silver_events') }}
    WHERE event_type = 'billing_event'
      AND created_at >= CURRENT_DATE - INTERVAL '30' DAY
    GROUP BY 1, 2
),

product AS (
    SELECT
        customer_id,
        tenant_id,
        COUNT(*) AS product_events_30d
    FROM {{ ref('stg_silver_events') }}
    WHERE event_type = 'product_event'
      AND created_at >= CURRENT_DATE - INTERVAL '30' DAY
    GROUP BY 1, 2
)

SELECT
    COALESCE(t.customer_id, b.customer_id, p.customer_id) AS customer_id,
    COALESCE(t.tenant_id,   b.tenant_id,   p.tenant_id)   AS tenant_id,
    CURRENT_DATE                                            AS snapshot_date,
    COALESCE(t.open_ticket_count, 0)    AS open_tickets,
    COALESCE(t.avg_priority_score, 1.0) AS avg_priority,
    COALESCE(t.high_priority_count, 0)  AS high_priority_tickets,
    COALESCE(b.payment_failures_30d, 0) AS payment_failures_30d,
    b.last_billing_event,
    COALESCE(p.product_events_30d, 0)   AS product_events_30d
FROM tickets t
FULL OUTER JOIN billing b USING (customer_id, tenant_id)
FULL OUTER JOIN product  p USING (customer_id, tenant_id)
