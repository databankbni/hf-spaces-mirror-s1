"""
Standalone Warehouse Creation
=============================
Creates a BigQuery warehouse via the IQ API.

Usage:
  python standalone_create_warehouse.py --env dev --email demo+test@sarasanalytics.com --company-name "TestCo" --project-id my-gcp-project --dataset my_dataset
"""

import sys
import argparse
import requests

from env_config import get_config, add_env_arg
from step3_get_token import get_auth_token


def create_warehouse(
    email: str,
    password: str,
    company_name: str,
    project_id: str,
    dataset: str,
    env: str = None,
    manual_token: str = None,
) -> bool:
    cfg = get_config(env)

    print(f"\n=== [{cfg.env_name}] Step 1: Getting Auth Token ===")
    auth_result = get_auth_token(email, password, env=env, manual_token=manual_token)

    if not auth_result.get("success"):
        print(f"\nError: Could not retrieve token. Reason: {auth_result.get('error')}")
        return False

    user_id = auth_result.get("user_id")
    token = auth_result.get("id_token")

    if not user_id:
        print("\nError: Token did not contain a 'userId'.")
        return False

    print(f"Extracted User ID: {user_id}")

    print(f"\n=== Step 2: Creating Warehouse ===")

    payload = {
        "name": f"{company_name} Dev Iq",
        "user_id": user_id,
        "warehouse_type": "bigquery",
        "is_active": True,
        "config": {
            "project_id": project_id,
            "dataset": dataset
        }
    }

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

    print(f"POST {cfg.WAREHOUSE_URL}")

    try:
        response = requests.post(
            cfg.WAREHOUSE_URL,
            json=payload,
            headers=headers,
            timeout=30
        )

        print(f"Response Status: {response.status_code}")

        if response.status_code in (200, 201):
            print("\nSUCCESS: Warehouse created!")
            print(f"Response: {response.text}")
            return True
        else:
            print(f"\nFAILED: {response.text}")
            return False

    except requests.exceptions.RequestException as e:
        print(f"\nFAILED: Network error: {e}")
        return False


def main():
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Create a warehouse in Saras IQ")
    add_env_arg(parser)
    parser.add_argument("--email", required=True, help="User email")
    parser.add_argument("--password", default=None, help="User password (default from env config)")
    parser.add_argument("--company-name", required=True, help="Company name for warehouse label")
    parser.add_argument("--project-id", required=True, help="GCP Project ID")
    parser.add_argument("--dataset", required=True, help="BigQuery dataset")
    args = parser.parse_args()

    cfg = get_config(args.env)
    password = args.password or cfg.DEFAULT_PASSWORD

    create_warehouse(
        email=args.email,
        password=password,
        company_name=args.company_name,
        project_id=args.project_id,
        dataset=args.dataset,
        env=args.env,
    )


if __name__ == "__main__":
    main()
