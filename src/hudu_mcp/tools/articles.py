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
"""Knowledge-base articles (global or per company)."""

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
    CompanyFilter,
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

Sharing = Annotated[bool | None, Field(description="Allow a public share link.")]
Draft = Annotated[bool | None, Field(description="Keep the article as a draft.")]


def register(mcp: FastMCP, client_factory: ClientFactory) -> None:
    @mcp.tool(annotations=READ_ONLY)
    async def hudu_list_articles(
        page: Page = None,
        page_size: PageSize = None,
        company_id: CompanyFilter = None,
        name: Annotated[str | None, Field(description="Exact article title.")] = None,
        draft: Annotated[bool | None, Field(description="true for drafts only, false for published only.")] = None,
    ) -> str:
        """List knowledge-base articles (title, company, folder, draft flag, share link)."""

        async def action(client: HuduClient) -> dict:
            params = {"company_id": company_id, "name": name, "draft": draft}
            return await list_page(client, "articles", "articles", params, page, page_size)

        return await run_tool("hudu_list_articles", client_factory, action)

    @mcp.tool(annotations=READ_ONLY)
    async def hudu_get_article(id: RecordId) -> str:
        """Get one article including its HTML content."""

        async def action(client: HuduClient) -> Any:
            return unwrap(await client.get(f"articles/{id}"), "article")

        return await run_tool("hudu_get_article", client_factory, action)

    @mcp.tool(annotations=WRITES)
    async def hudu_create_article(
        name: Annotated[str, Field(description="Article title.", min_length=1)],
        content: Annotated[str | None, Field(description="Article body (HTML).")] = None,
        folder_id: OptionalId = None,
        company_id: Annotated[int | None, Field(description="Company the article belongs to; omit for a global article.", ge=1)] = None,
        enable_sharing: Sharing = None,
        draft: Draft = None,
    ) -> str:
        """Create a knowledge-base article. Only when the user explicitly asks."""

        async def action(client: HuduClient) -> Any:
            body = compact(
                {"name": name, "content": content, "folder_id": folder_id, "company_id": company_id, "enable_sharing": enable_sharing, "draft": draft}
            )
            return unwrap(await client.post("articles", {"article": body}), "article")

        return await run_tool("hudu_create_article", client_factory, action)

    @mcp.tool(annotations=WRITES_IDEMPOTENT)
    async def hudu_update_article(
        id: RecordId,
        name: Text = None,
        content: Annotated[str | None, Field(description="New body (HTML); replaces the old one.")] = None,
        folder_id: OptionalId = None,
        company_id: OptionalId = None,
        enable_sharing: Sharing = None,
        draft: Draft = None,
    ) -> str:
        """Change an article; only the fields given change. Only when the user explicitly asks."""

        async def action(client: HuduClient) -> Any:
            body = require(
                compact(
                    {"name": name, "content": content, "folder_id": folder_id, "company_id": company_id, "enable_sharing": enable_sharing, "draft": draft}
                )
            )
            return unwrap(await client.put(f"articles/{id}", {"article": body}), "article")

        return await run_tool("hudu_update_article", client_factory, action)

    @mcp.tool(annotations=DESTRUCTIVE)
    async def hudu_delete_article(id: RecordId, confirm: Confirm = None) -> str:
        """Permanently delete an article. Irreversible; needs confirm: true (archiving is reversible).

        Only when the user explicitly asks.
        """

        async def action(client: HuduClient) -> Any:
            if confirm is not True:
                return not_confirmed(f"Permanently delete article {id}")
            await client.delete(f"articles/{id}")
            return {"done": True, "deleted_article_id": id}

        return await run_tool("hudu_delete_article", client_factory, action)

    @mcp.tool(annotations=WRITES_IDEMPOTENT)
    async def hudu_archive_article(id: RecordId) -> str:
        """Archive an article (hidden but kept). Only when the user explicitly asks."""

        async def action(client: HuduClient) -> Any:
            await client.put(f"articles/{id}/archive")
            return {"done": True, "archived_article_id": id}

        return await run_tool("hudu_archive_article", client_factory, action)
