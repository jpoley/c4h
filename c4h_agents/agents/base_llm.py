"""
LLM interaction layer providing completion and response handling.
Path: c4h_agents/agents/base_llm.py
"""

from typing import Dict, Any, List, Tuple, Optional
import time
import re
import json
from datetime import datetime
import litellm
from litellm import completion
from c4h_agents.agents.types import LLMProvider, LogDetail
from c4h_agents.utils.logging import get_logger

logger = get_logger()

class BaseLLM:
    """LLM interaction layer"""

    def _get_completion_with_continuation(
            self, 
            messages: List[Dict[str, str]],
            max_attempts: Optional[int] = None
        ) -> Tuple[str, Any]:
        """
        Get completion with automatic continuation handling.
        Uses multi-level overlap detection for reliable response joining.
        Handles overload conditions with exponential backoff.
        
        Args:
            messages: List of message dictionaries with role and content
            max_attempts: Maximum number of continuation attempts
            
        Returns:
            Tuple of (accumulated_content, final_response)
        """
        try:
            attempt = 0
            max_tries = max_attempts or self.max_continuation_attempts
            accumulated_content = ""
            final_response = None
            retry_count = 0
            max_retries = 5  # Max retries for overload conditions
            
            # Track JSON structure state
            json_state = {
                "depth": 0,          # Track nesting level
                "open_braces": 0,    # Count of unclosed braces
                "open_brackets": 0,  # Count of unclosed brackets
                "current_file": None,# Current file being processed
                "object_count": 0    # Number of complete objects
            }
            
            # Get provider config
            provider_config = self._get_provider_config(self.provider)
            
            # Track diagnostics for troubleshooting
            diagnostics = {
                "attempts": 0,
                "overlap_attempts": 0,
                "exact_matches": 0,
                "hash_matches": 0,
                "token_matches": 0,
                "fallbacks": 0,
                "structure_repairs": 0
            }
            
            logger.info("llm.continuation_starting", 
                    model=self.model_str,
                    max_attempts=max_tries)
            
            # Basic completion parameters
            completion_params = {
                "model": self.model_str,
                "messages": messages,
            }

            # Only add temperature for providers that support it
            if self.provider.value != "openai":
                completion_params["temperature"] = self.temperature
            
            # Add extended thinking only for Claude 3.7 Sonnet if explicitly enabled
            if self.provider.value == "anthropic" and "claude-3-7-sonnet" in self.model:
                # Check for extended thinking configuration
                agent_name = self._get_agent_name()
                agent_path = f"llm_config.agents.{agent_name}"
                
                # Get extended thinking settings from agent config
                agent_thinking_config = self.config_node.get_value(f"{agent_path}.extended_thinking")
                
                # If not set at agent level, get from provider config
                if not agent_thinking_config:
                    agent_thinking_config = provider_config.get("extended_thinking", {})
                
                # Apply extended thinking ONLY if explicitly enabled
                if agent_thinking_config and agent_thinking_config.get("enabled", False) is True:
                    budget_tokens = agent_thinking_config.get("budget_tokens", 32000)
                    
                    # Apply limits for budget_tokens
                    min_budget = provider_config.get("extended_thinking", {}).get("min_budget_tokens", 1024)
                    max_budget = provider_config.get("extended_thinking", {}).get("max_budget_tokens", 128000)
                    budget_tokens = max(min_budget, min(budget_tokens, max_budget))
                    
                    # Configure thinking parameter
                    completion_params["thinking"] = {
                        "type": "enabled",
                        "budget_tokens": budget_tokens
                    }
                    
                    # When extended thinking is enabled, temperature MUST be set to 1
                    # This is a requirement from Anthropic's API
                    completion_params["temperature"] = 1
                    
                    # Set max_tokens to a valid value for Claude 3.7 Sonnet (max 64000)
                    if "max_tokens" not in completion_params:
                        completion_params["max_tokens"] = 64000
                    else:
                        # Ensure max_tokens doesn't exceed the model's limit
                        completion_params["max_tokens"] = min(completion_params["max_tokens"], 64000)
                    
                    # Log extended thinking configuration
                    logger.info("llm.extended_thinking_enabled",
                            model=self.model,
                            budget_tokens=budget_tokens,
                            temperature=completion_params["temperature"],
                            max_tokens=completion_params["max_tokens"])
                else:
                    logger.debug("llm.extended_thinking_not_used",
                            model=self.model,
                            reason="not_explicitly_enabled")
            
            # Add any model-specific parameters from config
            model_params = provider_config.get("model_params", {})
            if model_params:
                logger.debug("llm.applying_model_params", 
                            provider=self.provider.serialize(),
                            params=list(model_params.keys()))
                completion_params.update(model_params)
            
            if "api_base" in provider_config:
                completion_params["api_base"] = provider_config["api_base"]
                
            # For extended thinking with large max_tokens, we need to use streaming
            use_streaming = False
            if (self.provider.value == "anthropic" and 
                "claude-3-7-sonnet" in self.model and
                "thinking" in completion_params and
                completion_params.get("max_tokens", 0) > 21333):
                use_streaming = True
                completion_params["stream"] = True
                logger.info("llm.stream_enabled_for_extended_thinking",
                        model=self.model,
                        max_tokens=completion_params.get("max_tokens"))

            # Check if we're dealing with Python/Code, JSON, or diff content
            is_code = any("```" in msg.get("content", "") or "def " in msg.get("content", "") 
                        for msg in messages if msg.get("role") == "user")
            is_json = any("json" in msg.get("content", "").lower() or 
                        msg.get("content", "").strip().startswith("{") or 
                        msg.get("content", "").strip().startswith("[") 
                        for msg in messages if msg.get("role") == "user")
            is_diff = any("--- " in msg.get("content", "") and "+++ " in msg.get("content", "")
                        for msg in messages if msg.get("role") == "user")

            # Define explicit overlap markers
            begin_marker = "---BEGIN_EXACT_OVERLAP---"
            end_marker = "---END_EXACT_OVERLAP---"

            # Helper function for analyzing JSON structure
            def analyze_json_structure(content: str) -> Dict[str, Any]:
                """Analyze JSON structure to determine current state"""
                state = {
                    "open_braces": 0,
                    "open_brackets": 0,
                    "in_string": False,
                    "escape_next": False,
                    "file_path": None
                }
                
                for char in content:
                    if state["escape_next"]:
                        state["escape_next"] = False
                        continue
                    
                    if char == '\\':
                        state["escape_next"] = True
                    elif char == '"' and not state["escape_next"]:
                        state["in_string"] = not state["in_string"]
                    elif not state["in_string"]:
                        if char == '{':
                            state["open_braces"] += 1
                        elif char == '}':
                            state["open_braces"] = max(0, state["open_braces"] - 1)
                        elif char == '[':
                            state["open_brackets"] += 1
                        elif char == ']':
                            state["open_brackets"] = max(0, state["open_brackets"] - 1)
                
                # Extract current file path if present
                file_path_match = re.search(r'"file_path"\s*:\s*"([^"]+)"', content)
                if file_path_match:
                    state["file_path"] = file_path_match.group(1)
                    
                return state

            # Helper function to sanitize problematic escape sequences
            def sanitize_escape_sequences(content: str) -> str:
                """Fix common escape sequence issues in JSON/diff content"""
                # Double escape any single backslashes that aren't already escaped
                # But avoid affecting already properly escaped sequences
                content = re.sub(r'(?<!\\)\\(?!["\\bfnrtu])', r'\\\\', content)
                
                # Fix specific problematic escape sequences
                content = content.replace('\\e', '\\\\e')
                content = content.replace('\\p', '\\\\p')
                
                return content
                
            # Helper function to validate and repair JSON
            def validate_and_repair_json(content: str, current_state: Dict[str, Any]) -> Tuple[str, bool, str]:
                """Validate and attempt to repair JSON content"""
                # First try basic sanitization
                sanitized = sanitize_escape_sequences(content)
                
                # Try parsing as JSON
                try:
                    json.loads(sanitized)
                    return sanitized, True, "Valid JSON after sanitization"
                except json.JSONDecodeError as e:
                    # Problem detected, try to fix
                    if e.msg.startswith('Invalid \\escape'):
                        # Handle invalid escape sequences
                        position = max(0, e.pos - 10)
                        context = sanitized[position:e.pos + 10]
                        logger.warning("json.invalid_escape", position=e.pos, context=context)
                        
                        # Apply more aggressive sanitization around the problem area
                        before = sanitized[:e.pos]
                        problem_char = sanitized[e.pos] if e.pos < len(sanitized) else ''
                        after = sanitized[e.pos+1:] if e.pos+1 < len(sanitized) else ''
                        
                        # Replace the problematic character
                        if problem_char == '\\':
                            # It's a backslash causing issues, escape it
                            repaired = before + '\\\\' + after
                        else:
                            # Otherwise just double any backslash before the problem
                            repaired = before + problem_char + after
                            
                        return repaired, False, f"Attempted escape sequence repair at position {e.pos}"
                        
                    elif e.msg.startswith('Expecting'):
                        # Handle structural issues
                        if current_state["open_braces"] > 0:
                            # Missing closing braces
                            repaired = sanitized + ('}' * current_state["open_braces"])
                            return repaired, False, f"Added {current_state['open_braces']} missing closing braces"
                        
                        if current_state["open_brackets"] > 0:
                            # Missing closing brackets
                            repaired = sanitized + (']' * current_state["open_brackets"])
                            return repaired, False, f"Added {current_state['open_brackets']} missing closing brackets"
                            
                # Could not repair automatically
                return sanitized, False, "Could not fully repair JSON structure"

            # Start completion loop with continuation handling
            while attempt < max_tries:
                if attempt > 0:
                    diagnostics["attempts"] += 1
                    
                    # Calculate appropriate overlap size based on content
                    content_lines = accumulated_content.splitlines()
                    
                    # Analyze the current JSON structure if applicable
                    if is_json:
                        current_state = analyze_json_structure(accumulated_content)
                        json_state.update(current_state)
                        
                        # Log the current structure state for debugging
                        logger.debug("json.structure_state", 
                                    open_braces=current_state["open_braces"],
                                    open_brackets=current_state["open_brackets"],
                                    current_file=current_state["file_path"])
                    
                    # Adaptive overlap size based on content length and type
                    if is_code:
                        # For code, use more lines to ensure complete syntactic blocks
                        overlap_size = min(max(5, min(len(content_lines) // 3, 15)), len(content_lines))
                    elif is_json or is_diff:
                        # For JSON/diff, try to include complete objects or chunks
                        overlap_size = min(max(8, min(len(content_lines) // 3, 20)), len(content_lines))
                    else:
                        # For text, fewer lines are usually sufficient
                        overlap_size = min(max(3, min(len(content_lines) // 4, 10)), len(content_lines))
                    
                    last_lines = content_lines[-overlap_size:]
                    overlap_context = "\n".join(last_lines)
                    
                    # Create diagnostic snapshot of content state
                    content_snapshot = {
                        "last_chars": accumulated_content[-50:] if len(accumulated_content) > 50 else accumulated_content,
                        "has_braces": "{" in overlap_context or "}" in overlap_context,
                        "has_brackets": "[" in overlap_context or "]" in overlap_context,
                        "has_parens": "(" in overlap_context or ")" in overlap_context,
                        "open_braces": overlap_context.count("{") - overlap_context.count("}"),
                        "open_brackets": overlap_context.count("[") - overlap_context.count("]"),
                        "open_parens": overlap_context.count("(") - overlap_context.count(")")
                    }
                    
                    logger.info("llm.continuation_attempt",
                            attempt=attempt,
                            messages_count=len(messages),
                            overlap_lines=overlap_size,
                            content_state=content_snapshot)
                    
                    # Choose appropriate continuation prompt based on content type
                    if is_json and is_diff:
                        # Special handling for JSON with diffs
                        current_file = json_state.get("file_path", "unknown file")
                        is_array_item = '"changes"' in accumulated_content
                        
                        continuation_prompt = (
                            "Continue the JSON response exactly from where you left off.\n\n"
                            f"Current context: Inside the 'changes' array, processing file {current_file}\n"
                            f"Structure state: {json_state['open_braces']} open braces, {json_state['open_brackets']} open brackets\n\n"
                            f"{begin_marker}\n{overlap_context}\n{end_marker}\n\n"
                            "Copy these lines exactly, then continue. Important rules:\n"
                            "1. Each change object must be complete with all fields (file_path, type, description, diff)\n"
                            "2. In diff content, escape all backslashes properly (use \\\\ for a single backslash)\n"
                            "3. Close all JSON objects and arrays properly\n"
                            "4. Maintain exact indentation and formatting"
                        )
                    elif is_json:
                        # Regular JSON continuation
                        continuation_prompt = (
                            "Continue the JSON response exactly from where you left off.\n\n"
                            "You MUST start by repeating these EXACT lines:\n\n"
                            f"{begin_marker}\n{overlap_context}\n{end_marker}\n\n"
                            "Do not modify these lines in any way - copy them exactly. "
                            "After repeating these lines exactly, continue with the next part of the JSON. "
                            "Make sure your response starts with this overlap to ensure proper continuity. "
                            "Be extra careful with escape sequences and ensure all JSON is valid."
                        )
                    elif is_code:
                        continuation_prompt = (
                            "Continue the code exactly from where you left off.\n\n"
                            "You MUST start by repeating these EXACT lines:\n\n"
                            f"{begin_marker}\n{overlap_context}\n{end_marker}\n\n"
                            "Do not modify these lines in any way - copy them exactly. "
                            "After repeating these lines exactly, continue with the next part of the code. "
                            "Maintain exact format, indentation, and structure. "
                            "Do not add any explanatory text, comments, or markers outside the overlap section."
                        )
                    else:
                        continuation_prompt = (
                            "Continue exactly from where you left off.\n\n"
                            "You MUST start by repeating these EXACT lines:\n\n"
                            f"{begin_marker}\n{overlap_context}\n{end_marker}\n\n"
                            "Do not modify these lines in any way - copy them exactly. "
                            "After repeating these lines exactly, continue where you left off. "
                            "Do not add any explanatory text or markers."
                        )
                    
                    # Add assistant and user messages for continuation
                    messages.append({"role": "assistant", "content": accumulated_content})
                    messages.append({"role": "user", "content": continuation_prompt})
                    completion_params["messages"] = messages
                
                try:
                    if use_streaming:
                        # Handle streaming response
                        full_content = ""
                        
                        # Get streamed response
                        response_stream = completion(**completion_params)
                        
                        # Process the stream
                        for chunk in response_stream:
                            try:
                                # Extract content from the chunk
                                if hasattr(chunk, 'choices') and chunk.choices:
                                    delta = chunk.choices[0].delta
                                    if hasattr(delta, 'content') and delta.content:
                                        full_content += delta.content
                            except Exception as e:
                                logger.error("llm.stream_chunk_processing_error", 
                                        error=str(e),
                                        chunk_type=type(chunk).__name__)
                        
                        # Create a proper response object with the necessary structure
                        class StreamedResponse:
                            def __init__(self, content):
                                self.choices = [type('Choice', (), {
                                    'message': type('Message', (), {'content': content}),
                                    'finish_reason': 'stop'
                                })]
                                self.usage = type('Usage', (), {
                                    'prompt_tokens': 0,
                                    'completion_tokens': 0,
                                    'total_tokens': 0
                                })
                                
                        # Create a response object that mimics the structure of a regular response
                        response = StreamedResponse(full_content)
                        
                        logger.info("llm.stream_processing_complete", 
                                content_length=len(full_content),
                                finish_reason='stop')
                    else:
                        # Standard non-streaming request
                        response = completion(**completion_params)

                    # Reset retry count on successful completion
                    retry_count = 0

                    if not hasattr(response, 'choices') or not response.choices:
                        logger.error("llm.no_response",
                                attempt=attempt,
                                provider=self.provider.serialize())
                        break

                    # Process response through standard interface
                    result = self._process_response(response, response)
                    final_response = response
                    
                    # Extract current content from the response
                    current_content = result['response']
                    
                    # For continuation attempts, handle joining with multi-level strategy
                    if attempt > 0:
                        # First, look for explicit markers
                        cleaned_content = self._clean_overlap_markers(current_content, begin_marker, end_marker)
                        
                        # If markers found and properly cleaned, use the cleaned content
                        if cleaned_content != current_content:
                            logger.info("llm.markers_found_and_cleaned")
                            current_content = cleaned_content
                            diagnostics["exact_matches"] += 1
                        else:
                            # Markers not found or not properly formatted, use advanced joining
                            diagnostics["overlap_attempts"] += 1
                            
                            # If json content, try to sanitize and validate
                            if is_json:
                                sanitized, is_valid, repair_msg = validate_and_repair_json(
                                    current_content, json_state)
                                    
                                if sanitized != current_content:
                                    logger.info("json.content_sanitized", message=repair_msg)
                                    current_content = sanitized
                                    diagnostics["structure_repairs"] += 1
                            
                            # If accumulated_content and last_lines are available, use sophisticated joining
                            if accumulated_content and last_lines:
                                # Log the first part of current content for debugging
                                logger.debug("llm.overlap_matching_attempt",
                                            overlap_lines=len(last_lines),
                                            expected_overlap_preview=overlap_context[:200] + "..." if len(overlap_context) > 200 else overlap_context,
                                            received_preview=current_content[:200] + "..." if len(current_content) > 200 else current_content)
                                
                                # Try multi-level matching with full diagnostics
                                joined_content, match_method = self._join_with_overlap(
                                    accumulated_content, 
                                    current_content,
                                    last_lines,
                                    is_code or is_json or is_diff
                                )
                                
                                # Update diagnostics based on match method
                                if match_method == "exact":
                                    diagnostics["exact_matches"] += 1
                                elif match_method == "hash":
                                    diagnostics["hash_matches"] += 1
                                elif match_method == "token":
                                    diagnostics["token_matches"] += 1
                                else:
                                    diagnostics["fallbacks"] += 1
                                
                                # Update accumulated content
                                accumulated_content = joined_content
                            else:
                                # No previous content or overlap lines, use directly
                                accumulated_content += current_content
                                diagnostics["fallbacks"] += 1
                    else:
                        # First response, just use it directly
                        accumulated_content = current_content
                    
                    # Validate joined content for potential syntax errors
                    if (is_code or is_json) and attempt > 0:
                        is_valid = self._validate_joined_content(accumulated_content, is_json)
                        if not is_valid:
                            logger.warning("llm.syntax_validation_warning", 
                                        attempt=attempt, 
                                        continuation_state="potential_syntax_issue")
                    
                    # Check if we need to continue
                    finish_reason = getattr(response.choices[0], 'finish_reason', None)
                    
                    if finish_reason == 'length':
                        logger.info("llm.length_limit_reached", attempt=attempt)
                        attempt += 1
                        continue
                    else:
                        logger.info("llm.completion_finished",
                                finish_reason=finish_reason,
                                continuation_count=attempt)
                        break

                except litellm.InternalServerError as e:
                    # Handle overload errors with exponential backoff
                    error_data = str(e)
                    if "overloaded_error" in error_data:
                        retry_count += 1
                        if retry_count > max_retries:
                            logger.error("llm.max_retries_exceeded",
                                    retries=retry_count,
                                    error=str(e))
                            raise
                            
                        # Exponential backoff
                        delay = min(2 ** (retry_count - 1), 32)  # Max 32 second delay
                        logger.warning("llm.overloaded_retrying",
                                    retry_count=retry_count,
                                    delay=delay)
                        time.sleep(delay)
                        continue
                    else:
                        raise

                except Exception as e:
                    logger.error("llm.request_failed", 
                            error=str(e),
                            attempt=attempt)
                    raise

            # Log summary of continuations
            if attempt > 0:
                logger.info("llm.continuation_summary", 
                        total_attempts=attempt,
                        model=self.model_str, 
                        total_length=len(accumulated_content),
                        diagnostics=diagnostics)

            # Update the content in the final response
            if final_response and hasattr(final_response, 'choices') and final_response.choices:
                final_response.choices[0].message.content = accumulated_content

            # Track actual continuation count for metrics
            self.metrics["continuation_attempts"] = attempt
            return accumulated_content, final_response

        except Exception as e:
            logger.error("llm.continuation_failed", error=str(e), error_type=type(e).__name__)
            raise

    def _join_with_overlap(self, previous: str, current: str, overlap_lines: List[str], is_code: bool = False) -> Tuple[str, str]:
        """
        Join content using multi-level overlap detection.
        Tries multiple strategies to find the best join point, with full diagnostics.
        
        Args:
            previous: First chunk of content
            current: Continuation chunk
            overlap_lines: Expected overlap lines from previous content
            is_code: Whether the content is code (for special handling)
            
        Returns:
            Tuple of (joined_content, match_method)
        """
        import hashlib
        
        # Check edge cases
        if not previous or not current:
            return previous + current, "direct"
        
        # LEVEL 1: Try exact overlap detection
        overlap_text = "\n".join(overlap_lines)
        
        # Check if our expected overlap is found at the beginning of current content
        current_lines = current.splitlines()
        if len(current_lines) >= len(overlap_lines):
            current_overlap = "\n".join(current_lines[:len(overlap_lines)])
            
            # Check for exact match of the overlap text
            if current_overlap == overlap_text:
                # Found exact match, join after removing overlap
                logger.info("llm.exact_overlap_match_found", overlap_lines=len(overlap_lines))
                return previous + "\n" + "\n".join(current_lines[len(overlap_lines):]), "exact"
        
        # LEVEL 2: Try normalized hash matching (ignores whitespace differences)
        try:
            # Create normalized hash of expected overlap
            def normalize_for_hash(text):
                # Remove whitespace and normalize case for non-code
                normalized = ''.join(text.lower().split()) if not is_code else ''.join(text.split())
                return normalized
                
            expected_hash = hashlib.md5(normalize_for_hash(overlap_text).encode()).hexdigest()
            
            # Try to find a matching section in the current content
            for i in range(min(20, len(current_lines))):  # Check first 20 positions
                if i + len(overlap_lines) <= len(current_lines):
                    window = "\n".join(current_lines[i:i+len(overlap_lines)])
                    window_hash = hashlib.md5(normalize_for_hash(window).encode()).hexdigest()
                    
                    if window_hash == expected_hash:
                        # Found hash match, join after removing overlap
                        logger.info("llm.hash_match_found", position=i, overlap_lines=len(overlap_lines))
                        return previous + "\n" + "\n".join(current_lines[i+len(overlap_lines):]), "hash"
        except Exception as e:
            logger.warning("llm.hash_matching_failed", error=str(e))
        
        # LEVEL 3: Try token-level matching for partial overlaps
        try:
            # Find best overlap point using token-level matching
            best_point = self._find_best_overlap_point(previous, current)
            if best_point > 0:
                logger.info("llm.token_match_found", token_position=best_point)
                return previous + current[best_point:], "token"
        except Exception as e:
            logger.warning("llm.token_matching_failed", error=str(e))
        
        # LEVEL 4: Special handling for code - check for syntax structures
        if is_code:
            try:
                # Log details about syntax state
                brace_balance = overlap_text.count("{") - overlap_text.count("}")
                bracket_balance = overlap_text.count("[") - overlap_text.count("]")
                paren_balance = overlap_text.count("(") - overlap_text.count(")")
                
                logger.info("llm.code_syntax_state", 
                        brace_balance=brace_balance, 
                        bracket_balance=bracket_balance,
                        paren_balance=paren_balance,
                        has_def=("def " in overlap_text),
                        has_class=("class " in overlap_text))
                        
                # Check for function/method boundary issues
                if "def " in previous[-200:] and "def " in current[:200]:
                    # Extract function names to check for duplication
                    prev_func_match = previous[-200:].rfind("def ")
                    curr_func_match = current[:200].find("def ")
                    
                    if prev_func_match >= 0 and curr_func_match >= 0:
                        prev_func_line = previous[-200+prev_func_match:].splitlines()[0]
                        curr_func_line = current[curr_func_match:curr_func_match+200].splitlines()[0]
                        
                        logger.debug("llm.function_boundary_check",
                                prev_func_preview=prev_func_line,
                                curr_func_preview=curr_func_line)
                        
                        # Check if they appear to be the same function
                        if prev_func_line.split("(")[0] == curr_func_line.split("(")[0]:
                            # Skip duplicate function definition 
                            func_end_pos = current.find(":", curr_func_match)
                            if func_end_pos > 0:
                                logger.info("llm.duplicate_function_detected", 
                                        function=prev_func_line.split("(")[0])
                                return previous + current[func_end_pos+1:].lstrip(), "code-structure"
            except Exception as e:
                logger.warning("llm.code_analysis_failed", error=str(e))
        
        # LEVEL 5: Fall back to syntax-aware basic joining
        logger.warning("llm.all_overlap_strategies_failed", 
                    falling_back="basic_join",
                    overlap_lines=len(overlap_lines))
        return self._basic_join(previous, current, is_code), "fallback"

    def _find_best_overlap_point(self, previous: str, current: str, min_tokens: int = 5) -> int:
        """
        Find best overlap point using token-level matching.
        Looks for a sequence of tokens that appear in both previous and current.
        
        Args:
            previous: First chunk of content
            current: Continuation chunk
            min_tokens: Minimum number of consecutive tokens to consider a match
            
        Returns:
            Position in current content where continuation should start (after overlap)
        """
        # Get last part of previous and first part of current content
        prev_tail = previous[-1000:] if len(previous) > 1000 else previous
        curr_head = current[:1000] if len(current) > 1000 else current
        
        # Simple tokenization by whitespace and punctuation
        def simple_tokenize(text):
            import re
            return re.findall(r'\w+|[^\w\s]', text)
        
        prev_tokens = simple_tokenize(prev_tail)
        curr_tokens = simple_tokenize(curr_head)
        
        # Look for matching token sequences
        best_match_len = 0
        best_match_pos = 0
        
        for i in range(len(prev_tokens) - min_tokens + 1):
            prev_seq = prev_tokens[i:i + min_tokens]
            
            for j in range(len(curr_tokens) - min_tokens + 1):
                curr_seq = curr_tokens[j:j + min_tokens]
                
                # Compare token sequences
                if prev_seq == curr_seq:
                    # Found match, see how long it continues
                    match_len = min_tokens
                    while (i + match_len < len(prev_tokens) and 
                        j + match_len < len(curr_tokens) and 
                        prev_tokens[i + match_len] == curr_tokens[j + match_len]):
                        match_len += 1
                    
                    # Track best match
                    if match_len > best_match_len:
                        best_match_len = match_len
                        best_match_pos = j + match_len
        
        # Only return a position if we found a good match
        if best_match_len >= min_tokens:
            # Calculate approximate character position
            char_pos = 0
            for i in range(best_match_pos):
                if i < len(curr_tokens):
                    char_pos += len(curr_tokens[i]) + 1  # +1 for spacing
            
            logger.debug("llm.token_match_details", 
                    match_length=best_match_len, 
                    token_position=best_match_pos,
                    char_position=char_pos)
            return char_pos
        
        # No good match found
        return 0

    def _validate_joined_content(self, content: str, is_json: bool = False) -> bool:
        """
        Enhanced syntax validation for potentially problematic patterns.
        Checks for unbalanced structures and other common issues.
        
        Args:
            content: The content to validate
            is_json: Whether to perform JSON-specific validation
            
        Returns:
            True if validation passes, False if issues detected
        """
        # Check for balanced braces, brackets, parentheses
        brace_balance = content.count("{") - content.count("}")
        bracket_balance = content.count("[") - content.count("]")
        paren_balance = content.count("(") - content.count(")")
        
        if is_json:
            # For JSON, attempt to parse a sample to detect issues
            try:
                # Try to find complete JSON objects and validate them
                if content.strip().startswith("{") and "}" in content:
                    # Find the last complete JSON object
                    last_brace_pos = content.rindex("}")
                    json_sample = content[:last_brace_pos+1]
                    json.loads(json_sample)
                    
                # Look for specific invalid escape sequences
                if re.search(r'(?<!\\)\\(?!["\\/bfnrt])', content):
                    logger.warning("llm.invalid_escape_sequences_detected")
                    return False
                    
            except json.JSONDecodeError as e:
                logger.warning("llm.json_validation_failed", 
                            error=str(e),
                            position=e.pos)
                return False
        else:
            # For code, check for incomplete Python blocks
            incomplete_block = False
            lines = content.splitlines()
            block_indent = None
            for i, line in enumerate(lines):
                stripped = line.strip()
                # Check for block starters without corresponding blocks
                if stripped.endswith(":") and i < len(lines) - 1:
                    indent = len(line) - len(line.lstrip())
                    next_indent = len(lines[i+1]) - len(lines[i+1].lstrip())
                    if next_indent <= indent:  # Next line should be indented if block continues
                        incomplete_block = True
                        break
        
        if brace_balance != 0 or bracket_balance != 0 or paren_balance != 0 or (not is_json and incomplete_block):
            logger.warning("llm.syntax_validation_failed",
                        brace_balance=brace_balance,
                        bracket_balance=bracket_balance,
                        paren_balance=paren_balance,
                        incomplete_block=incomplete_block if not is_json else None)
            return False
        return True

    def _clean_overlap_markers(self, content: str, begin_marker: str, end_marker: str) -> str:
        """
        Remove overlap markers and extract the proper continuation.
        Uses markers to extract the continuation after the overlap.
        
        Args:
            content: The content to clean
            begin_marker: Start marker for overlap section
            end_marker: End marker for overlap section
            
        Returns:
            Content with overlap section properly handled
        """
        # Check if both markers exist in the content
        if begin_marker not in content or end_marker not in content:
            return content
        
        # Find positions of markers
        begin_pos = content.find(begin_marker)
        end_pos = content.find(end_marker, begin_pos)
        
        if begin_pos >= 0 and end_pos > begin_pos:
            # Found both markers in the expected sequence
            after_marker = content[end_pos + len(end_marker):].lstrip()
            logger.debug("llm.overlap_markers_cleaned", 
                    begin_pos=begin_pos, 
                    end_pos=end_pos, 
                    content_after_markers=len(after_marker))
            return after_marker
        
        # Markers found but not in expected sequence
        return content

    def _basic_join(self, previous: str, current: str, is_code: bool = False) -> str:
        """
        Join content with basic cleaning and syntax awareness.
        Handles common formatting and indentation issues at join point.
        
        Args:
            previous: First chunk of content
            current: Continuation chunk
            is_code: Whether content is code (for special handling)
            
        Returns:
            Joined content with basic syntax fixes
        """
        # Clean up whitespace at the join point
        previous = previous.rstrip()
        current = current.lstrip()
        
        # For code content, do special syntax checking
        if is_code:
            # Check for syntax state at the join point
            open_braces = previous.count("{") - previous.count("}")
            open_brackets = previous.count("[") - previous.count("]")
            open_parens = previous.count("(") - previous.count(")")
            
            # Check if we're inside a string
            single_quotes = previous.count("'") % 2
            double_quotes = previous.count('"') % 2
            in_string = single_quotes != 0 or double_quotes != 0
            
            # Check if we're at a line continuation
            ends_with_continuation = previous.rstrip().endswith("\\")
            
            # Log details for debugging
            logger.debug("llm.join_point_syntax_state",
                    open_braces=open_braces,
                    open_brackets=open_brackets,
                    open_parens=open_parens,
                    in_string=in_string,
                    ends_with_continuation=ends_with_continuation)
            
            # Handle specific code patterns
            if open_braces > 0 and current.lstrip().startswith("}"):
                # Already have closing brace at start of continuation
                return previous + "\n" + current
            
            if open_brackets > 0 and current.lstrip().startswith("]"):
                # Already have closing bracket at start of continuation
                return previous + "\n" + current
            
            if open_parens > 0 and current.lstrip().startswith(")"):
                # Already have closing paren at start of continuation
                return previous + "\n" + current
            
            # Check for function/class context continuations
            if previous.rstrip().endswith(":") or previous.rstrip().endswith("{"):
                # Block starter, ensure newline before continuation
                return previous + "\n" + current
        
        # Handle JSON special cases
        if previous.rstrip().endswith(",") and current.lstrip().startswith(","):
            # Remove duplicate comma
            current = current[1:].lstrip()
        
        # Default joining with newline to maintain readability
        return previous + "\n" + current

    def _fuzzy_line_join(self, previous: str, overlap_lines: List[str], current: str) -> str:
        """
        Join content using line-by-line fuzzy matching when exact overlap fails.
        Works for both code and text content.
        """
        # Split current content into lines for analysis
        current_lines = current.splitlines()
        
        # Edge case - if no lines to match
        if not overlap_lines or not current_lines:
            return previous + "\n" + current
        
        # Try to find a match for the first few lines of the overlap
        match_size = min(3, len(overlap_lines))
        first_match_lines = overlap_lines[:match_size]
        
        for i in range(min(10, len(current_lines) - match_size + 1)):
            # Check if the current window matches our expected first lines
            window = current_lines[i:i+match_size]
            if window == first_match_lines:
                # Found a match, take everything after this match point
                logger.debug("llm.fuzzy_match_found", 
                           position=i, 
                           match_size=match_size)
                return previous + "\n" + "\n".join(current_lines[i+match_size:])
        
        # No good match found, fall back to basic joining
        logger.debug("llm.no_overlap_found", falling_back="basic_join")
        return self._basic_join(previous, current)

    def _basic_join(self, previous: str, current: str) -> str:
        """
        Join content with basic cleaning and special case handling.
        Generic approach that works reasonably well for different content types.
        """
        # Clean up the join point
        previous = previous.rstrip()
        current = current.lstrip()
        
        # Handle JSON continuation special cases
        if (previous.endswith(",") and current.startswith(",")) or \
        (previous.endswith("{") and current.startswith("{")):
            current = current[1:].lstrip()
        elif previous.endswith("}") and current.startswith("}"):
            # Multiple closing braces - might need to insert comma
            return previous + "," + current
            
        # Check if we need newline between code segments
        if previous.endswith((";", "{", "}", ":", ">")):
            return previous + "\n" + current
        
        # For most cases, just join with a space
        if not previous.endswith((" ", "\n", "\t")) and not current.startswith((" ", "\n", "\t")):
            return previous + " " + current
            
        return previous + current
        
    def _clean_overlap_markers(self, content: str, begin_marker: str, end_marker: str) -> str:
        """
        Remove overlap markers and extract the proper continuation.
        Uses markers to find where the real content starts.
        """
        if begin_marker not in content or end_marker not in content:
            return content
            
        # Find positions of markers
        begin_pos = content.find(begin_marker)
        end_pos = content.find(end_marker, begin_pos + len(begin_marker))
        
        if begin_pos >= 0 and end_pos > begin_pos:
            # Found both markers, extract everything after the end marker
            after_marker = content[end_pos + len(end_marker):].lstrip()
            return after_marker
            
        # Markers not found in expected sequence, return original
        return content

    def _process_response(self, content: str, raw_response: Any) -> Dict[str, Any]:
        """
        Process LLM response with comprehensive validation and logging.
        Maintains consistent response format while preserving metadata.
        
        Args:
            content: Initial content from LLM
            raw_response: Complete response object
            
        Returns:
            Standardized response dictionary with:
            - response: Processed content
            - raw_output: Original response string
            - timestamp: Processing time
            - usage: Token usage if available
            - error: Any processing errors
        """
        try:
            # Extract content using standard method
            processed_content = self._get_llm_content(content)
            
            # Debug logging for response processing
            if self._should_log(LogDetail.DEBUG):
                logger.debug("agent.processing_response",
                            content_length=len(str(processed_content)) if processed_content else 0,
                            response_type=type(raw_response).__name__,
                            continuation_attempts=self.metrics["continuation_attempts"])

            # Build standard response structure
            response = {
                "response": processed_content,
                "raw_output": str(raw_response),
                "timestamp": datetime.utcnow().isoformat()
            }

            # Log and include token usage if available
            if hasattr(raw_response, 'usage'):
                usage = raw_response.usage
                usage_data = {
                    "completion_tokens": getattr(usage, 'completion_tokens', 0),
                    "prompt_tokens": getattr(usage, 'prompt_tokens', 0),
                    "total_tokens": getattr(usage, 'total_tokens', 0)
                }
                logger.info("llm.token_usage", **usage_data)
                response["usage"] = usage_data

            return response

        except Exception as e:
            error_msg = str(e)
            logger.error("response_processing.failed", 
                        error=error_msg,
                        content_type=type(content).__name__)
            return {
                "response": str(content),
                "raw_output": str(raw_response),
                "timestamp": datetime.utcnow().isoformat(),
                "error": error_msg
            }

    def _get_model_str(self) -> str:
        """Get the appropriate model string for the provider"""
        if self.provider == LLMProvider.OPENAI:
            return f"openai/{self.model}"
        elif self.provider == LLMProvider.ANTHROPIC:
            return f"anthropic/{self.model}" 
        elif self.provider == LLMProvider.GEMINI:
            return f"google/{self.model}"
        else:
            return f"{self.provider.value}/{self.model}"

    def _setup_litellm(self, provider_config: Dict[str, Any]) -> None:
        """
        Configure litellm with provider settings.
        Handles extended thinking configuration for Claude 3.7 Sonnet.
        """
        try:
            litellm_params = provider_config.get("litellm_params", {})
            
            # Set retry configuration globally
            if "retry" in litellm_params:
                litellm.success_callback = []
                litellm.failure_callback = []
                litellm.retry = litellm_params.get("retry", True)
                litellm.max_retries = litellm_params.get("max_retries", 3)
                
                # Handle backoff settings
                backoff = litellm_params.get("backoff", {})
                litellm.retry_wait = backoff.get("initial_delay", 1)
                litellm.max_retry_wait = backoff.get("max_delay", 30)
                litellm.retry_exponential = backoff.get("exponential", True)
                
            # Set rate limits if provided
            if "rate_limit_policy" in litellm_params:
                rate_limits = litellm_params["rate_limit_policy"]
                litellm.requests_per_min = rate_limits.get("requests", 50)
                litellm.token_limit = rate_limits.get("tokens", 4000)
                litellm.limit_period = rate_limits.get("period", 60)

            # Configure api base if provided
            if "api_base" in provider_config:
                litellm.api_base = provider_config["api_base"]
            
            # Configure any provider-specific configurations
            # Only configure extended thinking support for Claude 3.7 Sonnet
            if self.provider.value == "anthropic" and "claude-3-7-sonnet" in self.model:
                # Check if extended thinking is explicitly enabled
                agent_name = self._get_agent_name()
                agent_path = f"llm_config.agents.{agent_name}"
                
                # Get extended thinking settings
                agent_thinking_config = self.config_node.get_value(f"{agent_path}.extended_thinking")
                if not agent_thinking_config:
                    agent_thinking_config = provider_config.get("extended_thinking", {})
                
                # Only configure if explicitly enabled
                if agent_thinking_config and agent_thinking_config.get("enabled", False) is True:
                    # Ensure litellm is configured to pass through the 'thinking' parameter
                    # This ensures the parameter will be added to the Anthropic API call
                    litellm.excluded_params = list(litellm.excluded_params) if hasattr(litellm, "excluded_params") else []
                    if "thinking" not in litellm.excluded_params:
                        litellm.excluded_params.append("thinking")
                        logger.debug("litellm.extended_thinking_support_configured",
                                model=self.model)
            
            if self._should_log(LogDetail.DEBUG):
                logger.debug("litellm.configured", 
                            provider=self.provider.serialize(),
                            retry_settings={
                                "enabled": litellm.retry,
                                "max_retries": litellm.max_retries,
                                "initial_delay": litellm.retry_wait,
                                "max_delay": litellm.max_retry_wait
                            })

        except Exception as e:
            logger.error("litellm.setup_failed", error=str(e))
            # Don't re-raise - litellm setup failure shouldn't be fatal

    def _get_llm_content(self, response: Any) -> Any:
        """Extract content from LLM response with robust error handling for different response formats"""
        try:
            # Handle different response types
            if hasattr(response, 'choices') and response.choices:
                # Standard response object
                if hasattr(response.choices[0], 'message') and hasattr(response.choices[0].message, 'content'):
                    content = response.choices[0].message.content
                    if self._should_log(LogDetail.DEBUG):
                        logger.debug("content.extracted_from_model", content_length=len(content) if content else 0)
                    return content
                # Handle delta format (used in streaming)
                elif hasattr(response.choices[0], 'delta') and hasattr(response.choices[0].delta, 'content'):
                    content = response.choices[0].delta.content
                    if self._should_log(LogDetail.DEBUG):
                        logger.debug("content.extracted_from_delta", content_length=len(content) if content else 0)
                    return content
            
            # If we have a simple string content
            if isinstance(response, str):
                return response
                
            # If response is already processed (dict with 'response' key)
            if isinstance(response, dict) and 'response' in response:
                return response['response']
                
            # Last resort fallback - convert to string
            result = str(response)
            logger.warning("content.extraction_fallback", 
                        response_type=type(response).__name__, 
                        content_preview=result[:100] if len(result) > 100 else result)
            return result
        except Exception as e:
            logger.error("content_extraction.failed", error=str(e))
            return str(response)

    def _should_log(self, level: str) -> bool:
        """Check if current log level includes the specified detail level"""
        log_levels = {
            LogDetail.MINIMAL: 0,
            LogDetail.BASIC: 1, 
            LogDetail.DETAILED: 2,
            LogDetail.DEBUG: 3
        }
        
        current_level = self.log_level
        target_level = LogDetail(level) if isinstance(level, str) else level
        
        return log_levels[target_level] <= log_levels[current_level]