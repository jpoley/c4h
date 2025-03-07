# c4h_services API Reference

## Introduction

The `c4h_services` library serves as a service orchestration layer that implements and exposes the core functionality provided by `c4h_agents`. It provides various implementations of the intent service interface, adds workflow orchestration, offers a REST API, and includes utilities for configuration management and logging. The primary purpose of this library is to:

1. Provide service-level implementations for agent orchestration
2. Support multiple execution modes (local, prefect-based workflows)
3. Expose agent functionality through a RESTful API
4. Manage teams of agents working together
5. Handle workflow execution, monitoring, and lineage tracking

The library acts as the integration layer between the agent system and external interfaces, ensuring proper configuration propagation, execution tracking, and error handling.

## Folder Structure

```
c4h_services/
├── src/
│   ├── bootstrap/
│   │   └── prefect_runner.py    # Main entry point for execution
│   ├── api/
│   │   ├── service.py           # FastAPI service implementation
│   │   └── models.py            # API request/response models
│   ├── intent/
│   │   ├── core/
│   │   │   └── service.py       # Intent service interface
│   │   └── impl/
│   │       ├── team/
│   │       │   └── service.py   # Team-based implementation
│   │       └── prefect/
│   │           ├── service.py   # Prefect implementation
│   │           ├── flows.py     # Workflow definitions
│   │           ├── tasks.py     # Task wrappers
│   │           ├── models.py    # Task models
│   │           ├── factories.py # Task factories
│   │           └── workflows.py # Core workflow logic
│   ├── orchestration/
│   │   ├── orchestrator.py      # Team orchestration
│   │   └── team.py              # Team implementation
│   └── utils/
│       ├── logging.py           # Logging utilities
│       ├── string_utils.py      # String handling utilities
│       └── __init__.py          # Package exports
```

## Class Diagram

```mermaid
classDiagram
    class IntentService {
        <<Protocol>>
        +process_intent(project_path, intent_desc, max_iterations)
        +get_status(intent_id)
        +cancel_intent(intent_id)
    }
    
    class TeamIntentService {
        +config: Dict
        +orchestrator: Orchestrator
        +__init__(config_path)
        +process_intent(project_path, intent_desc, max_iterations)
        +get_status(intent_id)
        +cancel_intent(intent_id)
    }
    
    class PrefectIntentService {
        +config: Dict
        +client: PrefectClient
        +__init__(config_path)
        +process_intent(project_path, intent_desc, max_iterations)
        +get_status(intent_id)
        +cancel_intent(intent_id)
        +create_deployment(name, schedule)
    }
    
    class Orchestrator {
        +config: Dict
        +teams: Dict
        +__init__(config)
        +execute_workflow(entry_team, context, max_teams)
        +_load_teams()
        +_load_default_teams()
    }
    
    class Team {
        +team_id: str
        +name: str
        +tasks: List
        +config: Dict
        +__init__(team_id, name, tasks, config)
        +execute(context)
        +_determine_next_team(results, context)
        +_evaluate_condition(condition, results, context)
    }
    
    class WorkflowRequest {
        +project_path: str
        +intent: Dict
        +system_config: Optional~Dict~
        +app_config: Optional~Dict~
    }
    
    class WorkflowResponse {
        +workflow_id: str
        +status: str
        +storage_path: Optional~str~
        +error: Optional~str~
    }
    
    class AgentTaskConfig {
        +agent_class: Any
        +config: Dict
        +task_name: Optional~str~
        +requires_approval: bool
        +max_retries: int
        +retry_delay_seconds: int
    }

    IntentService <|.. TeamIntentService
    IntentService <|.. PrefectIntentService
    TeamIntentService --> Orchestrator
    Orchestrator --> Team
```

## Main Entry Point: prefect_runner.py

The `prefect_runner.py` script serves as the main entry point for the services implementation, providing both command-line and API interfaces to the agent system.

```python
class prefect_runner:
    # Main entry point function
    def main()
    
    # Configuration loading
    def load_configs(app_config_path: Optional[str] = None, system_config_paths: Optional[List[str]] = None) -> Dict[str, Any]
    
    # Workflow execution
    def run_workflow(project_path: Optional[str], intent_desc: Dict[str, Any], config: Dict[str, Any]) -> Dict[str, Any]
```

### Usage Modes

The runner supports two primary modes:

1. **Workflow Mode**: Direct execution of agent workflows
   ```bash
   python -m c4h_services.src.bootstrap.prefect_runner workflow --project-path /path/to/project --intent-file intent.json
   ```

2. **Service Mode**: Running as a REST API service
   ```bash
   python -m c4h_services.src.bootstrap.prefect_runner service --port 8000 --config config.yml
   ```

### Configuration Loading

```python
# Load and merge configurations from multiple sources
config = load_configs(
    app_config_path="app_config.yml",
    system_config_paths=["system_config.yml", "override_config.yml"]
)
```

## Core Services Implementation

### IntentService Protocol (intent/core/service.py)

```python
@runtime_checkable
class IntentService(Protocol):
    # Process a refactoring intent
    def process_intent(
        self,
        project_path: Path,
        intent_desc: Dict[str, Any],
        max_iterations: int = 3
    ) -> Dict[str, Any]
    
    # Get status for a workflow run
    def get_status(self, intent_id: str) -> Dict[str, Any]
    
    # Cancel a running workflow
    def cancel_intent(self, intent_id: str) -> bool
```

### TeamIntentService (intent/impl/team/service.py)

```python
class TeamIntentService(IntentService):
    # Initialization
    def __init__(self, config_path: Optional[Path] = None)
    
    # Process refactoring intent through team workflow
    async def process_intent(
        self,
        project_path: Path,
        intent_desc: Dict[str, Any],
        max_iterations: int = 3
    ) -> Dict[str, Any]
    
    # Get status for a workflow run
    async def get_status(self, intent_id: str) -> Dict[str, Any]
    
    # Cancel a workflow run
    async def cancel_intent(self, intent_id: str) -> bool
```

### PrefectIntentService (intent/impl/prefect/service.py)

```python
class PrefectIntentService:
    # Initialization
    def __init__(self, config_path: Optional[Path] = None)
    
    # Process refactoring intent through Prefect workflow
    async def process_intent(
        self,
        project_path: Path,
        intent_desc: Dict[str, Any],
        max_iterations: int = 3
    ) -> Dict[str, Any]
    
    # Get status from Prefect flow run
    async def get_status(self, intent_id: str) -> Dict[str, Any]
    
    # Cancel Prefect flow run
    async def cancel_intent(self, intent_id: str) -> bool
    
    # Create a deployment for the intent workflow
    async def create_deployment(
        self,
        name: str,
        schedule: Optional[str] = None
    ) -> Dict[str, Any]
```

## Orchestration

### Orchestrator (orchestration/orchestrator.py)

```python
class Orchestrator:
    # Initialization
    def __init__(self, config: Dict[str, Any])
    
    # Load team configurations
    def _load_teams(self) -> None
    
    # Load default teams for backward compatibility
    def _load_default_teams(self) -> None
    
    # Execute a workflow starting from the specified team
    def execute_workflow(
        self, 
        entry_team: str = "discovery",
        context: Dict[str, Any] = None,
        max_teams: int = 10
    ) -> Dict[str, Any]
```

### Team (orchestration/team.py)

```python
class Team:
    # Initialization
    def __init__(self, team_id: str, name: str, tasks: List[AgentTaskConfig], config: Dict[str, Any])
    
    # Execute this team's agents in sequence
    def execute(self, context: Dict[str, Any]) -> Dict[str, Any]
    
    # Determine the next team to execute based on routing rules and results
    def _determine_next_team(self, results: List[Dict[str, Any]], context: Dict[str, Any]) -> Optional[str]
    
    # Evaluate a routing condition against results and context
    def _evaluate_condition(self, condition: str, results: List[Dict[str, Any]], context: Dict[str, Any]) -> bool
```

## Prefect Implementation

### AgentTaskConfig (intent/impl/prefect/models.py)

```python
class AgentTaskConfig(BaseModel):
    # Agent class or string path for dynamic loading
    agent_class: Any
    
    # Configuration dictionary
    config: Dict[str, Any] = Field(default_factory=dict)
    
    # Task name
    task_name: Optional[str] = None
    
    # Whether this task requires user approval
    requires_approval: bool = Field(default=False)
    
    # Max retry attempts
    max_retries: int = Field(default=3)
    
    # Seconds to wait between retries
    retry_delay_seconds: int = Field(default=30)
    
    class Config:
        arbitrary_types_allowed = True
```

### run_agent_task (intent/impl/prefect/tasks.py)

```python
@task(retries=2, retry_delay_seconds=10)
def run_agent_task(
    agent_config: AgentTaskConfig,
    context: Dict[str, Any],
    task_name: Optional[str] = None
) -> Dict[str, Any]
```

### Task Factories (intent/impl/prefect/factories.py)

```python
# Prepare configuration for an agent
def prepare_agent_config(config: Dict[str, Any], agent_section: str) -> Dict[str, Any]

# Create discovery agent task configuration
def create_discovery_task(config: Dict[str, Any]) -> AgentTaskConfig

# Create solution designer task configuration
def create_solution_task(config: Dict[str, Any]) -> AgentTaskConfig

# Create coder agent task configuration
def create_coder_task(config: Dict[str, Any]) -> AgentTaskConfig

# Create task configurations for a team from configuration
def create_team_tasks(config: Dict[str, Any], team_config: Dict[str, Any]) -> List[AgentTaskConfig]
```

### Workflows (intent/impl/prefect/workflows.py)

```python
# Prepare workflow configuration with proper run ID and context
def prepare_workflow_config(base_config: Dict[str, Any]) -> Dict[str, Any]

# Basic workflow implementing the core refactoring steps
@flow(name="basic_refactoring")
def run_basic_workflow(
    project_path: Path,
    intent_desc: Dict[str, Any],
    config: Dict[str, Any]
) -> Dict[str, Any]
```

### Flows (intent/impl/prefect/flows.py)

```python
# Main workflow for intent-based refactoring
@flow(name="intent_refactoring")
def run_intent_workflow(
    project_path: Path,
    intent_desc: Dict[str, Any],
    config: Dict[str, Any],
    max_iterations: int = 3
) -> Dict[str, Any]

# Recovery workflow for handling failed runs
@flow(name="intent_recovery")
def run_recovery_workflow(
    flow_run_id: str,
    config: Dict[str, Any]
) -> Dict[str, Any]
```

## API Service

### API Models (api/models.py)

```python
class WorkflowRequest(BaseModel):
    # Path to the project to be processed
    project_path: str = Field(..., description="Path to the project to be processed")
    
    # Intent description for the workflow
    intent: Dict[str, Any] = Field(..., description="Intent description for the workflow")
    
    # Base system configuration
    system_config: Optional[Dict[str, Any]] = Field(default=None, description="Base system configuration")
    
    # Application-specific configuration overrides
    app_config: Optional[Dict[str, Any]] = Field(default=None, description="Application-specific configuration overrides")

class WorkflowResponse(BaseModel):
    # Unique identifier for the workflow
    workflow_id: str = Field(..., description="Unique identifier for the workflow")
    
    # Current status of the workflow
    status: str = Field(..., description="Current status of the workflow")
    
    # Path to stored results if available
    storage_path: Optional[str] = Field(default=None, description="Path to stored results if available")
    
    # Error message if status is 'error'
    error: Optional[str] = Field(default=None, description="Error message if status is 'error'")
```

### FastAPI Service (api/service.py)

```python
def create_app(default_config: Dict[str, Any] = None) -> FastAPI:
    # Create FastAPI application with team-based orchestration
    
    @app.post("/api/v1/workflow", response_model=WorkflowResponse)
    async def run_workflow(request: WorkflowRequest):
        # Execute a team-based workflow with the provided configuration
        
    @app.get("/api/v1/workflow/{workflow_id}", response_model=WorkflowResponse)
    async def get_workflow(workflow_id: str):
        # Get workflow status and results
        
    @app.get("/health")
    async def health_check():
        # Simple health check endpoint
```

## System Configuration Structure

The system configuration (system_config.yml) provides a comprehensive configuration template for the entire agent system. It serves as the foundation that can be extended or overridden by application-specific configurations.

### Purpose

1. Provide default configurations for all components
2. Define provider settings (API endpoints, models, etc.)
3. Configure agent-specific parameters
4. Set up team composition and routing
5. Define workflow and lineage tracking settings
6. Configure logging and backup behavior

### Configuration Structure

```yaml
llm_config:
  # Provider configurations
  providers:
    anthropic:
      api_base: "https://api.anthropic.com"
      context_length: 200000
      env_var: "ANTHROPIC_API_KEY"
      default_model: "claude-3-5-sonnet-20241022"
      valid_models: [...]
      extended_thinking:
        enabled: false
        budget_tokens: 32000
      litellm_params:
        retry: true
        max_retries: 5
        timeout: 30
        
    openai:
      api_base: "https://api.openai.com/v1"
      env_var: "OPENAI_API_KEY"
      default_model: "gpt-4o"
      valid_models: [...]

  # Global defaults
  default_provider: "anthropic"
  default_model: "claude-3-opus-20240229"
  
  # Agent-specific configurations
  agents:
    base:  # Base settings all agents inherit
      storage:
        root_dir: "workspaces"
        
    lineage:  # Lineage tracking configuration
      enabled: true
      namespace: "c4h_agents"
      backend:
        type: "file"
        
    discovery:
      default_provider: "anthropic"
      default_model: "claude-3-5-sonnet-20241022"
      temperature: 0
      tartxt_config: {...}
      prompts: {...}
      
    solution_designer:
      provider: "anthropic"
      model: "claude-3-5-sonnet-20241022"
      temperature: 0
      prompts: {...}
      
    semantic_extract:
      provider: "anthropic"
      model: "claude-3-opus-20240229"
      temperature: 0
      prompts: {...}
      
    semantic_iterator:
      prompts: {...}
      
    semantic_fast_extractor:
      provider: "openai"
      model: "o3-mini" 
      temperature: 0
      prompts: {...}
      
    semantic_slow_extractor:
      provider: "openai"
      model: "o3-mini"  
      temperature: 0
      prompts: {...}
      
    semantic_merge:
      provider: "openai"
      model: "o3-mini"  
      temperature: 0
      merge_config: {...}
      prompts: {...}
      
    coder:
      provider: "anthropic"
      model: "claude-3-opus-20240229"
      temperature: 0
      prompts: {...}
    
    assurance:
      provider: "openai"
      model: "gpt-4-0125-preview"
      temperature: 0
      prompts: {...}

# Team orchestration configuration
orchestration:
  enabled: true
  entry_team: "discovery"  # First team to execute
  error_handling:
    retry_teams: true
    max_retries: 2
  teams:
    # Discovery team - analyzes project structure
    discovery:
      name: "Discovery Team"
      tasks: [...]
      routing:
        default: "solution"  # Go to solution team next
    
    # Solution team - designs code changes
    solution:
      name: "Solution Design Team"
      tasks: [...]
      routing:
        rules: [...]
        default: "coder"
    
    # Coder team - implements code changes
    coder:
      name: "Coder Team"
      tasks: [...]
      routing:
        rules: [...]
        default: null
    
    # Fallback team - handles failures with simplified approach
    fallback:
      name: "Fallback Team"
      tasks: [...]
      routing:
        default: null

# Runtime configuration for workflow and lineage
runtime:
  # Workflow storage configuration
  workflow:
    storage:
      enabled: true
      root_dir: "workspaces/workflows"
      format: "yymmdd_hhmm_{workflow_id}"
      retention:
        max_runs: 10
        max_days: 30
  # Lineage tracking configuration
  lineage:
    enabled: true
    namespace: "c4h_agents"
    separate_input_output: true
    backend:
      type: "file"
      path: "workspaces/lineage"

# Backup settings
backup:
  enabled: true
  path: "workspaces/backups"

# Logging configuration
logging:
  level: "INFO"
  format: "structured"
  agent_level: "INFO"
  providers:
    anthropic:
      level: "debug"
    openai:
      level: "debug"
  truncate:
    prefix_length: 30
    suffix_length: 30
```

## Usage Patterns

### Running as a Service

```python
from c4h_services.src.bootstrap.prefect_runner import create_app
from c4h_services.src.bootstrap.prefect_runner import load_configs

# Load configuration
config = load_configs("app_config.yml", ["system_config.yml"])

# Create FastAPI app
app = create_app(default_config=config)

# Run the service
import uvicorn
uvicorn.run(app, host="0.0.0.0", port=8000)
```

### Running a Direct Workflow

```python
from c4h_services.src.bootstrap.prefect_runner import run_workflow
from c4h_services.src.bootstrap.prefect_runner import load_configs
from pathlib import Path

# Load configuration
config = load_configs("app_config.yml", ["system_config.yml"])

# Define intent
intent = {
    "description": "Refactor code to follow single responsibility principle",
    "target_files": ["src/module.py", "src/utils.py"]
}

# Run workflow
result = run_workflow(
    project_path=Path("/path/to/project"),
    intent_desc=intent,
    config=config
)

# Process result
if result["status"] == "success":
    print(f"Changes applied: {len(result['changes'])}")
    for change in result.get("changes", []):
        print(f"- {change['file']}: {change['success']}")
else:
    print(f"Error: {result['error']}")
```

### Using the Team Orchestrator

```python
from c4h_services.src.orchestration.orchestrator import Orchestrator

# Create orchestrator with configuration
orchestrator = Orchestrator(config)

# Prepare context
context = {
    "project_path": "/path/to/project",
    "intent": {
        "description": "Add error handling to function X"
    },
    "workflow_run_id": "wf_12345"
}

# Execute workflow
result = orchestrator.execute_workflow(
    entry_team="discovery",
    context=context,
    max_teams=10
)

# Process result
print(f"Status: {result['status']}")
print(f"Execution path: {' -> '.join(result['execution_path'])}")
```

### Using the API

```python
import requests
import json

# API endpoint
url = "http://localhost:8000/api/v1/workflow"

# Request data
data = {
    "project_path": "/path/to/project",
    "intent": {
        "description": "Refactor code to improve error handling",
        "target_files": ["src/module.py"]
    },
    "system_config": None,
    "app_config": {
        "logging": {
            "level": "DEBUG"
        }
    }
}

# Send request
response = requests.post(url, json=data)
result = response.json()

# Get workflow ID
workflow_id = result["workflow_id"]

# Check status
status_url = f"http://localhost:8000/api/v1/workflow/{workflow_id}"
status = requests.get(status_url).json()

print(f"Status: {status['status']}")
print(f"Storage Path: {status['storage_path']}")
```

## Response Formats

### Workflow Response

```python
{
    "workflow_id": "wf_12345",
    "status": "success",
    "storage_path": "workspaces/lineage/wf_12345",
    "error": None
}
```

### Detailed Workflow Result

```python
{
    "status": "success",
    "workflow_run_id": "wf_12345",
    "execution_path": ["discovery", "solution", "coder"],
    "team_results": {
        "discovery": {
            "success": True,
            "data": {...},
            "next_team": "solution"
        },
        "solution": {
            "success": True,
            "data": {...},
            "next_team": "coder"
        },
        "coder": {
            "success": True,
            "data": {...},
            "next_team": None
        }
    },
    "data": {
        "changes": [
            {
                "file": "src/module.py",
                "success": True,
                "error": None,
                "backup": "workspaces/backups/20240307_123456/src/module.py"
            }
        ]
    },
    "teams_executed": 3,
    "timestamp": "2024-03-07T12:34:56Z"
}
```

## Key Design Principles

1. **Team-Based Execution**: Organize agents into teams with clear responsibilities
2. **Workflow Orchestration**: Sequential team execution with conditional routing
3. **Configuration Hierarchy**: System config + application overrides
4. **Service Independence**: Multiple service implementations with same interface
5. **Lineage Tracking**: Record execution paths and relationships
6. **Error Resilience**: Graceful fallback and recovery mechanisms
7. **Observability**: Comprehensive logging and monitoring

These principles ensure that the service layer can effectively coordinate agent activities while maintaining flexibility, reliability, and observability.