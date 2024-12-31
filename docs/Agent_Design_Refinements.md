Here are the key design principles we uncovered during this refactoring session:

1. **Template Configuration Over Code**
   - Moved ALL prompt text to config files
   - Extractors just populate templates with variables
   - Makes prompt engineering easier by centralizing in one place
   - Example: Moving fast/slow extraction prompts from code into system_config.yml

2. **Item-Agnostic Components**
   - Semantic extractors don't know about item structure
   - Caller defines what constitutes an item via instruction/format
   - Components focus on extraction mechanics not content
   - Example: Removing function-specific JSON structure from extractor prompts

3. **Clear Component Boundaries**
   - SemanticIterator coordinates but doesn't extract
   - FastExtractor handles bulk extraction
   - SlowExtractor handles sequential extraction
   - Each component has single responsibility
   - Example: SemanticIterator delegates to specialized extractors rather than doing extraction itself

4. **Configuration Inheritance Chain**
   - System config flows through component hierarchy
   - Each component needs its own config section
   - Components pass complete config to children
   - Example: Fixing config propagation from Iterator to FastExtractor

5. **Strong Prompts Over Validation**
   - Use precise, rule-focused prompts
   - Trust LLM to follow format requirements
   - Avoid post-processing/validation code
   - Example: Strengthening extractor prompts rather than adding JSON validation

6. **Explicit Over Implicit**
   - Clear prompt templates with placeholders
   - Explicit format requirements
   - No hidden assumptions about content
   - Example: Making template variables like {content}, {instruction}, {format} explicit

7. **Logging for Visibility**
   - Debug logging at key points
   - Track config and prompt propagation
   - Make component behavior observable
   - Example: Adding detailed config logging in initialization chain

8. **Clean Separation of Concerns**
   - Caller defines what to extract
   - Iterator manages extraction strategy
   - Extractors handle mechanics
   - Example: Moving item format definition to caller's config

These principles focus on making the system maintainable, predictable and easy to tune while keeping core logic in prompts rather than code.

Would you like me to expand on any of these principles or show additional examples?