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
"""Companies: the MSP's documented clients."""

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


def _company(**fields: Any) -> dict:
    return compact(fields)


def register(mcp: FastMCP, client_factory: ClientFactory) -> None:
    @mcp.tool(annotations=READ_ONLY)
    async def hudu_list_companies(
        page: Page = None,
        page_size: PageSize = None,
        name: Annotated[str | None, Field(description="Exact company name.")] = None,
        id_number: Annotated[str | None, Field(description="Company id number (e.g. the PSA id).")] = None,
        website: Text = None,
        phone_number: Text = None,
        city: Text = None,
        state: Text = None,
        archived: Annotated[bool | None, Field(description="true for archived companies only.")] = None,
    ) -> str:
        """List companies (clients) with type, address, phone and website; filter by name, id number or place."""

        async def action(client: HuduClient) -> dict:
            params = {
                "name": name,
                "id_number": id_number,
                "website": website,
                "phone_number": phone_number,
                "city": city,
                "state": state,
                "archived": archived,
            }
            return await list_page(client, "companies", "companies", params, page, page_size)

        return await run_tool("hudu_list_companies", client_factory, action)

    @mcp.tool(annotations=READ_ONLY)
    async def hudu_get_company(id: RecordId) -> str:
        """Get one company with its address, notes and integration links."""

        async def action(client: HuduClient) -> Any:
            return unwrap(await client.get(f"companies/{id}"), "company")

        return await run_tool("hudu_get_company", client_factory, action)

    @mcp.tool(annotations=WRITES)
    async def hudu_create_company(
        name: Annotated[str, Field(description="Company name.", min_length=1)],
        nickname: Text = None,
        company_type: Annotated[str | None, Field(description="Company type, e.g. Client or Vendor.")] = None,
        address_line_1: Text = None,
        address_line_2: Text = None,
        city: Text = None,
        state: Text = None,
        zip: Text = None,
        country_name: Text = None,
        phone_number: Text = None,
        fax_number: Text = None,
        website: Text = None,
        id_number: Text = None,
        notes: Text = None,
        parent_company_id: OptionalId = None,
    ) -> str:
        """Create a company. Only when the user explicitly asks."""

        async def action(client: HuduClient) -> Any:
            body = _company(
                name=name,
                nickname=nickname,
                company_type=company_type,
                address_line_1=address_line_1,
                address_line_2=address_line_2,
                city=city,
                state=state,
                zip=zip,
                country_name=country_name,
                phone_number=phone_number,
                fax_number=fax_number,
                website=website,
                id_number=id_number,
                notes=notes,
                parent_company_id=parent_company_id,
            )
            return unwrap(await client.post("companies", {"company": body}), "company")

        return await run_tool("hudu_create_company", client_factory, action)

    @mcp.tool(annotations=WRITES_IDEMPOTENT)
    async def hudu_update_company(
        id: RecordId,
        name: Text = None,
        nickname: Text = None,
        company_type: Text = None,
        address_line_1: Text = None,
        address_line_2: Text = None,
        city: Text = None,
        state: Text = None,
        zip: Text = None,
        country_name: Text = None,
        phone_number: Text = None,
        fax_number: Text = None,
        website: Text = None,
        id_number: Text = None,
        notes: Text = None,
        parent_company_id: OptionalId = None,
    ) -> str:
        """Change a company; only the fields given change. Only when the user explicitly asks."""

        async def action(client: HuduClient) -> Any:
            body = require(
                _company(
                    name=name,
                    nickname=nickname,
                    company_type=company_type,
                    address_line_1=address_line_1,
                    address_line_2=address_line_2,
                    city=city,
                    state=state,
                    zip=zip,
                    country_name=country_name,
                    phone_number=phone_number,
                    fax_number=fax_number,
                    website=website,
                    id_number=id_number,
                    notes=notes,
                    parent_company_id=parent_company_id,
                )
            )
            return unwrap(await client.put(f"companies/{id}", {"company": body}), "company")

        return await run_tool("hudu_update_company", client_factory, action)

    @mcp.tool(annotations=DESTRUCTIVE)
    async def hudu_delete_company(id: RecordId, confirm: Confirm = None) -> str:
        """Permanently delete a company and all of its documentation. Irreversible; needs confirm: true.

        Only when the user explicitly asks; hudu_archive_company is the reversible option.
        """

        async def action(client: HuduClient) -> Any:
            if confirm is not True:
                return not_confirmed(f"Permanently delete company {id} and all its assets, passwords and articles")
            await client.delete(f"companies/{id}")
            return {"done": True, "deleted_company_id": id}

        return await run_tool("hudu_delete_company", client_factory, action)

    @mcp.tool(annotations=WRITES_IDEMPOTENT)
    async def hudu_archive_company(id: RecordId) -> str:
        """Archive a company (hidden but kept; hudu_unarchive_company restores it). Only when explicitly asked."""

        async def action(client: HuduClient) -> Any:
            await client.put(f"companies/{id}/archive")
            return {"done": True, "archived_company_id": id}

        return await run_tool("hudu_archive_company", client_factory, action)

    @mcp.tool(annotations=WRITES_IDEMPOTENT)
    async def hudu_unarchive_company(id: RecordId) -> str:
        """Restore an archived company. Only when the user explicitly asks."""

        async def action(client: HuduClient) -> Any:
            await client.put(f"companies/{id}/unarchive")
            return {"done": True, "unarchived_company_id": id}

        return await run_tool("hudu_unarchive_company", client_factory, action)
