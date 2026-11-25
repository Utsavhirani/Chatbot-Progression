# AI Business Assistant --- Project Context and Development Roadmap

## 1. Project purpose

Build one progressively evolving, genuinely usable AI business-assistant
application. The initial product is a business customer-support chatbot.
Over successive versions, it will gain private knowledge retrieval,
measurable answer quality, tool use, memory, and production-oriented
optimization.

This is not a sequence of tutorial exercises or six disconnected
applications. It is one codebase and one evolving product. Each version
must leave the application in a working, demonstrable state.

The central development principle is:

> Introduce a technology when it solves a concrete problem in the
> application. Do not add frameworks, infrastructure, or abstractions
> merely because they are popular.

The first version must already be a complete conversational application,
not a minimal prompt-to-LLM demonstration. Later versions add
substantial new capabilities.

## 2. Product scenario

Use a business customer-support assistant as the initial reference use
case. A business should be able to configure its assistant, have users
converse with it, and eventually provide its own documents and business
tools.

Keep the architecture general enough that the same foundation could
later support other business assistants, internal knowledge assistants,
and task-oriented agents.

The application should have:

- A frontend chat experience.
- A backend responsible for model interaction, conversation state, security, orchestration, and business logic.
- Persistent storage.
- A provider-independent interface for hosted AI models.
- Tests and diagnostics that make the system verifiable.

Do not assume that the application is a public production service from
day one. The initial target is a reliable local development and
demonstration application, with a sensible path to deployment.

## 3. Important constraints and preferences

### 3.1 Model providers and API access

-   Prefer direct HTTP/REST API calls over provider-specific SDKs.
-   Use Python HTTPX or another standard HTTP client for backend
    requests.
-   Do not make the application depend on one provider's SDK, request
    schema, or model naming.
-   Start with GroqCloud as the first provider candidate, subject to
    account access, model availability, quota, and practical testing.
-   Keep the option to add Gemini or another provider as a secondary
    provider.
-   Do not assume that an OpenAI-compatible endpoint means every model
    supports the same features. Maintain a capability matrix and test
    each model.
-   Verify current provider model IDs, free-tier quotas, rate limits,
    context limits, tool support, structured-output support, streaming
    support, and vision support against current official documentation
    and the actual account console. Provider limits and model
    availability change.
-   Never hardcode a quota assumption as a guaranteed entitlement.
-   Build bounded retry/backoff for transient errors. Respect
    `Retry-After` when provided. Do not endlessly retry.
-   Treat authentication and malformed-request errors differently from
    temporary overload or rate-limit errors.
-   Be careful when failing over after tool execution: do not blindly
    replay side-effecting operations.

### 3.2 Hardware and budget

-   The project must not require a local GPU or local LLM inference.
-   Use hosted model APIs for generation.
-   CPU-based local embeddings are acceptable if practical, but should
    be benchmarked on the available machine.
-   Prefer free tiers for development and demonstration, while being
    realistic about rate and token limits.
-   Do not assume free-tier services are unlimited or guaranteed to
    remain free.
-   Start locally. Add deployment services only when there is a concrete
    need.
-   Avoid making paid infrastructure a prerequisite for early
    milestones.

### 3.3 Learning and implementation style

-   Build the application incrementally in the same repository.
-   Explain the purpose of a component before introducing it.
-   Avoid unnecessary theory detached from implementation.
-   Do not dump an entire large implementation without a plan. Work in
    coherent, reviewable pieces.
-   Before changing existing files, inspect the repository and
    understand its current structure and conventions.
-   Do not overwrite working functionality casually.
-   After each meaningful change, run relevant tests and report what
    passed, failed, or remains unverified.
-   Do not claim a feature works merely because code was written.
-   Keep setup instructions and environment-variable examples current.
-   Never commit API keys, credentials, personal data, or real customer
    documents.

## 4. High-level roadmap

| Version | Main capability | Result |
|---|---|---|
| V1 | Complete conversational AI application | Reliable chatbot foundation |
| V2 | Document ingestion and RAG | Assistant answers using private business knowledge |
| V3 | Advanced retrieval and evaluation | Retrieval and answer quality can be measured and improved |
| V4 | Tool use and agents | Assistant can perform controlled business tasks |
| V5 | Memory and personalization | Assistant can retain and use relevant user-specific context |
| V6 | Optimization and production readiness | Application becomes measurable, efficient, robust, and deployable |

Versions should be treated as capability milestones, not rigid calendar
estimates. Complete and verify one milestone before expanding scope.

------------------------------------------------------------------------

# Version 1 --- Complete Conversational AI Application

## 5. Objective

Build a complete, persistent, usable business chatbot. It must support
real conversations, maintain separate sessions, stream responses, handle
failures, and expose enough diagnostics to understand its behaviour and
usage.

This version combines the original foundational chatbot,
conversation-management, and reliability stages. Do not split these into
disposable mini-projects.

## 6. User-facing capabilities

### 6.1 Chat interface

The frontend should provide:

- A clean chat interface with user and assistant messages.
- Streaming assistant responses, where supported by the selected provider.
- A visible loading/generating state.
- A way to start a new conversation.
- A conversation list or history view.
- Clear handling of failed, interrupted, or empty responses.
- A way to retry an appropriate failed request without accidentally duplicating a completed message.
- Usable layout on common desktop and mobile screen sizes.

Do not spend excessive time on visual polish before the complete
workflow works. The interface should nevertheless feel like a coherent
application rather than a raw developer test page.

### 6.2 Conversation sessions and persistence

Implement:

- Distinct conversation/session IDs.
- Persistent conversation records and messages.
- Retrieval of prior conversations.
- Correct association between a user and their conversations.
- Isolation so one user cannot access another user's sessions.
- A clear policy for starting a new conversation.
- Consistent ordering and timestamps.

The frontend must not be the authority for access control. The backend
must verify ownership for every conversation operation.

### 6.3 Conversation context management

The model should receive the relevant conversation context, not an
unbounded transcript forever.

Implement:

- A system instruction or configurable assistant prompt.
- A defined message ordering policy.
- A configurable context/token budget.
- Token estimation or provider usage-based tracking where available.
- A strategy for trimming or summarizing older history when the context budget is approached.
- Preservation of recent and relevant messages.
- Safe handling of unusually long user messages.

Start with a simple, understandable strategy. Do not introduce a complex
memory framework in V1. Long-term semantic memory belongs in V5.

### 6.4 Model configuration

Support a sensible set of model parameters, such as:

- Provider.
- Model ID.
- Temperature, where supported.
- Maximum completion tokens.
- Streaming preference.
- System prompt.

Keep provider-specific configuration behind a backend interface. Do not
expose secrets or provider credentials to the browser.

### 6.5 Provider integration layer

Create a small internal provider abstraction that separates application
logic from provider-specific HTTP details.

It should handle, as appropriate:

- Endpoint and authentication configuration.
- Request serialization.
- Response parsing.
- Streaming response parsing.
- Model identifier.
- Usage information.
- Provider error normalization.
- Timeouts and cancellation.
- Feature/capability information.

The abstraction should not become an elaborate plugin framework. It only
needs enough structure to add or replace providers without rewriting
chat, persistence, or business logic.

Use direct REST calls. For example, a provider may expose an
OpenAI-compatible chat-completions endpoint, but keep the endpoint and
payload mapping in the provider adapter rather than scattering it
through application code.

Maintain a model capability record, at minimum covering:

- Chat completion.
- Streaming.
- Tool calling.
- Structured JSON output.
- Vision/image input.
- Context window.
- Maximum output.
- Relevant rate limits and quota notes.

Capabilities must be based on verified documentation and tests, not
assumptions.

### 6.6 Reliability and operational safeguards

Implement:

- Input validation.
- Request timeouts.
- Bounded retries for transient failures.
- Exponential backoff with jitter where appropriate.
- Rate limiting at the application boundary.
- Clear error responses.
- Handling for provider overload, quota exhaustion, invalid credentials, and malformed requests.
- Protection against duplicate submissions.
- Cancellation/disconnection handling for streaming requests.
- Basic health/readiness checks.
- Structured logs with request and conversation identifiers.
- No secrets in logs.
- Basic usage accounting: input tokens, output tokens, total tokens, provider/model, latency, status, and timestamp when available.

A fallback provider may be added if it can be done without making the
first implementation brittle. If fallback is not ready, the application
must still fail clearly and safely.

### 6.7 Authentication and access

For a multi-user demonstration, include a reasonable authentication
approach and enforce ownership of user data. If the first local demo
uses a single development user, keep that limitation explicit and do not
pretend it provides multi-user security.

Never trust a user ID or conversation ID supplied by the browser without
backend authorization.

## 7. Suggested V1 technology choices

| Area | Initial choice | Reason |
|---|---|---|
| Frontend | React + Vite | Familiar, lightweight web application foundation |
| Backend | Python + FastAPI | Clear API layer and Python ecosystem |
| HTTP client | HTTPX | Direct REST requests without provider SDK dependence |
| Validation | Pydantic | Request/response validation and typed models |
| Database | PostgreSQL | Durable relational storage that can later support pgvector |
| Hosted database option | Supabase PostgreSQL | Convenient development option, not a mandatory dependency |
| Testing | Pytest + HTTPX | Backend and API testing |
| Browser workflow tests | Playwright | Verify real user flows |
| Containers | Docker / Docker Compose | Reproducible setup and sharing |
| Version control | Git | Incremental, reviewable development |

Use a migration tool such as Alembic if the database schema is managed
through SQLAlchemy. Choose a consistent database access approach rather
than mixing multiple ORMs and query styles without reason.

## 8. V1 acceptance criteria

V1 is complete only when:

1. A user can open the application and start a conversation.
2. The assistant responds through a hosted model API.
3. Streaming works, or the chosen provider's limitation is documented and a non-streaming fallback works.
4. Conversations persist after a refresh or restart.
5. Multiple conversations remain separate.
6. Access to conversations is authorized.
7. Context is constructed within a deliberate budget.
8. Invalid input and provider failures produce understandable errors.
9. Timeouts and transient failures are handled without infinite retries.
10. Usage and latency are recorded when provider data is available.
11. Secrets remain server-side and are not committed.
12. The app can be started using documented instructions.
13. Automated tests cover the important API and conversation workflows.
14. The actual application can be demonstrated from its frontend; Swagger alone is not considered an adequate demonstration.

## 9. V1 test scenarios

Test at least:

- Normal question and answer.
- Empty or whitespace-only message.
- Very long user message.
- Invalid API key.
- Provider timeout.
- Provider 429/rate-limit response.
- Provider 5xx/overload response.
- Malformed provider response.
- Streaming interruption.
- Duplicate message submission.
- Refresh during or after a conversation.
- New conversation isolation.
- Attempt to access another user's conversation.
- Conversation history near the context limit.
- Missing provider configuration.
- Database unavailable.

------------------------------------------------------------------------

# Version 2 --- Document Ingestion and Retrieval-Augmented Generation (RAG)

## 10. Objective

Allow a business to provide its own documents and ask questions that
must be answered using those documents. The assistant should retrieve
relevant evidence and make it clear which sources support its answer.

RAG is an application-side pipeline. It does not require the LLM
provider itself to offer a special RAG product.

## 11. Document-management capabilities

Implement:

- Uploading supported document formats, initially PDF and text-based formats.
- File metadata: name, type, size, upload time, owner or tenant, processing status.
- Validation of file type and size.
- Duplicate handling.
- Processing status and useful failure messages.
- Document listing and deletion.
- Re-indexing when processing logic changes.
- Isolation of documents by user/business/tenant.

Do not assume that every PDF contains extractable text. Scanned
documents may require OCR, which can be added when needed.

## 12. Ingestion pipeline

Build a traceable pipeline:

1.  Receive and validate the file.
2.  Store it in an appropriate location.
3.  Extract text.
4.  Preserve useful metadata, such as filename, page number, section
    heading, and document ID.
5.  Clean extraction artefacts without destroying meaningful content.
6.  Split text into chunks.
7.  Generate embeddings.
8.  Store chunk text, metadata, and vectors.
9.  Mark the document as indexed or failed.

Keep the stages explicit so a failed extraction or embedding step can be
diagnosed and retried.

### 12.1 Chunking

Start with a simple chunking strategy that uses a configurable target
size and overlap. Preserve page and document metadata. Avoid splitting
in ways that needlessly separate headings from their content.

Do not assume one chunk size is universally best. Record the
configuration so later experiments can compare alternatives.

### 12.2 Embeddings

Start with a practical embedding model that can run on CPU if performance is acceptable. Candidate models include:

- `BAAI/bge-small-en-v1.5`
- `sentence-transformers/all-MiniLM-L6-v2`

Benchmark installation size, memory use, embedding speed, and retrieval
quality on the available machine. Do not make a GPU a requirement.

Keep the embedding model name and version associated with the index. If
the embedding model changes, plan for re-embedding rather than silently
mixing incompatible vectors.

### 12.3 Vector storage

Use PostgreSQL with pgvector as the first option. It reduces
infrastructure sprawl and keeps relational metadata close to vector
data.

Store sufficient metadata to filter retrieval by:

- User/business/tenant.
- Document.
- File type or category.
- Page or section.
- Other useful business-specific attributes.

A separate vector database should only be introduced if measured needs
justify it.

## 13. Retrieval and answer generation

At query time:

1. Identify the user's query and applicable access scope.
2. Generate a query embedding.
3. Retrieve the most relevant chunks.
4. Apply metadata and ownership filters.
5. Construct a compact context containing source information.
6. Send the question and retrieved evidence to the model.
7. Ask the model to answer from the evidence and acknowledge when evidence is insufficient.
8. Return citations that can be mapped to actual source documents and page/section locations.

The backend, not the model, must enforce document access restrictions.
Never retrieve a document from another tenant merely because its text is
semantically similar.

## 14. RAG behaviour requirements

-   The assistant should distinguish sourced information from general
    knowledge.
-   When the available documents do not answer the question, it should
    say so rather than inventing a source-supported answer.
-   Citations must refer to retrieved chunks and real document
    locations.
-   The user should be able to inspect the source document or relevant
    excerpt.
-   Document deletion must remove or invalidate its indexed chunks as
    well.
-   Failed or incomplete indexing must not be presented as successful.

## 15. Suggested V2 technologies

-   PyMuPDF for PDF text extraction.
-   Appropriate parsers for other supported file types.
-   Tesseract OCR later for scanned documents, if required.
-   Sentence Transformers for local embeddings.
-   PostgreSQL + pgvector for vector storage and metadata.
-   Existing FastAPI backend and React frontend.

## 16. V2 acceptance criteria

1.  A user can upload a supported document.
2.  The system reports processing status.
3.  Text and metadata are extracted and indexed.
4.  A user can ask questions about the document.
5.  Answers include verifiable source citations.
6.  Questions unsupported by the documents are handled honestly.
7.  Documents and chunks are isolated by owner/tenant.
8.  Deleting a document removes it from future retrieval.
9.  Processing failures can be diagnosed.
10. Tests cover ingestion, retrieval, citations, access control, and
    deletion.

## 17. V2 test scenarios

-   Clean text PDF.
-   Multi-page PDF.
-   PDF with tables or awkward layouts.
-   Scanned PDF, with OCR limitation clearly handled if OCR is not
    implemented.
-   Empty or corrupt file.
-   Unsupported file type.
-   Duplicate upload.
-   Question whose answer appears clearly in one chunk.
-   Question requiring information across multiple chunks.
-   Question with no answer in the documents.
-   Similar but irrelevant content.
-   Cross-user/tenant retrieval attempt.
-   Delete document and ask the same question again.
-   Re-index after changing chunking or embedding configuration.

------------------------------------------------------------------------

# Version 3 --- Advanced Retrieval and Evaluation

## 18. Objective

Move from "RAG works" to "we can measure and improve RAG quality."
Retrieval and answer generation are separate failure points. This
version should make it possible to determine which part is failing.

## 19. Retrieval improvements

Introduce these techniques incrementally and compare them against the V2
baseline.

### 19.1 Hybrid search

Combine semantic/vector search with keyword or lexical search. This helps when queries contain:

- Exact product codes.
- Part numbers.
- Names.
- Technical terminology.
- Exact phrases that embeddings may not rank well.

Use PostgreSQL full-text search or another suitable lexical mechanism
before adding a dedicated search engine.

### 19.2 Reranking

Retrieve a broader candidate set, then use a reranker to reorder
candidates by relevance to the actual query.

Evaluate whether reranking improves the quality of the final context
enough to justify its latency and compute cost.

### 19.3 Query rewriting and decomposition

For ambiguous or complex questions:

- Rewrite conversational references into a standalone search query.
- Expand abbreviations when safe.
- Break multi-part questions into subqueries where appropriate.
- Preserve the user's actual intent.
- Avoid changing a query into something the user did not ask.

Do not apply query rewriting to every request automatically. Measure
whether it helps.

### 19.4 Context selection and compression

-   Remove redundant retrieved chunks.
-   Avoid sending multiple near-duplicate passages.
-   Keep source metadata.
-   Prioritize evidence that directly answers the question.
-   Fit the evidence within a deliberate model-token budget.

## 20. Evaluation system

Create a repeatable evaluation dataset. Start with approximately 50--100
realistic questions and expand it as the application grows.

For each test case, store:

- Question.
- Relevant source document(s).
- Expected facts or answer characteristics.
- Whether the question is answerable from the knowledge base.
- Expected citation/source.
- Optional tags such as exact lookup, multi-document reasoning, or insufficient evidence.

Evaluate distinct layers:

### Retrieval quality

-   Did retrieval return the expected source?
-   Was relevant evidence ranked highly?
-   How much irrelevant context was retrieved?
-   Precision/recall-style measures where appropriate.
-   Recall@K and ranking metrics where useful.

### Answer quality

-   Is the answer factually supported by retrieved evidence?
-   Does it answer the actual question?
-   Does it invent unsupported details?
-   Are citations correct?
-   Does it abstain when evidence is insufficient?

### Operational quality

-   Latency.
-   Token consumption.
-   Error rate.
-   Cost or quota consumption.
-   Successful completion rate.

Use automated metrics as aids, not unquestionable truth. Inspect
representative failures manually.

## 21. Prompt and model experiments

Create a controlled way to compare:

- Chunk sizes and overlap.
- Embedding models.
- Top-K values.
- Vector-only versus hybrid search.
- Reranking on/off.
- Query rewriting on/off.
- Different prompts.
- Different LLM models.

Change one meaningful variable at a time where possible. Save
configurations and results so comparisons are reproducible.

## 22. Observability

Add richer traces around:

- Incoming request.
- Query transformation.
- Embedding.
- Retrieval.
- Reranking.
- Context assembly.
- Model request.
- Final response.

A tool such as Langfuse can be evaluated here. Do not make it a
mandatory dependency if simpler structured logs are enough at the
current scale.

## 23. Suggested V3 technologies

-   Ragas or DeepEval for RAG evaluation.
-   Promptfoo for prompt/model testing.
-   Langfuse for traces and observability.
-   PostgreSQL full-text search for lexical retrieval.
-   A reranking model or API, selected after testing.

Choose one evaluation approach first. Avoid installing several
overlapping frameworks before understanding what each contributes.

## 24. V3 acceptance criteria

1.  A repeatable evaluation dataset exists.
2.  Baseline retrieval and answer quality are measured.
3.  Hybrid retrieval can be compared against vector-only retrieval.
4.  Reranking can be evaluated independently.
5.  Query rewriting and context compression can be tested.
6.  Evaluation results are saved with configuration/version information.
7.  Regressions can be detected after changes.
8.  Representative failures can be traced through the pipeline.
9.  Quality improvements are supported by measurements, not intuition
    alone.

------------------------------------------------------------------------

# Version 4 --- Tool Use and AI Agents

## 25. Objective

Allow the assistant to perform controlled operations through backend
tools and external APIs. The model should decide when a tool is useful,
but the backend must remain responsible for permissions, validation, and
execution.

A model-generated tool call is a request, not authorization.

## 26. Tool-calling foundation

Implement:

- A registry of available tools.
- Tool name and description.
- Typed input schema.
- Backend execution function.
- Input validation.
- Output normalization.
- Timeout and error handling.
- Tool execution logs.
- Clear distinction between read-only and side-effecting tools.

The model should only see tools that are relevant and permitted for the
current user and task.

## 27. Initial tool examples

Start with safe, useful examples:

- Search the business knowledge base.
- Look up a product or service.
- Retrieve an order or lead status from a mock database.
- Calculate a quote using deterministic backend logic.
- Create a draft support ticket.
- Retrieve business hours or contact information.

Use mock data or a sandbox for early demonstrations. Add real external
integrations only after the execution and authorization model is
reliable.

## 28. Multi-step workflows

After basic tool calling works, add:

- Multiple tool calls in one task.
- Passing validated results between steps.
- Handling missing or contradictory tool results.
- Bounded execution steps.
- Cancellation.
- Timeouts.
- Recovery from tool failures.
- A clear summary of actions taken.

Do not assume that every multi-step task needs an autonomous agent
framework. A simple, explicit orchestration loop may be easier to
understand and debug.

Consider LangGraph only if stateful branching, resumability,
human-in-the-loop workflows, or complex orchestration justify it.

## 29. Security and human approval

-   Enforce user and tenant permissions in backend tools.
-   Validate every argument.
-   Use least-privilege credentials.
-   Never allow the model to execute arbitrary SQL or shell commands.
-   Require confirmation for consequential or irreversible actions.
-   Separate draft creation from final submission where possible.
-   Prevent accidental duplicate side effects.
-   Record who requested and approved each action.
-   Treat tool output and retrieved documents as untrusted data, not
    instructions.

## 30. V4 acceptance criteria

1.  The model can select an appropriate tool.
2.  Tool arguments are validated before execution.
3.  Backend permissions are enforced independently of model
    instructions.
4.  Tool failures are handled without corrupting the conversation.
5.  Multi-step execution is bounded and traceable.
6.  Side-effecting operations require appropriate confirmation.
7.  Tool calls and results are recorded.
8.  Tests cover invalid arguments, permission failures, timeouts,
    duplicate actions, and malicious instructions.

------------------------------------------------------------------------

# Version 5 --- Memory and Personalization

## 31. Objective

Give the assistant useful continuity across conversations without
treating the entire chat history as permanent memory.

Conversation history and long-term memory are different:

- Conversation history records what happened in a particular session.
- Long-term memory stores selected facts or preferences that may help in future sessions.

## 32. Memory capabilities

Implement:

- User-specific memory records.
- Memory extraction from conversations.
- Memory summaries.
- Relevance-based memory retrieval.
- Memory update and correction.
- Memory deletion.
- Memory provenance or a record of why a memory exists, where practical.
- Tenant and user isolation.
- Controls over what is eligible to be stored.

Do not store every statement automatically. Avoid storing sensitive
information unless there is a clear, authorized requirement and an
appropriate protection model.

## 33. Memory lifecycle

A possible lifecycle:

1.  Identify a candidate fact or preference.
2.  Apply storage rules and sensitivity checks.
3.  Decide whether it is useful and sufficiently stable.
4.  Store it with ownership and metadata.
5.  Retrieve only when relevant to a new request.
6.  Update or reconcile conflicting information.
7.  Allow the user to inspect, correct, or delete it.

The assistant should not invent memories or present uncertain inferences
as established facts.

## 34. V5 acceptance criteria

1.  Relevant user-specific information can persist across sessions.
2.  Irrelevant memory is not injected into every prompt.
3.  Different users cannot access each other's memories.
4.  Conflicting or outdated information can be corrected.
5.  Users can inspect and delete stored memory.
6.  Sensitive information is handled conservatively.
7.  Tests verify retrieval relevance, isolation, correction, and
    deletion.

------------------------------------------------------------------------

# Version 6 --- Optimization and Production Readiness

## 35. Objective

Make the application efficient, measurable, robust under realistic load,
and deployable. This version should use the experience and measurements
gathered in earlier versions to guide optimization.

Do not optimize blindly. Identify an observed bottleneck, measure it,
change one thing, and measure again.

## 36. Model routing and provider resilience

Implement:

- A model/provider registry.
- Routing based on task capability, quality, latency, or cost.
- Provider fallback for appropriate transient failures.
- Capability checks before routing.
- Per-provider quota and rate-limit tracking.
- Clear handling when no provider is available.
- Safe retry rules for requests that may have side effects.
- Model and prompt version records.

Do not route to a model merely because it is cheaper if it cannot
reliably perform the task.

## 37. Cost and latency optimization

Measure:

- Input and output tokens.
- Cost per request where pricing is known.
- Cost per successful task.
- Time to first token (TTFT).
- Total response latency.
- Retrieval and reranking latency.
- Tool execution latency.
- Error and retry rates.
- P50, P95, and P99 latency.
- Throughput and concurrency.

Explore:

- Prompt/context reduction.
- Caching repeated work where safe.
- Smaller models for simpler tasks.
- Larger models for tasks that justify them.
- Embedding and reranking optimization.
- Avoiding redundant model calls.
- Streaming improvements.

Caching must respect user/tenant access boundaries and must not return
one user's private content to another.

## 38. Load, reliability, and security testing

Test:

- Concurrent conversations.
- Bursts of requests.
- Provider rate-limit exhaustion.
- Database interruptions.
- Provider outages.
- Long-running tool calls.
- Interrupted streams.
- Large document ingestion.
- Recovery after restart.
- Authentication and authorization boundaries.
- Prompt injection through user messages and retrieved documents.
- Sensitive-data exposure in logs and traces.

Set realistic demonstration targets. Do not claim public-production
readiness merely because the application runs in Docker.

## 39. Deployment and operations

Add:

- Reproducible containerized deployment.
- Environment-specific configuration.
- Secret management.
- Database migrations.
- Health checks.
- Structured logs and monitoring.
- Backup and restore procedure.
- Deployment documentation.
- A simple rollback strategy.

Use a modest deployment setup appropriate to actual traffic and budget.
Kubernetes is not a default requirement.

## 40. V6 acceptance criteria

1.  The application can be deployed using documented steps.
2.  Secrets are managed outside source control.
3.  Database migrations and recovery procedures are documented.
4.  Load tests establish measured capacity and bottlenecks.
5.  P50/P95/P99 latency and error rates are available.
6.  Model/provider routing is tested.
7.  Cost per successful task can be estimated.
8.  Monitoring and useful traces are available.
9.  Backup and restore have been tested.
10. Security and tenant-isolation tests pass.
11. Known limitations and operational procedures are documented.

------------------------------------------------------------------------

# 41. Cross-version architecture principles

These principles apply throughout the project.

## 41.1 Keep business logic provider-independent

The chat service should not need to know the peculiarities of every
provider. Provider adapters translate between the application's internal
request/response representation and provider-specific REST APIs.

Do not over-generalize too early. Add abstraction only where it prevents
real coupling.

## 41.2 Keep RAG independent from the generation provider

Document extraction, chunking, embedding, retrieval, reranking, and
citation mapping should be application components. The LLM provider
receives the selected evidence and generates an answer.

This makes it possible to compare generation providers without
rebuilding the knowledge pipeline.

## 41.3 Keep tools under backend control

The model may request a tool. The backend validates the request, checks
permissions, executes the function, and returns a normalized result. The
model never receives direct access to secrets, databases, or arbitrary
system execution.

## 41.4 Make token and quota use visible

Track token consumption and provider limits from V1. Context history,
retrieved passages, tool loops, and output all contribute to usage. Do
not assume a large advertised context window means the free-tier
throughput can process that context continuously.

Use application-side context budgeting and provider-side rate-limit
handling. Treat published free-tier quotas as changeable and verify the
account's actual limits.

## 41.5 Keep evaluation data as a project asset

As soon as RAG is introduced, create and maintain a reusable evaluation
dataset. Add cases when bugs or failure modes are discovered. Reuse it
when changing chunking, embeddings, retrieval, prompts, or models.

## 41.6 Security is not a final-version feature

Authentication, authorization, secret handling, tenant isolation, input
validation, and safe logging must be present as soon as the
corresponding data or operations exist. V6 strengthens and tests these
controls; it does not introduce security for the first time.

## 41.7 Avoid premature technology adoption

Do not add these by default:

- LangChain.
- LangGraph.
- Redis.
- A separate vector database.
- Kubernetes.
- Local LLM inference.
- Multiple overlapping observability platforms.
- Complex microservice architecture.

They may become useful, but each must solve a demonstrated requirement.

------------------------------------------------------------------------

# 42. Suggested repository organization

The exact structure should be decided after inspecting the existing
repository. A possible conceptual organization is:

``` text
project/
  frontend/
    src/
      components/
      features/
      services/
      pages/
  backend/
    app/
      api/
      core/
      db/
      models/
      schemas/
      services/
      providers/
      conversations/
      documents/       # introduced in V2
      retrieval/       # introduced in V2
      evaluation/      # introduced in V3
      tools/           # introduced in V4
      memory/          # introduced in V5
    tests/
  migrations/
  scripts/
  docs/
  .env.example
  docker-compose.yml
  README.md
```

This is illustrative, not a requirement to create every directory
immediately. Add modules when their features are introduced. Avoid empty
folders and speculative abstractions.

------------------------------------------------------------------------

# 43. Working instructions for an AI coding assistant

When assisting with this repository:

1.  First inspect the current repository, README, dependency files,
    environment configuration, and tests.
2.  Identify the current completed version and the next intended
    milestone.
3.  Summarize the relevant existing architecture before proposing
    significant changes.
4.  Present a small implementation plan with files/components affected.
5.  Preserve working features and existing conventions unless there is a
    reason to change them.
6.  Implement in coherent increments.
7.  Run relevant automated tests and application-level checks.
8.  If a test cannot be run because of missing credentials, unavailable
    services, or environment limitations, state that explicitly.
9.  Do not fabricate test results, API quotas, model capabilities, or
    successful deployment.
10. Update documentation and `.env.example` when configuration changes.
11. Never put real API keys in source code or example files.
12. Do not add provider SDKs unless explicitly requested; use direct
    REST calls.
13. Do not introduce a new infrastructure dependency without explaining
    the problem it solves and its operational cost.
14. Keep the application runnable at the end of each completed
    implementation task.
15. Do not move to the next version until the current version's
    acceptance criteria have been checked.

## Expected response format for substantial implementation tasks

For a substantial change, report:

-   **Goal:** What capability is being added and why.
-   **Current state:** What the repository already contains.
-   **Plan:** The implementation steps and affected areas.
-   **Decisions:** Important technology or architecture choices and
    trade-offs.
-   **Implementation:** What changed.
-   **Verification:** Tests and actual application checks performed,
    with results.
-   **Limitations:** What remains incomplete or unverified.
-   **Next step:** The smallest logical next task.

Do not produce a large amount of code before understanding the existing
project and the intended change. Work with the repository rather than
replacing it with a fresh template.

------------------------------------------------------------------------

# 44. Immediate starting point

The immediate target is **V1: Complete Conversational AI Application**.

Before implementation:

1. Inspect the development machine and repository, if one already exists.
2. Confirm available Python and Node versions, memory, storage, and whether Docker is installed.
3. Verify current GroqCloud account access, actual model IDs, free-tier limits, and supported features.
4. Test the selected model through direct REST requests for normal chat, streaming, tool calling, structured output, and realistic context sizes.
5. Decide the database setup and authentication approach.
6. Produce a short architecture and implementation plan.
7. Begin V1 in coherent, testable increments.

Do not start by building only a one-message chatbot. The first
deliverable is the complete V1 application described above.

## Final project principle

Build a real application, learn the technologies because the application
needs them, measure the results, and evolve the same system. The goal is
not to collect framework names or complete tutorial exercises. The goal
is to understand how capable AI applications are designed, implemented,
tested, operated, and improved.
