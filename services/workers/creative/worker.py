"""
Creative worker — real queue plumbing via BaseWorker. Calls the model
router for copy generation and uploads finished artifacts to R2
rather than storing them inline in Redis/Postgres.
"""

import os
import uuid

import boto3
import httpx
from base_worker import BaseWorker

MODEL_ROUTER_URL = os.environ.get("MODEL_ROUTER_URL", "http://hermes:8000/internal/route")
R2_ENDPOINT = os.environ.get("R2_ENDPOINT")
R2_ACCESS_KEY_ID = os.environ.get("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = os.environ.get("R2_SECRET_ACCESS_KEY")
R2_BUCKET_ARTIFACTS = os.environ.get("R2_BUCKET_ARTIFACTS", "agentos-artifacts")


def _r2_client():
    if not (R2_ENDPOINT and R2_ACCESS_KEY_ID and R2_SECRET_ACCESS_KEY):
        return None
    return boto3.client(
        "s3",
        endpoint_url=R2_ENDPOINT,
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
    )


class CreativeWorker(BaseWorker):
    worker_type = "creative"
    queue_name = "queue:creative"

    def handle(self, task: dict) -> dict:
        payload = task["payload"]
        content_type = payload.get("content_type", "text")  # text | image_prompt
        brief = payload.get("brief")
        if not brief:
            raise ValueError("payload.brief is required")

        text = self._generate_text(content_type, brief)

        client = _r2_client()
        if client is None:
            # No R2 configured yet (Phase < 9 of README) — return the
            # text inline rather than pretending an upload happened.
            return {"content_type": content_type, "text": text, "r2_key": None,
                     "note": "R2 not configured — result returned inline"}

        key = f"creative/{task['task_id']}/{uuid.uuid4().hex}.txt"
        client.put_object(Bucket=R2_BUCKET_ARTIFACTS, Key=key, Body=text.encode("utf-8"))
        return {"content_type": content_type, "r2_key": key, "r2_bucket": R2_BUCKET_ARTIFACTS}

    def _generate_text(self, content_type: str, brief: str) -> str:
        resp = httpx.post(
            MODEL_ROUTER_URL,
            json={
                "task_type": "creative",
                "prompt": f"Content type: {content_type}\nBrief: {brief}",
            },
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json().get("text", "")


if __name__ == "__main__":
    CreativeWorker().run()
