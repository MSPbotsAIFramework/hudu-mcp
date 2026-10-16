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
"""Monitored websites (uptime, DNS, SSL and WHOIS checks)."""

from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from ..api_client import HuduClient
from ._common import (
    DESTRUCTIVE,
    READ_ONLY,
    WRITES,
    WRITES_IDEMPOTENT,
    ClientFactory,
    Confirm,
    OptionalId,
    Page,
    PageSize,
    RecordId,
    Text,
    compact,
    list_page,
    not_confirmed,
    require,
    run_tool,
    unwrap,
)

Check = Annotated[bool | None, Field(description="Turn this check off.")]


def _website_name(value: str) -> str:
    text = value.strip()
    if not text.lower().startswith(("http://", "https://")):
        raise ValueError("name is the website address and must start with http:// or https://.")
    return text


def register(mcp: FastMCP, client_factory: ClientFactory) -> None:
    @mcp.tool(annotations=READ_ONLY)
    async def hudu_list_websites(
        page: Page = None,
        page_size: PageSize = None,
        name: Annotated[str | None, Field(description="Exact website address.")] = None,
        company_id: Annotated[int | None, Field(description="Only this company's websites (filtered within the page).", ge=1)] = None,
    ) -> str:
        """List monitored websites with status, company, and DNS / SSL / WHOIS monitoring state."""

        async def action(client: HuduClient) -> dict:
            result = await list_page(client, "websites", "websites", {"name": name}, page, page_size)
            if company_id is not None:
                # The websites endpoint has no company filter; apply it to the page.
                result["websites"] = [w for w in result.get("websites", []) if isinstance(w, dict) and w.get("company_id") == company_id]
                result["count"] = len(result["websites"])
                result["company_filtered_in_page"] = True
            return result

        return await run_tool("hudu_list_websites", client_factory, action)

    @mcp.tool(annotations=READ_ONLY)
    async def hudu_get_website(id: RecordId) -> str:
        """Get one monitored website with its latest monitoring results."""

        async def action(client: HuduClient) -> Any:
            return unwrap(await client.get(f"websites/{id}"), "website")

        return await run_tool("hudu_get_website", client_factory, action)

    @mcp.tool(annotations=WRITES)
    async def hudu_create_website(
        name: Annotated[str, Field(description="Website address, e.g. https://www.example.com.", min_length=8)],
        notes: Text = None,
        paused: Annotated[bool | None, Field(description="Create with monitoring paused.")] = None,
        company_id: OptionalId = None,
        disable_dns: Check = None,
        disable_ssl: Check = None,
        disable_whois: Check = None,
    ) -> str:
        """Start monitoring a website for a company. Only when the user explicitly asks."""

        async def action(client: HuduClient) -> Any:
            body = compact(
                {
                    "name": _website_name(name),
                    "notes": notes,
                    "paused": paused,
                    "company_id": company_id,
                    "disable_dns": disable_dns,
                    "disable_ssl": disable_ssl,
                    "disable_whois": disable_whois,
                }
            )
            return unwrap(await client.post("websites", {"website": body}), "website")

        return await run_tool("hudu_create_website", client_factory, action)

    @mcp.tool(annotations=WRITES_IDEMPOTENT)
    async def hudu_update_website(
        id: RecordId,
        name: Annotated[str | None, Field(description="New website address.")] = None,
        notes: Text = None,
        paused: Annotated[bool | None, Field(description="Pause or resume monitoring.")] = None,
        company_id: OptionalId = None,
        disable_dns: Check = None,
        disable_ssl: Check = None,
        disable_whois: Check = None,
    ) -> str:
        """Change a monitored website (address, notes, pause, checks). Only when the user explicitly asks."""

        async def action(client: HuduClient) -> Any:
            body = require(
                compact(
                    {
                        "name": _website_name(name) if name else None,
                        "notes": notes,
                        "paused": paused,
                        "company_id": company_id,
                        "disable_dns": disable_dns,
                        "disable_ssl": disable_ssl,
                        "disable_whois": disable_whois,
                    }
                )
            )
            return unwrap(await client.put(f"websites/{id}", {"website": body}), "website")

        return await run_tool("hudu_update_website", client_factory, action)

    @mcp.tool(annotations=DESTRUCTIVE)
    async def hudu_delete_website(id: RecordId, confirm: Confirm = None) -> str:
        """Stop monitoring and delete a website. Irreversible; needs confirm: true. Only when explicitly asked."""

        async def action(client: HuduClient) -> Any:
            if confirm is not True:
                return not_confirmed(f"Permanently delete website {id}")
            await client.delete(f"websites/{id}")
            return {"done": True, "deleted_website_id": id}

        return await run_tool("hudu_delete_website", client_factory, action)
