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
"""Stored passwords (asset passwords).

Listing hides secret values so a whole company's credentials never land in
the agent's context at once; a single password is revealed by id.
"""

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

SECRET_FIELDS = ("password", "otp_secret")


def mask(record: Any) -> Any:
    if not isinstance(record, dict):
        return record
    masked = dict(record)
    for field in SECRET_FIELDS:
        if field in masked:
            masked[f"has_{field}"] = bool(masked[field])
            masked[field] = "********" if masked[field] else masked[field]
    return masked


def register(mcp: FastMCP, client_factory: ClientFactory) -> None:
    @mcp.tool(annotations=READ_ONLY)
    async def hudu_list_asset_passwords(
        page: Page = None,
        page_size: PageSize = None,
        company_id: CompanyFilter = None,
        name: Annotated[str | None, Field(description="Exact password entry name.")] = None,
        search: Annotated[str | None, Field(description="Text in the name, username or URL.")] = None,
    ) -> str:
        """List stored passwords (name, username, URL, type, linked asset); secret values are hidden.

        Use hudu_get_asset_password to reveal one password.
        """

        async def action(client: HuduClient) -> dict:
            params = {"company_id": company_id, "name": name, "search": search}
            result = await list_page(client, "asset_passwords", "asset_passwords", params, page, page_size)
            result["asset_passwords"] = [mask(p) for p in result.get("asset_passwords", [])]
            return result

        return await run_tool("hudu_list_asset_passwords", client_factory, action)

    @mcp.tool(annotations=READ_ONLY)
    async def hudu_get_asset_password(id: RecordId) -> str:
        """Get one stored password with the secret in clear text. Only when the user needs that credential."""

        async def action(client: HuduClient) -> Any:
            return unwrap(await client.get(f"asset_passwords/{id}"), "asset_password")

        return await run_tool("hudu_get_asset_password", client_factory, action)

    @mcp.tool(annotations=WRITES)
    async def hudu_create_asset_password(
        company_id: Annotated[int, Field(description="Company the password belongs to.", ge=1)],
        name: Annotated[str, Field(description="Entry name.", min_length=1)],
        username: Text = None,
        password: Annotated[str | None, Field(description="The secret to store.")] = None,
        otp_secret: Annotated[str | None, Field(description="TOTP seed for one-time codes.")] = None,
        url: Text = None,
        password_type: Annotated[str | None, Field(description="Password type label.")] = None,
        description: Text = None,
        passwordable_type: Annotated[str | None, Field(description="Type of the record it is attached to, e.g. Asset.")] = None,
        passwordable_id: OptionalId = None,
        in_portal: Annotated[bool | None, Field(description="Show it in the client portal.")] = None,
        password_folder_id: OptionalId = None,
    ) -> str:
        """Store a new password for a company (optionally on an asset). Only when the user explicitly asks."""

        async def action(client: HuduClient) -> Any:
            body = compact(
                {
                    "company_id": company_id,
                    "name": name,
                    "username": username,
                    "password": password,
                    "otp_secret": otp_secret,
                    "url": url,
                    "password_type": password_type,
                    "description": description,
                    "passwordable_type": passwordable_type,
                    "passwordable_id": passwordable_id,
                    "in_portal": in_portal,
                    "password_folder_id": password_folder_id,
                }
            )
            return mask(unwrap(await client.post("asset_passwords", {"asset_password": body}), "asset_password"))

        return await run_tool("hudu_create_asset_password", client_factory, action)

    @mcp.tool(annotations=WRITES_IDEMPOTENT)
    async def hudu_update_asset_password(
        id: RecordId,
        name: Text = None,
        username: Text = None,
        password: Annotated[str | None, Field(description="New secret.")] = None,
        otp_secret: Annotated[str | None, Field(description="New TOTP seed.")] = None,
        url: Text = None,
        password_type: Text = None,
        description: Text = None,
    ) -> str:
        """Change a stored password entry; only the fields given change. Only when the user explicitly asks."""

        async def action(client: HuduClient) -> Any:
            body = require(
                compact(
                    {
                        "name": name,
                        "username": username,
                        "password": password,
                        "otp_secret": otp_secret,
                        "url": url,
                        "password_type": password_type,
                        "description": description,
                    }
                )
            )
            return mask(unwrap(await client.put(f"asset_passwords/{id}", {"asset_password": body}), "asset_password"))

        return await run_tool("hudu_update_asset_password", client_factory, action)

    @mcp.tool(annotations=DESTRUCTIVE)
    async def hudu_delete_asset_password(id: RecordId, confirm: Confirm = None) -> str:
        """Permanently delete a stored password. Irreversible; needs confirm: true. Only when explicitly asked."""

        async def action(client: HuduClient) -> Any:
            if confirm is not True:
                return not_confirmed(f"Permanently delete stored password {id}")
            await client.delete(f"asset_passwords/{id}")
            return {"done": True, "deleted_asset_password_id": id}

        return await run_tool("hudu_delete_asset_password", client_factory, action)
