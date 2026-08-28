FROM mcr.microsoft.com/playwright/python:v1.47.0-jammy

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# tmpfs-mounted at runtime via docker-compose (see playwright service definition)
RUN mkdir -p /tmp/browser-artifacts

# Non-root: the official Playwright image already ships with pwuser.
# Reuse that user, grant it ownership of the app dir + browser cache +
# tmp artifacts dir, and run as that user. If browser launch fails with a
# sandbox/permission error after this change, the fallback (documented, not
# silently reverted) is to add `--no-sandbox` to the Chromium launch args in
# server.py — this is a known tradeoff for non-root Chromium in containers.
RUN chown -R pwuser:pwuser /app /tmp/browser-artifacts /ms-playwright
USER pwuser

EXPOSE 8200

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8200"]
