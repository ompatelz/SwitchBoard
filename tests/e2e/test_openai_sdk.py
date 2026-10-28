"""OpenAI Python SDK acceptance tests against a running Switchboard stack."""

import os

import pytest
from openai import OpenAI

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        os.getenv("SWITCHBOARD_E2E") != "1",
        reason="set SWITCHBOARD_E2E=1 after starting both services",
    ),
]


def test_openai_sdk_buffered_and_streaming_completions() -> None:
    """Prove the declared subset deserializes into standard SDK response types."""
    gateway_url = os.getenv("SWITCHBOARD_E2E_GATEWAY_URL", "http://127.0.0.1:8000")
    with OpenAI(
        base_url=f"{gateway_url.rstrip('/')}/v1",
        api_key="switchboard-local-placeholder",
        max_retries=0,
        timeout=5.0,
    ) as client:
        completion = client.chat.completions.create(
            model="mock-v1",
            messages=[{"role": "user", "content": "SDK compatibility test"}],
        )
        stream = client.chat.completions.create(
            model="mock-v1",
            messages=[{"role": "user", "content": "SDK compatibility test"}],
            stream=True,
        )
        chunks = list(stream)

    assert completion.object == "chat.completion"
    assert completion.model == "mock-v1"
    assert completion.choices[0].message.role == "assistant"
    assert completion.choices[0].message.content is not None
    assert completion._request_id is not None
    assert chunks
    assert all(chunk.object == "chat.completion.chunk" for chunk in chunks)
    assert chunks[0].choices[0].delta.role == "assistant"
    assert chunks[-1].choices[0].finish_reason == "stop"
    streamed_content = "".join(chunk.choices[0].delta.content or "" for chunk in chunks)
    assert streamed_content == completion.choices[0].message.content
