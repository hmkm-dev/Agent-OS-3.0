FROM python:3.14.7-slim

WORKDIR /app

# Node.js 20 (pinned via the official nodejs.org binary tarball, not
# the NodeSource setup script) + git, required to install and run the
# real OpenCode CLI (npm package: opencode-ai —
# https://opencode.ai/docs/, verified Aug 2026).
#
# Pinned to v20.20.2 — the FINAL Node.js 20 ("Iron") release before
# its End-of-Life on 2026-04-30 (confirmed via nodejs.org's official
# release blog/schedule, Aug 2026 — a real, currently-downloadable
# release, not guessed). Downloading the official linux-x64 tarball
# directly (rather than `curl setup_20.x | bash` + `apt-get install
# nodejs`) avoids depending on an unverified Debian package-revision
# suffix for the apt method, which this session cannot Docker-build
# to confirm exists — the tarball URL and version are independently
# verifiable by anyone via nodejs.org/en/download/archive/v20.
#
# HONEST FLAG, not silently fixed: Node 20 is EOL as of this pin. This
# keeps the existing OpenCode architecture unchanged as instructed (no
# upgrade to Node 22/24 was requested or made here) — treat "migrate
# off Node 20" as a real, separate follow-up decision, not something
# resolved by this pin.
RUN apt-get update && apt-get install -y --no-install-recommends \
        git curl ca-certificates xz-utils \
    && curl -fsSL https://nodejs.org/dist/v20.20.2/node-v20.20.2-linux-x64.tar.xz -o /tmp/node.tar.xz \
    && tar -xJf /tmp/node.tar.xz -C /usr/local --strip-components=1 \
    && rm /tmp/node.tar.xz \
    && rm -rf /var/lib/apt/lists/* \
    && node --version

# Real OpenCode CLI install, pinned to a specific published version
# for production reproducibility (npm registry confirmed 1.18.20 as a
# real, currently-published version — verified via npmjs.com listing,
# not guessed). Bump deliberately: check
# https://www.npmjs.com/package/opencode-ai?activeTab=versions before
# changing this, and re-verify `opencode run` invocation compatibility
# (see services/runtime/agent_runtime.py's docstring for the known
# upstream headless-hang issue this should be checked against).
RUN npm install -g opencode-ai@1.18.20 \
    && opencode --version

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# OpenCode reads provider config from ~/.config/opencode/opencode.json
# (or a project-local opencode.json). entrypoint.sh renders this from
# OPENROUTER_API_KEY at container start, since it's not known at build time.
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app

# Create the /workspace mount point (target of the `agent-workspaces`
# named volume in docker-compose.yml) and give it to appuser BEFORE
# switching users below. Without this, Docker creates the mount point
# owned by root when the volume is first attached, and appuser (UID
# 1000) would be unable to create per-task directories under it,
# clone into them, or let OpenCode modify files there — worker.py's
# os.makedirs(workspace_dir) would fail with a permission error on
# every real task. Must come AFTER `useradd` above, since appuser has
# to exist before it can own anything.
RUN mkdir -p /workspace && chown -R appuser:appuser /workspace

USER appuser

ENTRYPOINT ["/entrypoint.sh"]
CMD ["python", "worker.py"]
