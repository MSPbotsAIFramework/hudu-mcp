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
"""Request shapes, retries and tool behaviour against a mocked Hudu API."""

import json

import httpx
import pytest

from hudu_mcp import api_client
from hudu_mcp.api_client import HuduClient, HuduCredentials, HuduError
from hudu_mcp.server import _credentials_var, create_mcp_server

CREDS = HuduCredentials("https://docs.example.com", "key-123")


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    async def instant(_seconds):
        return None

    monkeypatch.setattr(api_client.asyncio, "sleep", instant)


class Recorder:
    """Mock transport: replies by method + path below /api/v1/."""

    def __init__(self, routes=None, default=None):
        self.requests: list[httpx.Request] = []
        self.routes = routes or {}
        self.default = default if default is not None else {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path.removeprefix("/api/v1/")
        reply = self.routes.get(f"{request.method} {path}", self.routes.get(path, self.default))
        if callable(reply):
            return reply(request)
        return httpx.Response(200, json=reply)

    def calls(self, path: str, method: str | None = None) -> list[httpx.Request]:
        return [r for r in self.requests if r.url.path == f"/api/v1/{path}" and (method is None or r.method == method)]


def body(request: httpx.Request):
    return json.loads(request.content) if request.content else None


async def _call(monkeypatch, recorder: Recorder, tool: str, args: dict):
    http = httpx.AsyncClient(transport=httpx.MockTransport(recorder))
    monkeypatch.setattr(api_client, "_get_shared_http_client", lambda: http)
    ctx = _credentials_var.set(CREDS)
    try:
        content, _ = await create_mcp_server().call_tool(tool, args)
    finally:
        _credentials_var.reset(ctx)
    return json.loads(content[0].text)


def _client(recorder: Recorder) -> HuduClient:
    return HuduClient(CREDS, httpx.AsyncClient(transport=httpx.MockTransport(recorder)))


# ---- client ----------------------------------------------------------------


async def test_api_key_header_and_bool_params():
    rec = Recorder({"companies": {"companies": []}})
    await _client(rec).get("companies", {"archived": True})
    request = rec.requests[0]
    assert request.headers["x-api-key"] == "key-123"
    assert str(request.url) == "https://docs.example.com/api/v1/companies?archived=true"


async def test_get_retries_5xx_but_writes_do_not():
    replies = iter([httpx.Response(502), httpx.Response(200, json={"companies": []})])
    rec = Recorder({"GET companies": lambda r: next(replies), "POST companies": lambda r: httpx.Response(500, json={})})
    client = _client(rec)
    await client.get("companies")
    with pytest.raises(HuduError):
        await client.post("companies", {})
    assert len(rec.calls("companies", "GET")) == 2 and len(rec.calls("companies", "POST")) == 1


async def test_validation_errors_are_readable(monkeypatch):
    rec = Recorder({"POST companies": lambda r: httpx.Response(422, json={"errors": {"name": ["has already been taken"]}})})
    result = await _call(monkeypatch, rec, "hudu_create_company", {"name": "Example"})
    assert result["error"]["code"] == "invalid_argument"
    assert "name has already been taken" in result["error"]["message"]


async def test_html_error_pages_are_not_echoed(monkeypatch):
    rec = Recorder({"companies/1": lambda r: httpx.Response(404, text="<html><body>Not Found</body></html>")})
    result = await _call(monkeypatch, rec, "hudu_get_company", {"id": 1})
    assert result["error"]["message"] == "Hudu returned HTTP 404 for companies/1"


# ---- lists -----------------------------------------------------------------


async def test_list_companies_paging(monkeypatch):
    rec = Recorder({"companies": {"companies": [{"id": i} for i in range(5)]}})
    result = await _call(monkeypatch, rec, "hudu_list_companies", {"page_size": 5, "name": "Example"})
    params = rec.requests[0].url.params
    assert (params["page"], params["page_size"], params["name"]) == ("1", "5", "Example")
    assert (result["count"], result["has_more"], result["next_page"]) == (5, True, 2)


async def test_websites_company_filter_is_applied_in_page(monkeypatch):
    rec = Recorder({"websites": {"websites": [{"id": 1, "company_id": 7}, {"id": 2, "company_id": 8}]}})
    result = await _call(monkeypatch, rec, "hudu_list_websites", {"company_id": 7})
    assert [w["id"] for w in result["websites"]] == [1]
    assert "company_id" not in rec.requests[0].url.params


# ---- records ---------------------------------------------------------------


async def test_company_create_wraps_body(monkeypatch):
    rec = Recorder({"POST companies": {"company": {"id": 3, "name": "Example"}}})
    result = await _call(monkeypatch, rec, "hudu_create_company", {"name": "Example", "city": "Springfield"})
    assert body(rec.requests[0]) == {"company": {"name": "Example", "city": "Springfield"}}
    assert result == {"id": 3, "name": "Example"}


async def test_archive_and_unarchive_company(monkeypatch):
    rec = Recorder()
    await _call(monkeypatch, rec, "hudu_archive_company", {"id": 3})
    await _call(monkeypatch, rec, "hudu_unarchive_company", {"id": 3})
    assert rec.calls("companies/3/archive", "PUT") and rec.calls("companies/3/unarchive", "PUT")


async def test_asset_get_looks_up_its_company(monkeypatch):
    rec = Recorder({"assets": {"assets": [{"id": 42, "company_id": 7}]}, "companies/7/assets/42": {"asset": {"id": 42, "name": "SRV01"}}})
    result = await _call(monkeypatch, rec, "hudu_get_asset", {"id": 42})
    assert rec.calls("assets")[0].url.params["id"] == "42"
    assert result == {"id": 42, "name": "SRV01"}


async def test_asset_get_with_company_skips_lookup(monkeypatch):
    rec = Recorder({"companies/7/assets/42": {"asset": {"id": 42}}})
    await _call(monkeypatch, rec, "hudu_get_asset", {"id": 42, "company_id": 7})
    assert not rec.calls("assets")


async def test_unknown_asset_is_not_found(monkeypatch):
    rec = Recorder({"assets": {"assets": []}})
    result = await _call(monkeypatch, rec, "hudu_archive_asset", {"id": 42})
    assert result["error"]["code"] == "not_found"


async def test_asset_create_and_update_bodies(monkeypatch):
    rec = Recorder({"POST companies/7/assets": {"asset": {"id": 1}}, "PUT companies/7/assets/1": {"asset": {"id": 1}}})
    args = {"company_id": 7, "asset_layout_id": 3, "name": "FW01", "custom_fields": {"ip_address": "10.0.0.1"}}
    await _call(monkeypatch, rec, "hudu_create_asset", args)
    assert body(rec.calls("companies/7/assets", "POST")[0]) == {"asset": {"name": "FW01", "asset_layout_id": 3, "custom_fields": [{"ip_address": "10.0.0.1"}]}}
    await _call(monkeypatch, rec, "hudu_update_asset", {"id": 1, "company_id": 7, "primary_serial": "SN1"})
    assert body(rec.calls("companies/7/assets/1", "PUT")[0]) == {"asset": {"primary_serial": "SN1"}}


@pytest.mark.parametrize(
    "tool,args,path",
    [
        ("hudu_delete_company", {"id": 3}, "companies/3"),
        ("hudu_delete_asset", {"id": 42, "company_id": 7}, "companies/7/assets/42"),
        ("hudu_delete_asset_password", {"id": 5}, "asset_passwords/5"),
        ("hudu_delete_article", {"id": 6}, "articles/6"),
        ("hudu_delete_website", {"id": 8}, "websites/8"),
    ],
)
async def test_deletes_need_confirm(monkeypatch, tool, args, path):
    rec = Recorder()
    result = await _call(monkeypatch, rec, tool, args)
    assert result["done"] is False and rec.requests == []
    await _call(monkeypatch, rec, tool, args | {"confirm": True})
    assert rec.calls(path, "DELETE")


async def test_password_list_masks_secrets(monkeypatch):
    rows = [{"id": 1, "name": "Admin", "username": "admin", "password": "hunter2", "otp_secret": ""}]
    rec = Recorder({"asset_passwords": {"asset_passwords": rows}})
    result = await _call(monkeypatch, rec, "hudu_list_asset_passwords", {"company_id": 7})
    entry = result["asset_passwords"][0]
    assert entry["password"] == "********" and entry["has_password"] is True
    assert entry["otp_secret"] == "" and entry["has_otp_secret"] is False
    assert "hunter2" not in json.dumps(result)


async def test_password_get_reveals_secret(monkeypatch):
    rec = Recorder({"asset_passwords/1": {"asset_password": {"id": 1, "password": "hunter2"}}})
    result = await _call(monkeypatch, rec, "hudu_get_asset_password", {"id": 1})
    assert result["password"] == "hunter2"


async def test_password_create_wraps_body_and_masks_echo(monkeypatch):
    rec = Recorder({"POST asset_passwords": {"asset_password": {"id": 2, "password": "s3cret"}}})
    result = await _call(monkeypatch, rec, "hudu_create_asset_password", {"company_id": 7, "name": "VPN", "password": "s3cret"})
    assert body(rec.requests[0]) == {"asset_password": {"company_id": 7, "name": "VPN", "password": "s3cret"}}
    assert result["password"] == "********"


async def test_website_name_must_be_a_url(monkeypatch):
    rec = Recorder()
    result = await _call(monkeypatch, rec, "hudu_create_website", {"name": "example.com"})
    assert result["error"]["code"] == "invalid_argument"
    rec = Recorder({"POST websites": {"website": {"id": 1}}})
    await _call(monkeypatch, rec, "hudu_create_website", {"name": "https://www.example.com", "company_id": 7})
    assert body(rec.requests[0]) == {"website": {"name": "https://www.example.com", "company_id": 7}}


async def test_article_and_layout_bodies(monkeypatch):
    rec = Recorder({"POST articles": {"article": {"id": 1}}, "POST asset_layouts": {"asset_layout": {"id": 2}}})
    await _call(monkeypatch, rec, "hudu_create_article", {"name": "Onboarding", "content": "<p>Hi</p>", "company_id": 7})
    await _call(monkeypatch, rec, "hudu_create_asset_layout", {"name": "Firewalls"})
    assert body(rec.calls("articles", "POST")[0]) == {"article": {"name": "Onboarding", "content": "<p>Hi</p>", "company_id": 7}}
    assert body(rec.calls("asset_layouts", "POST")[0]) == {"asset_layout": {"name": "Firewalls", "fields": []}}


async def test_update_without_fields_is_rejected(monkeypatch):
    rec = Recorder()
    result = await _call(monkeypatch, rec, "hudu_update_company", {"id": 3})
    assert result["error"]["code"] == "invalid_argument"
    assert rec.requests == []


@pytest.mark.parametrize(
    "tool,path",
    [
        ("hudu_list_folders", "folders"),
        ("hudu_list_procedures", "procedures"),
        ("hudu_list_activity_logs", "activity_logs"),
        ("hudu_list_relations", "relations"),
        ("hudu_list_magic_dash", "magic_dash"),
        ("hudu_list_asset_layouts", "asset_layouts"),
        ("hudu_list_articles", "articles"),
    ],
)
async def test_list_paths(monkeypatch, tool, path):
    rec = Recorder()
    await _call(monkeypatch, rec, tool, {})
    assert rec.calls(path, "GET")


async def test_connection_check(monkeypatch):
    rec = Recorder({"api_info": {"version": "2.46.0"}})
    result = await _call(monkeypatch, rec, "hudu_test_connection", {})
    assert result == {"connected": True, "instance": "https://docs.example.com", "api_info": {"version": "2.46.0"}}
