# C4H Services

Service implementations for the c4h_agents library.

## Available Services

### Intent Service

Core refactoring service with multiple implementations:

- Local: Simple synchronous implementation (default)
- Prefect: Advanced workflow orchestration with monitoring
  ```bash
  pip install "c4h_services[prefect]"
  ```

## Development Setup

```bash
# First install agents library
cd ../c4h_agents
pip install -e ".[test]"

# Then install services with all extras
cd ../c4h_services
pip install -e ".[test,prefect]"

# Run tests
pytest
```

## Project Structure

```
src/
└── intent/           # Intent service framework
    ├── core/         # Core interfaces
    └── impl/         # Implementations
        ├── prefect/  # Prefect-based implementation
        └── local/    # Simple local implementation
```