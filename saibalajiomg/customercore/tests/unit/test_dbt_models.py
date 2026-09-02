import os
import duckdb
import pytest

DB_PATH = "src/dbt/customercore.duckdb"

@pytest.fixture(scope="module")
def db_conn():
    """Module-level fixture to establish a connection to the materialized DuckDB catalog."""
    assert os.path.exists(DB_PATH), f"DuckDB database file {DB_PATH} does not exist. Run dbt run first."
    conn = duckdb.connect(DB_PATH, read_only=True)
    yield conn
    conn.close()

def test_duckdb_schema_exists(db_conn):
    """Verify that the gold_gold schema was successfully created in the DuckDB database."""
    schemas = db_conn.execute("select schema_name from information_schema.schemata").df()
    schema_list = schemas["schema_name"].tolist()
    assert "gold_gold" in schema_list, f"gold_gold schema not found. Existing: {schema_list}"

@pytest.mark.parametrize("table_name, expected_columns", [
    ("customer_health_daily", ["customer_id", "tenant_id", "snapshot_date", "open_tickets", "avg_priority", "payment_failures_30d"]),
    ("ticket_funnel_daily", ["tenant_id", "event_type", "priority", "source", "event_date", "event_count", "unique_customers"]),
    ("incident_severity_hourly", ["tenant_id", "incident_hour", "severity", "incident_count", "affected_customers"]),
    ("billing_failure_summary", ["tenant_id", "event_date", "priority", "billing_event_count", "payment_failures", "cancellations"]),
    ("product_adoption_features", ["tenant_id", "customer_id", "event_date", "total_product_events", "active_days"]),
    ("retention_cohort_metrics", ["cohort_date", "tenant_id", "cohort_size", "retained_d7", "retained_d30"]),
    ("support_agent_performance", ["tenant_id", "source", "report_date", "priority", "tickets_created", "unique_customers_served", "avg_body_length"])
])
def test_gold_tables_materialization(db_conn, table_name, expected_columns):
    """Verify that all 7 Gold analytical tables exist, have correct columns, and contain rows."""
    # Check table existence and columns
    cols_df = db_conn.execute(f"select column_name from information_schema.columns where table_schema='gold_gold' and table_name='{table_name}'").df()
    columns_list = cols_df["column_name"].tolist()
    for col in expected_columns:
        assert col in columns_list, f"Column '{col}' not found in table 'gold_gold.{table_name}'. Found columns: {columns_list}"
    
    # Verify rows exist
    count = db_conn.execute(f"select count(*) from gold_gold.{table_name}").fetchone()[0]
    assert count > 0, f"Table 'gold_gold.{table_name}' has 0 rows. Expected populated table."
    print(f"Table 'gold_gold.{table_name}' contains {count} rows. Verification OK.")
