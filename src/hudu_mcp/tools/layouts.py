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
"""Asset layouts: the templates (field sets) assets are built from."""

from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from ..api_client import HuduClient
from ._common import (
    READ_ONLY,
    WRITES,
    WRITES_IDEMPOTENT,
    ClientFactory,
    Offset,
    Page,
    PageSize,
    RecordId,
    Text,
    compact,
    list_page,
    require,
    run_tool,
    unwrap,
)

Flag = Annotated[bool | None, Field(description="Show this section on assets of the layout.")]
LayoutFields = Annotated[
    list[dict[str, Any]] | None,
    Field(description="Field definitions, e.g. [{\"label\": \"IP address\", \"field_type\": \"Text\", \"position\": 1}]."),
]


def _layout(**values: Any) -> dict:
    return compact(values)


def register(mcp: FastMCP, client_factory: ClientFactory) -> None:
    @mcp.tool(annotations=READ_ONLY)
    async def hudu_list_asset_layouts(
        page: Page = None,
        page_size: PageSize = None,
        offset: Offset = None,
        name: Annotated[str | None, Field(description="Exact layout name.")] = None,
    ) -> str:
        """List asset layouts (asset types such as Servers or Firewalls) with their field definitions."""

        async def action(client: HuduClient) -> dict:
            return await list_page(client, "asset_layouts", "asset_layouts", {"name": name}, page, page_size, offset)

        return await run_tool("hudu_list_asset_layouts", client_factory, action)

    @mcp.tool(annotations=READ_ONLY)
    async def hudu_get_asset_layout(id: RecordId) -> str:
        """Get one asset layout and its fields."""

        async def action(client: HuduClient) -> Any:
            return unwrap(await client.get(f"asset_layouts/{id}"), "asset_layout")

        return await run_tool("hudu_get_asset_layout", client_factory, action)

    @mcp.tool(annotations=WRITES)
    async def hudu_create_asset_layout(
        name: Annotated[str, Field(description="Layout name.", min_length=1)],
        icon: Annotated[str | None, Field(description="Font Awesome icon, e.g. fas fa-server.")] = None,
        color: Annotated[str | None, Field(description="Background colour, e.g. #1E90FF.")] = None,
        icon_color: Annotated[str | None, Field(description="Icon colour.")] = None,
        include_passwords: Flag = None,
        include_photos: Flag = None,
        include_comments: Flag = None,
        include_files: Flag = None,
        active: Annotated[bool | None, Field(description="Whether new assets can use the layout.")] = None,
        fields: LayoutFields = None,
    ) -> str:
        """Create an asset layout. Only when the user explicitly asks."""

        async def action(client: HuduClient) -> Any:
            body = _layout(
                name=name,
                icon=icon,
                color=color,
                icon_color=icon_color,
                include_passwords=include_passwords,
                include_photos=include_photos,
                include_comments=include_comments,
                include_files=include_files,
                active=active,
                fields=fields or [],
            )
            return unwrap(await client.post("asset_layouts", {"asset_layout": body}), "asset_layout")

        return await run_tool("hudu_create_asset_layout", client_factory, action)

    @mcp.tool(annotations=WRITES_IDEMPOTENT)
    async def hudu_update_asset_layout(
        id: RecordId,
        name: Text = None,
        icon: Text = None,
        color: Text = None,
        icon_color: Text = None,
        include_passwords: Flag = None,
        include_photos: Flag = None,
        include_comments: Flag = None,
        include_files: Flag = None,
        active: Annotated[bool | None, Field(description="Whether new assets can use the layout.")] = None,
        fields: Annotated[
            list[dict[str, Any]] | None, Field(description="Full field list; fields left out are removed from the layout.")
        ] = None,
    ) -> str:
        """Change an asset layout; a fields list replaces all fields. Only when the user explicitly asks."""

        async def action(client: HuduClient) -> Any:
            body = require(
                _layout(
                    name=name,
                    icon=icon,
                    color=color,
                    icon_color=icon_color,
                    include_passwords=include_passwords,
                    include_photos=include_photos,
                    include_comments=include_comments,
                    include_files=include_files,
                    active=active,
                    fields=fields,
                )
            )
            return unwrap(await client.put(f"asset_layouts/{id}", {"asset_layout": body}), "asset_layout")

        return await run_tool("hudu_update_asset_layout", client_factory, action)
