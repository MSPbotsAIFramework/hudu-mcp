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
"""Connection check."""

from mcp.server.fastmcp import FastMCP

from ..api_client import HuduClient
from ._common import READ_ONLY, ClientFactory, run_tool


def register(mcp: FastMCP, client_factory: ClientFactory) -> None:
    @mcp.tool(annotations=READ_ONLY)
    async def hudu_test_connection() -> str:
        """Check the Hudu connection and show the instance URL and Hudu version."""

        async def action(client: HuduClient) -> dict:
            info = await client.get("api_info")
            return {"connected": True, "instance": client.instance_url, "api_info": info}

        return await run_tool("hudu_test_connection", client_factory, action)
