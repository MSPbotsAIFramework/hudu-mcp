# Copyright 2026 MSPbots.ai
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""FastMCP factory and the per-request credential middleware."""

import contextvars
import re
import uuid
from collections.abc import Callable
from urllib.parse import urlsplit

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from ._arguments import EnvelopeFastMCP
from .api_client import HuduClient, HuduCredentials
from .config import Settings

HEADER_BASE_URL = "X-Hudu-Base-URL"
HEADER_API_KEY = "X-Hudu-API-Key"
REQUIRED_HEADERS = [HEADER_BASE_URL, HEADER_API_KEY]

_PLACEHOLDER = re.compile(r"^\$\{.*\}$")
_API_SUFFIX = re.compile(r"/api(/v1)?/?$", re.IGNORECASE)
_LOCAL_HOSTS = {"localhost", "127.0.0.1"}

# Per-request isolation: the middleware sets these for the duration of one
# HTTP request and resets them in `finally`. Nothing credential-related is
# ever stored at module level.
_credentials_var: contextvars.ContextVar[HuduCredentials | None] = contextvars.ContextVar(
    "hudu_credentials", default=None
)
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("hudu_request_id", default="-")

INSTRUCTIONS = (
    "Hudu is the MSP's IT documentation platform: per client company it holds "
    "assets (documented items built from asset layouts, e.g. servers, "
    "firewalls, licences), stored passwords, knowledge-base articles, "
    "monitored websites, procedures (checklists) and relations between them.\n"
    "Usage:\n"
    "- Find the company first: hudu_list_companies(name or search); company "
    "ids feed the other list tools.\n"
    "- Assets: hudu_list_assets(company_id, asset_layout_id, name) -> "
    "hudu_get_asset. Asset tools take company_id; when omitted it is looked "
    "up from the asset id.\n"
    "- Passwords: hudu_list_asset_passwords hides the secret values; "
    "hudu_get_asset_password returns one password in clear text, so fetch it "
    "only when the user needs that credential.\n"
    "- Lists page with page + page_size; has_more says whether to page on.\n"
    "Create, update and archive tools change the documentation: call them "
    "only when the user explicitly asks, with the exact values given. Delete "
    "tools are permanent and also need confirm: true after the user approved "
    "that exact deletion."
)


def get_client_from_context() -> HuduClient | None:
    """The client for the current request, or None outside a request."""
    credentials = _credentials_var.get()
    if credentials is None:
        return None
    return HuduClient(credentials)


def _clean(value: str | None) -> str | None:
    text = (value or "").strip()
    if not text or _PLACEHOLDER.match(text):
        return None
    return text


def normalize_base_url(value: str) -> str | None:
    """https origin (+ path prefix) of the Hudu instance, without /api/v1; None when unusable."""
    text = value.strip()
    if "://" not in text:
        text = f"https://{text}"
    parts = urlsplit(text)
    if not parts.hostname:
        return None
    if parts.scheme != "https" and not (parts.scheme == "http" and parts.hostname in _LOCAL_HOSTS):
        return None
    path = _API_SUFFIX.sub("", parts.path.rstrip("/"))
    return f"{parts.scheme}://{parts.netloc}{path}".rstrip("/")


class GatewayCredentialsMiddleware:
    """Reads X-Hudu-Base-URL and X-Hudu-API-Key on /mcp requests; 401 when missing, 400 when not https."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope.get("path", "").startswith("/mcp"):
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        base = _clean(request.headers.get(HEADER_BASE_URL))
        api_key = _clean(request.headers.get(HEADER_API_KEY))
        if not (base and api_key):
            missing = [h for h, v in ((HEADER_BASE_URL, base), (HEADER_API_KEY, api_key)) if not v]
            await JSONResponse(
                {"error": "Missing credentials", "message": f"Missing header(s): {', '.join(missing)}", "required_headers": REQUIRED_HEADERS},
                status_code=401,
            )(scope, receive, send)
            return
        base_url = normalize_base_url(base)
        if base_url is None:
            await JSONResponse(
                {"error": "Invalid base URL", "message": f"{HEADER_BASE_URL} must be the https URL of the Hudu instance"},
                status_code=400,
            )(scope, receive, send)
            return

        request_id = (request.headers.get("x-request-id") or "").strip()[:64] or uuid.uuid4().hex[:12]
        creds_token = _credentials_var.set(HuduCredentials(base_url, api_key))
        rid_token = request_id_var.set(request_id)
        try:
            await self.app(scope, receive, send)
        finally:
            _credentials_var.reset(creds_token)
            request_id_var.reset(rid_token)


def create_mcp_server(settings: Settings | None = None) -> FastMCP:
    """Build the FastMCP server and register every tool."""
    mcp = EnvelopeFastMCP(
        name="hudu-mcp",
        instructions=INSTRUCTIONS,
        # The service sits behind the gateway, so Host is never localhost;
        # DNS-rebinding protection would reject those requests with 421.
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
        stateless_http=True,
    )

    client_factory: Callable[[], HuduClient | None] = get_client_from_context

    from .tools import articles, assets, companies, layouts, misc, passwords, status, websites

    for module in (status, companies, assets, layouts, passwords, articles, websites, misc):
        module.register(mcp, client_factory)

    return mcp
