"""
Step 1: Create Account via Saras User Service API
==================================================
Single POST to the User Service -- no browser needed.
Backend creates Firebase user and sends verification email.

Usage:
  python step1_create_account.py --env dev --first Demo --last IQ --email demo+test@sarasanalytics.com --company TestCo
  python step1_create_account.py  # interactive mode
"""

import sys
import json
import argparse
import requests

from env_config import get_config, add_env_arg

REVENUE_OPTIONS = {
    "1": "<$15M",
    "2": "$15-50M",
    "3": "$50-100M",
    "4": "$100-200M",
    "5": "$200M+",
}

PRODUCT_OPTIONS = {
    "1": {"label": "Saras IQ",    "signupLabel": "Saras IQ"},
    "2": {"label": "Saras Pulse", "signupLabel": "Saras Pulse"},
    "3": {"label": "Saras Daton", "signupLabel": "Saras Daton"},
    "4": {"label": "Other",       "signupLabel": "Other"},
}


def create_account(
    first_name: str,
    last_name: str,
    email: str,
    company: str,
    revenue: str = "<$15M",
    product: str = "Saras IQ",
    env: str = None,
    company_id: str = None,
) -> dict:
    """
    Create a Saras account via the User Service API.

    Args:
        company_id: Optional. If provided, user is added to existing company instead of creating new one.

    Returns:
        dict with keys: success, user_id, email, error
    """
    cfg = get_config(env)
    signup_url = cfg.SIGNUP_URL

    payload = {
        "firstName": first_name,
        "lastName": last_name,
        "email": email,
    }

    # If company_id is provided, use existing company; otherwise create new one
    if company_id:
        payload["companyId"] = company_id
        print(f"[Step 1] Using existing company ID: {company_id}")
    else:
        payload["company"] = {
            "name": company,
            "annualRevenue": revenue,
            "productSigningUpFor": product,
        }
        print(f"[Step 1] Creating new company: {company}")

    print(f"\n[Step 1] [{cfg.env_name}] Creating account for {first_name} {last_name} ({email})")
    print(f"[Step 1] POST {signup_url}")
    print(f"[Step 1] Payload: {json.dumps(payload, indent=2)}")

    try:
        response = requests.post(
            signup_url,
            json=payload,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            timeout=30,
        )

        print(f"[Step 1] Status: {response.status_code}")

        if response.status_code in (200, 201):
            data = response.json()
            user_data = data.get("data", {})
            user_id = user_data.get("userId")
            print(f"[Step 1] Account created! userId={user_id}")
            print(f"[Step 1] Verification email sent to {email}")
            return {
                "success": True,
                "user_id": user_id,
                "email": email,
                "response": data,
                "error": None,
            }
        else:
            error_text = response.text[:500]
            print(f"[Step 1] Failed: {error_text}")
            return {
                "success": False,
                "user_id": None,
                "email": email,
                "response": None,
                "error": f"Status {response.status_code}: {error_text}",
            }

    except requests.exceptions.RequestException as e:
        print(f"[Step 1] Network error: {e}")
        return {
            "success": False,
            "user_id": None,
            "email": email,
            "response": None,
            "error": str(e),
        }


def main():
    parser = argparse.ArgumentParser(description="Step 1: Create Saras Account")
    add_env_arg(parser)
    parser.add_argument("--first", help="First name")
    parser.add_argument("--last", help="Last name")
    parser.add_argument("--email", help="Work email")
    parser.add_argument("--company", help="Company name")
    parser.add_argument("--revenue", default="<$15M", help="Annual revenue")
    parser.add_argument("--product", default="Saras IQ", help="Product signing up for")
    args = parser.parse_args()

    if not args.first:
        print("\n=== Step 1: Create Saras Account ===\n")
        args.first = input("First Name: ").strip()
        args.last = input("Last Name: ").strip()
        args.email = input("Work Email: ").strip()
        args.company = input("Company Name: ").strip()

        print("\nAnnual Revenue (USD):")
        for k, v in REVENUE_OPTIONS.items():
            print(f"  {k}. {v}")
        rev_choice = input(f"Choose (1-{len(REVENUE_OPTIONS)}) [1]: ").strip() or "1"
        args.revenue = REVENUE_OPTIONS.get(rev_choice, "<$15M")

        print("\nProduct:")
        for k, v in PRODUCT_OPTIONS.items():
            print(f"  {k}. {v['label']}")
        prod_choice = input(f"Choose (1-{len(PRODUCT_OPTIONS)}) [1]: ").strip() or "1"
        args.product = PRODUCT_OPTIONS.get(prod_choice, PRODUCT_OPTIONS["1"])["signupLabel"]

    result = create_account(
        first_name=args.first,
        last_name=args.last,
        email=args.email,
        company=args.company,
        revenue=args.revenue,
        product=args.product,
        env=args.env,
    )

    if result["success"]:
        print(f"\n{'='*50}")
        print(f"  SUCCESS! Account created.")
        print(f"  User ID: {result['user_id']}")
        print(f"  Email:   {result['email']}")
        print(f"  Next:    Run step2_verify_email.py --email {result['email']}")
        print(f"{'='*50}\n")
    else:
        print(f"\n  FAILED: {result['error']}")
        sys.exit(1)


if __name__ == "__main__":
    main()
