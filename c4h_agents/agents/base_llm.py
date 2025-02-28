"""
LLM interaction layer providing completion and response handling.
Path: c4h_agents/agents/base_llm.py
"""

from typing import Dict, Any, List, Tuple, Optional
import time
from datetime import datetime
import litellm
from litellm import completion
from c4h_agents.agents.types import LLMProvider, LogDetail  # Added missing imports
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
            Handles overload conditions with exponential backoff.
            Supports extended thinking for Claude 3.7 Sonnet.
            """
            try:
                attempt = 0
                max_tries = max_attempts or self.max_continuation_attempts
                accumulated_content = ""
                final_response = None
                retry_count = 0
                max_retries = 5  # Max retries for overload conditions
                
                # Get provider config
                provider_config = self._get_provider_config(self.provider)
                
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

                # Check if we're dealing with JSON
                is_json_context = any(
                    "json" in msg.get("content", "").lower() or
                    msg.get("content", "").strip().startswith("{") or 
                    msg.get("content", "").strip().startswith("[") 
                    for msg in messages if msg.get("role") == "user"
                )

                while attempt < max_tries:
                    if attempt > 0:
                        logger.info("llm.continuation_attempt",
                                attempt=attempt,
                                messages_count=len(messages))
                    
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
                        
                        # For JSON responses, handle joining carefully
                        current_content = result['response']
                        if is_json_context and attempt > 0:
                            # If this appears to be JSON, ensure clean joining
                            if accumulated_content.rstrip().endswith(",") and current_content.lstrip().startswith(","):
                                # Remove duplicate comma
                                accumulated_content = accumulated_content.rstrip()
                                current_content = current_content.lstrip()[1:].lstrip()
                        
                        accumulated_content += current_content
                        
                        finish_reason = getattr(response.choices[0], 'finish_reason', None)
                            
                        if finish_reason == 'length':
                            logger.info("llm.length_limit_reached", attempt=attempt)
                            messages.append({"role": "assistant", "content": result['response']})
                            
                            # Choose appropriate continuation prompt
                            if is_json_context:
                                continuation_prompt = (
                                    "Continue the JSON response exactly from where you left off. "
                                    "Make sure your response starts with a valid JSON fragment that "
                                    "will connect seamlessly with what you've already provided. "
                                    "Do not repeat any content."
                                )
                            else:
                                continuation_prompt = (
                                    "Continue exactly from where you left off, maintaining exact format and indentation. "
                                    "Do not repeat any content."
                                )
                            
                            messages.append({"role": "user", "content": continuation_prompt})
                            completion_params["messages"] = messages
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

                if final_response and hasattr(final_response, 'choices') and final_response.choices:
                    final_response.choices[0].message.content = accumulated_content

                self.metrics["continuation_attempts"] = attempt + 1
                return accumulated_content, final_response

            except Exception as e:
                logger.error("llm.continuation_failed", error=str(e))
                raise

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
            if self._should_log('DEBUG'):
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