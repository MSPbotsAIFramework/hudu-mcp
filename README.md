# Hudu MCP Server

An [MCP](https://modelcontextprotocol.io) server for the [Hudu](https://www.hudu.com) API (v1),
the IT documentation platform MSPs use per client. It lets an AI agent read companies,
documented assets and their layouts, stored passwords, knowledge-base articles and folders,
monitored websites, procedures, relations, Magic Dash tiles and the activity (audit) log and,
on explicit request, create, update and archive records and (with confirmation) delete them.

- Transport: MCP Streamable HTTP at `POST /mcp`, health probe at `GET /health`
- Stateless and multi-tenant: credentials arrive on every request as HTTP headers and are
  never stored; every tool is listed from the first `tools/list`
- Python 3.12, [uv](https://docs.astral.sh/uv/), FastMCP, httpx
- License: Apache-2.0, Copyright 2026 MSPbots.ai

<div align="center">

## MSPbots Connector

**The MCP Gateway built for MSPs: visible, controlled, and your data stays where it belongs.**

[**Get started at connect.mspbots.ai →**](https://connect.mspbots.ai)

</div>

---

MSPbots Connector gives your AI clients one MCP URL to reach your entire MSP stack (RMM, PSA, documentation, security, finance), and gives you control over who can call which tool and a record of everything that was called.

**Hosted service: [connect.mspbots.ai](https://connect.mspbots.ai)** · Free to use.

### Why Connector

![MSPbots Connector](https://stgoss.mspbots.ai/files/mcp/mspbots-mcp.png)

| | |
|---|---|
| **Visible** | Every tool call is logged: who, which vendor, when. Usage dashboard, CSV export, SIEM streaming. |
| **Controlled** | Role-based, per-tool allowlist. Deny by default. |
| **Protected** | Credentials encrypted per record. AI clients never see your vendor passwords or tokens. |
| **MSP-native** | Built for the MSP stack only: RMM, PSA, documentation, security, finance. |

### Quick start

1. **Sign up** at [connect.mspbots.ai](https://connect.mspbots.ai).
2. **Connect your vendors.** Pick from 150+ connectors and authorize each one on the vendor's own page, or bring your own API keys. No extra vendor accounts needed.
3. **Set access.** Create roles and decide which tools each role may call. Nothing is allowed until you allow it.
4. **Add your MCP URL to your AI client.** Copy the URL from your Connector dashboard into Claude, ChatGPT, Cursor, VS Code, Gemini, Codex, or any MCP-capable client.
5. **Ask your AI to do real work**, and watch every call appear in the audit log.

### Features

**Unified gateway**
- One MCP URL for all your AI clients
- 150+ connectors across the MSP stack
- Custom MCP servers supported, free
- Authorization happens on each vendor's own page; the AI never sees passwords or tokens
- Bring your own credentials: use the vendor API keys you already have
- Multiple accounts per app; connect once, reuse across AI clients
- Tool search: finds the right action for the task
- One sign-in; vendor credentials are injected behind the scenes and OAuth tokens refresh automatically

**Visibility**
- Audit log for every tool call (who, which vendor, when)
- Usage dashboard: call volume, top vendors, error rate, per-user activity
- Export audit logs to CSV, or stream to Loki, Graylog, or LogScale (SIEM)
- Optional recording of tool arguments and result summaries (off by default, enabled per organization)

**Control**
- Per-role, per-tool allowlist, deny by default
- owner / admin / member roles
- SCIM provisioning with Entra ID, Okta, JumpCloud, and Google Workspace

**Security**
- Credentials encrypted one record at a time (AES-256-GCM, per-record key)
- AI clients authenticate with OAuth 2.1 + PKCE
- Vendor responses are scanned for prompt-injection patterns and returned as structured data. This is one layer of defense, not a guarantee against every attack.
- Static egress IP for customer firewall and API allowlisting

### Pricing

**Free.**

Links: [connect.mspbots.ai](https://connect.mspbots.ai) · [mspbots.ai](https://mspbots.ai)

---

## Authentication headers

| Header | Required | Type | Default | Allowed values | Description | Example |
|---|---|---|---|---|---|---|
| `X-Hudu-Base-URL` | Yes | string | none | https URL | Root URL of the Hudu instance (a bare host gets `https://`; a trailing `/api/v1` is removed) | `https://docs.example.com` |
| `X-Hudu-API-Key` | Yes | string | none | - | Hudu API key | `your-hudu-api-key` |

Where to get them: in Hudu open the **Admin** area's API key settings and create a key. Use
the key options Hudu offers (such as limiting the key or its access to passwords) to give the
agent only what it needs. If Hudu restricts API access by IP, allow the public egress IP of
the environment that runs this server.

How the key is sent to Hudu: every call goes to `{X-Hudu-Base-URL}/api/v1/...` with the key in
the `x-api-key` header.

A request to `/mcp` without both headers gets HTTP 401 naming the missing one; a non-https URL
gets HTTP 400.

## Tools

All tools return a JSON string. List tools take `page` and `page_size` (default 25, max 200)
and return `{count, page, has_more, next_page, offset, next_offset}`. They also take `offset`
(a 0-based record position that overrides `page`): pass `next_offset` to continue, because when a
page is cut to fit the response size limit the rest of it is on no other page number. **write** marks tools that change data;
**confirm** marks deletes, which also need `confirm: true`.

| Area | Tools |
|---|---|
| Connection | `hudu_test_connection` |
| Companies | `hudu_list_companies` (name, id_number, website, phone_number, city, state, archived), `hudu_get_company` (**id**); **write**: `hudu_create_company` (**name**), `hudu_update_company` (**id**), `hudu_archive_company` (**id**), `hudu_unarchive_company` (**id**); **confirm**: `hudu_delete_company` (**id**) |
| Assets | `hudu_list_assets` (company_id, asset_layout_id, name, primary_serial, archived), `hudu_get_asset` (**id**, company_id); **write**: `hudu_create_asset` (**company_id**, **asset_layout_id**, **name**, custom_fields), `hudu_update_asset` (**id**, company_id), `hudu_archive_asset` (**id**, company_id); **confirm**: `hudu_delete_asset` (**id**, company_id) |
| Asset layouts | `hudu_list_asset_layouts` (name), `hudu_get_asset_layout` (**id**); **write**: `hudu_create_asset_layout` (**name**, fields), `hudu_update_asset_layout` (**id**) |
| Passwords | `hudu_list_asset_passwords` (company_id, name, search; secrets hidden), `hudu_get_asset_password` (**id**; secret in clear text); **write**: `hudu_create_asset_password` (**company_id**, **name**), `hudu_update_asset_password` (**id**); **confirm**: `hudu_delete_asset_password` (**id**) |
| Articles | `hudu_list_articles` (company_id, name, draft), `hudu_get_article` (**id**); **write**: `hudu_create_article` (**name**), `hudu_update_article` (**id**), `hudu_archive_article` (**id**); **confirm**: `hudu_delete_article` (**id**) |
| Websites | `hudu_list_websites` (name, company_id), `hudu_get_website` (**id**); **write**: `hudu_create_website` (name = the URL, or its alias url), `hudu_update_website` (**id**; name or url); **confirm**: `hudu_delete_website` (**id**) |
| Other | `hudu_list_folders`, `hudu_list_procedures`, `hudu_list_activity_logs` (user, resource, action, start_date), `hudu_list_relations`, `hudu_list_magic_dash` (company_id, title) |

Errors come back as a JSON envelope instead of an exception:

```json
{"error": {"code": "invalid_argument", "message": "Hudu returned HTTP 422 for companies: name has already been taken", "retryable": false}}
```

`code` is one of `not_configured`, `unauthorized`, `not_found`, `invalid_argument`,
`rate_limited`, `upstream_error`. Reads are retried with backoff on 429, 5xx and network
errors; writes only on 429. Hudu allows about 300 API requests per minute per instance.

## Run locally

```bash
uv sync
uv run python -m hudu_mcp          # listens on 0.0.0.0:8080
```

or with Docker:

```bash
docker build --platform linux/amd64 -t hudu-mcp:dev .
docker run --rm -p 8080:8080 hudu-mcp:dev
```

Configuration (environment variables, all optional): `MCP_HTTP_HOST` (default `0.0.0.0`),
`MCP_HTTP_PORT` (default `8080`), `LOG_LEVEL` (default `INFO`). Credentials are never read
from the environment.

## Testing example

```bash
# list tools
curl -s http://localhost:8080/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "X-Hudu-Base-URL: https://docs.example.com" \
  -H "X-Hudu-API-Key: your-hudu-api-key" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'

# assets of one company
curl -s http://localhost:8080/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "X-Hudu-Base-URL: https://docs.example.com" \
  -H "X-Hudu-API-Key: your-hudu-api-key" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"hudu_list_assets","arguments":{"company_id":12}}}'
```

Unit tests (no network access needed):

```bash
uv run pytest
```

## Delivery notes

- **Tool count (39).** Kept as is because the tool names are an existing contract.
- **Asset routes fixed.** Hudu serves single assets only under their company
  (`/companies/{company_id}/assets/{id}`); older versions called `/assets/{id}`, which does not
  exist, so getting, updating, deleting and archiving assets failed. The four tools now take an
  optional `company_id` and look it up from the asset id when it is omitted.
- **Password handling.** `hudu_list_asset_passwords` returns entries with `password` and
  `otp_secret` masked (plus `has_password` / `has_otp_secret`), so a company's credentials are
  not all exposed at once; `hudu_get_asset_password` reveals one entry. Create / update results
  are masked too.
- **Deletes need confirmation.** The five delete tools take `confirm: true` and otherwise
  return a "not done" result; archiving is the reversible alternative.
- **Websites.** Hudu stores the website address as its `name` (the API has no `url` field).
  `url` is accepted as an alias and sent as `name`; passing both with different values is
  rejected as `invalid_argument`. The websites list has no server-side company filter, so
  `company_id` filters the returned page.
- **Request bodies** are wrapped in the resource name Hudu expects (`{"company": {...}}`,
  `{"asset": {...}}`, ...).

## License

Apache License 2.0 - see [LICENSE](LICENSE) and [NOTICE](NOTICE).
