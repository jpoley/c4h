"""
Shared utilities for handling markdown code blocks.
Path: src/skills/shared/markdown_utils.py
"""

from typing import Dict, Any, Optional
import structlog
from dataclasses import dataclass

logger = structlog.get_logger(__name__)

@dataclass
class CodeBlock:
    """Represents a parsed code block"""
    content: str
    language: Optional[str] = None
    raw: str = ""

def extract_code_block(content: str) -> CodeBlock:
    """
    Extract code from markdown code blocks.
    Handles both fenced and inline code blocks.
    
    Args:
        content: String potentially containing markdown code blocks
        
    Returns:
        CodeBlock with extracted content and metadata
    """
    try:
        content = content.strip()
        
        # Track original for logging
        raw = content
        language = None
        
        # Handle fenced code blocks
        if content.startswith('```'):
            lines = content.split('\n')
            
            # Extract language if specified
            first_line = lines[0][3:].strip()
            if first_line:
                language = first_line
                lines = lines[1:]
            else:
                lines = lines[1:]
                
            # Remove closing fence
            if lines[-1].strip() == '```':
                lines = lines[:-1]
                
            content = '\n'.join(lines)
            
        # Strip any remaining backticks
        content = content.strip('`')
        
        logger.debug("markdown.extracted_code",
                    original_length=len(raw),
                    cleaned_length=len(content),
                    language=language,
                    content_preview=content[:100] if content else None)
                    
        return CodeBlock(
            content=content,
            language=language,
            raw=raw
        )
        
    except Exception as e:
        logger.error("markdown.extraction_failed", error=str(e))
        return CodeBlock(content=content, raw=content)

def is_code_block(content: str) -> bool:
    """
    Check if content appears to be a markdown code block.
    
    Args:
        content: String to check
        
    Returns:
        bool indicating if content is a code block
    """
    content = content.strip()
    return (
        content.startswith('```') and content.endswith('```')
        or content.strip('`') != content
    )