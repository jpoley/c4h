"""
Enhanced LLM response continuation handling with better logging and fallback strategies.
Path: c4h_agents/agents/base_llm_continuation.py
"""

from typing import Dict, Any, List, Tuple, Optional
import time
import re
import json
import hashlib
from datetime import datetime
import litellm
from litellm import completion
from c4h_agents.agents.types import LLMProvider, LogDetail
from c4h_agents.utils.logging import get_logger

logger = get_logger()

class ContinuationHandler:
    """Handles LLM response continuations with robust overlap detection"""

    def __init__(self, parent_agent):
        """Initialize with parent agent reference for configuration access"""
        self.parent = parent_agent
        self.model_str = parent_agent.model_str
        self.provider = parent_agent.provider
        self.temperature = parent_agent.temperature
        self.max_continuation_attempts = parent_agent.max_continuation_attempts
        self.continuation_token_buffer = parent_agent.continuation_token_buffer
        
        # Debug counters
        self.diagnostics = {
            "attempts": 0,
            "exact_matches": 0,
            "hash_matches": 0,
            "token_matches": 0,
            "llm_joins": 0,
            "fallbacks": 0,
            "structure_repairs": 0
        }

    def get_completion_with_continuation(
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
            
            # Detect content type for specialized handling
            content_type = self._detect_content_type(messages)
            
            logger.info("llm.continuation_starting", 
                    model=self.model_str,
                    max_attempts=max_tries,
                    content_type=content_type)
            
            # Basic completion parameters
            completion_params = self._build_completion_params(messages)
                
            # Start completion loop with continuation handling
            while attempt < max_tries:
                if attempt > 0:
                    self.diagnostics["attempts"] += 1
                    
                    # For continuation, need to analyze content and prepare overlap
                    overlap_lines, overlap_context = self._prepare_overlap_context(
                        accumulated_content, content_type)
                    
                    # Create appropriate continuation prompt
                    continuation_prompt = self._create_continuation_prompt(
                        overlap_context, content_type)
                    
                    # Log overlap context for debugging
                    logger.debug("llm.continuation_overlap_preview", 
                                overlap_lines=len(overlap_lines),
                                last_lines="\n".join(overlap_lines[-10:]) if len(overlap_lines) >= 10 else overlap_context)
                    
                    # Add assistant and user messages for continuation
                    messages.append({"role": "assistant", "content": accumulated_content})
                    messages.append({"role": "user", "content": continuation_prompt})
                    completion_params["messages"] = messages
                
                try:
                    # Make the actual LLM request
                    response = self._make_llm_request(completion_params)

                    # Reset retry count on successful completion
                    retry_count = 0

                    if not hasattr(response, 'choices') or not response.choices:
                        logger.error("llm.no_response",
                                attempt=attempt,
                                provider=self.provider.serialize())
                        break

                    # Process response through standard interface
                    result = self.parent._process_response(response, response)
                    final_response = response
                    
                    # Extract current content from the response
                    current_content = result['response']
                    
                    # Log response preview
                    if attempt > 0 and current_content:
                        current_lines = current_content.splitlines()
                        logger.debug("llm.continuation_response_preview", 
                                    first_lines="\n".join(current_lines[:10]) if len(current_lines) >= 10 else current_content[:500],
                                    last_lines="\n".join(current_lines[-10:]) if len(current_lines) >= 10 else "")
                    
                    # For continuation attempts, handle joining with multi-level strategy
                    if attempt > 0:
                        # Get the explicit overlap markers
                        begin_marker = "---BEGIN_EXACT_OVERLAP---"
                        end_marker = "---END_EXACT_OVERLAP---"
                        
                        # First, look for explicit markers
                        cleaned_content = self._clean_overlap_markers(current_content, begin_marker, end_marker)
                        
                        # If markers found and properly cleaned, use the cleaned content
                        if cleaned_content != current_content:
                            logger.info("llm.markers_found_and_cleaned")
                            current_content = cleaned_content
                            self.diagnostics["exact_matches"] += 1
                        else:
                            # Try multi-level matching
                            joined_content, match_method = self._join_with_overlap(
                                accumulated_content, 
                                current_content,
                                overlap_lines,
                                content_type
                            )
                            
                            # Update accumulated content
                            accumulated_content = joined_content
                            
                            # Update metrics based on match method
                            self._update_match_metrics(match_method)
                    else:
                        # First response, just use it directly
                        accumulated_content = current_content
                    
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
                    self._handle_litellm_error(e, retry_count)
                    retry_count += 1
                    continue
                    
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
                        diagnostics=self.diagnostics)

            # Update the content in the final response
            if final_response and hasattr(final_response, 'choices') and final_response.choices:
                final_response.choices[0].message.content = accumulated_content

            # Track actual continuation count for metrics
            self.parent.metrics["continuation_attempts"] = attempt
            return accumulated_content, final_response

        except Exception as e:
            logger.error("llm.continuation_failed", error=str(e), error_type=type(e).__name__)
            raise

    def _detect_content_type(self, messages: List[Dict[str, str]]) -> str:
        """Detect content type from messages for specialized handling"""
        content = ""
        for msg in messages:
            if msg.get("role") == "user":
                content = msg.get("content", "")
                break
                
        # Check for specific content types
        is_code = any("```" in msg.get("content", "") or "def " in msg.get("content", "") 
                    for msg in messages if msg.get("role") == "user")
        is_json = any("json" in msg.get("content", "").lower() or 
                    msg.get("content", "").strip().startswith("{") or 
                    msg.get("content", "").strip().startswith("[") 
                    for msg in messages if msg.get("role") == "user")
        is_diff = any("--- " in msg.get("content", "") and "+++ " in msg.get("content", "")
                    for msg in messages if msg.get("role") == "user")
        
        if is_code and is_json:
            return "json_code"
        elif is_code:
            return "code"
        elif is_json:
            return "json"
        elif is_diff:
            return "diff"
        else:
            return "text"

    def _build_completion_params(self, messages: List[Dict[str, str]]) -> Dict[str, Any]:
        """Build parameters for LLM completion request"""
        completion_params = {
            "model": self.model_str,
            "messages": messages,
        }

        # Only add temperature for providers that support it
        if self.provider.value != "openai":
            completion_params["temperature"] = self.temperature
            
        # Add provider-specific params
        provider_config = self.parent._get_provider_config(self.provider)
        
        # Add model-specific parameters from config
        model_params = provider_config.get("model_params", {})
        if model_params:
            logger.debug("llm.applying_model_params", 
                        provider=self.provider.serialize(),
                        params=list(model_params.keys()))
            completion_params.update(model_params)
        
        if "api_base" in provider_config:
            completion_params["api_base"] = provider_config["api_base"]
                
        return completion_params
        
    def _make_llm_request(self, completion_params: Dict[str, Any]) -> Any:
        """Make the actual LLM request with error handling"""
        response = completion(**completion_params)
        return response
        
    def _handle_litellm_error(self, error: Exception, retry_count: int) -> None:
        """Handle LiteLLM errors with appropriate retry logic"""
        error_data = str(error)
        if "overloaded_error" in error_data:
            max_retries = 5
            if retry_count > max_retries:
                logger.error("llm.max_retries_exceeded",
                        retries=retry_count,
                        error=str(error))
                raise
                
            # Exponential backoff
            delay = min(2 ** retry_count, 32)  # Max 32 second delay
            logger.warning("llm.overloaded_retrying",
                        retry_count=retry_count,
                        delay=delay)
            time.sleep(delay)
        else:
            # Other errors just get raised
            raise error
            
    def _update_match_metrics(self, match_method: str) -> None:
        """Update metrics dictionary based on match method"""
        if match_method == "exact":
            self.diagnostics["exact_matches"] += 1
        elif match_method == "hash":
            self.diagnostics["hash_matches"] += 1
        elif match_method == "token":
            self.diagnostics["token_matches"] += 1
        elif match_method == "llm":
            self.diagnostics["llm_joins"] += 1
        else:
            self.diagnostics["fallbacks"] += 1

    def _prepare_overlap_context(self, accumulated_content: str, content_type: str) -> Tuple[List[str], str]:
        """Calculate appropriate overlap based on content type"""
        content_lines = accumulated_content.splitlines()
        
        # Adaptive overlap size based on content length and type
        if content_type in ["code", "json_code"]:
            # For code, use more lines to ensure complete syntactic blocks
            overlap_size = min(max(5, min(len(content_lines) // 3, 15)), len(content_lines))
        elif content_type in ["json", "diff"]:
            # For JSON/diff, try to include complete objects or chunks
            overlap_size = min(max(8, min(len(content_lines) // 3, 20)), len(content_lines))
        else:
            # For text, fewer lines are usually sufficient
            overlap_size = min(max(3, min(len(content_lines) // 4, 10)), len(content_lines))
        
        last_lines = content_lines[-overlap_size:]
        overlap_context = "\n".join(last_lines)
        
        return last_lines, overlap_context

    def _create_continuation_prompt(self, overlap_context: str, content_type: str) -> str:
        """Create continuation prompt based on content type"""
        # Define explicit overlap markers
        begin_marker = "---BEGIN_EXACT_OVERLAP---"
        end_marker = "---END_EXACT_OVERLAP---"
        
        # Choose appropriate continuation prompt based on content type
        if content_type == "json_code":
            # Special handling for JSON with code
            continuation_prompt = (
                "Continue the JSON response exactly from where you left off.\n\n"
                "You MUST start by repeating these EXACT lines:\n\n"
                f"{begin_marker}\n{overlap_context}\n{end_marker}\n\n"
                "Do not modify these lines in any way - copy them exactly. "
                "After repeating these lines exactly, continue with the next part of the JSON code. "
                "Maintain exact format, indentation, and structure. "
                "Be extra careful with escape sequences and ensure all JSON is valid."
            )
        elif content_type == "json":
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
        elif content_type == "code":
            continuation_prompt = (
                "Continue the code exactly from where you left off.\n\n"
                "You MUST start by repeating these EXACT lines:\n\n"
                f"{begin_marker}\n{overlap_context}\n{end_marker}\n\n"
                "Do not modify these lines in any way - copy them exactly. "
                "After repeating these lines exactly, continue with the next part of the code. "
                "Maintain exact format, indentation, and structure. "
                "Do not add any explanatory text, comments, or markers outside the overlap section."
            )
        elif content_type == "diff":
            continuation_prompt = (
                "Continue the diff exactly from where you left off.\n\n"
                "You MUST start by repeating these EXACT lines:\n\n"
                f"{begin_marker}\n{overlap_context}\n{end_marker}\n\n"
                "Do not modify these lines in any way - copy them exactly. "
                "After repeating these lines exactly, continue with the next part of the diff. "
                "Maintain exact format, indentation, and structure including the +/- markers. "
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
            
        return continuation_prompt

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

    def _join_with_overlap(self, previous: str, current: str, 
                         overlap_lines: List[str], content_type: str) -> Tuple[str, str]:
        """
        Join content using multi-level overlap detection.
        Tries multiple strategies to find the best join point, with full diagnostics.
        
        Args:
            previous: First chunk of content
            current: Continuation chunk
            overlap_lines: Expected overlap lines from previous content
            content_type: Type of content being processed
            
        Returns:
            Tuple of (joined_content, match_method)
        """
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
                normalized = ''.join(text.lower().split()) if content_type == "text" else ''.join(text.split())
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
        
        # LEVEL 4: For complex content, attempt LLM-based joining
        if content_type in ["code", "json", "json_code", "diff"]:
            try:
                joined_content = self._llm_based_joining(previous, current, content_type)
                if joined_content:
                    logger.info("llm.smart_join_successful")
                    return joined_content, "llm"
            except Exception as e:
                logger.warning("llm.smart_join_failed", error=str(e))
        
        # LEVEL 5: Fall back to syntax-aware basic joining
        logger.warning("llm.all_overlap_strategies_failed", 
                    falling_back="basic_join",
                    overlap_lines=len(overlap_lines))
        return self._basic_join(previous, current, content_type == "code"), "fallback"
    
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
        
    def _llm_based_joining(self, previous: str, current: str, content_type: str) -> str:
        """
        Use LLM to intelligently join content when algorithmic approaches fail.
        Only used as a last resort for complex content types.
        
        Args:
            previous: First chunk of content
            current: Second chunk of content 
            content_type: Type of content being joined
            
        Returns:
            Intelligently joined content
        """
        # Create a specialized context extraction
        prev_context = previous[-300:] if len(previous) > 300 else previous
        curr_context = current[:300] if len(current) > 300 else current
        
        # Specialized prompt based on content type
        if content_type == "json":
            join_prompt = f"""
            I need to join two JSON fragments correctly. The first fragment ends with:
            ```json
            {prev_context}
            ```
            
            The second fragment begins with:
            ```json
            {curr_context}
            ```
            
            Please identify the exact join point to ensure valid JSON structure and return ONLY the complete properly joined content.
            """
        elif content_type == "code":
            join_prompt = f"""
            I need to join two code fragments correctly. The first fragment ends with:
            ```
            {prev_context}
            ```
            
            The second fragment begins with:
            ```
            {curr_context}
            ```
            
            Please identify the exact join point to ensure valid code structure and return ONLY the complete properly joined content.
            """
        else:
            join_prompt = f"""
            I need to join two content fragments correctly. The first fragment ends with:
            ```
            {prev_context}
            ```
            
            The second fragment begins with:
            ```
            {curr_context}
            ```
            
            Please identify the exact join point and return ONLY the complete properly joined content.
            """
        
        # Make a simple LLM call with low temperature
        try:
            # Use minimal parameters
            response = completion(
                model=self.model_str,
                messages=[{"role": "user", "content": join_prompt}],
                temperature=0.0  # Use lower temperature for deterministic results
            )
            
            # Process the result
            if not hasattr(response, 'choices') or not response.choices:
                logger.error("llm.smart_join_no_response")
                return previous + "\n" + current
                
            joined_content = response.choices[0].message.content
            
            # Extract code block if present
            if "```" in joined_content:
                # Extract code from inside code blocks
                matches = re.findall(r'```(?:\w*\n)?([\s\S]*?)```', joined_content)
                if matches:
                    joined_content = matches[0]
            
            # If the result is suspiciously short, fall back
            if len(joined_content) < (len(previous) + len(current)) * 0.8:
                logger.warning("llm.suspicious_join_result", 
                            expected_len=len(previous) + len(current),
                            actual_len=len(joined_content))
                return previous + "\n" + current
                
            return joined_content
            
        except Exception as e:
            logger.error("llm.smart_join_failed", error=str(e))
            # Fall back to basic joining on error
            return previous + "\n" + current

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