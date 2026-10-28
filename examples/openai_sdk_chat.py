"""Call local Switchboard through the standard OpenAI Python SDK."""

import os

from openai import OpenAI

DEFAULT_BASE_URL = "http://127.0.0.1:8000/v1"
PLACEHOLDER_API_KEY = "switchboard-local-placeholder"


def main() -> None:
    """Print one buffered completion and one incrementally streamed completion."""
    base_url = os.getenv("SWITCHBOARD_OPENAI_BASE_URL", DEFAULT_BASE_URL)
    with OpenAI(
        base_url=base_url,
        api_key=PLACEHOLDER_API_KEY,
        max_retries=0,
        timeout=5.0,
    ) as client:
        completion = client.chat.completions.create(
            model="mock-v1",
            messages=[{"role": "user", "content": "Explain ASGI"}],
        )
        print(f"non-streaming: {completion.choices[0].message.content}")

        stream = client.chat.completions.create(
            model="mock-v1",
            messages=[{"role": "user", "content": "Explain ASGI"}],
            stream=True,
        )
        print("streaming: ", end="")
        for chunk in stream:
            content = chunk.choices[0].delta.content
            if content is not None:
                print(content, end="", flush=True)
        print()


if __name__ == "__main__":
    main()
