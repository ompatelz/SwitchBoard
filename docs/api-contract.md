# Chat Completions API contract

## Phase 1B status

The public gateway and deterministic mock provider both serve the supported contract at
`POST /v1/chat/completions`. The gateway validates the request, assigns a request ID, forwards
through one typed HTTP provider adapter, validates the provider response, and returns it.

Compatibility is behavioral, not merely a matching URL. A compatible client must receive the
expected validation behavior, field names, data types, response shape, and streaming semantics.
Switchboard claims compatibility only for the subset below.

## Supported request fields

| Field | Type | Required | Rule |
| --- | --- | --- | --- |
| `model` | string | yes | Trimmed; 1 to 128 characters. The mock echoes this value. |
| `messages` | array | yes | 1 to 64 text-only messages. |
| `messages[].role` | string | yes | Exactly `system`, `user`, or `assistant`. |
| `messages[].content` | string | yes | 1 to 32,768 characters and not whitespace-only. Meaningful whitespace is preserved. |
| `stream` | boolean | no | Defaults to `false`; only `false` is accepted through Phase 1B. |

Every model rejects unknown fields. Switchboard does not accept and silently ignore parameters
whose semantics it has not implemented. For example, `temperature`, `max_tokens`, `tools`,
`response_format`, multimodal content arrays, `name`, and `tool_calls` receive HTTP `422` from
the gateway boundary. `stream: true` is also rejected until Phase 1C.

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

## Request IDs

The gateway accepts `X-Request-ID` only when it contains 1–64 log-safe ASCII characters: letters,
digits, `.`, `_`, and `-`, starting with a letter or digit. Missing or unsafe values are replaced
with an opaque generated ID. The chosen ID is forwarded to the provider, returned in the response
header, and included in gateway error details. It contains no user, host, or process information.

## Validation and failure semantics

Malformed JSON and structurally invalid requests are distinct. Empty message arrays, invalid
roles, blank or non-string content, over-limit values, `stream: true`, and unknown fields all fail
before provider communication.

Gateway errors use this non-sensitive envelope:

```json
{
  "error": {
    "message": "The provider timed out.",
    "type": "provider_error",
    "code": "provider_timeout",
    "request_id": "req_0123456789abcdef0123456789abcdef"
  }
}
```

| Condition | HTTP status | Stable code |
| --- | ---: | --- |
| Malformed JSON | 400 | `invalid_json` |
| Request validation failure | 422 | `invalid_request` |
| Provider rate limit | 429 | `provider_rate_limited` |
| Provider connection failure | 502 | `provider_connection_error` |
| Provider rejected a gateway-valid request | 502 | `provider_rejected_request` |
| Invalid provider JSON/schema/status | 502 | `invalid_provider_response` |
| Provider 5xx | 503 | `provider_unavailable` |
| Connect, read, write, or pool timeout | 504 | `provider_timeout` |

Provider URLs, response bodies, credentials, stack traces, and internal exception strings are not
included. The gateway does not retry or fall back, so one client request causes at most one
provider completion request in Phase 1B.

## Timeouts and resource ownership

Connect, read, write, and pool timeouts are separately configured with positive validated values.
One `httpx.AsyncClient` and its connection pool are created by FastAPI lifespan, borrowed by the
provider adapter for every request, and closed at application shutdown. Non-streaming responses
are fully buffered, validated, and explicitly closed before the route returns. Cancellation is not
caught by provider-error translation, so task cancellation can propagate to the HTTP operation.

## Compatibility limitations

- Only text content and the three documented roles are supported.
- Exactly one non-streaming assistant choice is returned.
- Streaming chunks, `[DONE]`, disconnect handling, and partial-stream rules arrive in Phase 1C.
- Temperature, token limits, tools, structured outputs, log probabilities, multiple choices,
  multimodal inputs, and provider-specific options are unsupported.
- The deterministic mock does not run an LLM and makes no quality or tokenizer-accuracy claim.
