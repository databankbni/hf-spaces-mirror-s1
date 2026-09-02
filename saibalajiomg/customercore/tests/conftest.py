import pytest
import os
import duckdb

def init_mock_duckdb():
    db_path = "src/dbt/customercore.duckdb"
    if os.path.exists(db_path):
        print(f"[CI/CD Setup] Using existing DuckDB database at: {db_path}")
        return
    
    print(f"[CI/CD Setup] Creating mock DuckDB database file at: {db_path}...")
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = duckdb.connect(db_path)
    
    print("[CI/CD Setup] Creating schema 'gold_gold'...")
    conn.execute("CREATE SCHEMA IF NOT EXISTS gold_gold")
    
    # customer_health_daily
    conn.execute("""
        CREATE TABLE gold_gold.customer_health_daily (
            customer_id VARCHAR,
            tenant_id VARCHAR,
            snapshot_date TIMESTAMP,
            open_tickets INTEGER,
            avg_priority DOUBLE,
            payment_failures_30d INTEGER
        )
    """)
    conn.execute("""
        INSERT INTO gold_gold.customer_health_daily VALUES
        ('c1', 'tenant1', '2026-05-27 12:00:00', 1, 2.5, 0)
    """)
    
    # ticket_funnel_daily
    conn.execute("""
        CREATE TABLE gold_gold.ticket_funnel_daily (
            tenant_id VARCHAR,
            event_type VARCHAR,
            priority VARCHAR,
            source VARCHAR,
            event_date TIMESTAMP,
            event_count INTEGER,
            unique_customers INTEGER
        )
    """)
    conn.execute("""
        INSERT INTO gold_gold.ticket_funnel_daily VALUES
        ('tenant1', 'type1', 'high', 'email', '2026-05-27 12:00:00', 5, 2)
    """)
    
    # incident_severity_hourly
    conn.execute("""
        CREATE TABLE gold_gold.incident_severity_hourly (
            tenant_id VARCHAR,
            incident_hour INTEGER,
            severity VARCHAR,
            incident_count INTEGER,
            affected_customers INTEGER
        )
    """)
    conn.execute("""
        INSERT INTO gold_gold.incident_severity_hourly VALUES
        ('tenant1', 14, 'critical', 1, 100)
    """)
    
    # billing_failure_summary
    conn.execute("""
        CREATE TABLE gold_gold.billing_failure_summary (
            tenant_id VARCHAR,
            event_date TIMESTAMP,
            priority VARCHAR,
            billing_event_count INTEGER,
            payment_failures INTEGER,
            cancellations INTEGER
        )
    """)
    conn.execute("""
        INSERT INTO gold_gold.billing_failure_summary VALUES
        ('tenant1', '2026-05-27 12:00:00', 'high', 3, 2, 1)
    """)
    
    # product_adoption_features
    conn.execute("""
        CREATE TABLE gold_gold.product_adoption_features (
            tenant_id VARCHAR,
            customer_id VARCHAR,
            event_date TIMESTAMP,
            total_product_events INTEGER,
            active_days INTEGER
        )
    """)
    conn.execute("""
        INSERT INTO gold_gold.product_adoption_features VALUES
        ('tenant1', 'c1', '2026-05-27 12:00:00', 15, 3)
    """)
    
    # retention_cohort_metrics
    conn.execute("""
        CREATE TABLE gold_gold.retention_cohort_metrics (
            cohort_date TIMESTAMP,
            tenant_id VARCHAR,
            cohort_size INTEGER,
            retained_d7 INTEGER,
            retained_d30 INTEGER
        )
    """)
    conn.execute("""
        INSERT INTO gold_gold.retention_cohort_metrics VALUES
        ('2026-05-27 12:00:00', 'tenant1', 50, 40, 25)
    """)
    
    # support_agent_performance
    conn.execute("""
        CREATE TABLE gold_gold.support_agent_performance (
            tenant_id VARCHAR,
            source VARCHAR,
            report_date TIMESTAMP,
            priority VARCHAR,
            tickets_created INTEGER,
            unique_customers_served INTEGER,
            avg_body_length DOUBLE
        )
    """)
    conn.execute("""
        INSERT INTO gold_gold.support_agent_performance VALUES
        ('tenant1', 'email', '2026-05-27 12:00:00', 'high', 10, 8, 120.5)
    """)
    
    print("[CI/CD Setup] Mock DuckDB database created successfully.")
    conn.close()

# Run initialization before tests run
init_mock_duckdb()

@pytest.fixture(autouse=True)
def set_test_env_vars():
    os.environ["APP_ENV"] = "test"
    os.environ["LITELLM_MASTER_KEY"] = "sk-test"
    yield
