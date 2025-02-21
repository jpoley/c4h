"""
Path: c4h_agents/agents/base_lineage.py
Robust lineage tracking implementation leveraging existing workflow event storage.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
from pathlib import Path
import json
import uuid
import structlog
import os
import traceback

# Try importing OpenLineage, but don't fail if it's not available
try:
    from openlineage.client import OpenLineageClient, set_producer
    from openlineage.client.run import RunEvent, RunState, InputDataset, OutputDataset
    from openlineage.client.facet import ParentRunFacet, DocumentationJobFacet
    OPENLINEAGE_AVAILABLE = True
except ImportError:
    OPENLINEAGE_AVAILABLE = False

from c4h_agents.agents.types import LLMMessages

logger = structlog.get_logger()

@dataclass
class LineageEvent:
    """Complete lineage event for LLM interaction"""
    input_context: Dict[str, Any]
    messages: LLMMessages
    raw_output: Any
    metrics: Optional[Dict] = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    parent_run_id: Optional[str] = None
    error: Optional[str] = None

class BaseLineage:
    """OpenLineage tracking implementation using existing workflow event storage"""

    def __init__(self, namespace: str, agent_name: str, config: Dict[str, Any]):
        """Initialize lineage tracking"""
        self.namespace = namespace
        self.agent_name = agent_name
        self.run_id = str(uuid.uuid4())
        
        # Extract lineage config with proper fallbacks
        runtime_config = config.get('runtime', {})
        self.config = runtime_config.get('lineage', {})
        
        # Use workflow storage config as fallback
        workflow_config = runtime_config.get('workflow', {}).get('storage', {})
        
        # Determine if lineage is enabled
        self.enabled = self.config.get('enabled', False)
        
        # Early exit if not enabled
        if not self.enabled:
            logger.info("lineage.disabled", agent=agent_name)
            return
            
        # Configure backend with robust error handling
        self.client = None
        self.lineage_dir = None
        
        try:
            backend = self.config.get('backend', {})
            backend_type = backend.get('type', 'file')
            
            if backend_type == 'marquez' and OPENLINEAGE_AVAILABLE:
                try:
                    marquez_url = backend.get('url')
                    if not marquez_url:
                        logger.error("lineage.marquez_url_missing")
                        self.enabled = False
                        return
                    self.client = OpenLineageClient(url=marquez_url)
                    logger.info("lineage.marquez_initialized", url=marquez_url)
                except Exception as e:
                    logger.error("lineage.marquez_init_failed", error=str(e))
                    self.enabled = False
                    return
            else:
                # Use file-based storage, preferring lineage path but falling back to workflow storage
                try:
                    # Determine storage path - prefer lineage config but fall back to workflow storage
                    lineage_path = (
                        backend.get('path') or 
                        workflow_config.get('root_dir') or 
                        'workspaces/lineage'
                    )
                    self.lineage_dir = Path(lineage_path)
                    
                    # Ensure directory exists and is writable
                    self.lineage_dir.mkdir(parents=True, exist_ok=True)
                    if not os.access(self.lineage_dir, os.W_OK):
                        logger.error("lineage.dir_not_writable", path=str(self.lineage_dir))
                        self.enabled = False
                        return
                        
                    # Create date-based directory structure - reuse workflow pattern
                    date_dir = datetime.now().strftime('%Y%m%d')
                    self.lineage_dir = self.lineage_dir / date_dir
                    self.lineage_dir.mkdir(parents=True, exist_ok=True)
                    
                    logger.info("lineage.file_storage_initialized", 
                              path=str(self.lineage_dir))
                    
                except Exception as e:
                    logger.error("lineage.file_backend_failed", 
                                error=str(e),
                                traceback=traceback.format_exc())
                    self.enabled = False
                    return
                    
            # Set producer information if using OpenLineage
            if OPENLINEAGE_AVAILABLE:
                try:
                    set_producer('c4h_agents', agent_name)
                except Exception as e:
                    logger.warning("lineage.producer_set_failed", error=str(e))
            
            logger.info("lineage.initialized",
                        namespace=namespace,
                        agent=agent_name,
                        run_id=self.run_id,
                        backend_type=backend.get('type', 'file'),
                        enabled=self.enabled)
                        
        except Exception as e:
            logger.error("lineage.init_failed", 
                        error=str(e),
                        traceback=traceback.format_exc())
            self.enabled = False

    def track_llm_interaction(self,
                             context: Dict[str, Any],
                             messages: LLMMessages,
                             response: Any,
                             metrics: Optional[Dict] = None) -> None:
        """Track complete LLM interaction"""
        if not self.enabled:
            logger.debug("lineage.tracking_skipped", enabled=False)
            return
            
        try:
            # Build event data
            event = LineageEvent(
                input_context=context,
                messages=messages,
                raw_output=response,
                metrics=metrics,
                parent_run_id=context.get('workflow_run_id')
            )
            
            # Route to appropriate backend
            if self.client:
                self._emit_marquez_event(event)
            else:
                self._write_file_event(event)
                
        except Exception as e:
            error_details = {
                "error": str(e),
                "agent": self.agent_name,
                "enabled": self.enabled,
                "has_client": bool(self.client),
                "lineage_dir": str(self.lineage_dir) if self.lineage_dir else None
            }
            logger.error("lineage.track_failed", **error_details)
            
            # Only raise if configured to do so
            if not self.config.get('error_handling', {}).get('ignore_failures', True):
                raise

    def _emit_marquez_event(self, event: LineageEvent) -> None:
        """Emit event to Marquez"""
        if not OPENLINEAGE_AVAILABLE or not self.client:
            logger.warning("lineage.marquez_not_available")
            return
            
        try:
            ol_event = RunEvent(
                eventType=RunState.COMPLETE,
                eventTime=event.timestamp.isoformat(),
                run={
                    "runId": self.run_id,
                    "facets": {
                        "parent": ParentRunFacet(run_id=event.parent_run_id) if event.parent_run_id else {},
                        "documentation": DocumentationJobFacet(description=f"Agent: {self.agent_name}")
                    }
                },
                job={
                    "namespace": self.namespace,
                    "name": self.agent_name
                },
                inputs=[InputDataset(
                    namespace=self.namespace,
                    name=f"{self.agent_name}_input",
                    facets={"context": event.input_context}
                )],
                outputs=[OutputDataset(
                    namespace=self.namespace,
                    name=f"{self.agent_name}_output",
                    facets={"metrics": event.metrics or {}}
                )]
            )
            self.client.emit(ol_event)
            logger.info("lineage.marquez_event_emitted")
        except Exception as e:
            logger.error("lineage.marquez_event_failed", error=str(e))

    def _write_file_event(self, event: LineageEvent) -> None:
        """Write event to file system reusing workflow storage pattern"""
        if not self.enabled or not self.lineage_dir:
            logger.debug("lineage.file_write_skipped", enabled=self.enabled)
            return
            
        try:
            # Create run directory using workflow pattern
            run_dir = self.lineage_dir / self.run_id
            run_dir.mkdir(parents=True, exist_ok=True)
            events_dir = run_dir / "events"
            events_dir.mkdir(exist_ok=True)
            
            # Generate unique event filename
            event_id = uuid.uuid4()
            event_file = events_dir / f"{event_id}.json"
            temp_file = events_dir / f"{event_id}.tmp"
            
            # Write event data atomically using temporary file
            with open(temp_file, 'w') as f:
                json.dump({
                    "timestamp": event.timestamp.isoformat(),
                    "agent": self.agent_name,
                    "input_context": event.input_context,
                    "messages": event.messages.to_dict(),
                    "metrics": event.metrics,
                    "parent_run_id": event.parent_run_id,
                    "error": event.error
                }, f, indent=2)
                    
            # Atomic rename to final filename
            temp_file.rename(event_file)
            
            logger.info("lineage.event_saved", 
                       path=str(event_file),
                       agent=self.agent_name,
                       run_id=self.run_id)
                
        except Exception as e:
            error_details = {
                "error": str(e),
                "lineage_dir": str(self.lineage_dir) if self.lineage_dir else None,
                "agent": self.agent_name,
                "run_id": self.run_id
            }
            logger.error("lineage.write_failed", **error_details)
            
            # Attempt to log error but don't propagate
            try:
                errors_dir = Path('workspaces/lineage/errors')
                errors_dir.mkdir(parents=True, exist_ok=True)
                error_file = errors_dir / f"error_{uuid.uuid4()}.json"
                with open(error_file, 'w') as f:
                    json.dump(error_details, f, indent=2)
            except:
                pass # Swallow errors in error logging