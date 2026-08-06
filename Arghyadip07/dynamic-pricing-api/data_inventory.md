# Data Inventory for Production-Focused Dynamic Pricing

This document lists the recommended data sources, required fields, frequency, and ownership for implementing the production-focused dynamic pricing ideas (capacity-aware pricing, supply volatility, B2B personalization, expiry-based pricing, and energy-driven pricing).

## 1. Factory / Capacity Signals (MES / SCADA)
- Examples: machine utilization, throughput, OEE, queue lengths, planned maintenance windows, machine health alerts
- Fields: `timestamp`, `machine_id`, `line_id`, `utilization_pct`, `throughput_units_per_min`, `oee_pct`, `maintenance_flag`, `predicted_downtime_minutes`
- Frequency: 1s–5m (aggregation to 1m / 5m for ML pipelines)
- Owner: Manufacturing / MES team

## 2. Production Orders & Inventory (ERP / WMS)
- Examples: open orders, scheduled runs, finished goods inventory by batch
- Fields: `order_id`, `product_id`, `batch_id`, `quantity`, `due_date`, `unit_cost`, `inventory_location`, `shelf_life_days`, `manufacture_date`
- Frequency: event-driven (order create/update) + nightly sync
- Owner: Production Planning / Inventory

## 3. Raw Material & Supplier Data (Procurement)
- Examples: spot prices, supplier lead time, contract prices, FX rates, order fill rates
- Fields: `material_id`, `timestamp`, `spot_price`, `contract_price`, `lead_time_days`, `supplier_id`, `price_source`
- Frequency: hourly / daily for commodities; event-driven for supplier updates
- Owner: Procurement

## 4. Energy & Grid Signals
- Examples: real-time energy price, TOU (time-of-use) windows, carbon intensity, renewable availability
- Fields: `timestamp`, `region`, `price_per_kwh`, `carbon_intensity`, `grid_load_pct`
- Frequency: 5m–hourly
- Owner: Facilities / Energy Manager

## 5. Market & Competitor Signals
- Examples: competitor prices (scrapers / partner feeds), market demand indices, macroeconomic indicators
- Fields: `product_id`, `timestamp`, `competitor_price`, `source`, `confidence`
- Frequency: minutes–daily depending on source
- Owner: Pricing / Intelligence

## 6. Sales & Contract History (CRM / ERP)
- Examples: historical orders, negotiated contracts, churn/retention, payment terms
- Fields: `customer_id`, `order_id`, `product_id`, `price_paid`, `discount`, `volume`, `contract_terms`
- Frequency: event-driven + nightly sync
- Owner: Sales / Finance

## 7. Quality & Cold-Chain Sensors (Perishables)
- Examples: temperature logs, humidity, shock/vibration per batch
- Fields: `batch_id`, `timestamp`, `sensor_type`, `value`, `anomaly_flag`
- Frequency: seconds–minutes
- Owner: Quality / Operations

## 8. Derived / Engineered Features
- Inventory age per batch, predicted fill rate, predicted supplier lead time, forecasted raw-material quantiles, estimated carbon-per-unit, expected overtime cost
- Where produced: feature store (recommended)

## Integration & Infrastructure Notes
- Ingest using event-driven pipelines (Kafka/CloudPubSub) where possible; batch-sync via ETL for legacy systems.
- Store raw events in a landing zone (S3 / blob storage) and produce cleaned tables in a centralized data warehouse / feature store.
- Include provenance metadata and dataset versioning (who/when/source) for governance and model explainability.

## Privacy & Compliance
- Access control on customer/contract data. Mask PII where models don't require identifiers.

## Next steps
1. Map concrete endpoints for each source (MES API, ERP DB schema, supplier API list).  
2. Create an ingestion plan and a minimal schema for a feature store.  
3. Prototype a small simulator that consumes the most important signals (capacity, unit cost, demand elasticity).  
