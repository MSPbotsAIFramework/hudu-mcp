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
"""Assets: documented items of a company, built from asset layouts.

Hudu serves single assets only under their company
(/companies/{company_id}/assets/{id}); /assets is a list endpoint.
"""

from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from ..api_client import HuduClient, HuduError
from ._common import (
    DESTRUCTIVE,
    READ_ONLY,
    WRITES,
    WRITES_IDEMPOTENT,
    ClientFactory,
    CompanyFilter,
    Confirm,
    Offset,
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

AssetCompany = Annotated[int | None, Field(description="Company id of the asset; looked up from the asset id when omitted.", ge=1)]
CustomFields = Annotated[
    dict[str, Any] | None,
    Field(description="Layout field values keyed by field label in snake_case, e.g. {\"ip_address\": \"10.0.0.5\"}."),
]


async def company_of(client: HuduClient, asset_id: int, company_id: int | None) -> int:
    if company_id is not None:
        return company_id
    payload = await client.get("assets", {"id": asset_id})
    rows = payload.get("assets") if isinstance(payload, dict) else payload
    match = next((a for a in rows or [] if isinstance(a, dict) and a.get("id") == asset_id), None)
    if not match or not match.get("company_id"):
        raise HuduError(404, f"No asset with id {asset_id}")
    return int(match["company_id"])


def _custom(fields: dict[str, Any] | None) -> list[dict[str, Any]] | None:
    # Hudu takes custom fields as a list of {label: value} objects.
    return [fields] if fields else None


def register(mcp: FastMCP, client_factory: ClientFactory) -> None:
    @mcp.tool(annotations=READ_ONLY)
    async def hudu_list_assets(
        page: Page = None,
        page_size: PageSize = None,
        offset: Offset = None,
        company_id: CompanyFilter = None,
        asset_layout_id: Annotated[int | None, Field(description="Only assets of this layout (e.g. Servers).", ge=1)] = None,
        name: Annotated[str | None, Field(description="Exact asset name.")] = None,
        primary_serial: Annotated[str | None, Field(description="Serial number.")] = None,
        archived: Annotated[bool | None, Field(description="true for archived assets only.")] = None,
    ) -> str:
        """List assets across companies, by company, layout, name or serial number."""

        async def action(client: HuduClient) -> dict:
            params = {
                "company_id": company_id,
                "asset_layout_id": asset_layout_id,
                "name": name,
                "primary_serial": primary_serial,
                "archived": archived,
            }
            return await list_page(client, "assets", "assets", params, page, page_size, offset)

        return await run_tool("hudu_list_assets", client_factory, action)

    @mcp.tool(annotations=READ_ONLY)
    async def hudu_get_asset(id: RecordId, company_id: AssetCompany = None) -> str:
        """Get one asset with all its layout fields, serial, model, manufacturer and links."""

        async def action(client: HuduClient) -> Any:
            company = await company_of(client, id, company_id)
            return unwrap(await client.get(f"companies/{company}/assets/{id}"), "asset")

        return await run_tool("hudu_get_asset", client_factory, action)

    @mcp.tool(annotations=WRITES)
    async def hudu_create_asset(
        company_id: Annotated[int, Field(description="Company the asset belongs to.", ge=1)],
        asset_layout_id: Annotated[int, Field(description="Asset layout (type) id from hudu_list_asset_layouts.", ge=1)],
        name: Annotated[str, Field(description="Asset name.", min_length=1)],
        primary_serial: Text = None,
        primary_model: Text = None,
        primary_manufacturer: Text = None,
        primary_mail: Text = None,
        custom_fields: CustomFields = None,
    ) -> str:
        """Create an asset for a company from an asset layout. Only when the user explicitly asks."""

        async def action(client: HuduClient) -> Any:
            body = compact(
                {
                    "name": name,
                    "asset_layout_id": asset_layout_id,
                    "primary_serial": primary_serial,
                    "primary_model": primary_model,
                    "primary_manufacturer": primary_manufacturer,
                    "primary_mail": primary_mail,
                    "custom_fields": _custom(custom_fields),
                }
            )
            return unwrap(await client.post(f"companies/{company_id}/assets", {"asset": body}), "asset")

        return await run_tool("hudu_create_asset", client_factory, action)

    @mcp.tool(annotations=WRITES_IDEMPOTENT)
    async def hudu_update_asset(
        id: RecordId,
        name: Text = None,
        company_id: AssetCompany = None,
        asset_layout_id: OptionalId = None,
        primary_serial: Text = None,
        primary_model: Text = None,
        primary_manufacturer: Text = None,
        primary_mail: Text = None,
        custom_fields: CustomFields = None,
    ) -> str:
        """Change an asset; only the fields given change. Only when the user explicitly asks."""

        async def action(client: HuduClient) -> Any:
            body = require(
                compact(
                    {
                        "name": name,
                        "asset_layout_id": asset_layout_id,
                        "primary_serial": primary_serial,
                        "primary_model": primary_model,
                        "primary_manufacturer": primary_manufacturer,
                        "primary_mail": primary_mail,
                        "custom_fields": _custom(custom_fields),
                    }
                )
            )
            company = await company_of(client, id, company_id)
            return unwrap(await client.put(f"companies/{company}/assets/{id}", {"asset": body}), "asset")

        return await run_tool("hudu_update_asset", client_factory, action)

    @mcp.tool(annotations=DESTRUCTIVE)
    async def hudu_delete_asset(id: RecordId, company_id: AssetCompany = None, confirm: Confirm = None) -> str:
        """Permanently delete an asset and its attached passwords and files. Irreversible; needs confirm: true.

        Only when the user explicitly asks; hudu_archive_asset is the reversible option.
        """

        async def action(client: HuduClient) -> Any:
            if confirm is not True:
                return not_confirmed(f"Permanently delete asset {id}")
            company = await company_of(client, id, company_id)
            await client.delete(f"companies/{company}/assets/{id}")
            return {"done": True, "deleted_asset_id": id}

        return await run_tool("hudu_delete_asset", client_factory, action)

    @mcp.tool(annotations=WRITES_IDEMPOTENT)
    async def hudu_archive_asset(id: RecordId, company_id: AssetCompany = None) -> str:
        """Archive an asset (hidden but kept). Only when the user explicitly asks."""

        async def action(client: HuduClient) -> Any:
            company = await company_of(client, id, company_id)
            await client.put(f"companies/{company}/assets/{id}/archive")
            return {"done": True, "archived_asset_id": id}

        return await run_tool("hudu_archive_asset", client_factory, action)
