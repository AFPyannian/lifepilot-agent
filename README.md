# LifePilot Agent

A personal assistant Agent built with LangGraph and LangChain.

## Current status

- [x] Python environment initialized
- [x] Project structure created
- [x] LangGraph workflow
- [ ] Tool calling
- [ ] Persistent memory
- [ ] Personal knowledge base
- [ ] Web interface
- [x] Automated tests
- [ ] Docker deployment
- [x] Centralized configuration validation
- [x] Secret-safe logging
- [x] Unified exception handling
- [x] Persistent note CRUD
- [x] Keyword note search
- [x] Note Agent tools
- [x] Structured user profile
- [x] Cross-thread long-term memory
- [x] User-scoped memory isolation
- [x] Explicit memory consent rules

## Python version

Python 3.11

## Agent tools

### Todo tools

- Add todo
- List todos
- Complete todo
- Delete todo

### Note tools

- Add note
- List notes
- Get note
- Search notes
- Update note
- Delete note

## Memory architecture

- Short-term memory: LangGraph checkpoints scoped by thread ID
- Long-term memory: SQLite user memories scoped by owner ID
- Business data: SQLite todos and notes