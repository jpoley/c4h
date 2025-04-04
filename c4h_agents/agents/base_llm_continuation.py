"""
Enhanced LLM response continuation handling with detailed logging and rate limit handling.
Path: c4h_agents/agents/base_llm_continuation.py
"""

from typing import Dict, Any, List, Tuple, Optional
import time
import re
import json
import hashlib
import random
from datetime import datetime
import litellm
from litellm import completion
from c4h_agents.agents.types import LLMProvider, LogDetail
from c4h_agents.utils.logging import get_logger

logger = get_logger()

class ContinuationHandler:
    """Handles LLM response continuations with robust overlap detection and detailed logging"""

    def __init__(self, parent_agent):
        """Initialize with parent agent reference for configuration access"""
        self.parent = parent_agent
        self.model_str = parent_agent.model_str
        self.provider = parent_agent.provider
        self.temperature = parent_agent.temperature
        self.max_continuation_attempts = parent_agent.max_continuation_attempts
        self.continuation_token_buffer = parent_agent.continuation_token_buffer
        
        # Get parent's configuration and logger for proper truncation
        self.config = getattr(parent_agent, 'config', None)
        self.logger = getattr(parent_agent, 'logger', logger)
        
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
        
        # Rate limit handling
        self.rate_limit_retry_base_delay = 2.0  # Base delay in seconds
        self.rate_limit_max_retries = 5  # Maximum number of rate limit retries
        self.rate_limit_max_backoff = 60  # Maximum backoff in seconds
        
        # Position tracking for request configuration
        self._position = 0  # Current continuation position

    def get_completion_with_continuation(
            self, 
            messages: List[Dict[str, str]],
            max_attempts: Optional[int] = None
        ) -> Tuple[str, Any]:
        """
        Get completion with automatic continuation handling.
        Uses multi-level overlap detection for reliable response joining.
        Handles overload conditions and rate limits with exponential backoff.
        
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
            
            # Rate limit handling
            rate_limit_retries = 0
            rate_limit_backoff = self.rate_limit_retry_base_delay
            
            # Detect content type for specialized handling
            content_type = self._detect_content_type(messages)
            
            # Use agent's logger or fall back to module logger
            # This ensures truncation of response content in logs
            self.logger.info("llm.continuation_starting", 
                    model=self.model_str,
                    max_attempts=max_tries,
                    content_type=content_type)
            
            # Basic completion parameters
            completion_params = self._build_completion_params(messages)
                
            # Start completion loop with continuation handling
            while attempt < max_tries:
                current_messages = messages.copy()
                overlap_context = None
                overlap_lines = []
                
                # Update position counter for the retry configuration
                self._position = attempt
                
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
                                attempt=attempt,
                                last_lines="\n".join(overlap_lines[-min(10, len(overlap_lines)):]) if overlap_lines else "",
                                continuation_prompt=continuation_prompt[:500] + "..." if len(continuation_prompt) > 500 else continuation_prompt)
                    
                    # Add assistant and user messages for continuation
                    current_messages = messages.copy()
                    current_messages.append({"role": "assistant", "content": accumulated_content})
                    current_messages.append({"role": "user", "content": continuation_prompt})
                
                # Create a unique request ID for this attempt
                request_id = f"attempt_{attempt}_{int(time.time())}"
                
                # Log the request details
                logger.info("llm.continuation_request", 
                        attempt=attempt,
                        request_id=request_id,
                        message_count=len(current_messages))
                        
                # Detailed logging of the messages
                for i, msg in enumerate(current_messages):
                    role = msg.get("role", "unknown")
                    content = msg.get("content", "")
                    logger.debug(f"llm.continuation_message_{i}", 
                            role=role, 
                            content_length=len(content),
                            content_preview=content[:200] + "..." if len(content) > 200 else content)
                
                request_params = completion_params.copy()
                request_params["messages"] = current_messages
                
                try:
                    # Make the actual LLM request
                    request_start = time.time()
                    response = self._make_llm_request(request_params)
                    request_duration = time.time() - request_start

                    # Reset retry count on successful completion
                    retry_count = 0
                    rate_limit_retries = 0  # Reset rate limit retries as well
                    rate_limit_backoff = self.rate_limit_retry_base_delay
                    
                    # Log the raw response for analysis
                    logger.debug("llm.continuation_raw_response", 
                            request_id=request_id,
                            attempt=attempt,
                            response_type=type(response).__name__,
                            has_choices=hasattr(response, 'choices'),
                            choices_count=len(response.choices) if hasattr(response, 'choices') else 0,
                            first_choice=str(response.choices[0])[:500] + "..." if hasattr(response, 'choices') and response.choices else None)

                    if not hasattr(response, 'choices') or not response.choices:
                        logger.error("llm.no_response",
                                attempt=attempt,
                                request_id=request_id,
                                provider=self.provider.serialize())
                        break

                    # Extract response details for logging
                    finish_reason = getattr(response.choices[0], 'finish_reason', None)
                    has_message = hasattr(response.choices[0], 'message')
                    has_content = has_message and hasattr(response.choices[0].message, 'content')
                    content_length = len(response.choices[0].message.content) if has_content else 0
                    
                    # Log the response details
                    logger.info("llm.continuation_response", 
                            request_id=request_id,
                            attempt=attempt,
                            finish_reason=finish_reason,
                            content_length=content_length,
                            request_duration_seconds=request_duration)
                    
                    # Process response through standard interface
                    result = self.parent._process_response(response, response)
                    final_response = response
                    
                    # Extract current content from the response
                    current_content = result['response']
                    
                    # Log response preview with more details
                    if current_content:
                        current_lines = current_content.splitlines()
                        line_count = len(current_lines)
                        
                        logger.debug("llm.continuation_response_preview", 
                                    request_id=request_id,
                                    attempt=attempt,
                                    line_count=line_count,
                                    first_lines="\n".join(current_lines[:min(10, line_count)]) if line_count else "",
                                    last_lines="\n".join(current_lines[-min(10, line_count):]) if line_count else "")
                    
                    # For continuation attempts, handle joining with multi-level strategy
                    if attempt > 0:
                        # Get the explicit overlap markers
                        begin_marker = "---BEGIN_EXACT_OVERLAP---"
                        end_marker = "---END_EXACT_OVERLAP---"
                        
                        # First, look for explicit markers
                        logger.debug("llm.checking_for_markers", 
                                request_id=request_id,
                                attempt=attempt,
                                begin_marker_present=begin_marker in current_content,
                                end_marker_present=end_marker in current_content)
                                
                        cleaned_content = self._clean_overlap_markers(current_content, begin_marker, end_marker)
                        
                        # If markers found and properly cleaned, use the cleaned content
                        if cleaned_content != current_content:
                            logger.info("llm.markers_found_and_cleaned",
                                    request_id=request_id,
                                    attempt=attempt,
                                    original_length=len(current_content),
                                    cleaned_length=len(cleaned_content))
                                    
                            current_content = cleaned_content
                            self.diagnostics["exact_matches"] += 1
                            # Update the accumulated content
                            accumulated_content = accumulated_content + "\n" + current_content
                        else:
                            logger.info("llm.no_markers_trying_overlap",
                                    request_id=request_id,
                                    attempt=attempt)
                                    
                            # Try multi-level matching and log details of each strategy
                            joined_content, match_method, join_details = self._join_with_overlap(
                                accumulated_content, 
                                current_content,
                                overlap_lines,
                                content_type,
                                request_id=request_id,
                                attempt=attempt
                            )
                            
                            # Update accumulated content
                            accumulated_content = joined_content
                            
                            # Update metrics based on match method
                            self._update_match_metrics(match_method)
                            
                            logger.debug("llm.joined_content_updated",
                                    request_id=request_id,
                                    attempt=attempt,
                                    match_method=match_method,
                                    joined_length=len(joined_content))
                    else:
                        # First response, just use it directly
                        accumulated_content = current_content
                        
                        logger.debug("llm.initial_content_stored",
                                request_id=request_id,
                                content_length=len(accumulated_content))
                    
                    # Check if we need to continue
                    finish_reason = getattr(response.choices[0], 'finish_reason', None)
                    
                    if finish_reason == 'length':
                        logger.info("llm.length_limit_reached", 
                                request_id=request_id,
                                attempt=attempt,
                                accumulated_length=len(accumulated_content))
                        
                        attempt += 1
                        continue
                    else:
                        logger.info("llm.completion_finished",
                                request_id=request_id,
                                finish_reason=finish_reason,
                                continuation_count=attempt,
                                final_length=len(accumulated_content))
                        
                        break

                except litellm.RateLimitError as e:
                    # Handle rate limit errors with exponential backoff
                    error_msg = str(e)
                    
                    rate_limit_retries += 1
                    
                    if rate_limit_retries > self.rate_limit_max_retries:
                        logger.error("llm.rate_limit_max_retries_exceeded", 
                                retry_count=rate_limit_retries,
                                error=error_msg[:200])
                        raise  # Re-raise if we've tried too many times
                                
                    # Calculate backoff with jitter
                    jitter = 0.1 * rate_limit_backoff * (0.5 - random.random())
                    current_backoff = min(rate_limit_backoff + jitter, self.rate_limit_max_backoff)
                    
                    logger.warning("llm.rate_limit_backoff", 
                                request_id=request_id,
                                attempt=attempt,
                                retry_count=rate_limit_retries,
                                backoff_seconds=current_backoff,
                                error=error_msg[:200])
                    
                    # Apply exponential backoff with base 2
                    time.sleep(current_backoff)
                    rate_limit_backoff = min(rate_limit_backoff * 2, self.rate_limit_max_backoff)
                    
                    # Don't increment the attempt counter since we'll retry with the same content
                    continue
                    
                except litellm.InternalServerError as e:
                    # Handle overload errors with exponential backoff
                    error_msg = str(e)
                    
                    logger.warning("llm.server_error", 
                                request_id=request_id,
                                attempt=attempt,
                                retry_count=retry_count,
                                error=error_msg)
                    
                    self._handle_litellm_error(e, retry_count)
                    retry_count += 1
                    continue
                    
                except Exception as e:
                    error_msg = str(e)
                    error_type = type(e).__name__
                    
                    logger.error("llm.request_failed", 
                            request_id=request_id,
                            error=error_msg,
                            error_type=error_type,
                            attempt=attempt)
                    
                    raise

            # Log summary of continuations
            if attempt > 0:
                logger.info("llm.continuation_summary", 
                        total_attempts=attempt,
                        model=self.model_str, 
                        total_length=len(accumulated_content),
                        diagnostics=self.diagnostics)

            # Apply syntax cleaning as a final step for code content
            if content_type in ["code", "json_code"] and attempt > 0:
                original_length = len(accumulated_content)
                accumulated_content = self._clean_continuation_artifacts(accumulated_content, content_type)
                
                if len(accumulated_content) != original_length:
                    logger.info("llm.syntax_artifacts_cleaned",
                            content_type=content_type,
                            continuation_count=attempt)

            # Update the content in the final response
            if final_response and hasattr(final_response, 'choices') and final_response.choices:
                final_response.choices[0].message.content = accumulated_content

            # Track actual continuation count for metrics
            self.parent.metrics["continuation_attempts"] = attempt
            return accumulated_content, final_response

        except Exception as e:
            error_msg = str(e)
            error_type = type(e).__name__
            
            logger.error("llm.continuation_failed", 
                    error=error_msg, 
                    error_type=error_type)
            
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
        
        content_type = "text"  # default
        if is_code and is_json:
            content_type = "json_code"
        elif is_code:
            content_type = "code"
        elif is_json:
            content_type = "json"
        elif is_diff:
            content_type = "diff"
            
        logger.debug("llm.content_type_detected", 
                   content_type=content_type,
                   is_code=is_code, 
                   is_json=is_json, 
                   is_diff=is_diff)
            
        return content_type

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
        """
        Make the actual LLM request with rate limit handling.
        Ensures no unsupported parameters are passed to the API.
        
        Args:
            completion_params: Complete parameters for the LLM request
            
        Returns:
            LLM response object
        """
        try:
            # Get provider config but don't add unsupported parameters
            provider_config = self.parent._get_provider_config(self.provider)
            
            # Ensure retry is enabled in litellm itself
            litellm.retry = True
            
            # Set appropriate retry count based on position
            position = getattr(self, '_position', 0)
            if position > 0:
                litellm.max_retries = 5
            else:
                litellm.max_retries = 3
            
            # Configure backoff settings
            litellm.retry_wait = 2
            litellm.max_retry_wait = 60
            litellm.retry_exponential = True
                
            # Make the actual request, but ensure we don't pass unsupported params
            # Only pass standard, known parameters to the completion API
            safe_params = {
                k: v for k, v in completion_params.items() 
                if k in ['model', 'messages', 'temperature', 'max_tokens', 'top_p', 'stream']
            }
            
            # Add api_base if it's in the provider config
            if "api_base" in provider_config:
                safe_params["api_base"] = provider_config["api_base"]
                
            logger.debug("llm.making_request", 
                    retry_enabled=litellm.retry,
                    max_retries=litellm.max_retries,
                    params=list(safe_params.keys()))
                    
            response = completion(**safe_params)
            return response
            
        except litellm.RateLimitError as e:
            # Log and re-raise for our custom handler to manage
            logger.warning("llm.rate_limit_error", 
                        error=str(e)[:200])
            raise
            
        except Exception as e:
            # For other errors, just log and re-raise
            logger.error("llm.request_error", error=str(e))
            raise
        
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
        """Calculate appropriate overlap based on content type with string detection"""
        content_lines = accumulated_content.splitlines()
        
        # Adaptive overlap size based on content length and type
        if content_type in ["code", "json_code"]:
            # For code, use more lines to ensure complete syntactic blocks
            base_overlap = min(max(5, min(len(content_lines) // 3, 15)), len(content_lines))
            overlap_size = base_overlap
            
            # Check last few lines for string continuation patterns
            check_lines = min(5, len(content_lines))
            for i in range(1, check_lines + 1):
                if len(content_lines) >= i:
                    line = content_lines[-i]
                    # Check for incomplete string patterns (f-strings, quotes, etc.)
                    if (('"' in line or "'" in line) and (line.count('"') % 2 != 0 or line.count("'") % 2 != 0)) or \
                    (any(pattern in line for pattern in ["f\"", "f'", "r\"", "r'", "'''", '"""']) and 
                        not any(line.rstrip().endswith(end) for end in ['"', "'", '"""', "'''"])):
                        # Increase overlap to capture the entire string construct
                        overlap_size = min(max(15, min(len(content_lines) // 2, 30)), len(content_lines))
                        logger.debug("llm.string_construct_detected", 
                                line_content=line,
                                increasing_overlap=True, 
                                overlap_size=overlap_size)
                        break
        elif content_type in ["json", "diff"]:
            # For JSON/diff, try to include complete objects or chunks
            overlap_size = min(max(8, min(len(content_lines) // 3, 20)), len(content_lines))
        else:
            # For text, fewer lines are usually sufficient
            overlap_size = min(max(3, min(len(content_lines) // 4, 10)), len(content_lines))
        
        last_lines = content_lines[-overlap_size:]
        overlap_context = "\n".join(last_lines)
        
        logger.debug("llm.overlap_context_created", 
                content_type=content_type,
                total_lines=len(content_lines),
                overlap_lines=overlap_size)
        
        return last_lines, overlap_context

    def _create_continuation_prompt(self, overlap_context: str, content_type: str) -> str:
        """Create continuation prompt based on content type with detailed logging"""
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
            logger.debug("llm.overlap_markers_not_found", 
                      begin_marker_found=begin_marker in content,
                      end_marker_found=end_marker in content)
            return content
        
        # Find positions of markers
        begin_pos = content.find(begin_marker)
        end_pos = content.find(end_marker, begin_pos)
        
        if begin_pos >= 0 and end_pos > begin_pos:
            # Found both markers in the expected sequence
            overlap_section = content[begin_pos + len(begin_marker):end_pos].strip()
            after_marker = content[end_pos + len(end_marker):].lstrip()
            
            logger.debug("llm.overlap_markers_cleaned", 
                      begin_pos=begin_pos, 
                      end_pos=end_pos,
                      overlap_length=len(overlap_section),
                      overlap_preview=overlap_section[:100] + "..." if len(overlap_section) > 100 else overlap_section,
                      content_after_markers_length=len(after_marker),
                      content_after_preview=after_marker[:100] + "..." if len(after_marker) > 100 else after_marker)
            
            return after_marker
        
        # Markers found but not in expected sequence
        logger.warning("llm.overlap_markers_wrong_sequence",
                     begin_pos=begin_pos,
                     end_pos=end_pos,
                     content_length=len(content))
        
        return content
    
    def _clean_continuation_artifacts(self, content: str, content_type: str) -> str:
        """Fix common syntax issues at continuation boundaries"""
        if content_type not in ["code", "json_code"]:
            return content
            
        # Common Python syntax patterns that get broken across chunks
        fixes = [
            # Fix f-strings split across chunks
            (r'(\w+)=f\s*\n\s*"', r'\1=f"'),
            (r'(\w+)=f\s*\n\s*\'', r'\1=f\''),
            
            # Fix regular strings split across chunks
            (r'(\w+)="\s*\n\s*', r'\1="'),
            (r'(\w+)=\'\s*\n\s*', r'\1=\''),
            
            # Fix string concatenation with + operator
            (r'"\s*\+\s*\n\s*"', r'" + "'),
            (r'\'\s*\+\s*\n\s*\'', r'\' + \''),
            
            # Fix parentheses/brackets split across chunks
            (r'\(\s*\n\s*', r'('),
            (r'\[\s*\n\s*', r'['),
            (r'\{\s*\n\s*', r'{'),
            (r'\s*\n\s*\)', r')'),
            (r'\s*\n\s*\]', r']'),
            (r'\s*\n\s*\}', r'}')
        ]
        
        # Apply all fixes
        for pattern, replacement in fixes:
            content = re.sub(pattern, replacement, content)
        
        return content    

    def _join_with_overlap(self, previous: str, current: str, 
                         overlap_lines: List[str], content_type: str, 
                         request_id: str = "", attempt: int = 0) -> Tuple[str, str, Dict[str, Any]]:
        """
        Join content using multi-level overlap detection.
        Tries multiple strategies to find the best join point, with full diagnostics.
        
        Args:
            previous: First chunk of content
            current: Continuation chunk
            overlap_lines: Expected overlap lines from previous content
            content_type: Type of content being processed
            request_id: Optional request ID for logging
            attempt: Attempt number for logging
            
        Returns:
            Tuple of (joined_content, match_method, join_details)
        """
        join_details = {
            "previous_length": len(previous),
            "current_length": len(current),
            "overlap_lines": len(overlap_lines),
            "content_type": content_type,
            "attempt": attempt,
            "request_id": request_id,
            "strategies_tried": []
        }
        
        # Check edge cases
        if not previous or not current:
            join_details["strategy"] = "direct"
            join_details["reason"] = "Empty input"
            logger.info("llm.direct_join", 
                      request_id=request_id,
                      attempt=attempt,
                      reason="empty_input")
            return previous + current, "direct", join_details
        
        # LEVEL 1: Try exact overlap detection
        join_details["strategies_tried"].append("exact_overlap")
        overlap_text = "\n".join(overlap_lines)
        
        # Check if our expected overlap is found at the beginning of current content
        current_lines = current.splitlines()
        
        logger.debug("llm.exact_overlap_attempt", 
                   request_id=request_id,
                   attempt=attempt,
                   overlap_lines=len(overlap_lines),
                   current_lines=len(current_lines),
                   has_enough_lines=len(current_lines) >= len(overlap_lines))
                   
        if len(current_lines) >= len(overlap_lines):
            current_overlap = "\n".join(current_lines[:len(overlap_lines)])
            
            # Log comparison details for debugging
            logger.debug("llm.exact_overlap_comparison",
                       request_id=request_id,
                       attempt=attempt,
                       expected_overlap=overlap_text[:100] + "..." if len(overlap_text) > 100 else overlap_text,
                       actual_overlap=current_overlap[:100] + "..." if len(current_overlap) > 100 else current_overlap,
                       match=current_overlap == overlap_text)
            
            # Check for exact match of the overlap text
            if current_overlap == overlap_text:
                # Found exact match, join after removing overlap
                logger.info("llm.exact_overlap_match_found", 
                          request_id=request_id,
                          attempt=attempt,
                          overlap_lines=len(overlap_lines))
                
                join_details["strategy"] = "exact"
                join_details["overlap_length"] = len(overlap_text)
                join_details["removed_lines"] = len(overlap_lines)
                
                joined = previous + "\n" + "\n".join(current_lines[len(overlap_lines):])
                return joined, "exact", join_details
        
        # LEVEL 2: Try normalized hash matching (ignores whitespace differences)
        join_details["strategies_tried"].append("hash_matching")
        try:
            # Create normalized hash of expected overlap
            def normalize_for_hash(text):
                # Remove whitespace and normalize case for non-code
                normalized = ''.join(text.lower().split()) if content_type == "text" else ''.join(text.split())
                return normalized
            
            normalized_overlap = normalize_for_hash(overlap_text)
            expected_hash = hashlib.md5(normalized_overlap.encode()).hexdigest()
            
            logger.debug("llm.hash_matching_attempt",
                       request_id=request_id,
                       attempt=attempt,
                       normalized_length=len(normalized_overlap),
                       expected_hash=expected_hash[:10])
            
            # Try to find a matching section in the current content
            max_positions = min(20, len(current_lines))
            logger.debug("llm.hash_searching", 
                       request_id=request_id,
                       attempt=attempt,
                       checking_positions=max_positions)
                       
            for i in range(max_positions):  # Check first 20 positions
                if i + len(overlap_lines) <= len(current_lines):
                    window = "\n".join(current_lines[i:i+len(overlap_lines)])
                    normalized_window = normalize_for_hash(window)
                    window_hash = hashlib.md5(normalized_window.encode()).hexdigest()
                    
                    if i % 5 == 0:  # Log every 5th position to avoid excessive logging
                        logger.debug("llm.hash_check_position", 
                                   position=i, 
                                   window_hash=window_hash[:10],
                                   match=window_hash == expected_hash)
                    
                    if window_hash == expected_hash:
                        # Found hash match, join after removing overlap
                        logger.info("llm.hash_match_found", 
                                  request_id=request_id,
                                  attempt=attempt,
                                  position=i, 
                                  overlap_lines=len(overlap_lines))
                        
                        join_details["strategy"] = "hash"
                        join_details["position"] = i
                        join_details["overlap_length"] = len(window)
                        join_details["normalized_match"] = True
                        
                        joined = previous + "\n" + "\n".join(current_lines[i+len(overlap_lines):])
                        return joined, "hash", join_details
                        
            logger.info("llm.hash_matching_no_match", 
                      request_id=request_id,
                      attempt=attempt,
                      positions_checked=max_positions)
            
        except Exception as e:
            logger.warning("llm.hash_matching_failed", 
                         request_id=request_id,
                         attempt=attempt,
                         error=str(e),
                         error_type=type(e).__name__)
            
            join_details["hash_matching_error"] = str(e)
        
        # LEVEL 3: Try token-level matching for partial overlaps
        join_details["strategies_tried"].append("token_matching")
        try:
            logger.info("llm.token_matching_attempt",
                      request_id=request_id,
                      attempt=attempt)
                      
            # Find best overlap point using token-level matching
            best_point, token_match_details = self._find_best_overlap_point(
                previous, current, min_tokens=5, 
                request_id=request_id, attempt=attempt
            )
            
            join_details["token_match_details"] = token_match_details
            
            if best_point > 0:
                logger.info("llm.token_match_found", 
                          request_id=request_id,
                          attempt=attempt,
                          token_position=best_point,
                          match_length=token_match_details.get("match_length", 0))
                          
                join_details["strategy"] = "token"
                join_details["position"] = best_point
                
                joined = previous + current[best_point:]
                return joined, "token", join_details
                
            logger.info("llm.token_matching_no_match",
                      request_id=request_id,
                      attempt=attempt)
                      
        except Exception as e:
            logger.warning("llm.token_matching_failed", 
                         request_id=request_id,
                         attempt=attempt,
                         error=str(e),
                         error_type=type(e).__name__)
                         
            join_details["token_matching_error"] = str(e)

        # LEVEL 4: For complex content, attempt LLM-based joining
        if content_type in ["code", "json", "json_code", "diff"]:
            join_details["strategies_tried"].append("llm_joining")
            try:
                logger.info("llm.smart_join_attempt",
                          request_id=request_id,
                          attempt=attempt,
                          content_type=content_type)
                          
                joined_content, llm_join_details = self._llm_based_joining(
                    previous, current, content_type,
                    request_id=request_id, attempt=attempt
                )
                
                join_details["llm_join_details"] = llm_join_details
                
                if joined_content:
                    logger.info("llm.smart_join_successful",
                              request_id=request_id,
                              attempt=attempt,
                              joined_length=len(joined_content))
                              
                    join_details["strategy"] = "llm"
                    return joined_content, "llm", join_details
                    
                logger.warning("llm.smart_join_returned_empty",
                             request_id=request_id,
                             attempt=attempt)
                             
            except Exception as e:
                logger.warning("llm.smart_join_failed", 
                             request_id=request_id,
                             attempt=attempt,
                             error=str(e),
                             error_type=type(e).__name__)
                             
                join_details["llm_joining_error"] = str(e)
                
        # LEVEL 5: Fall back to syntax-aware basic joining
        join_details["strategies_tried"].append("basic_join")
        logger.warning("llm.all_overlap_strategies_failed", 
                    request_id=request_id,
                    attempt=attempt,
                    falling_back="basic_join",
                    overlap_lines=len(overlap_lines),
                    strategies_tried=join_details["strategies_tried"])
                    
        join_details["strategy"] = "fallback"
        join_details["reason"] = "all_strategies_failed"
        
        joined_content = self._basic_join(
            previous, current, 
            is_code=(content_type == "code"),
            request_id=request_id, 
            attempt=attempt
        )
        
        return joined_content, "fallback", join_details

    def _find_best_overlap_point(self, previous: str, current: str, min_tokens: int = 5,
                              request_id: str = "", attempt: int = 0) -> Tuple[int, Dict[str, Any]]:
        """
        Find best overlap point using token-level matching.
        Looks for a sequence of tokens that appear in both previous and current.
        
        Args:
            previous: First chunk of content
            current: Continuation chunk
            min_tokens: Minimum number of consecutive tokens to consider a match
            request_id: Optional request ID for logging
            attempt: Attempt number for logging
            
        Returns:
            Tuple of (position, match_details)
        """
        match_details = {
            "min_tokens": min_tokens,
            "attempt": attempt,
            "request_id": request_id,
            "matches_found": 0
        }
        
        # Get last part of previous and first part of current content
        prev_tail = previous[-1000:] if len(previous) > 1000 else previous
        curr_head = current[:1000] if len(current) > 1000 else current
        
        logger.debug("llm.token_matching_context",
                   request_id=request_id,
                   attempt=attempt,
                   prev_tail_length=len(prev_tail),
                   curr_head_length=len(curr_head))
        
        # Simple tokenization by whitespace and punctuation
        def simple_tokenize(text):
            import re
            return re.findall(r'\w+|[^\w\s]', text)
        
        prev_tokens = simple_tokenize(prev_tail)
        curr_tokens = simple_tokenize(curr_head)
        
        match_details["prev_token_count"] = len(prev_tokens)
        match_details["curr_token_count"] = len(curr_tokens)
        
        logger.debug("llm.token_counts",
                   request_id=request_id,
                   attempt=attempt,
                   prev_tokens=len(prev_tokens),
                   curr_tokens=len(curr_tokens))
        
        # Record some sample tokens for debugging
        if len(prev_tokens) > 10:
            match_details["prev_token_samples"] = prev_tokens[-10:]
        if len(curr_tokens) > 10:
            match_details["curr_token_samples"] = curr_tokens[:10]
        
        # Look for matching token sequences
        best_match_len = 0
        best_match_pos = 0
        match_positions = []  # Track all matches for detailed logging
        
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
                    
                    # Log match found
                    logger.debug("llm.token_sequence_match",
                               request_id=request_id,
                               attempt=attempt,
                               prev_pos=i,
                               curr_pos=j,
                               match_len=match_len,
                               sequence=" ".join(prev_seq))
                    
                    match_positions.append({
                        "prev_pos": i,
                        "curr_pos": j,
                        "match_len": match_len,
                        "sequence": " ".join(prev_seq)
                    })
                    
                    # Track best match
                    if match_len > best_match_len:
                        best_match_len = match_len
                        best_match_pos = j + match_len
        
        match_details["matches_found"] = len(match_positions)
        match_details["best_match_length"] = best_match_len
        match_details["match_positions"] = match_positions[:5]  # Keep only the first 5 matches to avoid log bloat
        
        # Only return a position if we found a good match
        if best_match_len >= min_tokens:
            # Calculate approximate character position
            char_pos = 0
            for i in range(best_match_pos):
                if i < len(curr_tokens):
                    char_pos += len(curr_tokens[i]) + 1  # +1 for spacing
            
            logger.info("llm.token_match_details", 
                    request_id=request_id,
                    attempt=attempt,
                    match_length=best_match_len, 
                    token_position=best_match_pos,
                    char_position=char_pos,
                    total_matches=len(match_positions))
            
            match_details["char_position"] = char_pos
            match_details["token_position"] = best_match_pos
            match_details["match_length"] = best_match_len
            
            return char_pos, match_details
        
        logger.info("llm.no_sufficient_token_match",
                  request_id=request_id,
                  attempt=attempt,
                  total_matches=len(match_positions),
                  best_match_length=best_match_len,
                  min_required=min_tokens)
        
        # No good match found
        return 0, match_details

    def _llm_based_joining(self, previous: str, current: str, content_type: str, 
                           request_id: str = "", attempt: int = 0) -> Tuple[str, Dict[str, Any]]:
        """
        Use LLM to intelligently join content when algorithmic approaches fail.
        Only used as a last resort for complex content types.
        
        Args:
            previous: First chunk of content
            current: Second chunk of content 
            content_type: Type of content being joined
            request_id: Request ID for logging
            attempt: Attempt number for logging
            
        Returns:
            Tuple of (intelligently joined content, join details)
        """
        join_details = {
            "request_id": request_id,
            "attempt": attempt,
            "content_type": content_type,
            "previous_length": len(previous),
            "current_length": len(current)
        }
        
        # Create a specialized context extraction
        prev_context = previous[-300:] if len(previous) > 300 else previous
        curr_context = current[:300] if len(current) > 300 else current
        
        join_details["prev_context_length"] = len(prev_context)
        join_details["curr_context_length"] = len(curr_context)
        
        logger.debug("llm.smart_join_context_prepared",
                   request_id=request_id,
                   attempt=attempt,
                   prev_context_length=len(prev_context),
                   curr_context_length=len(curr_context),
                   content_type=content_type)
        
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
            Also analyze the JSON structure at the join point to ensure proper syntax (brackets, commas, etc).
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
            Pay special attention to indent levels, brackets, and syntax state at the join point.
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
            
        join_details["prompt_type"] = content_type
        join_details["prompt_length"] = len(join_prompt)
        
        # Make a simple LLM call with low temperature
        try:
            logger.info("llm.smart_join_request",
                      request_id=request_id,
                      attempt=attempt)
            
            # Use minimal parameters
            join_start_time = time.time()
            response = completion(
                model=self.model_str,
                messages=[{"role": "user", "content": join_prompt}],
                temperature=0.0  # Use lower temperature for deterministic results
            )
            join_duration = time.time() - join_start_time
            
            join_details["join_duration"] = join_duration
            
            # Log the raw join response
            logger.debug("llm.smart_join_raw_response",
                       request_id=request_id,
                       attempt=attempt,
                       join_duration=join_duration,
                       has_choices=hasattr(response, 'choices'),
                       choices_count=len(response.choices) if hasattr(response, 'choices') else 0)
            
            # Process the result
            if not hasattr(response, 'choices') or not response.choices:
                logger.error("llm.smart_join_no_response",
                          request_id=request_id,
                          attempt=attempt)
                
                join_details["error"] = "No response from LLM"
                join_details["fallback"] = "basic_join"
                
                return previous + "\n" + current, join_details
                
            joined_content = response.choices[0].message.content
            join_details["joined_raw_length"] = len(joined_content)
            
            # Extract code block if present
            if "```" in joined_content:
                logger.debug("llm.smart_join_code_block_detected",
                           request_id=request_id,
                           attempt=attempt)
                
                # Extract code from inside code blocks
                matches = re.findall(r'```(?:\w*\n)?([\s\S]*?)```', joined_content)
                if matches:
                    pre_extraction_length = len(joined_content)
                    joined_content = matches[0]
                    
                    logger.info("llm.smart_join_code_extracted",
                              request_id=request_id,
                              attempt=attempt,
                              before_length=pre_extraction_length,
                              after_length=len(joined_content))
                    
                    join_details["code_extracted"] = True
                    join_details["before_extraction"] = pre_extraction_length
                    join_details["after_extraction"] = len(joined_content)
            
            # If the result is suspiciously short, fall back
            expected_length = (len(previous) + len(current)) * 0.8
            if len(joined_content) < expected_length:
                logger.warning("llm.suspicious_join_result", 
                             request_id=request_id,
                             attempt=attempt,
                             expected_len=int(expected_length),
                             actual_len=len(joined_content),
                             ratio=len(joined_content) / (len(previous) + len(current)))
                
                join_details["error"] = "Result too short"
                join_details["fallback"] = "basic_join"
                join_details["expected_length"] = int(expected_length)
                join_details["actual_length"] = len(joined_content)
                join_details["ratio"] = len(joined_content) / (len(previous) + len(current))
                
                return previous + "\n" + current, join_details
            
            join_details["joined_length"] = len(joined_content)
            join_details["success"] = True
            
            logger.info("llm.smart_join_success", 
                      request_id=request_id,
                      attempt=attempt,
                      joined_length=len(joined_content),
                      join_duration=join_duration)
                
            return joined_content, join_details
            
        except Exception as e:
            error_msg = str(e)
            error_type = type(e).__name__
            
            logger.error("llm.smart_join_failed", 
                       request_id=request_id,
                       attempt=attempt,
                       error=error_msg,
                       error_type=error_type)
            
            join_details["error"] = error_msg
            join_details["error_type"] = error_type
            join_details["fallback"] = "basic_join"
            
            # Fall back to basic joining on error
            return previous + "\n" + current, join_details

    def _basic_join(self, previous: str, current: str, is_code: bool = False,
                      request_id: str = "", attempt: int = 0) -> str:
        """
        Join content with basic cleaning and syntax awareness.
        Handles common formatting and indentation issues at join point.
        
        Args:
            previous: First chunk of content
            current: Continuation chunk
            is_code: Whether content is code (for special handling)
            request_id: Request ID for logging
            attempt: Attempt number for logging
            
        Returns:
            Joined content with basic syntax fixes
        """
        # Clean up whitespace at the join point
        previous = previous.rstrip()
        current = current.lstrip()
        
        logger.info("llm.basic_join_attempt",
                  request_id=request_id,
                  attempt=attempt,
                  is_code=is_code,
                  prev_end=previous[-20:] if len(previous) >= 20 else previous,
                  curr_start=current[:20] if len(current) >= 20 else current)
        
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
                    request_id=request_id,
                    attempt=attempt,
                    open_braces=open_braces,
                    open_brackets=open_brackets,
                    open_parens=open_parens,
                    in_string=in_string,
                    ends_with_continuation=ends_with_continuation)
            
            # Handle specific code patterns
            if open_braces > 0 and current.lstrip().startswith("}"):
                # Already have closing brace at start of continuation
                logger.info("llm.join_brace_match", 
                          request_id=request_id,
                          attempt=attempt,
                          open_braces=open_braces)
                return previous + "\n" + current
            
            if open_brackets > 0 and current.lstrip().startswith("]"):
                # Already have closing bracket at start of continuation
                logger.info("llm.join_bracket_match", 
                          request_id=request_id,
                          attempt=attempt,
                          open_brackets=open_brackets)
                return previous + "\n" + current
            
            if open_parens > 0 and current.lstrip().startswith(")"):
                # Already have closing paren at start of continuation
                logger.info("llm.join_paren_match", 
                          request_id=request_id,
                          attempt=attempt,
                          open_parens=open_parens)
                return previous + "\n" + current
            
            # Check for function/class context continuations
            if previous.rstrip().endswith(":") or previous.rstrip().endswith("{"):
                # Block starter, ensure newline before continuation
                logger.info("llm.join_block_starter", 
                          request_id=request_id,
                          attempt=attempt,
                          ends_with=previous[-1])
                return previous + "\n" + current
        
        # Handle JSON special cases
        if previous.rstrip().endswith(",") and current.lstrip().startswith(","):
            # Remove duplicate comma
            logger.info("llm.join_duplicate_comma", 
                      request_id=request_id,
                      attempt=attempt)
            current = current[1:].lstrip()
        
        # Default joining with newline to maintain readability
        logger.info("llm.basic_join_complete", 
                  request_id=request_id,
                  attempt=attempt,
                  joined_length=len(previous) + len(current) + 1)
        
        return previous + "\n" + current


