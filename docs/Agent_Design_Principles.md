# Agent Design Principles

## Overarching Principles

1. **LLM-First Processing**
   - Offload most logic and decision-making to the LLM
   - Use LLM for verification and validation where possible
   - Agents focus on:
     - Managing intent prompts
     - Processing responses
     - Managing local environment side effects

2. **Minimal Agent Logic**
   - Keep agent code focused on infrastructure concerns
   - Avoid embedding business logic in agents
   - Let LLM handle complex decision trees

## Implementation Principles

### 1. Single Responsibility
- Each agent has one clear, focused task
- No processing of tasks that belong to other agents
- Pass through data without unnecessary interpretation
- Example: Discovery agent handles only file analysis, Solution Designer only creates prompts

### 2. Minimal Processing
- Default to passing data through to LLM
- Only transform data if it's core to the agent's infrastructure role
- Don't duplicate validation or processing done by other agents
- Let LLM handle data interpretation where possible

### 3. Clear Boundaries
- Discovery agent handles file analysis and scoping
- Solution Designer creates optimal prompts
- Semantic Iterator handles response parsing and iteration
- Each agent trusts other agents' output
- No cross-agent validation

### 4. Logging Over Validation
- Focus on detailed logging for debugging
- Let calling agents handle validation
- Log key events, inputs, and outputs
- Make agent behavior observable
- Reserve validation for infrastructure concerns only

### 5. Error Handling
- Handle only errors specific to infrastructure tasks
- Pass through errors from external services (like LLM)
- Provide clear error context in logs
- Don't swallow or transform errors unnecessarily
- Let LLM handle business logic errors

### 6. Stateless Operation
- Agents don't maintain state between operations
- Each request is self-contained
- State management happens at orchestration level
- Makes testing and debugging simpler

### 7. Composability
- Agents can be chained together
- Output format matches input format of next agent
- No hidden dependencies between agents
- Clean interfaces between agents

### 8. Observable Behavior
- Extensive structured logging
- Clear input/output contracts
- Traceable request/response flow
- Debuggable operation

### 9. Focused Testing
- Test only the agent's infrastructure responsibility
- Don't test downstream agent behavior
- Mock external services appropriately
- Test logging and error handling
- Don't test LLM decision logic

### 10. Forward-Only Flow
- Data flows forward through agent chain
- No backward dependencies
- Each agent adds its specific value
- Clean sequential processing

## Practical Examples

### Good Agent Design
```python
class SolutionDesigner:
    async def process(self, context: Dict[str, Any]) -> AgentResponse:
        # Log receipt
        self.logger.info("design_request_received", intent=context.get('intent'))
        
        # Pass to LLM for processing
        return await self.llm.process(self._format_request(context))
```

### Poor Agent Design
```python
class SolutionDesigner:
    async def process(self, context: Dict[str, Any]) -> AgentResponse:
        # Don't validate business rules in agent
        if not self._is_valid_refactor_request(context):  # BAD
            return AgentResponse(success=False)
            
        # Don't transform data before LLM
        transformed = self._preprocess_code(context)  # BAD
        return await self.llm.process(transformed)
```

## Benefits
- Simpler codebase
- Easier to maintain
- More flexible and adaptable
- Better separation of concerns
- Clearer responsibility boundaries
- More testable infrastructure
- Leverages LLM capabilities optimally

## Application Guidelines
1. When adding validation, ask "Is this infrastructure or business logic?"
2. When adding processing, ask "Could the LLM handle this?"
3. Keep agent code focused on:
   - Managing I/O
   - Logging
   - Infrastructure error handling
   - Environment interactions
4. Let the LLM handle:
   - Business validation
   - Code analysis
   - Decision making
   - Content transformation

Would you like me to add any other sections or expand on any of these points?