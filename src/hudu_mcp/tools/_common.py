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
"""Shared argument types, list / record helpers, confirmation and the error-handling wrapper."""

import logging
import time
from collections.abc import Awaitable, Callable
from typing import Annotated, Any

from mcp.types import ToolAnnotations
from pydantic import Field

from .._json import dump_json_capped, error_envelope
from ..api_client import HuduClient, HuduError
from ..config import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE

logger = logging.getLogger("hudu_mcp.tools")

ClientFactory = Callable[[], HuduClient | None]

READ_ONLY = ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=True)
WRITES = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True)
WRITES_IDEMPOTENT = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=True)
DESTRUCTIVE = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=True)

NOT_CONFIGURED = error_envelope(
    "not_configured", "Hudu credentials are missing for this request (X-Hudu-Base-URL, X-Hudu-API-Key).", False
)

RecordId = Annotated[int, Field(description="Numeric Hudu id.", ge=1)]
OptionalId = Annotated[int | None, Field(description="Numeric Hudu id.", ge=1)]
CompanyFilter = Annotated[int | None, Field(description="Only records of this company id.", ge=1)]
Page = Annotated[int | None, Field(description="Page number, from 1 (default 1).", ge=1)]
PageSize = Annotated[int | None, Field(description=f"Records per page (default {DEFAULT_PAGE_SIZE}, max {MAX_PAGE_SIZE}).", ge=1, le=MAX_PAGE_SIZE)]
Offset = Annotated[
    int | None,
    Field(description="Record position to start from (0-based, overrides page); pass next_offset from the previous result.", ge=0),
]
Text = Annotated[str | None, Field(description="Value.")]
Confirm = Annotated[bool | None, Field(description="Must be true, set only after the user approved this exact deletion.")]


def compact(values: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in values.items() if v is not None}


def unwrap(payload: Any, key: str) -> Any:
    """Hudu wraps single records as {"company": {...}}; return the record itself."""
    if isinstance(payload, dict) and isinstance(payload.get(key), (dict, list)) and len(payload) == 1:
        return payload[key]
    return payload


def locate(offset: int | None, page: int | None, page_size: int | None) -> tuple[int, int, int]:
    """(page, page_size, start) for a read from record ``start``.

    Hudu pages by number only, so a position is reached by asking for the page that
    holds it (same page size) and skipping the records before it.
    """
    size = page_size or DEFAULT_PAGE_SIZE
    start = offset if offset is not None else ((page or 1) - 1) * size
    return start // size + 1, size, start


async def list_page(
    client: HuduClient,
    path: str,
    key: str,
    params: dict[str, Any],
    page: int | None,
    page_size: int | None,
    offset: int | None = None,
) -> dict:
    """GET a list endpoint and return {<key>, count, page, has_more, next_page, offset, next_offset}.

    next_offset continues right after the last record returned, also when the result is cut
    to fit the size limit (a page number cannot: the rest of a cut page is on no other page).
    """
    number, size, start = locate(offset, page, page_size)
    payload = await client.get(path, compact(params) | {"page": number, "page_size": size})
    items = payload.get(key) if isinstance(payload, dict) else payload
    items = items if isinstance(items, list) else []
    more = len(items) >= size
    items = items[start - (number - 1) * size :]
    return compact(
        {
            key: items,
            "count": len(items),
            "page": number,
            "has_more": more,
            "next_page": number + 1 if more else None,
            "offset": start,
            "next_offset": start + len(items) if more else None,
            "_resume": {"key": "next_offset", "start": start},
        }
    )


def require(body: dict) -> dict:
    if not body:
        raise ValueError("Nothing to update: pass at least one field to change.")
    return body


def not_confirmed(action: str) -> dict:
    return {
        "done": False,
        "action": action,
        "message": "Not done. Describe this deletion to the user and call again with confirm: true only after they approve it.",
    }


async def run_tool(
    name: str,
    client_factory: ClientFactory,
    action: Callable[[HuduClient], Awaitable[Any]],
) -> str:
    """Resolve the caller's client, run ``action``, and always return a string.

    Errors never escape as exceptions: they become the standard error envelope.
    """
    client = client_factory()
    if client is None:
        return NOT_CONFIGURED
    started = time.monotonic()
    try:
        result = await action(client)
    except HuduError as e:
        logger.info("tool=%s outcome=error status=%s ms=%d", name, e.status_code, _ms(started))
        return e.to_envelope()
    except ValueError as e:
        logger.info("tool=%s outcome=invalid_argument ms=%d", name, _ms(started))
        return error_envelope("invalid_argument", str(e), False)
    except Exception as e:  # noqa: BLE001 - tools must never raise
        logger.warning("tool=%s outcome=unexpected error=%s ms=%d", name, type(e).__name__, _ms(started))
        return error_envelope("upstream_error", f"Unexpected error: {type(e).__name__}", True)
    logger.info("tool=%s outcome=ok ms=%d", name, _ms(started))
    if result is None:
        result = {"done": True}
    return result if isinstance(result, str) else dump_json_capped(result)


def _ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)
