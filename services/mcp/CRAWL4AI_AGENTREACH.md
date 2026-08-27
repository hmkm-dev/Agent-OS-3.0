# Crawl4AI + Agent Reach

Agent OS exposes two optional MCP capabilities:

- **Crawl4AI**: asynchronous web crawling/extraction through the official Python SDK.
- **Agent Reach**: external capability layer invoked through the installed `agent-reach` CLI.

Crawl4AI is used for reading/crawling web pages; interactive browser actions remain in Playwright. Agent Reach is used as a reading/search capability layer and must not be treated as a browser replacement.

The MCP gateway returns explicit configuration errors when either dependency is unavailable; it never fabricates a successful result.

Install/configure the upstream tools in the deployment environment before enabling these capabilities. Keep credentials/session data outside the repository.
