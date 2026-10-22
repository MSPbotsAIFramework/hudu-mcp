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


async def test_website_url_is_sent_as_name(monkeypatch):
    rec = Recorder({"POST websites": {"website": {"id": 5}}, "PUT websites/5": {"website": {"id": 5}}})
    await _call(monkeypatch, rec, "hudu_create_website", {"url": "https://www.example.com", "company_id": 2})
    await _call(monkeypatch, rec, "hudu_update_website", {"id": 5, "url": "https://www.example.org"})
    assert body(rec.calls("websites", "POST")[0]) == {"website": {"name": "https://www.example.com", "company_id": 2}}
    assert body(rec.calls("websites/5", "PUT")[0]) == {"website": {"name": "https://www.example.org"}}


async def test_website_same_name_and_url_is_accepted(monkeypatch):
    rec = Recorder({"POST websites": {"website": {"id": 5}}})
    await _call(monkeypatch, rec, "hudu_create_website", {"name": "https://www.example.com", "url": " https://www.example.com "})
    assert body(rec.requests[0]) == {"website": {"name": "https://www.example.com"}}


@pytest.mark.parametrize(
    "tool,args",
    [
        ("hudu_create_website", {"company_id": 2}),
        ("hudu_create_website", {"name": "Example site", "company_id": 2}),
    ],
)
async def test_website_missing_address_is_rejected(monkeypatch, tool, args):
    rec = Recorder()
    result = await _call(monkeypatch, rec, tool, args)
    assert result["error"]["code"] == "invalid_argument"
    assert rec.requests == []



async def test_website_name_wins_and_label_falls_back_to_url(monkeypatch):
    rec = Recorder()
    await _call(monkeypatch, rec, "hudu_create_website", {"name": "https://www.example.com", "url": "https://www.example.org", "company_id": 2})
    await _call(monkeypatch, rec, "hudu_create_website", {"name": "Example site", "url": "https://www.example.org", "company_id": 2})
    sent = [json.loads(r.content)["website"]["name"] for r in rec.requests]
    assert sent == ["https://www.example.com", "https://www.example.org"]


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


# ---- size cap never skips records (PRD-20956) --------------------------------

_LONG_ASSETS = [{"id": i, "name": f"asset-{i}", "fields": [{"label": "notes", "value": "x" * 4800}]} for i in range(1, 48)]
_WIDE_ASSETS = [{"id": i, "name": f"asset-{i}", "fields": [{"label": f"field-{j}", "value": "v" * 60} for j in range(60)]} for i in range(1, 48)]


@pytest.mark.parametrize("assets", [_LONG_ASSETS, _WIDE_ASSETS], ids=["long-field", "many-fields"])
async def test_paging_large_assets_returns_every_record_once(monkeypatch, assets):
    def route(request):
        page = int(request.url.params.get("page", 1))
        size = int(request.url.params.get("page_size", 25))
        return httpx.Response(200, json={"assets": assets[(page - 1) * size : page * size]})

    seen, args = [], {}
    for _ in range(50):
        out = await _call(monkeypatch, Recorder({"assets": route}), "hudu_list_assets", args)
        ids = [a["id"] for a in out["assets"]]
        assert out["count"] == len(ids)
        seen += ids
        if out.get("next_page"):
            args = {**args, "page": out["next_page"]}
        elif out.get("retry_page_size") and "page_size" not in args:
            args, seen = {"page_size": out["retry_page_size"]}, []
        else:
            break
    assert seen == list(range(1, 48))


# ---- Page-number paging that survives truncation (offset / next_offset) -----------------------------
# Self-test checklist: a cut page continues right after the last record returned (from page 1 and
# from a later page); offset aligned / not aligned to a page; offset 0; offset past the end; offset
# wins over page; page-only calls send the same request as before; no retry hint for a page size.

TOTAL = 137
ROWS = [{"id": i, "name": f"Row {i}", **{f"f{k}": f"value {k}" for k in range(40)}} for i in range(TOTAL)]
SMALL = [{"id": i} for i in range(TOTAL)]

PAGED_TOOLS = [
    ("hudu_list_companies", "companies"),
    ("hudu_list_assets", "assets"),
    ("hudu_list_asset_layouts", "asset_layouts"),
    ("hudu_list_asset_passwords", "asset_passwords"),
    ("hudu_list_articles", "articles"),
    ("hudu_list_websites", "websites"),
    ("hudu_list_folders", "folders"),
    ("hudu_list_procedures", "procedures"),
    ("hudu_list_activity_logs", "activity_logs"),
    ("hudu_list_relations", "relations"),
    ("hudu_list_magic_dash", "magic_dash"),
]


def _paged_api(path, rows):
    """Pages by page / page_size like Hudu, under the {<path>: [...]} wrapper."""

    def reply(request):
        number, size = int(request.url.params["page"]), int(request.url.params["page_size"])
        return httpx.Response(200, json={path: rows[(number - 1) * size : number * size]})

    return Recorder({path: reply})


def _sent(rec):
    params = rec.requests[0].url.params
    return int(params["page"]), int(params["page_size"])


async def _walk(monkeypatch, rec, tool, key, args):
    ids, calls, cut = [], 0, 0
    while True:
        result = await _call(monkeypatch, rec, tool, args)
        calls += 1
        assert "retry_page_size" not in result, result.get("note")
        cut += bool(result.get("truncated"))
        ids += [r["id"] for r in result[key]]
        if result.get("next_offset") is None:
            return ids, cut
        args = {k: v for k, v in args.items() if k != "page"} | {"offset": result["next_offset"]}
        assert calls < 200


@pytest.mark.parametrize("tool,key", PAGED_TOOLS)
async def test_cut_pages_continue_without_gaps_from_page_1(monkeypatch, tool, key):
    ids, cut = await _walk(monkeypatch, _paged_api(key, ROWS), tool, key, {"page_size": 50})
    assert cut > 0  # pages really were cut
    assert ids == [r["id"] for r in ROWS]  # no gaps, no duplicates


@pytest.mark.parametrize("tool,key", PAGED_TOOLS)
async def test_cut_pages_continue_without_gaps_from_a_later_page(monkeypatch, tool, key):
    ids, cut = await _walk(monkeypatch, _paged_api(key, ROWS), tool, key, {"page": 3, "page_size": 40})
    assert cut > 0
    assert ids == [r["id"] for r in ROWS[80:]]


@pytest.mark.parametrize("tool,key", PAGED_TOOLS)
@pytest.mark.parametrize("offset,size,page,first", [(30, 25, 2, 30), (50, 25, 3, 50), (0, 25, 1, 0), (7, None, 1, 7)])
async def test_offset_reads_the_page_that_holds_it(monkeypatch, tool, key, offset, size, page, first):
    rec = _paged_api(key, SMALL)
    result = await _call(monkeypatch, rec, tool, {"offset": offset} | ({"page_size": size} if size else {}))
    size = size or 25  # DEFAULT_PAGE_SIZE
    assert _sent(rec) == (page, size)
    assert result[key][0]["id"] == first and result["offset"] == offset
    assert result["next_offset"] == page * size  # rest of the page returned, next page starts after it


@pytest.mark.parametrize("tool,key", PAGED_TOOLS)
async def test_offset_past_the_end_is_empty(monkeypatch, tool, key):
    result = await _call(monkeypatch, _paged_api(key, SMALL), tool, {"offset": 500, "page_size": 25})
    assert (result["count"], result["has_more"], result.get("next_offset")) == (0, False, None)


@pytest.mark.parametrize("tool,key", PAGED_TOOLS)
async def test_offset_wins_over_page(monkeypatch, tool, key):
    rec = _paged_api(key, SMALL)
    result = await _call(monkeypatch, rec, tool, {"offset": 10, "page": 4, "page_size": 10})
    assert _sent(rec) == (2, 10) and result[key][0]["id"] == 10


@pytest.mark.parametrize("tool,key", PAGED_TOOLS)
async def test_page_only_sends_the_same_request_as_before(monkeypatch, tool, key):
    rec = _paged_api(key, SMALL)
    result = await _call(monkeypatch, rec, tool, {"page": 2, "page_size": 25})
    assert set(rec.requests[0].url.params) == {"page", "page_size"} and _sent(rec) == (2, 25)
    assert [r["id"] for r in result[key]] == list(range(25, 50))
    assert (result["page"], result["next_page"], result["has_more"]) == (2, 3, True)
    assert (result["offset"], result["next_offset"]) == (25, 50)


async def test_websites_company_filter_keeps_an_unfiltered_next_offset(monkeypatch):
    rows = [{"id": i, "company_id": 7 if i % 3 == 0 else 8} for i in range(TOTAL)]
    result = await _call(monkeypatch, _paged_api("websites", rows), "hudu_list_websites", {"company_id": 7, "offset": 30, "page_size": 25})
    assert [w["id"] for w in result["websites"]] == [30, 33, 36, 39, 42, 45, 48]
    assert result["next_offset"] == 50  # counts every record of the page, not only the filtered ones
