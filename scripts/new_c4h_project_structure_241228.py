"""
Create modern Python library and service structures.
Path: scripts/create_structure.py
"""

import os
from pathlib import Path
import subprocess
from typing import List

def create_dirs(directories: List[str]):
    """Create directories ensuring parents exist"""
    for directory in directories:
        Path(directory).mkdir(parents=True, exist_ok=True)

def create_library_structure():
    """Create the core agents library structure"""
    lib_dirs = [
        # Core library
        "c4h_agents/src/agents",
        "c4h_agents/src/skills",
        "c4h_agents/src/skills/shared",
        "c4h_agents/tests",
        "c4h_agents/docs",
        "c4h_agents/examples"
    ]
    create_dirs(lib_dirs)

def create_services_structure():
    """Create the services structure with intent service"""
    service_dirs = [
        # Service framework
        "c4h_services/src/intent/core",
        "c4h_services/src/intent/impl/prefect",  # Prefect-specific implementation
        "c4h_services/src/intent/impl/local",    # Simple local implementation
        "c4h_services/config",
        "c4h_services/tests/intent",
        "c4h_services/docs",
    ]
    create_dirs(service_dirs)

def create_library_pyproject():
    """Create pyproject.toml for the agents library"""
    content = '''
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "c4h_agents"
version = "0.1.0"
description = "LLM-based code refactoring agents library"
readme = "README.md"
requires-python = ">=3.9"
dependencies = [
    "litellm>=1.0.0",
    "structlog>=24.1.0",
    "rich>=13.0.0",
    "PyYAML>=6.0",
    "pydantic>=2.0.0",
]

[project.optional-dependencies]
test = [
    "pytest>=7.0.0",
    "pytest-cov>=4.1.0",
    "pytest-asyncio>=0.21.0",
]

[tool.hatch.build.targets.wheel]
packages = ["src/agents", "src/skills"]

[tool.pytest.ini_options]
addopts = "--cov=src --cov-report=xml --cov-report=term-missing"
testpaths = ["tests"]
'''
    with open('c4h_agents/pyproject.toml', 'w') as f:
        f.write(content.strip())

def create_services_pyproject():
    """Create pyproject.toml for the services package"""
    content = '''
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "c4h_services"
version = "0.1.0"
description = "Service implementations for c4h_agents"
readme = "README.md"
requires-python = ">=3.9"
dependencies = [
    "c4h_agents",
    "fastapi>=0.100.0",
    "typer>=0.9.0",
]

[project.optional-dependencies]
prefect = [
    "prefect>=2.14.0",
]
test = [
    "pytest>=7.0.0",
    "pytest-cov>=4.1.0",
    "pytest-asyncio>=0.21.0",
]

[tool.hatch.build.targets.wheel]
packages = ["src/intent"]

[tool.pytest.ini_options]
addopts = "--cov=src --cov-report=xml --cov-report=term-missing"
testpaths = ["tests"]
'''
    with open('c4h_services/pyproject.toml', 'w') as f:
        f.write(content.strip())

def setup_git_repos():
    """Initialize git repositories with .gitignore"""
    gitignore_content = '''
# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
env/
build/
develop-eggs/
dist/
downloads/
eggs/
.eggs/
lib/
lib64/
parts/
sdist/
var/
wheels/
*.egg-info/
.installed.cfg
*.egg
.env
.venv
venv/
ENV/

# Testing
.coverage
coverage.xml
.pytest_cache/
htmlcov/

# IDEs
.idea/
.vscode/
*.swp
*.swo

# OS
.DS_Store
Thumbs.db
'''
    
    for project in ['c4h_agents', 'c4h_services']:
        os.chdir(project)
        subprocess.run(['git', 'init'])
        with open('.gitignore', 'w') as f:
            f.write(gitignore_content.strip())
        os.chdir('..')

def create_readmes():
    """Create README files for both packages"""
    agents_readme = '''# C4H Agents Library

Modern Python library for LLM-based code refactoring agents.

## Installation

```bash
pip install c4h_agents
```

## Development Setup

```bash
# Create and activate virtual environment
python -m venv venv
source venv/bin/activate  # or `venv\\Scripts\\activate` on Windows

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
'''
    
    services_readme = '''# C4H Services

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
'''
    
    with open('c4h_agents/README.md', 'w') as f:
        f.write(agents_readme.strip())
        
    with open('c4h_services/README.md', 'w') as f:
        f.write(services_readme.strip())

def main():
    print("Creating project structures...")
    create_library_structure()
    create_services_structure()
    
    print("Creating project configurations...")
    create_library_pyproject()
    create_services_pyproject()
    
    print("Setting up git repositories...")
    setup_git_repos()
    
    print("Creating documentation...")
    create_readmes()
    
    print("Project structures created successfully!")

if __name__ == "__main__":
    main()