# C4H Agents Library Interface Documentation

## Overview
C4H Agents is a modern Python library for LLM-based code refactoring using autonomous agents. It provides a set of specialized agents that work together to analyze, design, and implement code changes based on natural language intent.

## Key Components

### Core Agents

1. **DiscoveryAgent**
   ```python
   from c4h_agents.agents.discovery import DiscoveryAgent
   
   agent = DiscoveryAgent(config=config)
   result = agent.process({"project_path": "path/to/project"})
   ```
   - Analyzes project structure and files
   - Returns file manifest and content analysis
   - Handles project scanning with configurable exclusions

2. **SolutionDesigner**
   ```python
   from c4h_agents.agents.solution_designer import SolutionDesigner
   
   agent = SolutionDesigner(config=config)
   result = agent.process({
       "input_data": {
           "discovery_data": discovery_result.data,
           "intent": intent_description
       }
   })
   ```
   - Designs code modifications based on intent
   - Returns structured change plans
   - Supports iterative refinement

3. **Coder**
   ```python
   from c4h_agents.agents.coder import Coder
   
   agent = Coder(config=config)
   result = agent.process({
       "input_data": solution_result.data
   })
   ```
   - Implements code changes
   - Handles file modifications with backup
   - Preserves code formatting and structure

4. **AssuranceAgent**
   ```python
   from c4h_agents.agents.assurance import AssuranceAgent
   
   agent = AssuranceAgent(config=config)
   result = agent.process({
       "changes": coder_result.data.get("changes", []),
       "intent": intent_description
   })
   ```
   - Validates implemented changes
   - Runs tests and checks
   - Ensures quality and correctness

### Agent Response Format
All agents return responses in a standard format:
```python
@dataclass
class AgentResponse:
    success: bool
    data: Dict[str, Any]
    error: Optional[str] = None
    timestamp: datetime = datetime.utcnow()
```

### Configuration

Required configuration structure:
```yaml
providers:
  anthropic:  # or openai, gemini
    api_base: "https://api.anthropic.com"
    env_var: "ANTHROPIC_API_KEY"
    default_model: "claude-3-opus-20240229"

llm_config:
  default_provider: "anthropic"
  default_model: "claude-3-opus-20240229"
  agents:
    discovery:
      tartxt_config:
        input_paths: ["src"]
        exclusions: ["**/__pycache__/**"]
    
    solution_designer:
      provider: "anthropic"
      model: "claude-3-opus-20240229"
      temperature: 0

backup:
  enabled: true
  path: "workspaces/backups"

logging:
  level: "INFO"
  format: "structured"
```

## Usage Examples

### Basic Usage with Single Agent
```python
from c4h_agents.config import load_config
from c4h_agents.agents.discovery import DiscoveryAgent

# Load configuration
config = load_config("path/to/config.yml")

# Initialize agent
discovery = DiscoveryAgent(config=config)

# Process request
result = discovery.process({
    "project_path": "path/to/project"
})

if result.success:
    files = result.data.get("files", {})
    raw_output = result.data.get("raw_output", "")
```

### Complete Refactoring Flow
```python
from c4h_agents.config import load_config
from c4h_agents.agents.discovery import DiscoveryAgent
from c4h_agents.agents.solution_designer import SolutionDesigner
from c4h_agents.agents.coder import Coder
from c4h_agents.agents.assurance import AssuranceAgent

# Load config
config = load_config("config.yml")

# Define intent
intent = {
    "description": "Add logging to all functions and replace print statements"
}

# Run discovery
discovery = DiscoveryAgent(config=config)
discovery_result = discovery.process({
    "project_path": "path/to/project"
})

# Design solution
designer = SolutionDesigner(config=config)
solution_result = designer.process({
    "input_data": {
        "discovery_data": discovery_result.data,
        "intent": intent
    }
})

# Implement changes
coder = Coder(config=config)
coder_result = coder.process({
    "input_data": solution_result.data
})

# Validate changes
assurance = AssuranceAgent(config=config)
assurance_result = assurance.process({
    "changes": coder_result.data.get("changes", []),
    "intent": intent
})
```

### Change Format
The standard format for code changes:
```json
{
    "changes": [
        {
            "file_path": "path/to/file.py",
            "type": "modify",
            "description": "Added logging to functions",
            "content": "complete file content"
        }
    ]
}
```

Change types:
- `create`: New file creation
- `modify`: File modification
- `delete`: File deletion

## Error Handling

All agents provide detailed error information:
```python
try:
    result = agent.process(context)
    if not result.success:
        print(f"Error: {result.error}")
        print(f"Partial data: {result.data}")
except Exception as e:
    print(f"Agent execution failed: {str(e)}")
```

## Best Practices

1. **Configuration Management**
   - Use separate configs for development/production
   - Override specific agent settings as needed
   - Keep sensitive credentials in environment variables

2. **Error Handling**
   - Always check result.success before using data
   - Log errors with context for debugging
   - Enable backups before making changes

3. **Performance**
   - Use appropriate models for each agent
   - Configure batch sizes for large projects
   - Enable caching when possible

4. **Safety**
   - Always enable backups
   - Review changes before applying
   - Use AssuranceAgent to validate changes

## Dependencies

Required packages:
- `litellm`: For LLM provider management
- `structlog`: For structured logging
- `pyyaml`: For configuration handling

Optional dependencies:
- `prefect`: For workflow orchestration
- `rich`: For console output formatting

## Environment Variables

Required environment variables based on provider:
```bash
# For Anthropic
ANTHROPIC_API_KEY=your_key_here

# For OpenAI
OPENAI_API_KEY=your_key_here

# For Google/Gemini
GEMINI_API_KEY=your_key_here
```