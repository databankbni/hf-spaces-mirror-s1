"""
LangGraph Orchestrator for Saras Client Onboarding (Multi-Env)
==============================================================
Runs the full onboarding pipeline: account creation -> email verification ->
token retrieval -> role assignment -> GCS upload -> warehouse creation.

Usage:
  python onboard_client.py --env dev --first John --last Doe --email john@example.com --company Acme --project-id my-project --dataset my_dataset
  python onboard_client.py --env dev  # interactive mode
  python onboard_client.py  # fully interactive
"""

import sys
import argparse
from typing import TypedDict, Optional
from langgraph.graph import StateGraph, START, END

from env_config import get_config, add_env_arg
from step1_create_account import create_account
# step2 uses playwright/greenlet — lazy-import to avoid DLL issues when skipping email
# from step2_verify_email import verify_and_set_password
from step3_get_token import get_auth_token, set_manual_token
from step4_assign_roles import assign_roles, verify_user_exists
from gcs_upload import upload_directory
from create_warehouse_api import create_warehouse
from create_warehouse_api import create_warehouse


class OnboardingState(TypedDict):
    env: str
    first_name: str
    last_name: str
    email: str
    company_name: str
    product_type: str
    revenue: str
    password: str
    project_id: str
    dataset: str
    logic_dir: Optional[str]
    yaml_dir: Optional[str]
    super_admin_token: Optional[str]

    # Generated values
    user_id: Optional[int]
    company_id: Optional[str]
    auth_token: Optional[str]       # Super admin token (for roles, user lookup)
    user_token: Optional[str]       # New user's token (for warehouse creation)
    errors: list[str]


def format_error(state: OnboardingState, step: str, error: str) -> OnboardingState:
    state["errors"].append(f"[{step}] {error}")
    print(f"\n  Error in {step}: {error}")
    return state


def node_create_account(state: OnboardingState):
    print("\n[Node: Create Account] Executing...")
    result = create_account(
        first_name=state["first_name"],
        last_name=state["last_name"],
        email=state["email"],
        company=state["company_name"],
        revenue=state["revenue"],
        product=state["product_type"],
        env=state["env"],
    )
    if result.get("success"):
        state["user_id"] = result.get("user_id")
        print(f"  Account Created: User ID {state['user_id']}")
    else:
        state = format_error(state, "Create Account", result.get("error"))
    return state


def node_verify_email(state: OnboardingState):
    if state["errors"]:
        return state

    print("\n[Node: Wait for User Setup] Executing...")
    print(f"  Waiting up to 10 minutes for {state['email']} to click the email link and set their password...")
    
    import time
    from step3_get_token import get_auth_token
    
    max_attempts = 60  # 60 attempts * 10 seconds = 10 minutes (600 seconds)
    
    for attempt in range(1, max_attempts + 1):
        # Physically attempt to log in to Firebase using the credentials provided in the UI
        auth_result = get_auth_token(state["email"], state["password"], env=state["env"])
        
        if auth_result.get("success"):
            print(f"\n  [SUCCESS] Login successful! User has verified their email and set their password.")
            
            # Since we just logged in, we can instantly cache their Token and IDs for the Warehouse step!
            state["user_token"] = auth_result.get("id_token")
            
            # Optionally update user_id / company_id if they were missing
            if not state.get("user_id") and auth_result.get("user_id"):
                state["user_id"] = auth_result.get("user_id")
            if not state.get("company_id") and auth_result.get("company_id"):
                state["company_id"] = str(auth_result.get("company_id"))
                
            return state
            
        else:
            # Login failed. They haven't set it yet.
            print(f"  [Attempt {attempt}/{max_attempts}] Not verified yet. Waiting 10 seconds...")
            time.sleep(10)
            
    # If the 10 minutes completely expire
    return format_error(state, "Wait User Setup", "User did not set their password within the 10-minute timeout window.")


def node_get_token(state: OnboardingState):
    """
    Get super admin token, then lookup the NEW user's real company_id
    via GET /user/{userId}. This avoids using the admin's company_id.

    - DEV: Firebase REST API (auto, we have the key)
    - TEST/PROD: Playwright browser login OR pre-cached manual token
    """
    if state["errors"]:
        return state
    print("\n[Node: Get Admin Token & Lookup User] Executing...")
    cfg = get_config(state["env"])

    if not cfg.REQUIRES_MANUAL_TOKEN:
        # DEV/TEST: Firebase auto-login
        auth_result = get_auth_token(
            cfg.SUPER_ADMIN_EMAIL, cfg.SUPER_ADMIN_PASSWORD, env=state["env"]
        )
    else:
        # PROD: Use pre-cached token if provided at startup, else throw error
        if state.get("super_admin_token"):
            print(f"  Using pre-cached admin token")
            auth_result = {"success": True, "id_token": state["super_admin_token"]}
        else:
            return format_error(state, "Get Admin Token", "Super Admin token is required for PROD but none was provided. Browser login is deprecated.")

    if not auth_result.get("success"):
        return format_error(state, "Get Admin Token", auth_result.get("error"))

    state["auth_token"] = auth_result.get("id_token")
    admin_token = state["auth_token"]
    print(f"  [Admin Token Captured]: {str(admin_token)[:40]}...[TRUNCATED]")
    print("  -> Going to use this token to authenticate with User API and assign IQ Admin roles.")

    # Now lookup the NEW user to get their real company_id
    if state.get("user_id"):
        print(f"  Looking up User {state['user_id']} to get real company_id...")
        lookup = verify_user_exists(state["user_id"], admin_token, env=state["env"])
        if lookup.get("success"):
            user_data = lookup["user"]
            real_company_id = user_data.get("companyId") or user_data.get("company_id") or user_data.get("company", {}).get("companyId")
            if real_company_id:
                state["company_id"] = real_company_id
                print(f"  User's Company ID: {state['company_id']}")
            else:
                print(f"  Warning: User data did not contain companyId. Data: {user_data}")
        else:
            print(f"  Warning: Could not lookup user: {lookup.get('error')}")

    if not state.get("company_id"):
        print(f"  Warning: company_id still unknown — GCS upload may fail.")

    return state


def node_assign_roles(state: OnboardingState):
    if state["errors"] or not state.get("user_id"):
        return state
    print("\n[Node: Assign Roles] Executing via Super Admin...")
    p_type = "IQ" if "iq" in state["product_type"].lower() else "DATON"

    # Check company mismatch
    admin_company = state.get("auth_token_company_id", "1585")  # Default to dev super admin's company
    user_company = state.get("company_id")
    if user_company and admin_company != user_company:
        print(f"[Node: Assign Roles] ⚠️  COMPANY MISMATCH DETECTED!")
        print(f"  - Super Admin Company: {admin_company}")
        print(f"  - New User Company: {user_company}")
        print(f"  - The super admin may not have cross-company permissions!")

    roles_to_assign = ["iq admin"]

    result = assign_roles(
        user_id=state["user_id"],
        role_names=roles_to_assign,
        product_type=p_type,
        env=state["env"],
    )

    if result.get("success"):
        print(f"  Roles assigned successfully.")
    else:
        print(f"[Node: Assign Roles] Role name lookup failed, trying direct role ID 37 as fallback...")
        # Fallback: Try direct role ID 37 (IQ Admin for dev/test)
        result = assign_roles_by_id(
            user_id=state["user_id"],
            role_ids=[37],
            product_type=p_type,
            env=state["env"],
        )
        if result.get("success"):
            print(f"  ✅ Roles assigned successfully via fallback ID!")
            print(f"  User {state['user_id']} now has IQ Admin role (ID 37)")
        else:
            print(f"[Node: Assign Roles] ⚠️  WARNING: Role assignment failed")
            print(f"  Error: {result.get('error')}")
            print(f"  Status: The account was created successfully.")
            print(f"  Next Step: You can assign roles manually using the Swagger UI")
            print(f"  Endpoint: PUT /support/add-any-user-roles")
            print(f"  Role ID 37 = IQ Admin")

    return state


# (node_get_user_token removed since we fetch it natively inside the 10-minute wait loop)


def _validate_token_basic(token: str) -> tuple:
    """Validate a JWT token (basic — no admin claims required)."""
    import json
    import base64
    import time

    try:
        parts = token.split(".")
        if len(parts) != 3:
            return False, {"error": f"Not a valid JWT (expected 3 parts, got {len(parts)})"}

        payload_b64 = parts[1]
        padding = 4 - len(payload_b64) % 4
        if padding != 4:
            payload_b64 += "=" * padding
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))

        exp = payload.get("exp", 0)
        now = time.time()
        expires_in_sec = exp - now

        if expires_in_sec <= 0:
            mins_ago = int(abs(expires_in_sec) / 60)
            return False, {"error": f"Token expired {mins_ago} minutes ago. Please get a fresh one."}

        return True, {
            "name": payload.get("name", "Unknown"),
            "email": payload.get("email", "Unknown"),
            "user_id": payload.get("userId"),
            "company_id": payload.get("companyId"),
            "expires_in_min": int(expires_in_sec / 60),
        }

    except Exception as e:
        return False, {"error": f"Could not decode token: {e}"}


def node_upload_gcs(state: OnboardingState):
    if state["errors"] or not state.get("company_id"):
        return state
    print("\n[Node: Upload GCS] Executing...")
    cfg = get_config(state["env"])
    company_id = str(state["company_id"])
    success = True

    if not state.get("logic_dir") and not state.get("yaml_dir"):
        print("  -> SKIPPED: No local directories provided for Business Logic or YAMLs.")

    if state.get("logic_dir"):
        print(f"  -> Uploading logic from {state['logic_dir']}")
        if not upload_directory(company_id, state["logic_dir"], f"{cfg.GCS_BASE_PATH}/company_business_logic", env=state["env"]):
            success = False

    if state.get("yaml_dir"):
        print(f"  -> Uploading yamls from {state['yaml_dir']}")
        if not upload_directory(company_id, state["yaml_dir"], f"{cfg.GCS_BASE_PATH}/company_yamls", env=state["env"]):
            success = False

    if success:
        print("  Completed GCS upload")
    return state


def node_create_warehouse(state: OnboardingState):
    if state["errors"]:
        return state
    if not state.get("auth_token"):
        return format_error(state, "Create Warehouse", "No admin token available — cannot create warehouse")
    if not state.get("company_id"):
        return format_error(state, "Create Warehouse", "No company_id available — cannot create warehouse")
    print("\n[Node: Create Warehouse] Executing...")
    result = create_warehouse(
        company_id=state["company_id"],
        admin_token=state["auth_token"],       # Use ADMIN's token for company warehouse creation
        company_name=state["company_name"],
        project_id=state["project_id"],
        dataset=state["dataset"],
        env=state["env"],
    )
    if result:
        print("  Company Warehouse Created")
    else:
        state = format_error(state, "Create Warehouse", "Failed to create company warehouse")
    return state


def build_workflow():
    workflow = StateGraph(OnboardingState)

    workflow.add_node("account", node_create_account)
    workflow.add_node("email", node_verify_email)
    workflow.add_node("token", node_get_token)
    workflow.add_node("roles", node_assign_roles)
    workflow.add_node("gcs", node_upload_gcs)
    workflow.add_node("warehouse", node_create_warehouse)

    workflow.add_edge(START, "account")
    workflow.add_edge("account", "email")
    workflow.add_edge("email", "token")
    workflow.add_edge("token", "roles")
    workflow.add_edge("roles", "gcs")
    workflow.add_edge("gcs", "warehouse")
    workflow.add_edge("warehouse", END)

    return workflow.compile()




def _validate_token(token: str) -> tuple:
    """
    Validate a JWT token: check it decodes, isn't expired, has admin claims.
    Returns (is_valid: bool, info: dict).
    """
    import json
    import base64
    import time

    try:
        parts = token.split(".")
        if len(parts) != 3:
            return False, {"error": "Not a valid JWT (expected 3 parts, got {})".format(len(parts))}

        payload_b64 = parts[1]
        padding = 4 - len(payload_b64) % 4
        if padding != 4:
            payload_b64 += "=" * padding
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))

        # Check expiration
        exp = payload.get("exp", 0)
        now = time.time()
        expires_in_sec = exp - now

        if expires_in_sec <= 0:
            mins_ago = int(abs(expires_in_sec) / 60)
            return False, {"error": f"Token expired {mins_ago} minutes ago. Please get a fresh one."}

        # Check admin claims
        claims = payload.get("saras_claims", [])
        has_admin = any(c in claims for c in ["SarasAdmin", "IQAdmin"])

        if not has_admin:
            return False, {"error": f"Token does not have admin claims. Found: {claims}. Need SarasAdmin or IQAdmin."}

        return True, {
            "name": payload.get("name", "Unknown"),
            "email": payload.get("email", "Unknown"),
            "claims": claims,
            "user_id": payload.get("userId"),
            "company_id": payload.get("companyId"),
            "expires_in_min": int(expires_in_sec / 60),
        }

    except Exception as e:
        return False, {"error": f"Could not decode token: {e}"}


def collect_inputs_interactive(args):
    """Collect all inputs upfront before running the workflow."""
    from env_config import ENVIRONMENTS

    # ── 1. Environment (always first) ────────────────────────────────
    if not args.env:
        env_list = list(ENVIRONMENTS.keys())
        print("\n" + "=" * 60)
        print("  Saras Client Onboarding - Environment Selection")
        print("=" * 60)
        for i, env_name in enumerate(env_list, 1):
            print(f"  {i}. {env_name.upper()}")
        choice = input(f"\nSelect environment (1-{len(env_list)}): ").strip()
        try:
            args.env = env_list[int(choice) - 1]
        except (ValueError, IndexError):
            args.env = env_list[0]
            print(f"  Defaulting to: {args.env}")

    cfg = get_config(args.env)

    # ── 2. All company & project details ─────────────────────────────
    print(f"\n{'=' * 60}")
    print(f"  [{cfg.env_name.upper()}] Enter Client Onboarding Details")
    print(f"{'=' * 60}\n")

    print("-- Company Details --")
    args.first = args.first or input("  First Name           : ").strip()
    args.last = args.last or input("  Last Name            : ").strip()
    args.email = args.email or input("  Work Email           : ").strip()
    args.company = args.company or input("  Company Name         : ").strip()

    if not args.product:
        print("\n  Product Options:")
        print("    1. Saras IQ")
        print("    2. Saras Pulse")
        print("    3. Saras Daton")
        print("    4. Other")
        prod_choice = input("  Select product (1-4) [1]: ").strip() or "1"
        product_map = {"1": "Saras IQ", "2": "Saras Pulse", "3": "Saras Daton", "4": "Other"}
        args.product = product_map.get(prod_choice, "Saras IQ")

    if not args.revenue:
        print("\n  Revenue Options:")
        print("    1. <$15M")
        print("    2. $15-50M")
        print("    3. $50-100M")
        print("    4. $100-200M")
        print("    5. $200M+")
        rev_choice = input("  Select revenue (1-5) [1]: ").strip() or "1"
        revenue_map = {"1": "<$15M", "2": "$15-50M", "3": "$50-100M", "4": "$100-200M", "5": "$200M+"}
        args.revenue = revenue_map.get(rev_choice, "<$15M")

    print("\n-- Warehouse / BigQuery Details --")
    args.project_id = args.project_id or input("  GCP Project ID       : ").strip()
    args.dataset = args.dataset or input("  BigQuery Dataset ID  : ").strip()

    print("\n-- Account Security --")
    if not getattr(args, "password", None):
        pw_input = input(f"  New User Password    [{cfg.DEFAULT_PASSWORD}]: ").strip()
        args.password = pw_input if pw_input else cfg.DEFAULT_PASSWORD

    print("\n-- File Uploads (optional) --")
    args.logic_dir = args.logic_dir or input("  Business Logic Dir   (Enter to skip): ").strip() or None
    args.yaml_dir = args.yaml_dir or input("  Company YAML Dir     (Enter to skip): ").strip() or None

    # ── 3. Confirm before executing ──────────────────────────────────
    print(f"\n{'=' * 60}")
    print(f"  Review - Onboarding [{cfg.env_name.upper()}]")
    print(f"{'=' * 60}")
    print(f"  Environment      : {cfg.env_name.upper()}")
    print(f"  Name             : {args.first} {args.last}")
    print(f"  Email            : {args.email}")
    print(f"  Company          : {args.company}")
    print(f"  Product          : {args.product}")
    print(f"  Revenue          : {args.revenue}")
    print(f"  GCP Project ID   : {args.project_id}")
    print(f"  BigQuery Dataset : {args.dataset}")
    print(f"  Business Logic   : {args.logic_dir or '(none)'}")
    print(f"  Company YAMLs    : {args.yaml_dir or '(none)'}")
    print(f"  Authentication   : {'Automated via Browser' if cfg.REQUIRES_MANUAL_TOKEN else 'Fully Automated via Firebase (No GUI)'}")
    print(f"  Password         : {args.password}")
    print(f"{'=' * 60}")

    confirm = input("\n  Proceed with onboarding? (Y/n): ").strip().lower()
    if confirm in ("n", "no"):
        print("\n  Aborted by user.")
        sys.exit(0)

    return args, cfg


def main():
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="LangGraph Orchestrator for Saras Client Onboarding (Multi-Env)")
    add_env_arg(parser)

    parser.add_argument("--first", help="First Name")
    parser.add_argument("--last", help="Last Name")
    parser.add_argument("--password", help="New User Password")
    parser.add_argument("--email", help="Work Email")
    parser.add_argument("--company", help="Company Name")
    parser.add_argument("--product", help="Product (e.g. Saras IQ)")
    parser.add_argument("--revenue", help="Revenue Bracket")
    parser.add_argument("--project-id", help="GCP Project ID")
    parser.add_argument("--dataset", help="BigQuery Dataset")
    parser.add_argument("--logic-dir", help="Path to local business logic files")
    parser.add_argument("--yaml-dir", help="Path to local yaml files")

    args = parser.parse_args()

    # If all required args provided via CLI, use them directly; otherwise go interactive
    all_provided = args.env and args.first and args.last and args.email and args.company and args.project_id and args.dataset
    if all_provided:
        cfg = get_config(args.env)
    else:
        args, cfg = collect_inputs_interactive(args)

    env_name = args.env or "dev"
    super_admin_token = getattr(args, 'super_admin_token', None)

    # Pre-cache the manual token so step3/step4/warehouse won't ask again
    if super_admin_token:
        set_manual_token(env_name, super_admin_token)

    initial_state = OnboardingState(
        env=env_name,
        first_name=args.first,
        last_name=args.last,
        email=args.email,
        company_name=args.company,
        product_type=args.product or "Saras IQ",
        revenue=args.revenue or "<$15M",
        password=args.password,
        project_id=args.project_id,
        dataset=args.dataset,
        logic_dir=args.logic_dir,
        yaml_dir=args.yaml_dir,
        super_admin_token=super_admin_token,
        user_id=None,
        company_id=None,
        auth_token=None,
        user_token=None,
        errors=[],
    )

    print("\n" + "=" * 60)
    print(f"  Starting Onboarding Workflow [{cfg.env_name.upper()}]")
    print("=" * 60)

    app = build_workflow()
    final_state = app.invoke(initial_state)

    print("\n" + "=" * 60)
    print("  Onboarding Summary")
    print("=" * 60)
    print(f"  Environment : {cfg.env_name.upper()}")
    print(f"  Company     : {final_state['company_name']}")
    print(f"  Email       : {final_state['email']}")
    print(f"  User ID     : {final_state.get('user_id')}")
    print(f"  Company ID  : {final_state.get('company_id')}")
    print(f"  Project ID  : {final_state['project_id']}")
    print(f"  Dataset     : {final_state['dataset']}")

    if final_state["errors"]:
        print("\n  Completed with Errors:")
        for err in final_state["errors"]:
            print(f"  - {err}")
    else:
        print("\n  Onboarding fully successful!")


if __name__ == "__main__":
    main()
