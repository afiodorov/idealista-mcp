## AWS Lambda (`lambda` branch)

This fork adds a Python 3.13 Lambda Function URL adapter and fixes upstream
request signing for location names containing spaces (for example, Las Palmas).
Signatures use form encoding (`+` for spaces), matching Idealista's verifier;
upstream v0.1.1 used `%20`, causing HTTP 400 "Invalid request headers".
The five MCP tools and their schemas remain compatible with upstream.

```sh
make test-lambda
make lambda-package
# Or: python3 lambda_package.py --output /path/to/build
```

`lambda_package.py` runs the Go tests and builds this checkout for **Linux ARM64**
using a digest-pinned Go 1.26.1 Docker image. Docker is required; a local Go
installation is not. It writes `pkg/idealista-mcp`, `pkg/lambda_handler.py`,
`pkg/README.md` and `pkg/build-info.json` beneath the output directory. The build
metadata records the source revision, dirty state and binary checksum. No
credentials are bundled. The existing Go build targets also remain available.

Deploy the package on an ARM64 Python 3.13 Lambda. The application handler is
`lambda_handler.handler`; the deployment must put an authentication gate in front
of it. The handler alone does not authenticate callers. Our deployment uses the
shared GitHub OAuth gate from the separate private infrastructure repository,
including on the bare Function URL.

Required environment variables:

| Variable | Purpose |
| --- | --- |
| `IDEALISTA_CLIENT_KEY` | OAuth client ID |
| `IDEALISTA_CLIENT_SECRET` | OAuth client secret |
| `IDEALISTA_SIGNING_SECRET` | Raw request-signing secret, distinct from the OAuth secret |

Inject secrets from your deployment's secret store, never commit them. The
signing secret is the **raw** value; upstream base64-encodes it internally. A
pre-encoded value would be encoded twice and signatures would fail.

The adapter exposes stateless Streamable HTTP with JSON responses. It delegates
protocol negotiation and tool handling to a new stdio process per invocation;
notifications return 202, and GET/SSE is unsupported. The private `/tmp` config
and upstream OAuth token/device cache are reused by warm invocations. The child
does not inherit AWS credentials, gate secrets, or debug flags. Adapter errors
hide subprocess stderr and redact upstream credentials and cached bearer tokens.
Allow a 60-second Lambda timeout (the adapter bounds requests to 55 seconds).

The local transport tests run without credentials or network access:
`python3 -m unittest test_lambda_handler -v`.

---

<div align="center">

**MCP server for the Idealista property search platform**

*Ask your AI assistant to search for properties, filter by price or size, and find location IDs — right from the chat*

<p>
  <img src="https://img.shields.io/github/v/release/galimru/idealista-mcp" alt="Latest release">
  <img src="https://img.shields.io/badge/MCP-compatible-blueviolet" alt="MCP">
  <img src="https://img.shields.io/badge/Go-1.23+-00ADD8?style=flat&logo=go&logoColor=white" alt="Go">
  <img src="https://img.shields.io/badge/license-MIT-blue" alt="License">
</p>

</div>

---

Connect your AI assistant to Idealista. Search for properties for sale or rent, filter by price, size, and rooms, search around a center point, and resolve location names to IDs — all through natural conversation.

## Quick Start

**1. Install**

Download a binary from the [releases page](https://github.com/galimru/idealista-mcp/releases).

Or build from source:

```bash
git clone https://github.com/galimru/idealista-mcp.git
cd idealista-mcp
make install
```

**2. Connect to Claude Desktop**

Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "idealista": {
      "command": "/path/to/idealista-mcp"
    }
  }
}
```

Then edit `~/.config/idealista-mcp/config.json`:

```json
{
  "client_key": "your-client-key",
  "client_secret": "your-client-secret",
  "signing_secret": "your-signing-secret"
}
```

## Tools

| Tool | What it does |
|------|--------------|
| `search_locations` | Search for location IDs by name prefix (needed as input for `search_ads`) |
| `search_ads` | Search property listings by location ID or by `center` + `distance`, with filters for price, size, rooms, and more |

### Example workflow

1. Use `search_locations` with `prefix=Valencia` to get the location ID for Valencia
2. Use `search_ads` with the returned `location_id` to browse listings

You can also search by coordinates using:
- `center` in `lat,lng` format
- `distance` in metres

`search_ads` accepts either `location_id` or `center` + `distance`, but not both together.

## Configuration

**Config file**

`idealista-mcp` stores required credentials in `~/.config/idealista-mcp/config.json`.
If the file does not exist, the server creates it with empty string values on first use.

| Field | Required | Description |
|-------|----------|-------------|
| `client_key` | Yes | OAuth client key (client ID) |
| `client_secret` | Yes | OAuth client secret |
| `signing_secret` | Yes | Raw HMAC-SHA256 signing secret for request authentication |

**Environment variables**

| Variable | Required | Description |
|----------|----------|-------------|
| `IDEALISTA_DEBUG` | No | Set to any non-empty value to log HTTP traffic to stderr |

The server starts and advertises tools even if the config file is incomplete. Missing credentials fail individual tool calls with an actionable error pointing at the config path.

A persistent session file is stored at `~/.config/idealista-mcp/session.json`. It holds a stable device identifier (generated once on first authenticated call) and the cached OAuth token so restarts reuse a valid token without re-fetching.

## Notes

- This project is not affiliated with Idealista or its parent company.

## Contributing

Bug fixes and clear improvements are welcome. Open an issue first for anything non-trivial.

## License

MIT
