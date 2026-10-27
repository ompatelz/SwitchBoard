# Chat Completions API contract

## Phase 1A status

Phase 1A defines and tests the supported Chat Completions data contract. The deterministic
mock provider serves that contract at `POST /v1/chat/completions`. The public gateway does not
forward this endpoint until Phase 1B, so this document is not yet a gateway quick-start guide.

Compatibility is behavioral, not merely a matching URL. A compatible client must receive the
expected validation behavior, field names, data types, response shape, and streaming semantics.
Switchboard claims compatibility only for the subset below.

## Supported request fields

| Field | Type | Required | Rule |
| --- | --- | --- | --- |
| `model` | string | yes | Trimmed; 1 to 128 characters. The Phase 1A mock echoes this value. |
| `messages` | array | yes | 1 to 64 text-only messages. |
| `messages[].role` | string | yes | Exactly `system`, `user`, or `assistant`. |
| `messages[].content` | string | yes | 1 to 32,768 characters and not whitespace-only. Meaningful whitespace is preserved. |
| `stream` | boolean | no | Defaults to `false`; only `false` is accepted in Phase 1A. |

Every model rejects unknown fields. Switchboard does not accept and silently ignore parameters
whose semantics it has not implemented. For example, `temperature`, `max_tokens`, `tools`,
`response_format`, multimodal content arrays, `name`, and `tool_calls` receive HTTP `422` from
the Phase 1A mock boundary. `stream: true` is also rejected until Phase 1C.

Pydantic performs runtime validation at the HTTP boundary. Static type checking helps developers
reason about Python code before execution, but it cannot validate untrusted JSON arriving over
the network. The Pydantic models are transport contracts; later provider/domain logic should not
be coupled to every wire-format detail.

## Non-streaming response

The successful response has this shape:

```json
{
  "id": "chatcmpl-mock-<24 deterministic hexadecimal characters>",
  "object": "chat.completion",
  "created": 1700000000,
  "model": "mock-v1",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "Deterministic mock completion <16 hexadecimal characters>"
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 2,
    "completion_tokens": 4,
    "total_tokens": 6
  }
}
```

The mock canonicalizes the validated request and hashes it with SHA-256. Equivalent requests,
including an omitted versus explicit `stream: false`, therefore produce the same ID, timestamp,
text, and usage fixture. This repeatability makes regressions easy to identify and prevents time,
randomness, or invocation order from making tests flaky.

The mock's `prompt_tokens` and `completion_tokens` count whitespace-separated words. They are
experimental test metadata only, not output from any model tokenizer and not suitable for
billing, quota, or cost claims. A real provider adapter must preserve or explicitly characterize
the provider's accounting rather than treating these fixtures as truth.

## Validation behavior

The Phase 1A mock uses FastAPI's HTTP `422` validation response. Empty message arrays, invalid
roles, blank or non-string content, over-limit values, `stream: true`, and unknown fields fail
before mock generation runs. A stable public gateway error envelope is intentionally deferred to
Phase 1B, where malformed JSON and downstream failures can be designed together.

## Compatibility limitations

- The gateway does not expose the Chat Completions route yet; only the test mock does.
- Only text content and the three documented roles are supported.
- Exactly one non-streaming assistant choice is returned.
- Streaming chunks, `[DONE]`, disconnect handling, and partial-stream rules arrive in Phase 1C.
- Temperature, token limits, tools, structured outputs, log probabilities, multiple choices,
  multimodal inputs, and provider-specific options are unsupported.
- The deterministic mock does not run an LLM and makes no quality or tokenizer-accuracy claim.
