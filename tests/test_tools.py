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
"""tools/list snapshot and error-envelope mapping. No network access."""

import asyncio
import json

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from hudu_mcp.api_client import HuduError
from hudu_mcp.server import INSTRUCTIONS, create_mcp_server

ID = {"id"}

# Tool names are a public contract: existing agents and tenant connections
# depend on them. Changing this snapshot is a breaking change.
EXPECTED_TOOLS: dict[str, set[str]] = {
    "hudu_test_connection": set(),
    "hudu_list_companies": set(),
    "hudu_get_company": ID,
    "hudu_create_company": {"name"},
    "hudu_update_company": ID,
    "hudu_delete_company": ID,
    "hudu_archive_company": ID,
    "hudu_unarchive_company": ID,
    "hudu_list_assets": set(),
    "hudu_get_asset": ID,
    "hudu_create_asset": {"company_id", "asset_layout_id", "name"},
    "hudu_update_asset": ID,
    "hudu_delete_asset": ID,
    "hudu_archive_asset": ID,
    "hudu_list_asset_layouts": set(),
    "hudu_get_asset_layout": ID,
    "hudu_create_asset_layout": {"name"},
    "hudu_update_asset_layout": ID,
    "hudu_list_asset_passwords": set(),
    "hudu_get_asset_password": ID,
    "hudu_create_asset_password": {"company_id", "name"},
    "hudu_update_asset_password": ID,
    "hudu_delete_asset_password": ID,
    "hudu_list_articles": set(),
    "hudu_get_article": ID,
    "hudu_create_article": {"name"},
    "hudu_update_article": ID,
    "hudu_delete_article": ID,
    "hudu_archive_article": ID,
    "hudu_list_websites": set(),
    "hudu_get_website": ID,
    "hudu_create_website": {"name"},
    "hudu_update_website": ID,
    "hudu_delete_website": ID,
    "hudu_list_folders": set(),
    "hudu_list_procedures": set(),
    "hudu_list_activity_logs": set(),
    "hudu_list_relations": set(),
    "hudu_list_magic_dash": set(),
}
DELETE_TOOLS = {n for n in EXPECTED_TOOLS if "_delete_" in n}
READ_TOOLS = {n for n in EXPECTED_TOOLS if n.startswith(("hudu_list_", "hudu_get_")) or n == "hudu_test_connection"}


@pytest.fixture(scope="module")
def tools():
    return {t.name: t for t in asyncio.run(create_mcp_server().list_tools())}


def test_tool_names_are_stable(tools):
    assert set(tools) == set(EXPECTED_TOOLS)


@pytest.mark.parametrize("name", sorted(EXPECTED_TOOLS))
def test_required_params(tools, name):
    assert set(tools[name].inputSchema.get("required", [])) == EXPECTED_TOOLS[name]


@pytest.mark.parametrize("name", sorted(EXPECTED_TOOLS))
def test_description_budget(tools, name):
    description = (tools[name].description or "").strip()
    assert description, f"{name} has no description"
    assert len(description) <= 500
    assert len(description.splitlines()[0]) <= 100


@pytest.mark.parametrize("name", sorted(EXPECTED_TOOLS))
def test_annotations_match_side_effects(tools, name):
    annotations = tools[name].annotations
    assert annotations is not None
    assert annotations.readOnlyHint is (name in READ_TOOLS)
    assert bool(annotations.destructiveHint) is (name in DELETE_TOOLS)


@pytest.mark.parametrize("name", sorted(set(EXPECTED_TOOLS) - READ_TOOLS))
def test_write_tools_say_when_to_use_them(tools, name):
    assert "explicitly ask" in tools[name].description


@pytest.mark.parametrize("name", sorted(DELETE_TOOLS))
def test_delete_tools_take_confirm(tools, name):
    assert "confirm" in tools[name].inputSchema["properties"]


@pytest.mark.parametrize("name", ["hudu_get_asset", "hudu_update_asset", "hudu_delete_asset", "hudu_archive_asset"])
def test_asset_tools_accept_company_id(tools, name):
    assert "company_id" in tools[name].inputSchema["properties"]


def test_page_size_is_capped_at_200(tools):
    paged = [t for t in tools.values() if "page_size" in t.inputSchema["properties"]]
    assert len(paged) == 11
    for tool in paged:
        assert tool.inputSchema["properties"]["page_size"]["anyOf"][0]["maximum"] == 200, tool.name
    with pytest.raises(ToolError, match="less than or equal to 200"):
        asyncio.run(create_mcp_server().call_tool("hudu_list_companies", {"page_size": 201}))


def test_instructions_budget():
    assert len(INSTRUCTIONS) <= 1500


@pytest.mark.parametrize(
    "status,code,retryable",
    [
        (401, "unauthorized", False),
        (403, "unauthorized", False),
        (404, "not_found", False),
        (422, "invalid_argument", False),
        (429, "rate_limited", True),
        (500, "upstream_error", True),
        (0, "upstream_error", True),
    ],
)
def test_error_envelope(status, code, retryable):
    envelope = json.loads(HuduError(status, "boom").to_envelope())
    assert envelope == {"error": {"code": code, "message": "boom", "retryable": retryable}}


def test_tool_without_credentials_returns_not_configured():
    content, _ = asyncio.run(create_mcp_server().call_tool("hudu_list_companies", {}))
    assert json.loads(content[0].text)["error"]["code"] == "not_configured"
