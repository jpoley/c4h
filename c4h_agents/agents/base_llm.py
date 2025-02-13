"""
LLM interaction layer providing completion and response handling.
Path: c4h_agents/agents/base_llm.py
"""

from typing import Dict, Any, List, Tuple, Optional
import structlog
import time
from datetime import datetime
import litellm
from litellm import completion
from c4h_agents.agents.types import LLMProvider, LogDetail  # Added missing imports

logger = structlog.get_logger()

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
            
            if "api_base" in provider_config:
                completion_params["api_base"] = provider_config["api_base"]

            while attempt < max_tries:
                if attempt > 0:
                    logger.info("llm.continuation_attempt",
                            attempt=attempt,
                            messages_count=len(messages))
                
                try:
                    response = completion(**completion_params)

                    # Reset retry count on successful completion
                    retry_count = 0

                    if not response or not response.choices:
                        logger.error("llm.no_response",
                                attempt=attempt,
                                provider=self.provider.serialize())
                        break

                    # Process response through standard interface
                    result = self._process_response(response, response)
                    final_response = response
                    accumulated_content += result['response']
                    
                    finish_reason = getattr(response.choices[0], 'finish_reason', None)
                        
                    if finish_reason == 'length':
                        logger.info("llm.length_limit_reached", attempt=attempt)
                        messages.append({"role": "assistant", "content": result['response']})
                        messages.append({
                            "role": "user", 
                            "content": "Continue exactly from where you left off, maintaining exact format and indentation. Do not repeat any content."
                        })
                        completion_params["messages"] = messages
                        attempt += 1
                        continue
                    else:
                        logger.info("llm.completion_finished",
                                finish_reason=finish_reason,
                                continuation_count=attempt)
                        break

                except litellm.InternalServerError as e:
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

            if final_response and final_response.choices:
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
        """Configure litellm with provider settings"""
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