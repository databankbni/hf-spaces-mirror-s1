import sys
from pathlib import Path
from typing import Any

import os
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import networkx as nx
import pandas as pd
import requests
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.core.settings import settings



def get_api_base_url() -> str:
    env_url = os.getenv("DASHBOARD_API_URL")
    if env_url:
        return env_url.rstrip("/")
    return settings.dashboard_api_base_url.rstrip("/")


import os

def call_api(method: str, path: str, **kwargs):
    base = get_api_base_url()
    
    # Inject Hugging Face token to bypass shared-IP rate limits between spaces
    headers = kwargs.pop("headers", {})
    hf_token = os.getenv("HF_TOKEN")
    if hf_token:
        headers["Authorization"] = f"Bearer {hf_token}"
        
    response = requests.request(method, f"{base}{path}", timeout=120, headers=headers, **kwargs)
    if response.status_code == 429:
        raise requests.HTTPError(
            "429 Rate Limit: The Hugging Face API Space is temporarily throttled. "
            "Please wait ~60 seconds and try again. "
            "If the Autonomous Agent is running, stop it or increase its interval to ≥300s.",
            response=response,
        )
    if not response.ok:
        try:
            error_details = response.json()
            raise requests.HTTPError(f"{response.status_code} Error: {error_details}", response=response)
        except ValueError:
            response.raise_for_status()
    return response.json()


def render_pricing_metrics(data: dict) -> None:
    col1, col2, col3 = st.columns(3)
    col1.metric("Optimal Price", f"₹{data['optimal_price']:.2f}")
    col2.metric("Expected Demand", f"{data['expected_demand']:.2f}")
    col3.metric("Expected Profit", f"₹{data['expected_profit']:.2f}")
    # Strategy label (section 7.5.5)
    strategy = data.get("strategy", "")
    if strategy:
        st.info(f"🎯 **Selected Strategy:** {strategy}")


def build_default_scenarios(
    competitor_price: float,
    inventory: int,
    day_of_week: int,
    unit_cost: float,
    inventory_aware: bool = True,
) -> list[dict]:
    return [
        {
            "name": "Base Market",
            "competitor_price": competitor_price,
            "inventory": inventory,
            "day_of_week": day_of_week,
            "unit_cost": unit_cost,
            "inventory_aware": inventory_aware,
        },
        {
            "name": "Competitor Price Drop",
            "competitor_price": max(1.0, competitor_price * 0.9),
            "inventory": inventory,
            "day_of_week": day_of_week,
            "unit_cost": unit_cost,
            "inventory_aware": inventory_aware,
        },
        {
            "name": "Demand Surge",
            "competitor_price": competitor_price,
            "inventory": max(0, int(inventory * 0.55)),
            "day_of_week": 5,
            "unit_cost": unit_cost,
            "inventory_aware": inventory_aware,
        },
    ]


def render_analysis_report(data: dict) -> None:
    st.subheader("Performance Tracking")
    performance = data["performance"]
    metrics = st.columns(4)
    metrics[0].metric("Accuracy", f"{performance['prediction_accuracy_percent']:.1f}%")
    metrics[1].metric("RMSE", f"{performance['rmse']:.2f}")
    metrics[2].metric("MAE", f"{performance['mae']:.2f}")
    metrics[3].metric("Rows Scored", performance["rows_scored"])

    st.subheader("Bias & Drift Detection")
    drift = pd.DataFrame(data["drift"]["features"])
    drift_cols = st.columns(2)
    drift_cols[0].metric("Status", data["drift"]["status"].replace("_", " ").title())
    drift_cols[1].metric("Max Drift", f"{data['drift']['max_drift_score']:.1%}")
    st.bar_chart(drift, x="feature", y="drift_score")
    st.dataframe(drift, use_container_width=True, hide_index=True)

    st.subheader("A/B Testing")
    ab_summary = pd.DataFrame(
        [
            {"group": group, **values}
            for group, values in data["ab_summary"].get("groups", {}).items()
        ]
    )
    if ab_summary.empty:
        st.info("No A/B outcomes have been recorded yet.")
    else:
        st.bar_chart(ab_summary, x="group", y="mean_metric")
        st.dataframe(ab_summary, use_container_width=True, hide_index=True)

    st.subheader("What-if Analysis")
    scenarios = pd.DataFrame(data["what_if"]["scenarios"])
    if not scenarios.empty and "expected_profit_margin_percent" in scenarios.columns:
        st.metric("Average Profit Margin", f"{scenarios['expected_profit_margin_percent'].mean():.2f}%")
    st.line_chart(scenarios, x="scenario", y="expected_profit")
    st.dataframe(scenarios, use_container_width=True, hide_index=True)

    st.subheader("Causal Inference")
    causal = data["causal_effect"]
    causal_cols = st.columns(2)
    causal_cols[0].metric("Estimated Effect", f"{causal['estimated_effect']:.2f}")
    causal_cols[1].metric("R-squared", f"{causal['r_squared']:.2f}")


def build_analysis_report_fallback() -> dict:
    performance = call_api("GET", "/monitoring/performance")
    drift = call_api("GET", "/monitoring/drift")
    ab_summary = call_api("GET", "/admin/ab_summary", params={"experiment": "model_vs_static_pricing"})
    what_if = call_api(
        "POST",
        "/what_if/analyze",
        json={"scenarios": build_default_scenarios(115.0, 500, 0, 60.0, st.session_state.market.get("inventory_aware", True))},
    )
    causal_effect = call_api(
        "POST",
        "/causal_effect/estimate",
        json={
            "rows": [
                {"price_change": -10, "profit": 900, "inventory": 700},
                {"price_change": -5, "profit": 980, "inventory": 650},
                {"price_change": 0, "profit": 1040, "inventory": 620},
                {"price_change": 5, "profit": 1120, "inventory": 560},
                {"price_change": 10, "profit": 1080, "inventory": 520},
            ],
            "treatment_column": "price_change",
            "outcome_column": "profit",
            "control_columns": ["inventory"],
        },
    )

    return {
        "performance": performance,
        "drift": drift,
        "ab_summary": ab_summary,
        "what_if": what_if,
        "causal_effect": causal_effect,
    }


def load_analysis_report() -> dict:
    try:
        return call_api("GET", "/analysis/report")
    except requests.HTTPError as exc:
        status_code = getattr(exc.response, "status_code", None)
        if status_code == 404:
            return build_analysis_report_fallback()
        raise


def render_error_rate_report(window_seconds: int = 300) -> None:
    data = call_api("GET", "/monitoring/error_rate", params={"window_seconds": window_seconds, "bucket_seconds": 60})
    metrics = st.columns(4)
    metrics[0].metric("Requests (Window)", data["total_requests"])
    metrics[1].metric("Errors (Window)", data["total_errors"])
    metrics[2].metric("Error Rate", f"{data['error_rate_percent']:.2f}%")
    metrics[3].metric("Avg Latency", f"{data['average_latency_ms']:.1f} ms")

    series = pd.DataFrame(data.get("series", []))
    if not series.empty:
        st.line_chart(series, x="bucket_start", y=["requests", "errors", "error_rate_percent"])

    endpoints = pd.DataFrame(data.get("endpoints", []))
    if not endpoints.empty:
        st.dataframe(endpoints, use_container_width=True, hide_index=True)


def render_causal_dag(graph_str: str | None = None) -> None:
    """Display the pricing causal DAG dynamically using Graphviz."""
    if graph_str:
        st.graphviz_chart(graph_str, use_container_width=True)
    else:
        st.info("No causal graph available. Fit the model to generate one.")


def render_dashboard() -> None:
    st.set_page_config(page_title="Dynamic Pricing AI", page_icon="DP", layout="wide")

    if "market" not in st.session_state:
        st.session_state.market = {
            "product_id": 101,
            "current_price": 120.0,
            "competitor_price": 115.0,
            "inventory": 500,
            "day_of_week": 0,
            "unit_cost": 60.0,
            "inventory_aware": True
        }

    st.title("Dynamic Pricing AI")
    st.caption(f"FastAPI service: {get_api_base_url()}")

    with st.sidebar:
        st.header("Navigation")
        pages = ["Optimizer", "Elasticity", "RL Policy", "Monitoring", "Analysis", "Causal Analysis", "Experiments", "Autonomous Agent"]
        
        if "selected_page" not in st.session_state:
            st.session_state.selected_page = "Optimizer"
            
        for page in pages:
            is_active = (st.session_state.selected_page == page)
            if st.button(page, use_container_width=True, type="primary" if is_active else "secondary"):
                st.session_state.selected_page = page
                st.rerun()

    selected_page = st.session_state.selected_page

    mc = st.session_state.market
    product_id = mc["product_id"]
    current_price = mc["current_price"]
    competitor_price = mc["competitor_price"]
    inventory = mc["inventory"]
    day_of_week = mc["day_of_week"]
    unit_cost = mc["unit_cost"]

    pricing_payload = {
        "product_id": product_id,
        "current_price": current_price,
        "competitor_price": competitor_price,
        "inventory": inventory,
        "day_of_week": day_of_week,
        "unit_cost": unit_cost,
        "inventory_aware": mc.get("inventory_aware", True)
    }
    rl_payload = {
        "competitor_price": competitor_price,
        "inventory": inventory,
        "day_of_week": day_of_week,
        "unit_cost": unit_cost,
    }

    def update_market():
        if "_product_id" in st.session_state:
            st.session_state.market["product_id"] = st.session_state._product_id
        if "_current_price" in st.session_state:
            st.session_state.market["current_price"] = st.session_state._current_price
        if "_competitor_price" in st.session_state:
            st.session_state.market["competitor_price"] = st.session_state._competitor_price
        if "_inventory" in st.session_state:
            st.session_state.market["inventory"] = st.session_state._inventory
        if "_day_of_week" in st.session_state:
            st.session_state.market["day_of_week"] = st.session_state._day_of_week
        if "_unit_cost" in st.session_state:
            st.session_state.market["unit_cost"] = st.session_state._unit_cost
        if "_inventory_aware" in st.session_state:
            st.session_state.market["inventory_aware"] = st.session_state._inventory_aware

    if selected_page == "Optimizer":
        st.header("Market Context")
        
        # Initialize widget keys from the persistent market state if they were cleared
        if "_product_id" not in st.session_state:
            st.session_state._product_id = product_id
            st.session_state._current_price = current_price
            st.session_state._competitor_price = competitor_price
            st.session_state._inventory = inventory
            st.session_state._day_of_week = day_of_week
            st.session_state._unit_cost = unit_cost
            st.session_state._inventory_aware = st.session_state.market.get("inventory_aware", True)

        col1, col2, col3 = st.columns(3)
        col1.number_input("Product ID", min_value=1, step=1, key="_product_id", on_change=update_market)
        col2.number_input("Current Price", min_value=1.0, step=1.0, key="_current_price", on_change=update_market)
        col3.number_input("Competitor Price", min_value=1.0, step=1.0, key="_competitor_price", on_change=update_market)
        
        col4, col5, col6 = st.columns(3)
        col4.number_input("Inventory", min_value=0, step=10, key="_inventory", on_change=update_market)
        col5.selectbox(
            "Day of Week",
            options=[0, 1, 2, 3, 4, 5, 6],
            format_func=lambda x: ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][x],
            key="_day_of_week",
            on_change=update_market
        )
        col6.number_input("Unit Cost", min_value=0.0, step=1.0, key="_unit_cost", on_change=update_market)

        st.toggle(
            "Inventory-Aware Strategy (Clearance & Scarcity)", 
            value=st.session_state.market.get("inventory_aware", True), 
            key="_inventory_aware", 
            on_change=update_market,
            help="If enabled, the AI will sacrifice some profit margin to aggressively liquidate overstocked inventory, and raise prices to protect understocked inventory. If disabled, it strictly maximizes pure profit."
        )

        st.divider()

        # Overwrite payloads if a widget change just triggered a rerun, so we use the most up-to-date values!
        if "_current_price" in st.session_state:
            pricing_payload["current_price"] = float(st.session_state._current_price)
            pricing_payload["product_id"] = int(st.session_state._product_id)
            pricing_payload["competitor_price"] = float(st.session_state._competitor_price)
            pricing_payload["inventory"] = int(st.session_state._inventory)
            pricing_payload["day_of_week"] = int(st.session_state._day_of_week)
            pricing_payload["unit_cost"] = float(st.session_state._unit_cost)
            if "_inventory_aware" in st.session_state:
                pricing_payload["inventory_aware"] = st.session_state._inventory_aware

        if st.button("Calculate Optimal Price", type="primary"):
            try:
                data = call_api("POST", settings.dashboard_pricing_endpoint, json=pricing_payload)
                st.success("Optimal price computed")
                render_pricing_metrics(data)

                # Section 7.5.5 — Reinforcement Learning decision (where applicable)
                with st.expander("🤖 Reinforcement Learning Decision", expanded=True):
                    try:
                        rl_data = call_api("POST", "/rl_pricing", json=rl_payload)
                        rl_col1, rl_col2 = st.columns(2)
                        rl_col1.metric("RL Recommended Price", f"₹{rl_data['rl_price']:.2f}")
                        rl_col2.metric("RL Expected Profit", f"₹{rl_data['expected_profit']:.2f}")
                        st.caption(f"🧠 RL Strategy: {rl_data['strategy']}")
                    except requests.RequestException as rl_exc:
                        st.caption(f"RL agent not available: {rl_exc}")
            except requests.RequestException as exc:
                st.error(f"API request failed: {exc}")

    elif selected_page == "Elasticity":
        col1, col2, col3 = st.columns(3)
        min_price = col1.number_input("Minimum Price", min_value=1.0, value=80.0, step=5.0)
        max_price = col2.number_input("Maximum Price", min_value=1.0, value=180.0, step=5.0)
        price_points = col3.slider("Price Points", min_value=3, max_value=20, value=8)

        if st.button("Estimate Elasticity"):
            payload = {
                "price": current_price,
                "competitor_price": competitor_price,
                "inventory": inventory,
                "day_of_week": day_of_week,
                "price_points": price_points,
                "min_price": min_price,
                "max_price": max_price,
            }
            try:
                data = call_api("POST", "/estimate_elasticity_range", json=payload)
                curve = pd.DataFrame(data["elasticity_curve"])
                st.line_chart(curve, x="price", y="elasticity")
                st.dataframe(curve, use_container_width=True, hide_index=True)
            except requests.RequestException as exc:
                st.error(f"API request failed: {exc}")

    elif selected_page == "RL Policy":
        col1, col2 = st.columns(2)
        if col1.button("Get RL Recommendation"):
            try:
                data = call_api("POST", "/rl_pricing", json=rl_payload)
                col1.metric("RL Price", f"₹{data['rl_price']:.2f}")
                col1.metric("Expected Profit", f"₹{data['expected_profit']:.2f}")
                col1.caption(data["strategy"])
            except requests.RequestException as exc:
                st.error(f"API request failed: {exc}")

        st.subheader("Strategy Comparison")
        if st.button("Compare Traditional vs RL"):
            try:
                optimizer = call_api("POST", settings.dashboard_pricing_endpoint, json=pricing_payload)
                rl = call_api("POST", "/rl_pricing", json=rl_payload)
                comparison = pd.DataFrame(
                    [
                        {
                            "strategy": "Model Optimizer",
                            "price": optimizer["optimal_price"],
                            "expected_profit": optimizer["expected_profit"],
                        },
                        {
                            "strategy": "RL Policy",
                            "price": rl["rl_price"],
                            "expected_profit": rl["expected_profit"],
                        },
                    ]
                )
                metric_cols = st.columns(2)
                metric_cols[0].bar_chart(comparison, x="strategy", y="expected_profit")
                metric_cols[1].dataframe(comparison, use_container_width=True, hide_index=True)
            except requests.RequestException as exc:
                st.error(f"API request failed: {exc}")

        episodes = col2.slider("Training Episodes", min_value=1, max_value=100, value=5)
        if col2.button("Train RL Agent"):
            try:
                data = call_api("POST", "/rl_training", json={**rl_payload, "num_episodes": episodes})
                col2.metric("Episodes", data["episodes_completed"])
                col2.metric("Average Reward", f"₹{data['average_reward']:.2f}")
                col2.metric("Replay Buffer", data["buffer_size"])
            except requests.RequestException as exc:
                st.error(f"API request failed: {exc}")

    elif selected_page == "Monitoring":
        col1, col2 = st.columns(2)
        if col1.button("Refresh Performance", type="primary"):
            try:
                data = call_api("GET", "/monitoring/performance")
                metrics = st.columns(4)
                metrics[0].metric("Accuracy", f"{data['prediction_accuracy_percent']:.1f}%")
                metrics[1].metric("RMSE", f"{data['rmse']:.2f}")
                metrics[2].metric("MAE", f"{data['mae']:.2f}")
                metrics[3].metric("Rows Scored", data["rows_scored"])
            except requests.RequestException as exc:
                st.error(f"API request failed: {exc}")

        if col2.button("Check Drift"):
            try:
                data = call_api("GET", "/monitoring/drift")
                status = data["status"].replace("_", " ").title()
                col2.metric("Drift Status", status)
                col2.metric("Max Drift", f"{data['max_drift_score']:.1%}")
                drift = pd.DataFrame(data["features"])
                st.bar_chart(drift, x="feature", y="drift_score")
                st.dataframe(drift, use_container_width=True, hide_index=True)
            except requests.RequestException as exc:
                st.error(f"API request failed: {exc}")

        retrain_col1, retrain_col2 = st.columns(2)
        if retrain_col1.button("Check Retrain Need"):
            try:
                result = call_api("POST", "/monitoring/retrain_check")
                retrain_col1.write(result)
            except requests.RequestException as exc:
                st.error(f"API request failed: {exc}")
        if retrain_col2.button("Force Retrain"):
            try:
                result = call_api("POST", "/monitoring/retrain_check", params={"force": True})
                retrain_col2.write(result)
            except requests.RequestException as exc:
                st.error(f"API request failed: {exc}")

        st.subheader("What-if Analysis")
        inventory_aware = mc.get("inventory_aware", True)
        scenario_payload = {"scenarios": build_default_scenarios(competitor_price, inventory, day_of_week, unit_cost, inventory_aware)}
        if st.button("Run What-if Scenarios"):
            try:
                data = call_api("POST", "/what_if/analyze", json=scenario_payload)
                scenarios = pd.DataFrame(data["scenarios"])
                st.line_chart(scenarios, x="scenario", y="expected_profit")
                st.dataframe(scenarios, use_container_width=True, hide_index=True)
            except requests.RequestException as exc:
                st.error(f"API request failed: {exc}")

        with st.expander("Price Response Curve"):
            min_price = st.number_input("Curve Minimum Price", min_value=1.0, value=80.0, step=5.0)
            max_price = st.number_input("Curve Maximum Price", min_value=1.0, value=180.0, step=5.0)
            price_points = st.slider("Curve Points", min_value=5, max_value=50, value=20)
            if st.button("Plot Price Response"):
                try:
                    data = call_api(
                        "POST",
                        "/price_response_curve",
                        json={
                            **rl_payload,
                            "min_price": min_price,
                            "max_price": max_price,
                            "price_points": price_points,
                        },
                    )
                    curve = pd.DataFrame(data["curve"])
                    st.line_chart(curve, x="price", y=["expected_demand", "expected_profit"])
                    st.dataframe(curve, use_container_width=True, hide_index=True)
                except requests.RequestException as exc:
                    st.error(f"API request failed: {exc}")

    elif selected_page == "Analysis":
        st.caption("Performance tracking, drift monitoring, A/B summaries, what-if analysis, and causal inference in one view.")
        if st.button("Refresh Analysis Report", type="primary"):
            try:
                st.session_state["analysis_report"] = load_analysis_report()
            except requests.RequestException as exc:
                st.error(f"API request failed: {exc}")

        report = st.session_state.get("analysis_report")
        if report:
            render_analysis_report(report)
            st.subheader("Real-time Error Rate")
            try:
                render_error_rate_report(window_seconds=300)
            except requests.RequestException as exc:
                st.error(f"API request failed: {exc}")
        else:
            st.info("Click Refresh Analysis Report to load the full analysis view.")

    elif selected_page == "Causal Analysis":
        st.subheader("Causal Analysis via DoWhy")
        st.caption(
            "Estimates the **causal effect** of price changes on demand, controlling for "
            "competitor price, inventory, and day of week. Uses 3 refutation tests to "
            "validate the causal estimate is not spurious."
        )

        st.markdown("---")
        n_col, seed_col, btn_col = st.columns([2, 2, 1])
        n_samples = n_col.slider("Synthetic Samples", min_value=200, max_value=5000, value=2000, step=200)
        seed = seed_col.number_input("Random Seed", min_value=0, value=42, step=1)

        if btn_col.button("Fit Causal Model", type="primary"):
            with st.spinner("Fitting causal model and running refutations (may take ~20s)..."):
                try:
                    result = call_api("POST", "/causal/fit", params={"n_samples": n_samples, "seed": seed})
                    st.session_state["causal_result"] = result
                    st.success("Causal model fitted successfully!")
                except requests.RequestException as exc:
                    st.error(f"API error: {exc}")

        if st.button("Load Saved Summary"):
            try:
                result = call_api("GET", "/causal/summary")
                st.session_state["causal_result"] = result
            except requests.RequestException as exc:
                st.error(f"API error: {exc}")

        result = st.session_state.get("causal_result")
        if result and result.get("status") == "fitted":
            st.markdown("---")
            st.markdown("#### Dynamic Causal Graph (DAG)")
            render_causal_dag(result.get("causal_graph"))

            st.markdown("#### Average Treatment Effect (ATE)")
            ate_col, interp_col = st.columns([1, 3])
            ate_col.metric(
                label="ATE (demand / unit price)",
                value=f"{result['ate']:.4f}",
                help="A negative ATE means raising price reduces demand.",
            )
            interp_col.info(result["ate_interpretation"])

            all_passed = result.get("all_refutations_passed")
            if all_passed:
                st.success("All 3 refutation tests passed — the causal estimate is robust!")
            else:
                st.warning("One or more refutation tests failed — review results below.")

            st.markdown("#### Refutation Test Results")
            refutations = result.get("refutations", [])
            if refutations:
                ref_df = pd.DataFrame([
                    {
                        "Refuter": r["refuter"].replace("_", " ").title(),
                        "Original ATE": r["original_ate"],
                        "New ATE": r["new_ate"],
                        "Passed": "✅ PASS" if r["passed"] else ("⚠️ FAIL" if r["passed"] is False else "❓ N/A"),
                    }
                    for r in refutations
                ])
                st.dataframe(ref_df, use_container_width=True, hide_index=True)

                fig, ax = plt.subplots(figsize=(7, 3), facecolor="#0e1117")
                ax.set_facecolor("#0e1117")
                labels = [r["refuter"].replace("_refuter", "").replace("_", " ").title() for r in refutations]
                orig_vals = [r["original_ate"] if r["original_ate"] is not None else 0 for r in refutations]
                new_vals = [r["new_ate"] if r["new_ate"] is not None else 0 for r in refutations]
                x = range(len(labels))
                width = 0.35
                bars1 = ax.bar([i - width/2 for i in x], orig_vals, width, label="Original ATE", color="#4f8ef7", alpha=0.9)
                bars2 = ax.bar([i + width/2 for i in x], new_vals, width, label="New ATE", color="#e67e22", alpha=0.9)
                ax.set_xticks(list(x))
                ax.set_xticklabels(labels, color="white", fontsize=8)
                ax.tick_params(colors="white")
                ax.set_ylabel("ATE Value", color="white")
                ax.set_title("ATE: Original vs. Refuted", color="white", fontsize=11)
                ax.legend(facecolor="#1e2130", labelcolor="white", fontsize=8)
                ax.spines["bottom"].set_color("#444")
                ax.spines["left"].set_color("#444")
                ax.spines["top"].set_visible(False)
                ax.spines["right"].set_visible(False)
                st.pyplot(fig)
                plt.close(fig)

                st.markdown("#### Interpretation")
                for r in refutations:
                    st.markdown(f"**{r['refuter'].replace('_', ' ').title()}**: {r['interpretation']}")
        elif result and result.get("status") == "not_fitted":
            st.info("Click 'Fit Causal Model' to run the analysis.")

    elif selected_page == "Experiments":
        col1, col2 = st.columns(2)
        experiment = col1.text_input("Experiment", value="model_vs_static_pricing")
        subject_id = col2.text_input("Subject ID", value=f"product-{int(product_id)}")

        col1, col2, col3 = st.columns(3)
        if col1.button("Assign A/B Group"):
            try:
                data = call_api("POST", "/ab_test/assign", json={"experiment": experiment, "subject_id": subject_id})
                col1.metric("Assigned Group", data["group"])
            except requests.RequestException as exc:
                st.error(f"API request failed: {exc}")

        outcome_metric = col2.number_input("Outcome Metric", value=0.0, step=10.0)
        if col2.button("Record Outcome"):
            try:
                data = call_api(
                    "POST",
                    "/ab_test/outcome",
                    json={
                        "experiment": experiment,
                        "subject_id": subject_id,
                        "outcome": {"metric": outcome_metric},
                    },
                )
                col2.success(f"Recorded for {data['group']}")
            except requests.RequestException as exc:
                st.error(f"API request failed: {exc}")

        if col3.button("Load A/B Summary"):
            try:
                summary = call_api("GET", "/admin/ab_summary", params={"experiment": experiment})
                groups = pd.DataFrame(
                    [
                        {"group": group, **values}
                        for group, values in summary.get("groups", {}).items()
                    ]
                )
                if groups.empty:
                    col3.info("No outcomes recorded yet")
                else:
                    groups["mean_metric"] = groups["mean_metric"].fillna(0)
                    st.bar_chart(groups, x="group", y="mean_metric")
                    st.dataframe(groups, use_container_width=True, hide_index=True)
            except requests.RequestException as exc:
                st.error(f"API request failed: {exc}")

        st.subheader("Causal Effect")
        causal_rows = [
            {"price_change": -10, "profit": 900, "inventory": 700},
            {"price_change": -5, "profit": 980, "inventory": 650},
            {"price_change": 0, "profit": 1040, "inventory": 620},
            {"price_change": 5, "profit": 1120, "inventory": 560},
            {"price_change": 10, "profit": 1080, "inventory": 520},
        ]
        st.dataframe(pd.DataFrame(causal_rows), use_container_width=True, hide_index=True)
        if st.button("Estimate Price-change Effect"):
            try:
                data = call_api(
                    "POST",
                    "/causal_effect/estimate",
                    json={
                        "rows": causal_rows,
                        "treatment_column": "price_change",
                        "outcome_column": "profit",
                        "control_columns": ["inventory"],
                    },
                )
                st.metric("Estimated Effect On Profit", f"{data['estimated_effect']:.2f}")
                st.metric("R-squared", f"{data['r_squared']:.2f}")
            except requests.RequestException as exc:
                st.error(f"API request failed: {exc}")

    elif selected_page == "Autonomous Agent":
        col1, col2, col3 = st.columns(3)
        if col1.button("Start Agent"):
            try:
                st.success(call_api("POST", "/agent/start")["message"])
            except requests.RequestException as exc:
                st.error(f"API request failed: {exc}")
        if col2.button("Stop Agent"):
            try:
                st.info(call_api("POST", "/agent/stop")["message"])
            except requests.RequestException as exc:
                st.error(f"API request failed: {exc}")
        interval = col3.number_input("Interval Seconds", min_value=60.0, max_value=3600.0, value=300.0,
                                     help="Minimum 60s recommended on HF free tier (rate limit: 1000 req / 5 min)")
        if col3.button("Set Interval"):
            try:
                data = call_api("POST", "/agent/interval", params={"seconds": interval})
                st.success(f"Interval set to {data['interval_seconds']:.1f}s")
            except requests.RequestException as exc:
                st.error(f"API request failed: {exc}")

        if st.button("Refresh Agent Status", type="primary"):
            try:
                status = call_api("GET", "/agent/status")
                metric_cols = st.columns(4)
                metric_cols[0].metric("Running", "Yes" if status["running"] else "No")
                metric_cols[1].metric("Cycles", status["cycles_completed"])
                metric_cols[2].metric("Average Reward", f"₹{status['average_reward']:.2f}")
                metric_cols[3].metric("History", status["history_size"])
                if status["last_decision"]:
                    st.dataframe(pd.DataFrame([status["last_decision"]]), use_container_width=True, hide_index=True)
            except requests.RequestException as exc:
                st.error(f"API request failed: {exc}")

        with st.expander("Recent Decisions"):
            history_limit = st.slider("History Limit", min_value=1, max_value=100, value=20)
            if st.button("Load History"):
                try:
                    history = call_api("GET", "/agent/history", params={"limit": history_limit})
                    st.dataframe(pd.DataFrame(history), use_container_width=True, hide_index=True)
                except requests.RequestException as exc:
                    st.error(f"API request failed: {exc}")

        st.subheader("RL Policy State")
        if st.button("Refresh Policy Info"):
            try:
                info = call_api("GET", "/agent/policy_info")
                p_cols = st.columns(3)
                p_cols[0].metric("Q-Table States", info.get("policy_size", "N/A"))
                p_cols[1].metric("Replay Buffer", info.get("replay_buffer_size", "N/A"))
                p_cols[2].metric("Last Saved", info.get("last_saved_at") or "Not yet saved")
                st.caption(f"Policy file: {info.get('policy_path', '')}")
            except requests.RequestException as exc:
                st.error(f"API request failed: {exc}")


if __name__ == "__main__":
    render_dashboard()
