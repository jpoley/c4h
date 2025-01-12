# Configuration Design Principles

## Overarching Principles

1. **Hierarchical Configuration**
   - All configuration follows a strict hierarchy
   - Base config provides defaults and templates
   - Override config adds or updates leaf nodes
   - Preserve structure during merges
   - Config paths follow consistent patterns (e.g., llm_config.agents.[name])

2. **Smart Merge Behavior**
   - Base config provides foundation
   - Override config can add new nodes
   - Override config can update leaf values
   - Preserve parent node structure
   - Don't break existing config paths

3. **Separation of Responsibilities**
   - config.py owns configuration management
   - BaseAgent provides config access methods
   - Each agent responsible for its own config section
   - No cross-agent config dependencies
   - Config handling isolated from business logic

## Implementation Principles

### 1. Config Location
- Clear hierarchical paths (e.g., llm_config.agents.[name])
- Consistent lookup patterns
- Fail gracefully with empty dict if not found
- Log lookup attempts and results
- Support project-based config overrides

### 2. Config Access
- Agents access only their own config section
- Use BaseAgent methods for config retrieval
- Get agent name for lookups
- Handle missing config gracefully
- Log config access patterns

### 3. Config Processing
- Process config at initialization
- Cache needed values
- Minimal runtime config lookups
- Log config state changes
- Handle config errors gracefully

### 4. Config Validation
- Basic structure validation in config.py
- Type validation where critical
- Log validation failures
- Fail fast on critical config missing
- Allow flexible extension

### 5. Config Resilience
- Handle missing config as critical failure
- Defaults only come from configuration hence merging behavior
- Log configuration issues
- Support runtime updates
- Maintain backward compatibility

## Practical Examples

### 1. Config Hierarchy
```yaml
llm_config:
  agents:
    solution_designer:  # Agent-specific section
      provider: "anthropic"
      model: "claude-3"
      prompts:
        system: "..."
        solution: "..."
      intent:
        description: "..."
```

### 2. Agent Config Access
```python
def _get_agent_config(self) -> Dict[str, Any]:
    """Get agent configuration - fails if not found"""
    agent_name = self._get_agent_name()
    agent_config = locate_config(self.config, agent_name)
    if not agent_config:
        raise ValueError(f"No configuration found for agent: {agent_name}")
    return agent_config
```

### 3. Smart Config Location
```python
def locate_config(config: Dict[str, Any], target_name: str) -> Dict[str, Any]:
    """Locate agent config or return empty dict"""
    try:
        path = ['llm_config', 'agents', target_name]
        result = get_by_path(config, path)
        return result if isinstance(result, dict) else {}
    except Exception as e:
        logger.error("config.locate_failed", error=str(e))
        return {}
```

## Benefits
- Clear configuration ownership
- Predictable config behavior
- Easy to extend and modify
- Resilient to changes
- Maintainable config structure
- Clear debugging paths
- Isolated responsibilities
- Higer level components remain generic
- No bleeding of business logic into higer order components

## Application Guidelines

1. When adding new config:
   - Follow existing hierarchy
   - Add to appropriate section
   - Maintain structure
   - Document the addition
   - Consider backward compatibility

2. When accessing config:
   - Use agent name for lookup
   - Access only owned section
   - Handle missing values
   - Log access patterns
   - Use BaseAgent methods

3. When merging config:
   - Preserve structure
   - Only override leaf nodes
   - Add new nodes as needed
   - Log merge results
   - Maintain hierarchy

4. When debugging config:
   - Check hierarchy path
   - Verify config merge
   - Look for log patterns
   - Validate structure
   - Check access methods