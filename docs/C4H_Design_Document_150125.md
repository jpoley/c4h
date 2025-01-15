# Prefect Runner Architecture Documentation

## Overview
This document provides a comprehensive view of the Prefect Runner architecture through various UML and architectural diagrams.

## Class Diagram
The class diagram shows the core classes and their relationships in the system.

```mermaid
classDiagram
    class PrefectRunner {
        +run_flow(mode: RunMode, config: Dict, agent_type: str)
        +format_output(data: Dict, mode: RunMode)
        +load_configs(config_path: str)
    }
    
    class AgentTaskConfig {
        +agent_class: Type[BaseAgent]
        +config: Dict
        +task_name: str
        +requires_approval: bool
        +max_retries: int
        +retry_delay_seconds: int
    }
    
    class BaseAgent {
        +process(context: Dict)
        +_format_request(context: Dict)
        +_process_llm_response(content: str)
    }

    class TaskFactory {
        +create_discovery_task(config: Dict)
        +create_solution_task(config: Dict)
        +create_coder_task(config: Dict)
        +create_assurance_task(config: Dict)
    }
    
    class WorkflowService {
        +run_basic_workflow(project_path: Path, intent_desc: Dict, config: Dict)
        +run_intent_workflow(project_path: Path, intent_desc: Dict, config: Dict)
    }

    BaseAgent <|-- DiscoveryAgent
    BaseAgent <|-- SolutionDesigner
    BaseAgent <|-- Coder
    BaseAgent <|-- AssuranceAgent
    
    PrefectRunner --> AgentTaskConfig
    PrefectRunner --> WorkflowService
    WorkflowService --> TaskFactory
    TaskFactory --> AgentTaskConfig
    AgentTaskConfig --> BaseAgent
```

## Sequence Diagram
The sequence diagram illustrates the interaction flow between components during execution.

```mermaid
sequenceDiagram
    participant CLI as PrefectRunner CLI
    participant Runner as PrefectRunner
    participant Workflow as WorkflowService
    participant Factory as TaskFactory
    participant Agent as BaseAgent
    participant LLM as LLMService

    CLI->>Runner: run_flow(mode, config)
    Runner->>Runner: load_configs()
    
    alt agent mode
        Runner->>Factory: create_agent_task(config)
        Factory-->>Runner: AgentTaskConfig
        Runner->>Agent: process(context)
        Agent->>LLM: run_completion()
        LLM-->>Agent: response
        Agent-->>Runner: result
    else workflow mode
        Runner->>Workflow: run_basic_workflow()
        activate Workflow
        Workflow->>Factory: create_discovery_task()
        Workflow->>Factory: create_solution_task()
        Workflow->>Factory: create_coder_task()
        
        loop For each agent
            Workflow->>Agent: process(context)
            Agent->>LLM: run_completion()
            LLM-->>Agent: response
            Agent-->>Workflow: result
        end
        deactivate Workflow
        Workflow-->>Runner: workflow_result
    end
    
    Runner-->>CLI: formatted_output
```

## State Diagram
The state diagram shows the possible states and transitions of the system.

```mermaid
stateDiagram-v2
    [*] --> Initialized: Create PrefectRunner
    Initialized --> ConfigLoaded: Load Configs
    ConfigLoaded --> AgentMode: mode=agent
    ConfigLoaded --> WorkflowMode: mode=workflow
    
    state AgentMode {
        [*] --> TaskCreated: create_agent_task
        TaskCreated --> Processing: process
        Processing --> Complete: success
        Processing --> Failed: error
    }
    
    state WorkflowMode {
        [*] --> DiscoveryStage
        DiscoveryStage --> SolutionStage: success
        SolutionStage --> CoderStage: success
        CoderStage --> AssuranceStage: success
        
        DiscoveryStage --> Failed: error
        SolutionStage --> Failed: error
        CoderStage --> Failed: error
        AssuranceStage --> Failed: error
        
        AssuranceStage --> Complete: success
    }
    
    Complete --> [*]
    Failed --> [*]
```

## Architecture Diagram
The architecture diagram provides a high-level view of the system components and their organization.

```mermaid
graph TB
    subgraph CLI["Command Line Interface"]
        cli[PrefectRunner CLI]
    end

    subgraph Core["Core Components"]
        runner[PrefectRunner]
        factory[TaskFactory]
        config[ConfigManager]
    end

    subgraph Workflows["Workflow Services"]
        basic[BasicWorkflow]
        intent[IntentWorkflow]
        recovery[RecoveryWorkflow]
    end

    subgraph Agents["Agent Layer"]
        discovery[DiscoveryAgent]
        solution[SolutionDesigner]
        coder[Coder]
        assurance[AssuranceAgent]
    end

    subgraph Infrastructure["Infrastructure"]
        prefect[Prefect Backend]
        llm[LLM Services]
        fs[File System]
    end

    cli --> runner
    runner --> factory
    runner --> config
    
    factory --> Agents
    runner --> Workflows
    
    Workflows --> Agents
    Agents --> llm
    Agents --> fs
    
    Workflows --> prefect
    prefect --> Agents
```

## Key Architectural Principles

1. **Single Responsibility**: Each component has a well-defined and specific role
   - PrefectRunner handles orchestration
   - TaskFactory manages agent creation
   - Agents perform specific tasks
   - WorkflowService manages workflow execution

2. **Open/Closed**: The system is designed for extension
   - New agents can be added without modifying existing code
   - New workflows can be created using existing components
   - Factory pattern allows for new agent types

3. **Dependency Injection**
   - Configuration is injected into components
   - Agent dependencies are managed through AgentTaskConfig
   - Services are loosely coupled through interfaces

4. **Interface Segregation**
   - Clean separation between CLI, runner, and agents
   - Well-defined interfaces between components
   - Minimal dependencies between layers

5. **Separation of Concerns**
   - Clear separation of responsibilities
   - Modular design with distinct layers
   - Independent scaling of components