# Contributing to Crucible Agent

Thank you for your interest in contributing to Crucible Agent! This guide will help you get started.

## Development Setup

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (package manager)
- Docker & Docker Compose (for full-stack development)

### Getting Started

```bash
# Clone the repository
git clone https://github.com/kumagallium/crucible-agent.git
cd crucible-agent

# Run setup script (installs uv + dependencies)
./setup.sh

# Or manually:
uv sync --dev

# Copy environment variables
cp .env.example .env

# Start development server
uv run uvicorn crucible_agent.main:app --reload --port 8090
```

### Running Tests

```bash
# Unit tests with coverage
uv run pytest

# E2E browser tests (requires Playwright)
uv sync --extra e2e
uv run playwright install chromium
uv run pytest tests/e2e_browser/
```

### Linting

```bash
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
```

## How to Contribute

### Reporting Bugs

1. Search [existing issues](https://github.com/kumagallium/crucible-agent/issues) to avoid duplicates
2. Open a new issue with:
   - Steps to reproduce
   - Expected vs actual behavior
   - Python version and OS

### Suggesting Features

Open an issue with the `enhancement` label describing:
- The problem you're trying to solve
- Your proposed solution
- Any alternatives you've considered

### Pull Requests

1. Fork the repository
2. Create a feature branch (`git checkout -b feat/your-feature`)
3. Make your changes
4. Run linting (`uv run ruff check src/ tests/`)
5. Run tests and ensure they pass (`uv run pytest`)
6. Commit with a clear message following the [commit convention](#commit-messages)
7. Push and open a Pull Request

### Commit Messages

```
[type] Short description

Types:
  feat     - New feature
  fix      - Bug fix
  docs     - Documentation only
  refactor - Code refactoring
  chore    - Maintenance tasks
  test     - Adding or updating tests
```

Example: `[feat] Add session branching support`

## Code Style

- **Linter/Formatter**: [Ruff](https://docs.astral.sh/ruff/) (configured in `pyproject.toml`)
- **Line length**: 100 characters
- **Type hints**: Use type annotations for all function signatures
- **Lint rules**: E, F, I, N, UP, B, A, SIM

## Project Structure

```
src/crucible_agent/
├── main.py            # FastAPI entry point
├── config.py          # Pydantic Settings
├── api/               # REST / WebSocket endpoints
│   ├── routes.py
│   ├── schemas.py
│   └── auth.py
├── agent/             # Agent runtime
│   ├── runner.py
│   └── adapter.py
├── crucible/          # Crucible Registry integration
│   ├── discovery.py
│   └── cli_executor.py
├── provenance/        # PROV-DM audit trail
│   ├── recorder.py
│   └── models.py
└── prompts/           # Prompt profile management
    └── loader.py
```

## License

By contributing, you agree that your contributions will be licensed under the [MIT License](LICENSE).
