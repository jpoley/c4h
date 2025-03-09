# C4H Services API Integration Guide

## Introduction

This guide provides comprehensive details for integrating with the C4H Services API, a system designed for orchestrating intelligent code refactoring workflows. The API allows you to submit code refactoring intents and receive structured results, making it ideal for building GUI interfaces for code analysis and transformation.

## API Overview

The C4H Services exposes a RESTful API for managing workflow executions. The primary endpoints are:

- `POST /api/v1/workflow` - Submit a new workflow request
- `GET /api/v1/workflow/{workflow_id}` - Check status of an existing workflow
- `GET /health` - Service health check

## Core Concepts

### Workflow

A workflow represents an end-to-end execution process that typically includes:

1. **Discovery** - Analysis of the project structure and files
2. **Solution Design** - Planning modifications based on intent
3. **Code Implementation** - Applying the planned changes

### Intent

An "intent" specifies what you want to accomplish with the codebase. Examples include:
- Adding error handling
- Improving logging
- Refactoring for performance
- Applying design patterns

### Teams

The system uses a team-based approach where specialized agent teams handle different aspects of the workflow:
- **Discovery Team** - Analyzes project files and structure
- **Solution Team** - Designs changes based on intent
- **Coder Team** - Implements the designed changes

## API Reference

### Submit Workflow

```
POST /api/v1/workflow
```

#### Request Body

```json
{
  "project_path": "/path/to/project",
  "intent": {
    "description": "Description of your refactoring intent"
  },
  "app_config": {
    "key": "value"
  },
  "system_config": {
    "key": "value"
  }
}
```

| Field | Type | Description |
|-------|------|-------------|
| project_path | string | Path to the project directory |
| intent | object | Description of refactoring intent |
| app_config | object | Optional application-specific configuration |
| system_config | object | Optional system-level configuration |

#### Response

```json
{
  "workflow_id": "wf_12345678-abcd-1234-efgh-123456789abc",
  "status": "pending",
  "storage_path": "workspaces/lineage/wf_12345678-abcd-1234-efgh-123456789abc",
  "error": null
}
```

### Check Workflow Status

```
GET /api/v1/workflow/{workflow_id}
```

#### Response

```json
{
  "workflow_id": "wf_12345678-abcd-1234-efgh-123456789abc",
  "status": "success",
  "storage_path": "workspaces/lineage/wf_12345678-abcd-1234-efgh-123456789abc",
  "error": null
}
```

Status values:
- `pending` - Processing in progress
- `success` - Completed successfully
- `error` - Failed (error field contains details)

## Configuration Structure

The system uses a hierarchical configuration structure. Here's a comprehensive example:

```yaml
# Project settings
project:
  path: "/path/to/project"
  workspace_root: "workspaces"

# Intent description
intent:
  description: "Add logging to all functions with lineage tracking"

# LLM Configuration
llm_config:
  # Provider settings
  providers:
    anthropic:
      api_base: "https://api.anthropic.com"
      context_length: 200000
      env_var: "ANTHROPIC_API_KEY"
      default_model: "claude-3-5-sonnet-20241022"
      valid_models:
        - "claude-3-7-sonnet-20250219"
        - "claude-3-5-sonnet-20241022"
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
      valid_models:
        - "gpt-4o"
        - "gpt-4o-mini"
  
  # Global defaults
  default_provider: "anthropic"
  default_model: "claude-3-opus-20240229"
  
  # Agent-specific configurations
  agents:
    discovery:
      default_provider: "anthropic"
      default_model: "claude-3-5-sonnet-20241022"
      temperature: 0
      tartxt_config:
        script_path: "c4h_agents/skills/tartxt.py"
        input_paths: ["./"]
        exclusions: ["**/__pycache__/**"]
    
    solution_designer:
      provider: "anthropic"
      model: "claude-3-5-sonnet-20241022"
      temperature: 0
    
    coder:
      provider: "anthropic"
      model: "claude-3-opus-20240229"
      temperature: 0

# Orchestration settings
orchestration:
  enabled: true
  entry_team: "discovery"
  error_handling:
    retry_teams: true
    max_retries: 2
  teams:
    discovery:
      name: "Discovery Team"
      tasks:
        - name: "discovery"
          agent_class: "c4h_agents.agents.discovery.DiscoveryAgent"
          requires_approval: false
      routing:
        default: "solution"
    
    solution:
      name: "Solution Design Team"
      tasks:
        - name: "solution_designer"
          agent_class: "c4h_agents.agents.solution_designer.SolutionDesigner"
          requires_approval: true
      routing:
        default: "coder"
    
    coder:
      name: "Coder Team"
      tasks:
        - name: "coder"
          agent_class: "c4h_agents.agents.coder.Coder"
          requires_approval: true
      routing:
        default: null

# Runtime configuration
runtime:
  workflow:
    storage:
      enabled: true
      root_dir: "workspaces/workflows"
      
  lineage:
    enabled: true
    namespace: "c4h_agents"
    backends:
      file:
        enabled: true
        path: "workspaces/lineage"
      marquez:
        enabled: true
        url: "http://localhost:5005"

# Backup settings
backup:
  enabled: true
  path: "workspaces/backups"

# Logging configuration
logging:
  level: "INFO"
  format: "structured"
  agent_level: "INFO"
```

## Project Model

The system uses a project model that includes:

### Project Paths
- `root` - Project root directory
- `workspace` - Directory for working files
- `source` - Source code directory
- `output` - Output directory for modifications
- `config` - Configuration files location

### Project Metadata
- `name` - Project name (derived from directory name)
- `description` - Optional project description
- `version` - Optional version information
- `settings` - Custom project settings

## Workflow Execution Flow

1. **Initialization**:
   - Client submits workflow request with project path and intent
   - Server generates a workflow ID
   - Server prepares configuration with default values

2. **Team Execution**:
   - Discovery team analyzes project structure
   - Solution team designs code modifications
   - Coder team implements changes

3. **Result Storage**:
   - Changes are written to the project files
   - Backup copies are created
   - Lineage information is recorded
   - Status information is stored for retrieval

## Design Principles

The system follows these core design principles:

### Agent Design Principles

1. **LLM-First Processing**
   - Offload logic and decision-making to the LLM
   - Use LLM for verification and validation
   - Agents focus on infrastructure concerns

2. **Minimal Agent Logic**
   - Keep agent code focused on infrastructure
   - Avoid embedding business logic in agents
   - Let LLM handle complex decision trees

3. **Single Responsibility**
   - Each agent has one clear, focused task
   - No processing of tasks that belong to other agents
   - Pass through data without unnecessary interpretation

### Configuration Design Principles

1. **Hierarchical Configuration**
   - All configuration follows a strict hierarchy
   - Base config provides defaults and templates
   - Override config adds or updates leaf nodes

2. **Smart Merge Behavior**
   - Base config provides foundation
   - Override config can add new nodes
   - Preserve parent node structure

3. **Separation of Responsibilities**
   - Each component owns its configuration section
   - No cross-agent config dependencies

## Implementation Considerations for GUI

When building a GUI application over this API, consider:

1. **Project Selection**:
   - Allow users to select/browse project directories
   - Validate project structure before submission

2. **Intent Formulation**:
   - Provide templates for common intents
   - Allow custom intent descriptions
   - Offer guided intent creation

3. **Configuration Management**:
   - Provide UI for editing hierarchical configuration
   - Group configuration by component
   - Offer sensible defaults

4. **Workflow Monitoring**:
   - Poll the status endpoint at reasonable intervals
   - Display execution progress
   - Show team transitions

5. **Result Visualization**:
   - Display diffs between original and modified files
   - Allow navigation through changed files
   - Provide options to accept/reject changes

6. **Error Handling**:
   - Display meaningful error messages
   - Offer troubleshooting guidance
   - Provide retry mechanisms

## Example Client Implementation

Here's a basic example of a client implementation in Python:

```python
import requests
import time
import json

class C4HClient:
    def __init__(self, base_url="http://localhost:8000"):
        self.base_url = base_url
        
    def submit_workflow(self, project_path, intent_description, config=None):
        """Submit a new workflow request"""
        url = f"{self.base_url}/api/v1/workflow"
        
        payload = {
            "project_path": project_path,
            "intent": {
                "description": intent_description
            }
        }
        
        if config:
            payload["app_config"] = config
            
        response = requests.post(url, json=payload)
        response.raise_for_status()
        return response.json()
    
    def get_workflow_status(self, workflow_id):
        """Get status of a workflow"""
        url = f"{self.base_url}/api/v1/workflow/{workflow_id}"
        response = requests.get(url)
        response.raise_for_status()
        return response.json()
    
    def wait_for_completion(self, workflow_id, interval=5, timeout=300):
        """Wait for workflow completion with polling"""
        start_time = time.time()
        while time.time() - start_time < timeout:
            status = self.get_workflow_status(workflow_id)
            if status["status"] in ["success", "error"]:
                return status
            time.sleep(interval)
        raise TimeoutError(f"Workflow did not complete within {timeout} seconds")
```

## Common Workflows

### Adding Logging

```json
{
  "project_path": "./my_project",
  "intent": {
    "description": "Add logging to all functions with proper error handling and level-appropriate log messages"
  }
}
```

### Implementing Design Patterns

```json
{
  "project_path": "./my_project",
  "intent": {
    "description": "Refactor to use the Factory pattern for class creation in the user module"
  }
}
```

### Performance Optimization

```json
{
  "project_path": "./my_project",
  "intent": {
    "description": "Optimize database queries in the data_access.py file to reduce execution time"
  }
}
```

## Error Handling

Common errors and their solutions:

| Error | Possible Cause | Solution |
|-------|----------------|----------|
| "No input paths configured" | Missing tartxt_config.input_paths | Ensure discovery agent has tartxt_config with input_paths |
| "Team not found" | Invalid entry_team | Verify orchestration.entry_team matches available teams |
| "No project path specified" | Missing project path | Provide valid project_path in request |
| "Invalid configuration" | Malformed config | Check configuration structure against schema |

## Security Considerations

- The service operates on the filesystem, ensure proper isolation
- Consider running in a container or restricted environment
- Validate project paths to prevent path traversal attacks
- Implement authentication for multi-user environments

## Conclusion

The C4H Services API provides a powerful foundation for building intelligent code refactoring interfaces. By following this guide, you can create rich GUI applications that leverage the underlying capabilities for code analysis, design, and implementation.