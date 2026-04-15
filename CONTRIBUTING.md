# Contributing to ProContext Crawler

Thank you for your interest in contributing. This guide covers everything you need to get started.

---

## Before you start

For non-trivial changes — new endpoints, architectural decisions, changes that touch multiple modules, or anything security-relevant — open an issue first to discuss the approach. ProContext Crawler follows a spec-first development process: significant changes should align with, or update, the relevant spec documents in [`docs/specs/`](docs/specs/) before code is written.

This isn't gatekeeping; it's to avoid wasted effort. A PR that conflicts with the roadmap or an already-planned design decision will be closed regardless of code quality.

For bug fixes and documentation improvements, you can go straight to a PR.

---

## Prerequisites

- **Python 3.12+**
- **[uv](https://docs.astral.sh/uv/)** — used for dependency management, virtual environments, and running the project
- **Chromium** (optional, only for Playwright rendering work) — install once via `uv run playwright install chromium`

---

## Setup

```bash
git clone https://github.com/procontexthq/procontext-crawler.git
cd procontext-crawler
uv sync --dev
```

This creates a virtual environment and installs all runtime + dev dependencies.

Verify the setup:

```bash
uv run ruff check src/ tests/    # Lint
uv run ruff format --check src/ tests/   # Format check
uv run pyright src/              # Type check
uv run pytest                    # Tests
```

---

## Development Workflow

### 1. Pick something to work on

- Check [open issues](https://github.com/procontexthq/procontext-crawler/issues) for bugs or feature requests.
- Review the specs in [`docs/specs/`](docs/specs/) and open an issue for anything unclear or inconsistent.
- The post-v0.1 roadmap lives in [`docs/implementation-plan.md`](docs/implementation-plan.md) §8.

If you're unsure whether a change is wanted, open an issue first to discuss it.

### 2. Create a branch

```bash
git checkout -b <type>/<short-description>
```

Branch naming convention:

| Prefix      | Use for                                     |
| ----------- | ------------------------------------------- |
| `feat/`     | New features                                |
| `fix/`      | Bug fixes                                   |
| `docs/`     | Documentation changes                       |
| `refactor/` | Code restructuring without behaviour change |
| `test/`     | Adding or improving tests                   |
| `chore/`    | Build, CI, tooling changes                  |

### 3. Make your changes

Before writing code, read the relevant spec documents — the project follows a spec-first approach:

- [Functional Specification](docs/specs/01-functional-spec.md) — what each endpoint does and the v0.1 scope
- [Technical Specification](docs/specs/02-technical-spec.md) — architecture, module boundaries, internal contracts
- [API Reference](docs/specs/04-api-reference.md) — wire format, error codes, pagination
- [Security Specification](docs/specs/05-security-spec.md) — threat model, SSRF, size limits, auth

See the [Coding Conventions](#coding-conventions) section below for the rules that matter most.

### 4. Write tests first

This project follows test-first development (see [`.claude/rules/coding-guidelines.md`](.claude/rules/coding-guidelines.md) §16). Branch coverage must stay at or above 90%:

```bash
uv run pytest --cov=src/proctx_crawler --cov-fail-under=90
```

### 5. Run all checks before pushing

```bash
uv run ruff check src/ tests/
uv run ruff format src/ tests/
uv run pyright src/
uv run pytest --cov=src/proctx_crawler --cov-fail-under=90
```

All four must pass. CI runs the same checks — a PR with failures will not be reviewed.

### 6. Commit and push

Commit messages must follow [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>[optional scope]: <description>

[optional body]

[optional footer: BREAKING CHANGE: <description>]
```

**Types**: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`

Examples:

```
feat(engine): add llms_txt source discovery

fix(fetcher): re-validate SSRF on each redirect hop

docs(spec): clarify cursor-pagination contract

BREAKING CHANGE: rename Crawler.fetch() to Crawler.content()
```

Breaking changes **must** include `BREAKING CHANGE:` in the commit footer — this drives major version bumps and changelog entries.

### 7. Open a pull request

- Target the `main` branch.
- Describe what changed and why.
- Reference any related issue (e.g., `Closes #12`).
- If the PR introduces new behaviour, include the relevant test cases.

Smaller, focused PRs get reviewed faster. A clean 50-line change with a clear description can be reviewed the same day. A 500-line multi-module PR may wait weeks — and the larger it is, the more likely it is to conflict with in-progress work.

---

## Coding Conventions

These are the conventions that trip people up. Standard Python practices (PEP 8, type hints, etc.) are assumed. For the full set of non-obvious rules, see [`.claude/rules/coding-guidelines.md`](.claude/rules/coding-guidelines.md).

### Architecture

- **Layered design.** API (FastAPI) → `Crawler` class → core engine → fetchers/extractors. Core modules have zero framework imports. A lower layer never reaches into a higher one.
- **Repository protocol.** Job and URL metadata persistence is typed against the `Repository` protocol in `core/repository.py`. The SQLite implementation lives in `infrastructure/`. Write new storage backends against the protocol, never against `SQLiteRepository` directly.
- **Dependency injection at `Crawler`.** The `Crawler` class receives its repository, content store, browser pool, and fetcher as constructor arguments. No module-level singletons, no global state.
- **Dual fetch paths.** Static fetch via `httpx` is the default. Playwright is behind `render=True` and the browser pool is lazily initialised on first use — code paths that never render must not force browser startup.

### Error handling

- **Use the `CrawlerError` hierarchy.** Raise domain-specific subclasses (`FetchError`, `RenderError`, `ValidationError`, etc.) defined in `models/errors.py`. API handlers catch these and serialise them into the standard error envelope.
- **Never swallow errors in core modules.** The fetcher, engine, and repository must propagate errors with context. Top-level handlers (HTTP routes, CLI dispatch, background tasks) may catch to keep the process alive, but must log with `exc_info=True` — never `pass` or a silent comment.
- **Wrap infrastructure exceptions at the module boundary.** Callers must not need to import `httpx`, `aiosqlite`, or `playwright` to handle errors from higher-level modules.

See [`.claude/rules/coding-guidelines.md`](.claude/rules/coding-guidelines.md) §7–§11 for the full rules.

### Code style

- **`from __future__ import annotations`** in every module. Type-only imports go inside `if TYPE_CHECKING:` blocks.
- **`X | None`** union syntax, not `Optional[X]`.
- **pyright** is the type checker (not mypy). Standard mode is enforced.
- **ruff** handles linting and formatting. Line length is 100.
- **structlog only.** Never use the stdlib `logging` module directly, and never `print()`. Logs go to stderr.
- **Platform-aware paths.** Use `platformdirs` for default directories. Never hardcode Unix paths.
- **No imports inside functions**, except for breaking genuine circular imports or guarding optional dependencies — and both cases require an explanatory comment. See [`.claude/rules/coding-guidelines.md`](.claude/rules/coding-guidelines.md) §15.

### Testing

- **pytest + anyio** (not `pytest-asyncio`). Mark async tests with `@pytest.mark.anyio` or use the configured default.
- **respx** for `httpx` mocking. Never make real network calls in tests.
- **In-memory or `tmp_path` SQLite** per test — no shared database state.
- **`anyio.fail_after(5)`** around indefinite waits (`event.wait()`, `stream.receive()`) to prevent hangs. Avoid fixed-duration `anyio.sleep()` — use `anyio.Event` instead.

**When to write tests**

- Bug fix → add a regression test that fails before the fix and passes after.
- New endpoint or `Crawler` method → integration test in `tests/integration/`.
- New internal function → unit test in `tests/unit/test_<module>.py`.
- Security-relevant input handling (SSRF, size limits, auth) → explicit test regardless of where it lives.

**Where to put them**

- `tests/unit/` — tests a single module in isolation with mocked collaborators.
- `tests/integration/` — tests the full pipeline (HTTP API, Python API, CLI) end-to-end with a mocked network. See `tests/integration/conftest.py` for the shared fixtures (`patch_fetcher`, `mock_pages`, `tmp_crawler`).
- Match the filename to the module: changes to `core/engine.py` → `tests/unit/test_engine.py`.

Integration tests must test the public API and observable behaviour, not internal implementation details. A complete internal rewrite must not break any integration test — if it does, the tests are pinned to implementation rather than contract.

---

## Project Structure

```
src/proctx_crawler/
├── __init__.py              # Re-exports the Crawler class
├── crawler.py               # Crawler class — public Python API, async context manager
├── cli.py                   # argparse CLI (crawl, markdown, content, links, serve)
├── config.py                # Settings via pydantic-settings + YAML
├── logging_config.py        # structlog setup
├── api/
│   ├── app.py               # FastAPI app factory, lifespan, error handlers
│   ├── routes.py            # All HTTP routes
│   ├── middleware.py        # ASGI auth middleware (Bearer token)
│   └── errors.py            # ErrorCode → HTTP status mapping
├── core/
│   ├── engine.py            # BFS crawl loop (run_crawl)
│   ├── fetcher.py           # httpx static fetcher with SSRF protection
│   ├── renderer.py          # Playwright renderer
│   ├── browser_pool.py      # Shared Chromium pool (lazy init, crash recovery)
│   ├── discovery.py         # Seed-URL discovery (links, llms.txt)
│   ├── ssrf.py              # SSRF validation (scheme, private IPs, redirect re-check)
│   ├── url_utils.py         # URL normalisation, pattern matching, domain checks
│   └── repository.py        # Repository Protocol
├── extractors/
│   ├── markdown.py          # HTML → Markdown via markdownify
│   ├── links.py             # Link extraction and deduplication
│   └── content.py           # Raw HTML extraction
├── infrastructure/
│   ├── sqlite_repository.py # SQLite Repository implementation (WAL mode)
│   └── content_storage.py   # Filesystem content storage + manifest.json
└── models/                  # Pydantic models (job, url_record, input, output, errors)
```

---

## AI-assisted contributions

AI-assisted code contributions are welcome — using AI tools to write, refactor, or improve code is fine. What matters is the quality and intent behind the submission, not the tools used to produce it.

What we will close:

- Submissions that don't align with the spec documents or the project's design decisions
- Generic improvements that show no familiarity with the codebase (e.g., adding docstrings everywhere, renaming things for style preferences, broad refactors without a stated reason)
- Code that doesn't respect the architecture — layering discipline, the `Repository` protocol boundary, the `CrawlerError` hierarchy, structlog-only logging, the static-vs-render fetch split

What we expect from any PR, AI-assisted or not: that the author has read the relevant spec, understands why the code is structured the way it is, and can explain the change in the PR description. If you used an AI tool to help write the code, that's fine — but the understanding behind the submission should be yours.

---

## Security

If you find a security issue (SSRF bypass, auth bypass, data leak, etc.), do **not** open a public issue. Email the maintainers listed in the repository metadata, or use GitHub's private vulnerability reporting. See [`docs/specs/05-security-spec.md`](docs/specs/05-security-spec.md) for the current threat model.

---

## Questions?

- Open a [GitHub Issue](https://github.com/procontexthq/procontext-crawler/issues) for bugs or concrete feature requests.
- Use [GitHub Discussions](https://github.com/procontexthq/procontext-crawler/discussions) for questions, ideas, or anything that isn't a bug or actionable request.
