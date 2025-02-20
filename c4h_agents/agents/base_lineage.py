"""
Path: c4h_agents/agents/base_lineage.py
Robust implementation with better error handling and directory creation
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
    """OpenLineage tracking implementation with robust error handling"""

    def __init__(self, namespace: str, agent_name: str, config: Dict[str, Any]):
        """Initialize lineage tracking"""
        self.namespace = namespace
        self.agent_name = agent_name
        self.run_id = str(uuid.uuid4())
        self.config = config.get('runtime', {}).get('lineage', {})
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
                # Use file-based storage with robust path handling
                try:
                    lineage_path = backend.get('path', 'workspaces/lineage')
                    self.lineage_dir = Path(lineage_path)
                    
                    # First check if path exists or can be created
                    if not self.lineage_dir.exists():
                        try:
                            self.lineage_dir.mkdir(parents=True, exist_ok=True)
                            logger.info("lineage.dir_created", path=str(self.lineage_dir))
                        except Exception as e:
                            logger.error("lineage.dir_creation_failed", 
                                        path=str(self.lineage_dir),
                                        error=str(e))
                            self.enabled = False
                            return
                            
                    # Check if directory is writable
                    if not os.access(self.lineage_dir, os.W_OK):
                        logger.error("lineage.dir_not_writable", 
                                    path=str(self.lineage_dir))
                        self.enabled = False
                        return
                        
                    # Create date-based directory 
                    self.lineage_dir = self.lineage_dir / datetime.now().strftime('%Y%m%d')
                    self.lineage_dir.mkdir(parents=True, exist_ok=True)
                    
                    # Validate run directory can be created
                    test_run_dir = self.lineage_dir / "test_run"
                    test_run_dir.mkdir(exist_ok=True)
                    test_file_path = test_run_dir / "test.txt"
                    with open(test_file_path, 'w') as f:
                        f.write("test")
                    if test_file_path.exists():
                        test_file_path.unlink()
                        logger.info("lineage.file_test_succeeded")
                    else:
                        logger.error("lineage.file_test_failed")
                        self.enabled = False
                        return
                        
                except Exception as e:
                    logger.error("lineage.file_backend_failed", 
                                error=str(e),
                                traceback=traceback.format_exc())
                    self.enabled = False
                    return
                    
            # Set producer information
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
            event = LineageEvent(
                input_context=context,
                messages=messages,
                raw_output=response,
                metrics=metrics,
                parent_run_id=context.get('workflow_run_id')
            )
            
            if self.client:
                self._emit_marquez_event(event)
            else:
                self._write_file_event(event)
                
        except Exception as e:
            if not self.config.get('error_handling', {}).get('ignore_failures', True):
                raise
            logger.error("lineage.track_failed", 
                        error=str(e),
                        traceback=traceback.format_exc())

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
            logger.info("lineage.marquez_event_emitted", event_type=RunState.COMPLETE)
        except Exception as e:
            logger.error("lineage.marquez_event_failed", error=str(e))

    def _write_file_event(self, event: Any) -> None:
        """Write event to file system with robust error handling"""
        if not self.enabled or not self.lineage_dir:
            logger.debug("lineage.file_write_skipped", enabled=self.enabled)
            return
            
        try:
            # Create run and event directories
            event_dir = self.lineage_dir / self.run_id / "events"
            event_dir.mkdir(parents=True, exist_ok=True)
            
            # Generate unique event filename
            event_id = uuid.uuid4()
            event_file = event_dir / f"{event_id}.json"
            temp_file = event_dir / f"{event_id}.tmp"
            
            # Write event data to temporary file first
            with open(temp_file, 'w') as f:
                if isinstance(event, LineageEvent):
                    json.dump({
                        "timestamp": event.timestamp.isoformat(),
                        "agent": self.agent_name,
                        "input_context": event.input_context,
                        "messages": event.messages.to_dict(),
                        "metrics": event.metrics,
                        "parent_run_id": event.parent_run_id,
                        "error": event.error
                    }, f, indent=2)
                else:
                    # Handle RunEvent objects
                    try:
                        json.dump(event.to_dict(), f, indent=2)
                    except:
                        # Fallback for non-serializable objects
                        json.dump({
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "agent": self.agent_name,
                            "event_type": str(type(event)),
                            "summary": str(event)
                        }, f, indent=2)
                    
            # Atomic rename to final filename
            temp_file.rename(event_file)
            
            # Log success
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
            
            # Attempt to log the error to a special errors directory
            try:
                errors_dir = Path('workspaces/lineage/errors')
                errors_dir.mkdir(parents=True, exist_ok=True)
                error_file = errors_dir / f"error_{uuid.uuid4()}.json"
                with open(error_file, 'w') as f:
                    json.dump(error_details, f, indent=2)
            except:
                # Last resort - don't raise exceptions here
                pass