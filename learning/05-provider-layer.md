# 05 · The provider layer

The provider layer is the **only** part of the backend that knows Groq exists. Everything else speaks a small, neutral language. This chapter covers that boundary, how failures are classified, and the retry policy.

All files are in [`backend/app/providers/`](../backend/app/providers/).

## The adapter pattern

```mermaid
flowchart LR
    subgraph "Our application (provider-neutral)"
        CS[ChatService]
    end
    subgraph "providers/ (the boundary)"
        BASE["base.py<br/>ChatRequest, StreamEvent,<br/>ProviderError hierarchy,<br/>ProviderAdapter protocol"]
        GROQ["groq.py<br/>GroqProvider"]
        FAKE["fake.py<br/>FakeProvider"]
        FUT["(future)<br/>GeminiProvider ..."]
    end
    API1[(Groq REST API)]
    CS -->|uses only base.py types| BASE
    GROQ -.implements.-> BASE
    FAKE -.implements.-> BASE
    FUT -.implements.-> BASE
    GROQ <--> API1
```

An **adapter** translates between your language and someone else's. `ChatService` asks for "a stream of events for this `ChatRequest`" and never sees JSON, URLs or HTTP status codes.

The contract is the `ProviderAdapter` **Protocol** in [`base.py:162`](../backend/app/providers/base.py#L162). A Protocol says "any object with these methods qualifies", without forcing inheritance:

| Method | Returns |
|---|---|
| `stream(request)` | An async iterator of events: `TextDelta`*, optional `UsageEvent`, then exactly one `Finish` |
| `complete(request)` | One `ChatResult` (non-streaming; used by summaries and the self-check) |
| `aclose()` | Releases the HTTP connection pool |

## Neutral data types

```mermaid
classDiagram
    class ChatRequest {
      model
      messages: list~ChatMessage~
      max_tokens
      temperature?
      reasoning_effort?
    }
    class ChatMessage { role: system|user|assistant
      content }
    class TextDelta { text }
    class UsageEvent { usage: Usage }
    class Usage { input_tokens
      output_tokens
      total_tokens
      reasoning_tokens }
    class Finish { reason
      attempts
      rate_limit: dict }
    ChatRequest --> ChatMessage
    UsageEvent --> Usage
```

See [`base.py:20-75`](../backend/app/providers/base.py#L20). They are **frozen dataclasses**: immutable, so no code can accidentally modify a request halfway through.

## Classifying failures (the error hierarchy)

A provider can fail in many ways. The key question for each failure: **should we try again?**

```mermaid
classDiagram
    ProviderError <|-- ProviderNotConfigured
    ProviderError <|-- ProviderAuthError
    ProviderError <|-- ProviderBadRequest
    ProviderBadRequest <|-- ProviderContextTooLarge
    ProviderError <|-- ProviderRequestTooLarge
    ProviderError <|-- ProviderRateLimited
    ProviderError <|-- ProviderUnavailable
    ProviderError <|-- ProviderTimeout
    ProviderError <|-- ProviderMalformedResponse
    ProviderError <|-- ProviderStreamInterrupted
    class ProviderError { code
      retryable
      http_status
      retry_after
      attempts }
    class ProviderRateLimited { retryable = True }
    class ProviderUnavailable { retryable = True }
    class ProviderTimeout { retryable = True }
```

Defined in [`base.py:78-160`](../backend/app/providers/base.py#L78). How raw HTTP responses map onto them, in [`groq.py:280` `error_from_response`](../backend/app/providers/groq.py#L280):

| What happened | Error | Retry? | Why |
|---|---|---|---|
| 401/403 | `ProviderAuthError` | ❌ | A wrong key stays wrong |
| 400/404/422 | `ProviderBadRequest` | ❌ | The same request fails the same way |
| 400 "reduce the length" | `ProviderContextTooLarge` | ❌ | Too long is too long |
| **413** | `ProviderRequestTooLarge` | ❌ | Bigger than the per-minute limit, so it *can never* fit (discovered by the probe) |
| 429 | `ProviderRateLimited` | ✅ | Wait and it frees up |
| 5xx, 408, 498 | `ProviderUnavailable` | ✅ | Temporary server trouble |
| Network timeout | `ProviderTimeout` | ✅ | Often transient |
| Connection dropped | `ProviderUnavailable` | ✅ | Often transient |
| Invalid JSON | `ProviderMalformedResponse` | ❌ | Retrying would waste quota |
| Broke **after** text was sent | `ProviderStreamInterrupted` | ❌ **never** | See below |

Each error carries a stable `code` (like `provider_rate_limited`). The rest of the app, and the frontend, rely on these codes, never on provider wording.

## The retry policy

Retrying sounds simple ("try again on failure") but naive retries cause real damage: hammering an overloaded server, waiting forever, or worse, **duplicating output**. The policy lives in one small, pure, well-tested class: [`retry.py:20` `RetryPolicy`](../backend/app/providers/retry.py#L20).

### Rule 1: bounded attempts

At most `max_attempts` (default 3). Never infinite.

### Rule 2: exponential backoff with full jitter

Wait longer after each failure, and **randomise** the wait:

```mermaid
xychart-beta
    title "Maximum wait (ceiling) per attempt, base 0.5s, cap 8s"
    x-axis "after attempt" [1, 2, 3, 4, 5, 6]
    y-axis "seconds" 0 --> 9
    bar [0.5, 1, 2, 4, 8, 8]
```

The actual wait is a **random value between 0 and the ceiling** ("full jitter"). Why random? If 100 clients fail at the same moment and all wait exactly 1 s, they all retry at the same moment and overload the server again (the "thundering herd"). Randomness spreads them out.

A generic illustration of the formula (not our code):

```
ceiling = min(cap, base * 2^(attempt-1))
wait    = random_between(0, ceiling)
```

Ours: [`retry.py:25` `backoff`](../backend/app/providers/retry.py#L25).

### Rule 3: respect `Retry-After`, but don't make users wait forever

If the server says "retry after 3 s", wait at least 3 s. If it says "retry after 30 s", **give up immediately** and pass the 30 to the user ("try again in 30 s"), rather than holding their request open ([`retry.py:42`](../backend/app/providers/retry.py#L42)).

### Rule 4: an overall deadline

All attempts together must finish within 120 s. Never start a wait that would cross the deadline ([`retry.py:47`](../backend/app/providers/retry.py#L47)).

### Rule 5: never retry after output has been sent

```mermaid
flowchart TB
    F[failure] --> Q1{any text already<br/>sent to the user?}
    Q1 -->|yes| NO1[❌ no retry → ProviderStreamInterrupted<br/>partial reply is kept]
    Q1 -->|no| Q2{error retryable?}
    Q2 -->|no| NO2[❌ raise]
    Q2 -->|yes| Q3{attempts left?}
    Q3 -->|no| NO3[❌ raise with attempts count]
    Q3 -->|yes| Q4{Retry-After > cap?}
    Q4 -->|yes| NO4[❌ raise, surface retry_after]
    Q4 -->|no| Q5{wait fits before deadline?}
    Q5 -->|no| NO5[❌ raise]
    Q5 -->|yes| W[⏳ wait, then try again]
```

**Why rule 5 matters:** suppose "Hello, your order" was streamed and then the connection dropped. A silent retry would produce a *different* answer, and the user would see "Hello, your orderThank you for contacting us…". Garbage. So once text has been emitted, a failure becomes a **partial** reply that the user can explicitly retry. The whole decision tree is one method: [`retry.py:30` `next_delay`](../backend/app/providers/retry.py#L30).

## How the Groq adapter uses the policy

```mermaid
sequenceDiagram
    participant CS as ChatService
    participant GP as GroqProvider.stream
    participant ONE as _stream_once
    participant G as Groq
    CS->>GP: stream(request)
    loop attempts
        GP->>ONE: attempt N (tracks "emitted")
        ONE->>G: POST /chat/completions (stream)
        alt HTTP error before any text
            G-->>ONE: 503
            ONE-->>GP: ProviderUnavailable
            GP->>GP: policy.next_delay(...) → wait
        else success
            G-->>ONE: chunks...
            ONE-->>CS: TextDelta, TextDelta, ...
            ONE-->>CS: UsageEvent, Finish(attempts=N)
        end
    end
```

- The outer loop is [`groq.py:80` `stream`](../backend/app/providers/groq.py#L80).
- One attempt is [`groq.py:119` `_stream_once`](../backend/app/providers/groq.py#L119).

Notice how low-level network errors are translated into our error types ([`groq.py:151-160`](../backend/app/providers/groq.py#L151)), and how `_interrupted_or` turns *any* failure into `ProviderStreamInterrupted` once text has gone out ([`groq.py:200`](../backend/app/providers/groq.py#L200)).

**Timeouts are layered:**
- **connect** 5 s: can we reach the server at all?
- **read** 30 s: the maximum silence between chunks
- **total** 120 s: the overall deadline, checked between chunks

**Testability trick:** the adapter accepts `sleep` and `clock` functions in its constructor ([`groq.py:49`](../backend/app/providers/groq.py#L49)). Tests pass fakes, so "wait 8 seconds" takes 0 seconds, and a "deadline in 1 second" can be simulated deterministically.

## The fake provider

[`fake.py:56` `FakeProvider`](../backend/app/providers/fake.py#L56) implements the same protocol without any network. It echoes the user's message ("(fake reply) You said: …") and can be told to misbehave with **markers inside the message text**:

```mermaid
flowchart LR
    M["message contains<br/>[fake:rate_limit]"] --> E1[raises ProviderRateLimited]
    M2["[fake:cut]"] --> E2[streams half, then StreamInterrupted]
    M3["[fake:slow]"] --> E3[slow chunks, for Stop tests]
    M4["[fake:fail_once]"] --> E4[fails first time, then works, for Retry tests]
    M5["[fake:length]"] --> E5[finish_reason=length]
```

The full list is in the file's docstring. Why markers? The **browser tests** can't reach into the server's memory to inject a failure, but they *can* type a message. So the trigger lives in the message text.

It makes possible:
- tests that are **fast, free, deterministic and offline**
- e2e browser tests with no API key
- demos with `PROVIDER=fake` (the setup script offers this if you have no key)

## Choosing the provider at startup

[`registry.py:70` `build_provider`](../backend/app/providers/registry.py#L70) reads the settings:
- `PROVIDER=fake` gives a `FakeProvider`.
- `PROVIDER=groq` with a key gives a `GroqProvider`, built with the timeouts and retry settings from config.
- `PROVIDER=groq` **without** a key gives `None`. The app still starts, but `/health/ready` reports `provider_not_configured`, and chat returns a clear 503 instead of crashing.

## Exercise
Read [`backend/tests/unit/test_groq_provider.py`](../backend/tests/unit/test_groq_provider.py). Each test name is a sentence describing one rule above. Pick one, predict what the code does, then trace it through `groq.py` and `retry.py`.

**Next:** [06 · Backend skeleton →](06-backend-skeleton.md)
