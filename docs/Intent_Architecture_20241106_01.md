Over arching Goals

As long as the minimum structure is met, allow the llm to resolve the errors

i want the interactions to be more emergent and interactive, 
each agent knows what it needs to do, it specialises in its task, discovery passes, intent + scope, 

solutino doesnt need to spend too much time validating the inpput, thats up to the remote llm to interpret, 
its job is to manage the specific prompts and itneractions with the llm to provide a solution over the scope that fulfills the intent
Currently - we want the solution to be a series of Merges or File creations (e.g. a merge over a non existent file)
In the future the prompt may include other skills such install packages, or initialise a database etc.
When the llm responds, based upon the structure instructions of the Solution Agent, it passes it on to the coder.

The code takes the Actions from the Solution Agent, which should be a series of merges of merges over files, existing or not existing
It uses the LLM to execute a specific code merge action
It then write the updated file out

Ultimately it passes to the assurance agent to do its thing

```mermaid
stateDiagram-v2
    [*] --> Created: Intent Created
    Created --> Analyzing: Discovery Agent
    
    Analyzing --> Transforming: Solution Architect
    Transforming --> Completed: Coder
    Transforming --> Failed: Error in Changes
    Analyzing --> Failed: Discovery Error
    
    note right of Created
        Intent object initialized with:
        - Description of changes
        - Project path
        - Merge strategy
    end note
    
    note right of Analyzing
        Discovery Agent:
        1. Scans project files
        2. Uses tartxt to analyze code
        3. Builds project structure
        4. Maps dependencies
    end note
    
    note right of Transforming
        Solution Architect: 
        1. Plans changes based on intent
        2. Creates diff-based changes
        3. Returns JSON actions array
        
        Coder:
        1. Applies diffs using LLM
        2. Creates file backups
        3. Writes changes
    end note
    
    note right of Completed
        Successful state when:
        1. All files processed
        2. Changes applied
        3. No merge errors
    end note
    
    note right of Failed
        Failure cases:
        1. Invalid project structure
        2. JSON parsing errors
        3. Failed merges
        4. File write errors
    end note

    Completed --> [*]: End Success
    Failed --> [*]: End 
```

I'll create a sequence diagram showing the detailed interactions between the Intent Agent and other components.

```mermaid
sequenceDiagram
    participant CLI as Command Line
    participant IA as Intent Agent
    participant DA as Discovery Agent
    participant SA as Solution Architect
    participant CD as Coder
    participant LLM as OpenAI LLM
    participant FS as File System
    
    Note over CLI,FS: Refactoring Process Flow
    
    CLI->>+IA: process(project_path, intent_desc)
    
    rect rgb(200, 220, 240)
        Note over IA,DA: Discovery Phase
        IA->>+DA: analyze(project_path)
        DA->>+FS: scan files
        FS-->>-DA: file list & contents
        DA->>+LLM: process discovery output
        LLM-->>-DA: analyzed structure
        DA-->>-IA: discovery_output
    end

    rect rgb(220, 240, 200)
        Note over IA,SA: Solution Planning Phase
        IA->>+SA: analyze(context)
        SA->>+LLM: plan changes
        LLM-->>-SA: proposed changes
        SA->>SA: format as diffs
        SA-->>-IA: actions JSON
    end
    
    rect rgb(240, 220, 200)
        Note over IA,CD: Implementation Phase
        IA->>+CD: transform(solution)
        
        loop For each action
            CD->>+FS: read file
            FS-->>-CD: original content
            CD->>+LLM: merge changes
            LLM-->>-CD: merged content
            CD->>+FS: backup file
            FS-->>-CD: backup created
            CD->>+FS: write changes
            FS-->>-CD: write status
        end
        
        CD-->>-IA: implementation result
    end
    
    alt Success
        IA-->>CLI: Success Status & Modified Files
    else Error
        IA-->>CLI: Error Status & Context
    end
    
    IA-->>-CLI: Complete

    Note over CLI,FS: Error paths omitted for clarity

```

Key interaction points:

1. **Initial Setup**
   - CLI initiates process with project path and intent description
   - Intent Agent coordinates all phases

2. **Discovery Phase (Blue)**
   - Discovery Agent scans filesystem
   - Uses tartxt for code analysis
   - LLM processes and structures discovery output

3. **Solution Planning (Green)**
   - Solution Architect takes discovery output
   - LLM plans changes based on intent
   - Returns JSON structure with diff-based actions

4. **Implementation Phase (Red)**
   - Coder handles each action sequentially
   - For each file:
     1. Reads original content
     2. Uses LLM to merge changes
     3. Creates backup
     4. Writes changes
   - Returns aggregated results

5. **Result Handling**
   - Success: Returns modified files list
   - Error: Returns error context
   - Both include full execution context

Key aspects not shown in diagram for clarity:
1. Error handling paths
2. Retry logic
3. Validation steps
4. Autogen interaction details
5. Logging operations

Would you like me to:
1. Add error handling paths?
2. Show more detail about the LLM interactions?
3. Include the validation steps?
4. Show the specific message formats?

```mermaid
sequenceDiagram
    participant CLI as API Call
    participant IA as Intent Agent
    participant DA as Discovery Agent
    participant SA as Solution Architect
    participant CD as Coder
    participant LLM as OpenAI LLM
    participant FS as File System

    Note over CLI,FS: Refactoring Process Flow

    CLI->>+IA: process(project_path, intent_desc)
    
    rect rgb(200, 220, 240)
        Note over IA,DA: Discovery Phase
        IA->>+DA: analyze(project_path)
        DA->>+FS: scan files
        FS-->>-DA: file list & contents
        DA->>+LLM: prompt("Analyze project structure and dependencies")
        LLM-->>-DA: { structure: {...}, dependencies: [...] }
        DA-->>-IA: discovery_output
    end

    alt Discovery Failure
        DA-->>IA: error("File system inaccessible")
        IA-->>CLI: error("Discovery failed")
    end
    
    rect rgb(220, 240, 200)
        Note over IA,SA: Solution Planning Phase
        IA->>+SA: analyze(context)
        SA->>+LLM: prompt("Plan code changes based on structure and intent")
        LLM-->>-SA: { actions: [{file: "x", change: "merge"}...] }
        SA->>SA: validate(actions)
        SA-->>-IA: actions JSON
    end

    alt Solution Validation Failure
        SA-->>IA: error("Invalid actions generated")
        IA->>LLM: prompt("Resolve invalid actions with constraints")
        LLM-->>IA: resolved_actions JSON
        IA->>SA: retry(resolved_actions)
    end
    
    rect rgb(240, 220, 200)
        Note over IA,CD: Implementation Phase
        IA->>+CD: transform(solution)
        
        loop For each action
            CD->>+FS: read(file_path)
            FS-->>-CD: file content
            CD->>+LLM: prompt("Apply changes to file: merge content")
            LLM-->>-CD: merged_content
            CD->>+FS: write(file_path, merged_content)
            FS-->>-CD: write status
        end
        
        CD-->>-IA: implementation result
    end
    
    alt Implementation Errors
        CD-->>IA: error("Merge conflict in file X")
        IA->>LLM: prompt("Resolve merge conflict for file X")
        LLM-->>IA: resolved_content
        IA->>CD: retry(resolved_content)
    end
    
    alt Overall Success
        IA-->>CLI: Success Status & Modified Files
    else Overall Failure
        IA-->>CLI: Error Status & Context
    end
    
    IA-->>-CLI: Complete

    Note over CLI,FS: Fallback and LLM repair interactions included
```