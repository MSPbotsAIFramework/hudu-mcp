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
"""Folders, procedures, activity logs, relations and Magic Dash tiles (read-only)."""

from typing import Annotated

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from ..api_client import HuduClient
from ._common import (
    READ_ONLY,
    ClientFactory,
    CompanyFilter,
    Offset,
    Page,
    PageSize,
    list_page,
    run_tool,
)

Name = Annotated[str | None, Field(description="Exact name.")]


def register(mcp: FastMCP, client_factory: ClientFactory) -> None:
    @mcp.tool(annotations=READ_ONLY)
    async def hudu_list_folders(page: Page = None, page_size: PageSize = None, offset: Offset = None, company_id: CompanyFilter = None, name: Name = None) -> str:
        """List knowledge-base folders (global or per company) with their parent folder."""

        async def action(client: HuduClient) -> dict:
            return await list_page(client, "folders", "folders", {"company_id": company_id, "name": name}, page, page_size, offset)

        return await run_tool("hudu_list_folders", client_factory, action)

    @mcp.tool(annotations=READ_ONLY)
    async def hudu_list_procedures(page: Page = None, page_size: PageSize = None, offset: Offset = None, company_id: CompanyFilter = None, name: Name = None) -> str:
        """List procedures (checklists / process templates), global or per company, with completion progress."""

        async def action(client: HuduClient) -> dict:
            return await list_page(client, "procedures", "procedures", {"company_id": company_id, "name": name}, page, page_size, offset)

        return await run_tool("hudu_list_procedures", client_factory, action)

    @mcp.tool(annotations=READ_ONLY)
    async def hudu_list_activity_logs(
        page: Page = None,
        page_size: PageSize = None,
        offset: Offset = None,
        user_id: Annotated[int | None, Field(description="Only actions by this user id.", ge=1)] = None,
        user_email: Annotated[str | None, Field(description="Only actions by this user email.")] = None,
        resource_id: Annotated[int | None, Field(description="Only actions on this record id (with resource_type).", ge=1)] = None,
        resource_type: Annotated[str | None, Field(description="Record type, e.g. Asset, AssetPassword, Article, Company.")] = None,
        action_message: Annotated[str | None, Field(description="Action text, e.g. viewed, updated, deleted.")] = None,
        start_date: Annotated[str | None, Field(description="ISO 8601 date: only activity on or after it.")] = None,
    ) -> str:
        """List the audit trail: who viewed, created, changed or deleted which record, and when."""

        async def action(client: HuduClient) -> dict:
            params = {
                "user_id": user_id,
                "user_email": user_email,
                "resource_id": resource_id,
                "resource_type": resource_type,
                "action_message": action_message,
                "start_date": start_date,
            }
            return await list_page(client, "activity_logs", "activity_logs", params, page, page_size, offset)

        return await run_tool("hudu_list_activity_logs", client_factory, action)

    @mcp.tool(annotations=READ_ONLY)
    async def hudu_list_relations(page: Page = None, page_size: PageSize = None, offset: Offset = None) -> str:
        """List relations: links between records (asset to asset, asset to password, article to company, ...)."""

        async def action(client: HuduClient) -> dict:
            return await list_page(client, "relations", "relations", {}, page, page_size, offset)

        return await run_tool("hudu_list_relations", client_factory, action)

    @mcp.tool(annotations=READ_ONLY)
    async def hudu_list_magic_dash(
        page: Page = None,
        page_size: PageSize = None,
        offset: Offset = None,
        company_id: CompanyFilter = None,
        title: Annotated[str | None, Field(description="Exact tile title.")] = None,
    ) -> str:
        """List Magic Dash tiles: status cards pushed by integrations (e.g. backup state per company)."""

        async def action(client: HuduClient) -> dict:
            return await list_page(client, "magic_dash", "magic_dash", {"company_id": company_id, "title": title}, page, page_size, offset)

        return await run_tool("hudu_list_magic_dash", client_factory, action)
