"""
Step 4: Assign Roles to User
============================
Authenticates as super admin and assigns roles to a given user ID.

Usage:
  python step4_assign_roles.py --env dev --user-id 1497 --roles "iq admin"
  python step4_assign_roles.py --env dev --user-id 1497 --role-ids 37
"""

import sys
import json
import argparse
import requests
from typing import List

from env_config import get_config, add_env_arg
from step3_get_token import get_auth_token


def verify_user_exists(user_id: int, token: str, env: str = None) -> dict:
    """
    Verify that the user exists and get their details.
    """
    cfg = get_config(env)
    print(f"\n[Step 4] Verifying User {user_id} exists...")
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    try:
        resp = requests.get(
            f"{cfg.GET_USER_URL}/{user_id}",
            headers=headers,
            timeout=15
        )

        if resp.status_code == 200:
            user_data = resp.json().get("data", {})
            print(f"[Step 4] User found: {user_data.get('email', 'N/A')}")
            print(f"[Step 4] User's Company ID: {user_data.get('companyId', 'N/A')}")
            return {"success": True, "user": user_data}
        else:
            print(f"[Step 4] User not found: {resp.status_code}")
            return {"success": False, "error": f"User {user_id} not found"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def assign_roles_by_id(user_id: int, role_ids: List[int], product_type: str = "IQ", env: str = None) -> dict:
    """
    Authenticate as super admin and assign role IDs directly to the user.
    Uses the PUT /support/add-any-user-roles endpoint.
    """
    cfg = get_config(env)
    print(f"\n[Step 4] [{cfg.env_name}] Authenticating as Super Admin ({cfg.SUPER_ADMIN_EMAIL})...")
    auth_result = get_auth_token(cfg.SUPER_ADMIN_EMAIL, cfg.SUPER_ADMIN_PASSWORD, env=env)

    if not auth_result.get("success"):
        return {"success": False, "error": f"Super Admin Auth Failed: {auth_result.get('error')}"}

    token = auth_result["id_token"]
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    verify_result = verify_user_exists(user_id, token, env=env)
    if not verify_result.get("success"):
        return verify_result

    print(f"\n[Step 4] Assigning Role IDs {role_ids} to User {user_id}...")
    payload = {"userId": user_id, "roleIds": role_ids}

    assign_resp = requests.put(
        cfg.ADD_ROLES_URL,
        json=payload,
        headers=headers,
        params={"productType": product_type},
        timeout=15
    )

    print(f"[Step 4] Response Status: {assign_resp.status_code}")
    print(f"[Step 4] Endpoint: {cfg.ADD_ROLES_URL}")
    print(f"[Step 4] Payload: {json.dumps(payload)}")
    print(f"[Step 4] Product Type: {product_type}")

    if assign_resp.status_code == 200:
        print(f"[Step 4] Successfully assigned roles!")
        return {"success": True, "role_ids": role_ids}
    else:
        print(f"[Step 4] Full Response: {assign_resp.text}")
        return {"success": False, "error": f"Role assignment failed: {assign_resp.status_code} - {assign_resp.text}"}


def assign_roles(user_id: int, role_names: List[str], product_type: str = "IQ", env: str = None) -> dict:
    """
    Authenticate as super admin and assign roles to a user by name.
    """
    cfg = get_config(env)
    print(f"\n[Step 4] [{cfg.env_name}] Authenticating as Super Admin ({cfg.SUPER_ADMIN_EMAIL})...")
    auth_result = get_auth_token(cfg.SUPER_ADMIN_EMAIL, cfg.SUPER_ADMIN_PASSWORD, env=env)

    if not auth_result.get("success"):
        return {"success": False, "error": f"Super Admin Auth Failed: {auth_result.get('error')}"}

    token = auth_result["id_token"]
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    print(f"[Step 4] Fetching available roles for product {product_type}...")
    try:
        resp = requests.get(
            cfg.GET_ROLES_URL,
            params={"productType": product_type},
            headers=headers,
            timeout=15
        )
        if resp.status_code != 200:
            return {"success": False, "error": f"Failed to fetch roles: {resp.text}"}

        roles_data = resp.json().get("data", [])
        print(f"[Step 4] DEBUG: Available roles from API:")
        for r in roles_data:
            print(f"  - {r.get('roleName', r.get('name'))} (ID: {r.get('roleId')})")

        role_map = {}
        for r in roles_data:
            name = r.get("roleName") or r.get("name")
            role_id = r.get("roleId")
            if name and role_id is not None:
                role_map[name.lower()] = role_id

        role_ids = []
        missing_roles = []
        for requested in role_names:
            req_lower = requested.lower().replace(" ", "").replace("_", "")
            found = False

            # Try exact match first
            if req_lower in role_map:
                role_ids.append(role_map[req_lower])
                print(f"[Step 4] Found role '{requested}' -> ID {role_map[req_lower]}")
                found = True
            else:
                # Try fuzzy match (ignore spaces and underscores)
                for role_name, role_id in role_map.items():
                    role_name_normalized = role_name.lower().replace(" ", "").replace("_", "")
                    if role_name_normalized == req_lower:
                        role_ids.append(role_id)
                        print(f"[Step 4] Found role '{requested}' (matched as '{role_name}') -> ID {role_id}")
                        found = True
                        break

            if not found:
                missing_roles.append(requested)

        if missing_roles:
            print(f"[Step 4] Warning: Could not find Role IDs for: {', '.join(missing_roles)}")
            print(f"[Step 4] Available roles: {list(role_map.keys())}")

        if not role_ids:
            return {"success": False, "error": "No valid role IDs found to assign."}

        print(f"\n[Step 4] Assigning Role IDs {role_ids} to User {user_id}...")
        payload = {"userId": user_id, "roleIds": role_ids}

        assign_resp = requests.put(
            cfg.ADD_ROLES_URL,
            json=payload,
            headers=headers,
            params={"productType": product_type},
            timeout=15
        )

        print(f"[Step 4] Response Status: {assign_resp.status_code}")
        print(f"[Step 4] Endpoint: {cfg.ADD_ROLES_URL}")
        print(f"[Step 4] Payload: {json.dumps(payload)}")
        print(f"[Step 4] Product Type: {product_type}")

        if assign_resp.status_code == 200:
            print(f"[Step 4] Successfully assigned roles!")
            return {"success": True, "role_ids": role_ids}
        else:
            print(f"[Step 4] Full Response: {assign_resp.text}")
            return {"success": False, "error": f"Role assignment failed: {assign_resp.status_code} - {assign_resp.text}"}

    except requests.exceptions.RequestException as e:
        return {"success": False, "error": f"Network error: {str(e)}"}


def main():
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Step 4: Assign Roles to User")
    add_env_arg(parser)
    parser.add_argument("--user-id", type=int, required=True, help="Numeric user ID")
    parser.add_argument("--roles", nargs="+", help="List of role names to assign")
    parser.add_argument("--role-ids", nargs="+", type=int, help="List of role IDs to assign directly")
    parser.add_argument("--product", default="IQ", help="Product type (default: IQ)")
    args = parser.parse_args()

    if not args.roles and not args.role_ids:
        parser.error("Must provide either --roles or --role-ids")

    if args.role_ids:
        result = assign_roles_by_id(args.user_id, args.role_ids, args.product, env=args.env)
    else:
        result = assign_roles(args.user_id, args.roles, args.product, env=args.env)

    if not result["success"]:
        print(f"\n  FAILED: {result['error']}")
        sys.exit(1)

    print("\n  SUCCESS: Roles assigned!")


if __name__ == "__main__":
    main()
