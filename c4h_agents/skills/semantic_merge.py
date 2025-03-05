"""
Semantic merge implementation for code modifications.
Path: c4h_agents/skills/semantic_merge.py
"""

from typing import Dict, Any, Optional
from pathlib import Path
from c4h_agents.agents.base_agent import BaseAgent, AgentResponse 
from c4h_agents.config import locate_config
from c4h_agents.utils.logging import get_logger

logger = get_logger()

class SemanticMerge(BaseAgent):
    """Handles merging of code modifications."""
    
    def __init__(self, config: Dict[str, Any] = None):
        """Initialize merger with configuration."""
        super().__init__(config=config)
        
        # Get merge-specific configs
        merge_config = locate_config(self.config or {}, self._get_agent_name())
        merge_config = merge_config.get('merge_config', {})
        self.preserve_formatting = merge_config.get('preserve_formatting', True)
        self.allow_partial = merge_config.get('allow_partial', False)
        
        logger.info("semantic_merge.initialized")

    def _get_agent_name(self) -> str:
        """Get agent name for config lookup"""
        return "semantic_merge"

    def _get_original_content(self, file_path: str) -> Optional[str]:
        """Read original file content if it exists"""
        try:
            # If self.project is defined, use its path resolution
            if self.project:
                path = self.project.resolve_path(file_path)
            else:
                # Otherwise use direct path
                path = Path(file_path)
                
            # Check if path exists and is a file
            if path.is_file():
                try:
                    content = path.read_text()
                    logger.debug("merge.read_original_success", 
                                file_path=str(path), 
                                content_length=len(content))
                    return content
                except Exception as e:
                    logger.error("merge.read_file_error", 
                                file_path=str(path), 
                                error=str(e))
                    return None
            
            logger.debug("merge.file_not_found", file_path=str(path))
            return None
            
        except Exception as e:
            logger.error("merge.read_original_failed", error=str(e))
            return None

    def _format_request(self, context: Dict[str, Any]) -> str:
        """Format merge request using merge prompt template"""
        try:
            # Get merge prompt template
            merge_template = self._get_prompt('merge')
            
            # Extract key merge components
            original = context.get('original', '')
            diff = context.get('diff', '')
            
            # Log merge components at debug level
            logger.debug("merge.request_prepared",
                        has_original=bool(original),
                        diff_lines=len(diff.split('\n')) if diff else 0)
            
            return merge_template.format(
                original=original,
                diff=diff
            )
            
        except Exception as e:
            logger.error("merge.format_failed", error=str(e))
            raise

    def process(self, context: Dict[str, Any]) -> AgentResponse:
        """Process merge by passing entire context to LLM"""
        logger.info("merge.starting")

        try:
            # Validate required inputs
            if not isinstance(context, dict):
                return AgentResponse(
                    success=False,
                    error="Invalid context format",
                    data={}
                )

            file_path = context.get('file_path')
            diff = context.get('diff')
            content = context.get('content')
            
            if not file_path:
                return AgentResponse(
                    success=False,
                    error="Missing required file_path",
                    data=context
                )
            
            # Handle content-only create operations directly
            if context.get('type') == 'create' and content and not diff:
                logger.info("merge.direct_content", 
                           file_path=file_path, 
                           content_length=len(content))
                return AgentResponse(
                    success=True,
                    data={
                        "response": content,
                        "raw_output": content
                    }
                )
                
            # Require diff for non-create operations
            if not diff and not context.get('type') == 'create':
                return AgentResponse(
                    success=False,
                    error=f"Missing required diff for {file_path}",
                    data=context
                )

            # First try to get original from context
            original = context.get('original')
            
            # If not in context but file exists, read it directly
            if not original:
                # Try to read file content directly
                file_content = self._get_original_content(file_path)
                if file_content:
                    original = file_content
                    logger.info("merge.file_content_read", 
                               file_path=file_path, 
                               content_length=len(file_content))
            
            # For non-existent files on create operations, use empty string
            if not original and context.get('type') == 'create':
                original = ""
                logger.info("merge.create_operation", 
                           file_path=file_path, 
                           using_empty_original=True)
            # For other operations, require content unless allow_partial is True
            elif not original and not self.allow_partial:
                return AgentResponse(
                    success=False,
                    error=f"Original file not found: {file_path}",
                    data=context
                )
            
            if not original:
                logger.warning("merge.missing_original", 
                             file=file_path,
                             proceeding=True)

            # Prepare merge context with complete information
            merge_context = {
                **context,
                'original': original or '',  # Empty string for new files
                'file_path': str(file_path)
            }

            # Let LLM handle merge with complete context
            result = super().process(merge_context)
            
            if not result.success:
                logger.warning("merge.failed", error=result.error)
                return result

            return AgentResponse(
                success=True,
                data={
                    "response": result.data.get("response", ""),
                    "raw_output": result.data.get("raw_output")
                }
            )

        except Exception as e:
            logger.error("merge.failed", error=str(e))
            return AgentResponse(success=False, data={}, error=str(e))