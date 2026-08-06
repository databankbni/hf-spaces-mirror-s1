"""
Environment Configuration
=========================
Central config for all environments (dev, staging, prod).
All scripts import from here instead of hardcoding URLs/keys.

Usage:
  from env_config import get_config
  cfg = get_config("dev")
  print(cfg.USER_SERVICE_URL)
"""

import os
import argparse
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass
class EnvConfig:
    """Configuration for a single environment."""
    # Required fields (no defaults) — must come first
    env_name: str
    USER_SERVICE_URL: str
    IQ_API_URL: str
    GCS_BUCKET: str

    # Optional / defaulted fields
    GCS_BASE_PATH: str = "dev"
    FIREBASE_API_KEY: str = ""
    FIREBASE_PROJECT_ID: str = ""
    REQUIRES_MANUAL_TOKEN: bool = False
    SUPER_ADMIN_EMAIL: str = ""
    SUPER_ADMIN_PASSWORD: str = ""
    PORTAL_LOGIN_URL: str = ""                   # IQ portal login page
    OUTLOOK_EMAIL: str = "vignesh.bodiga@sarasanalytics.com"
    OUTLOOK_PASSWORD: str = os.getenv("OUTLOOK_PASSWORD", "")
    DEFAULT_PASSWORD: str = "Test@1234"
    DEFAULT_PRODUCT_TYPE: str = "IQ"

    @property
    def FIREBASE_SIGNIN_URL(self) -> str:
        return f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={self.FIREBASE_API_KEY}"

    @property
    def FIREBASE_REFRESH_URL(self) -> str:
        return f"https://securetoken.googleapis.com/v1/token?key={self.FIREBASE_API_KEY}"

    @property
    def SIGNUP_URL(self) -> str:
        return f"{self.USER_SERVICE_URL}/user?productType={self.DEFAULT_PRODUCT_TYPE}"

    @property
    def GET_ROLES_URL(self) -> str:
        return f"{self.USER_SERVICE_URL}/role/all"

    @property
    def ADD_ROLES_URL(self) -> str:
        return f"{self.USER_SERVICE_URL}/support/add-any-user-roles"

    @property
    def GET_USER_URL(self) -> str:
        return f"{self.USER_SERVICE_URL}/user"

    @property
    def WAREHOUSE_URL(self) -> str:
        return f"{self.IQ_API_URL}/company-warehouses"


# ── Environment Definitions ──────────────────────────────────────────

ENVIRONMENTS = {
    "dev": EnvConfig(
        env_name="dev",
        USER_SERVICE_URL="https://dev-user-service.sarasanalytics.com/v1/api",
        FIREBASE_API_KEY=os.getenv("DEV_FIREBASE_API_KEY", ""),
        FIREBASE_PROJECT_ID="dev-daton-37754",
        IQ_API_URL="https://deviqapi.sarasanalytics.com",
        GCS_BUCKET="iq-dev-test",
        GCS_BASE_PATH="dev",
        PORTAL_LOGIN_URL="https://deviq.sarasanalytics.com",
        SUPER_ADMIN_EMAIL="bheem+dev@sarasanalytics.com",
        SUPER_ADMIN_PASSWORD=os.getenv("DEV_SUPER_ADMIN_PASSWORD", ""),
    ),
    "test": EnvConfig(
        env_name="test",
        USER_SERVICE_URL="https://test-user-service.sarasanalytics.com/v1/api",
        FIREBASE_API_KEY=os.getenv("TEST_FIREBASE_API_KEY", ""),
        IQ_API_URL="https://testiqapi.sarasanalytics.com",
        GCS_BUCKET="iq-dev-test",
        GCS_BASE_PATH="qa",
        PORTAL_LOGIN_URL="https://testiq.sarasanalytics.com",
        SUPER_ADMIN_EMAIL="rajavardhan@sarasanalytics.com",
        SUPER_ADMIN_PASSWORD=os.getenv("TEST_SUPER_ADMIN_PASSWORD", ""),
        DEFAULT_PRODUCT_TYPE="SARAS",
        REQUIRES_MANUAL_TOKEN=False,
    ),
    "prod": EnvConfig(
        env_name="prod",
        USER_SERVICE_URL="https://user-service.sarasanalytics.com/v1/api",
        FIREBASE_API_KEY=os.getenv("PROD_FIREBASE_API_KEY", ""),
        IQ_API_URL="https://iqapi.sarasanalytics.com",
        GCS_BUCKET="iq-prod",
        GCS_BASE_PATH="prod",
        PORTAL_LOGIN_URL="https://accounts.sarasanalytics.com/login?productType=iq",
        SUPER_ADMIN_EMAIL="abhishek.diwan@sarasanalytics.com",
        SUPER_ADMIN_PASSWORD=os.getenv("PROD_SUPER_ADMIN_PASSWORD", ""),
        DEFAULT_PRODUCT_TYPE="SARAS",
        REQUIRES_MANUAL_TOKEN=False,
    ),
}


def get_config(env: str = None) -> EnvConfig:
    """
    Get config for the given environment.
    Falls back to ENV_NAME env var, then defaults to 'dev'.
    """
    env = env or os.environ.get("SARAS_ENV", "dev")
    env = env.lower().strip()

    if env not in ENVIRONMENTS:
        available = ", ".join(ENVIRONMENTS.keys())
        raise ValueError(f"Unknown environment '{env}'. Available: {available}")

    return ENVIRONMENTS[env]


def add_env_arg(parser: argparse.ArgumentParser):
    """Add the --env argument to any script's argument parser."""
    parser.add_argument(
        "--env", default=None,
        choices=list(ENVIRONMENTS.keys()),
        help="Target environment (default: dev, or SARAS_ENV env var)"
    )
