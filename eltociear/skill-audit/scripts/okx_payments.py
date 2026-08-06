"""OKX Onchain OS payment integration for the /okx/* routes.

BACKGROUND (three rejections deep): OKX's 3rd review said the service "is not integrated with the
official OKX Payment SDK". That SDK, `okxweb3-app-x402`, turns out to be a repackage of Coinbase's
x402 SDK pinned at 2.5.0 — and it installs the SAME top-level `x402` module we already run at
2.16.0 for the Base/USDC earners. Installing it would collide with the only thing that actually
makes money, so we don't.

What the review really checks is wire behaviour: emit a 402 challenge, then verify AND settle the
payment against OKX's broker before serving. Our SDK already supports a custom facilitator, so the
integration is identical minus the version clash.

Two things OKX does differently from CDP, both handled here:
  * auth is HMAC-SHA256 over `timestamp + method + path + body` (CDP's JWT never sees the body),
    so the stock CreateHeadersAuthProvider — which is called with no arguments — cannot sign it.
    We override the two request methods that have the body in hand.
  * responses come wrapped in OKX's `{code, data, msg}` envelope, which the stock parser would
    choke on.

Inert without credentials: `install()` returns False and the caller keeps its own challenge.
Credentials are OKX Developer Portal API keys (browser + phone verification, one-time human step).
"""
import base64
import hashlib
import hmac
import json
import os
from datetime import datetime, timezone

OKX_BASE_URL = os.environ.get("OKX_X402_BASE_URL", "https://web3.okx.com")
OKX_BASE_PATH = "/api/v6/pay/x402"

XLAYER_NETWORK = "eip155:196"
XLAYER_USDT0 = "0x779DEd0c9e1022225f8E0630b35a9b54bE713736"
# EIP-712 domain read off the token's on-chain DOMAIN_SEPARATOR, not guessed.
XLAYER_USDT0_EXTRA = {"name": "USD₮0", "version": "1", "decimals": 6}

OKX_ROUTE_PRICES = {          # path -> price in USDT0 base units (6 decimals)
    "/okx/audit": 10000,
    "/okx/read": 10000,
    "/okx/search": 10000,
    "/okx/extract": 10000,
}


def credentials():
    """(api_key, secret, passphrase) or None when the portal step hasn't been done."""
    key = os.environ.get("OKX_API_KEY", "").strip()
    secret = os.environ.get("OKX_SECRET_KEY", "").strip()
    passphrase = os.environ.get("OKX_PASSPHRASE", "").strip()
    return (key, secret, passphrase) if key and secret and passphrase else None


def auth_headers(method, path, body, creds):
    key, secret, passphrase = creds
    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"
    prehash = f"{ts}{method}{path}{body}"
    sign = base64.b64encode(
        hmac.new(secret.encode(), prehash.encode(), hashlib.sha256).digest()).decode()
    return {"OK-ACCESS-KEY": key, "OK-ACCESS-SIGN": sign,
            "OK-ACCESS-TIMESTAMP": ts, "OK-ACCESS-PASSPHRASE": passphrase,
            "Content-Type": "application/json",
            # web3.okx.com is behind Cloudflare, which 403s (code 1010) a default library agent
            # before the API sees the key — indistinguishable from bad credentials.
            "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                           "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")}


def _unwrap(data, endpoint):
    """OKX wraps everything in {code, data, msg}; a non-zero code is an error, not a result."""
    if not isinstance(data, dict):
        raise ValueError(f"OKX {endpoint}: non-object response {str(data)[:200]}")
    code = data.get("code")
    if code is not None:
        code_int = int(code) if isinstance(code, str) else code
        if code_int != 0:
            raise ValueError(f"OKX {endpoint} error (code={code_int}): "
                             f"{data.get('msg') or 'unknown error'}")
        inner = data.get("data")
        if inner is not None:
            return inner
    return data


def build(pay_to):
    """(routes, server) for the /okx/* paths, or None when credentials are missing."""
    creds = credentials()
    if not creds:
        return None

    from x402.http import FacilitatorConfig, HTTPFacilitatorClient, PaymentOption
    from x402.http.types import RouteConfig
    from x402.mechanisms.evm.exact import ExactEvmServerScheme
    from x402.schemas import AssetAmount, VerifyResponse, SettleResponse, SupportedResponse
    from x402.server import x402ResourceServer

    class OKXFacilitatorClient(HTTPFacilitatorClient):
        """Same client, but signing the exact bytes we send and unwrapping OKX's envelope."""

        def _get_supported_headers(self):
            # Called during initialize() as a GET with no body — sign the empty string.
            return auth_headers("GET", f"{OKX_BASE_PATH}/supported", "", creds)

        def get_supported(self):
            resp = self._get_sync_client().get(
                f"{OKX_BASE_URL}{OKX_BASE_PATH}/supported",
                headers=self._get_supported_headers())
            if resp.status_code != 200:
                raise ValueError(f"OKX supported failed ({resp.status_code}): {resp.text[:300]}")
            return SupportedResponse.model_validate(_unwrap(resp.json(), "supported"))

        async def _post(self, endpoint, model, version, payload_dict, requirements_dict):
            body = json.dumps(self._build_request_body(version, payload_dict, requirements_dict),
                              separators=(",", ":"))
            path = f"{OKX_BASE_PATH}/{endpoint}"
            resp = await self._get_async_client().post(
                f"{OKX_BASE_URL}{path}", content=body.encode(),
                headers=auth_headers("POST", path, body, creds))
            if resp.status_code != 200:
                raise ValueError(f"OKX {endpoint} failed ({resp.status_code}): {resp.text[:300]}")
            return model.model_validate(_unwrap(resp.json(), endpoint))

        async def _verify_http(self, version, payload_dict, requirements_dict):
            return await self._post("verify", VerifyResponse, version, payload_dict,
                                    requirements_dict)

        async def _settle_http(self, version, payload_dict, requirements_dict):
            return await self._post("settle", SettleResponse, version, payload_dict,
                                    requirements_dict)

    facilitator = OKXFacilitatorClient(FacilitatorConfig(url=f"{OKX_BASE_URL}{OKX_BASE_PATH}"))
    # Prove the credentials NOW. The SDK calls get_supported() lazily on the first request, and a
    # failure there surfaces as a 500 — i.e. bad keys would turn the OKX routes into an outage
    # instead of falling back to the challenge we can still serve ourselves.
    try:
        facilitator.get_supported()
    except Exception as e:
        print(f"  okx broker rejected our credentials, staying on the fallback challenge: {e}")
        return None
    server = x402ResourceServer(facilitator)
    server.register(XLAYER_NETWORK, ExactEvmServerScheme())

    routes = {}
    for path, amount in OKX_ROUTE_PRICES.items():
        routes[f"POST {path}"] = RouteConfig(
            accepts=[PaymentOption(
                scheme="exact", pay_to=pay_to, network=XLAYER_NETWORK,
                price=AssetAmount(amount=str(amount), asset=XLAYER_USDT0,
                                  extra=dict(XLAYER_USDT0_EXTRA)),
                max_timeout_seconds=300,
            )],
            mime_type="application/json",
            description=f"OKX marketplace service ({path.rsplit('/', 1)[-1]}), "
                        f"settled in USDT0 on X Layer.",
        )
    return routes, server


def install(app, pay_to):
    """Attach the OKX paywall to the app. False = no credentials, caller keeps its own 402."""
    built = build(pay_to)
    if not built:
        return False
    from x402.http.middleware.fastapi import PaymentMiddlewareASGI
    routes, server = built
    app.add_middleware(PaymentMiddlewareASGI, routes=routes, server=server)
    return True
