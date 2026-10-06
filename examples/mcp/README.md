# MCP clients

Install from a source checkout with Python 3.12+: `python -m pip install -e .`.
The current candidate is unpublished; `pip install kabuforge` is the intended
stable PyPI command after publication. A release candidate needs `--pre` or an
explicit version. Run `kabuforge doctor` before connecting a client.

Replace both absolute paths in the examples. On Windows the command is
`C:/path/to/venv/Scripts/kabuforge.exe`; forward slashes work in JSON. The workspace
is a local directory dedicated to this client. Do not put secrets in these files.

| Client | Configuration |
| --- | --- |
| Claude Desktop | Merge `claude-desktop.json` into `claude_desktop_config.json` via Settings → Developer → Edit Config; restart Desktop |
| Claude Code | Merge `claude-code.json` into the project's `.mcp.json`, or use the command below |
| Cursor | Merge `cursor.json` into `.cursor/mcp.json` or `~/.cursor/mcp.json`; enable the server in MCP settings |
| Generic stdio | Start the command below; send newline-delimited JSON-RPC on stdin and read responses on stdout |

```shell
claude mcp add --transport stdio kabuforge -- /absolute/path/to/venv/bin/kabuforge --locale en_US mcp --workspace /absolute/path/to/agent_workspace
/absolute/path/to/venv/bin/kabuforge --locale en_US mcp --workspace /absolute/path/to/agent_workspace
```

Verify `initialize`, `notifications/initialized`, and `tools/list`. Research uses
explicit inputs beneath the workspace. Paper writes are disabled by default;
enabling paper requires the server's `--enable-paper` flag and each tool's explicit
opt-in. These examples retain the default. Results remain RESEARCH-ONLY with
`pit_guarantee=false`; no broker order submission is supported.

Sources: [Claude Code](https://code.claude.com/docs/en/mcp),
[Claude Desktop](https://modelcontextprotocol.io/quickstart/user),
[Cursor](https://prod.cursor.com/docs/mcp).
