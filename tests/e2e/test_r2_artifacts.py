"""
Integration test: R2 artifact upload -> download -> integrity check.
Real boto3 calls against your configured R2 bucket (S3-compatible
API) — not a mock. SKIPS honestly if R2 env vars aren't set.

    R2_ENDPOINT=... R2_ACCESS_KEY_ID=... R2_SECRET_ACCESS_KEY=... \
    R2_BUCKET_ARTIFACTS=agentos-artifacts \
        python3 -m pytest tests/e2e/test_r2_artifacts.py -v -s

Not executed in the environment that generated this repo (no R2
credentials there). Cleans up after itself (deletes the test object)
whether the test passes or fails.
"""
import hashlib
import os
import uuid

import pytest

REQUIRED = ["R2_ENDPOINT", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET_ARTIFACTS"]
missing = [v for v in REQUIRED if not os.environ.get(v)]

pytestmark = [pytest.mark.e2e, pytest.mark.external, pytest.mark.skipif(
    bool(missing),
    reason=f"EXTERNAL_CREDENTIAL_REQUIRED: missing env vars: {missing}. See module docstring.",
)]

if not missing:
    import boto3


@pytest.fixture
def r2_client():
    return boto3.client(
        "s3",
        endpoint_url=os.environ["R2_ENDPOINT"],
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
    )


def test_upload_download_roundtrip_and_integrity(r2_client):
    bucket = os.environ["R2_BUCKET_ARTIFACTS"]
    key = f"e2e-test/{uuid.uuid4().hex}.txt"
    content = b"agent-os R2 integration test artifact - " + uuid.uuid4().bytes
    expected_hash = hashlib.sha256(content).hexdigest()

    try:
        # Upload
        r2_client.put_object(Bucket=bucket, Key=key, Body=content)

        # Confirm metadata is retrievable (proves it's really there,
        # not just that put_object didn't throw)
        head = r2_client.head_object(Bucket=bucket, Key=key)
        assert head["ContentLength"] == len(content)

        # Download and verify byte-for-byte integrity
        downloaded = r2_client.get_object(Bucket=bucket, Key=key)["Body"].read()
        actual_hash = hashlib.sha256(downloaded).hexdigest()
        assert actual_hash == expected_hash, (
            "downloaded content hash does not match uploaded content — "
            "R2 round-trip is NOT byte-identical, this is a real data integrity failure"
        )
    finally:
        # Clean up regardless of pass/fail — don't leave test junk in the real bucket
        r2_client.delete_object(Bucket=bucket, Key=key)


def test_nonexistent_key_raises_not_silently_returns_empty(r2_client):
    bucket = os.environ["R2_BUCKET_ARTIFACTS"]
    key = f"e2e-test/definitely-does-not-exist-{uuid.uuid4().hex}.txt"
    with pytest.raises(Exception):
        r2_client.get_object(Bucket=bucket, Key=key)
