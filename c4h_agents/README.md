# C4H Agents Library

Modern Python library for LLM-based code refactoring agents.

## Installation

```bash
pip install c4h_agents
```

## Development Setup

```bash
# Create and activate virtual environment
python -m venv venv
source venv/bin/activate  # or `venv\Scripts\activate` on Windows

# Install in development mode with test dependencies
pip install -e ".[test]"

# Run tests
pytest
```

## Project Structure

```
src/
├── agents/     # Core agent implementations
└── skills/     # Reusable skills and utilities
    └── shared/ # Shared types and utilities
```

## Design Principles

1. LLM-First Processing
2. Minimal Agent Logic
3. Clear Boundaries
4. Single Responsibility
5. Stateless Operation

See [Agent Design Principles](docs/agent_design.md) for details.