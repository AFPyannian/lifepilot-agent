# Changelog

All notable changes to LifePilot Agent are documented in this file.

The project follows [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Optional invitation-only registration with a closed-by-default policy.
- Admin-only APIs and Streamlit controls for creating, listing and revoking one-time invitations.
- Atomic invitation redemption and user creation with registration throttling and audit events.
- Local account management with Argon2id password hashing and admin CLI commands.
- Revocable opaque Bearer Sessions, login throttling and security audit events.
- End-to-end user isolation for conversations, checkpoints, tools, memories, knowledge files and Chroma metadata.
- Offline backup and migration command for existing `local-user` data.
- Streamlit login, logout and password-change session support.

### Changed

- Replaced the shared API Key with authenticated user Sessions on all business routes.
- Namespaced LangGraph checkpoint thread IDs by authenticated user UUID.

### Security

- User identity is injected only from the server-side authentication result and is hidden from model tool schemas.
- Password changes, account disabling and logout-all revoke active Sessions.
- Session tokens are returned only to the client; the database stores SHA-256 digests.

## [1.0.0] - 2026-08-27

### Added

- LangGraph assistant/tool workflow with SQLite Checkpoint persistence.
- DeepSeek chat model integration with configurable timeout and retries.
- Todo, note, user profile and long-term memory tools.
- Owner-scoped SQLite repositories and cross-thread long-term memory.
- Local RAG knowledge base using BGE Chinese embeddings and Chroma.
- Knowledge document upload, listing, search and deletion.
- Human approval and interrupt/resume flow for destructive operations.
- FastAPI chat, streaming, conversation and knowledge management endpoints.
- Streamlit chat, conversation, knowledge base and approval interface.
- SSE token, approval, completion and error events.
- Structured logging, request IDs and optional LangSmith tracing.
- API Key authentication, sliding-window rate limiting and security headers.
- Agent recursion limit and secret-safe configuration validation.
- Offline pytest suite, branch coverage threshold, Agent evaluation and RAG evaluation.
- Ruff, mypy, pre-commit, pre-push and GitHub Actions quality gates.
- Architecture, configuration, testing and design decision documentation.

### Security

- Real secrets are loaded from the ignored local `.env` file.
- Sensitive configuration values use Pydantic SecretStr and are not written to logs by default.
- Destructive Agent tools require explicit user approval.
- Business API routes can require a shared `X-API-Key`.

[1.0.0]: https://github.com/AFPyannian/lifepilot-agent/releases/tag/v1.0.0
