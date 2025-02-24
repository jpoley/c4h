"""
Lineage tracking implementation leveraging existing workflow event storage.
Path: c4h_agents/agents/base_lineage.py
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
from pathlib import Path
import json
import uuid
import structlog
import os

# Try importing OpenLineage, but don't fail if it's not available
try:
    from openlineage.client import OpenLineageClient, set_producer
    from openlineage.client.run import RunEvent, RunState, InputDataset, OutputDataset
    from openlineage.client.facet import ParentRunFacet, DocumentationJobFacet
    OPENLINEAGE_AVAILABLE = True
except ImportError:
    OPENLINEAGE_AVAILABLE = False

from c4h_agents.agents.types import LLMMessages
from c4h_agents.config import locate_config, get_value

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
    """OpenLineage tracking implementation"""
    def __init__(self, namespace: str, agent_name: str, config: Dict[str, Any]):
        """Initialize lineage tracking"""
        self.namespace = namespace  # Store namespace
        self.agent_name = agent_name
        self.enabled = False
        
        # Get lineage config first
        lineage_config = locate_config(config or {}, "lineage")
        if not lineage_config:
            logger.info(f"{agent_name}.lineage_disabled", reason="no_config")
            return
            
        # Prioritize runid from system namespace, then check hierarchical paths using a more robust approach
        self.run_id = self._extract_run_id(config)
        
        # Log a warning if we're still generating a UUID
        if self.run_id.startswith("generated:"):
            logger.warning("lineage.missing_run_id", agent=agent_name, generated_id=self.run_id[10:])
        else:
            logger.debug("lineage.using_run_id", agent=agent_name, run_id=self.run_id)

        # Set minimal defaults for lineage configuration
        self.config = {
            "enabled": lineage_config.get("enabled", False),
            "namespace": lineage_config.get("namespace", self.namespace),
            "backend": lineage_config.get("backend", {
                "type": "file",
                "path": "workspaces/lineage"
            })
        }
        
        self.enabled = self.config["enabled"]
        if not self.enabled:
            logger.info(f"{agent_name}.lineage_disabled", reason="not_enabled")
            return

        # Setup storage directory
        try:
            base_dir = Path(self.config["backend"]["path"])
            date_str = datetime.now().strftime('%Y%m%d')
            
            # Extract only the UUID part if it has a prefix
            clean_run_id = self.run_id[10:] if self.run_id.startswith("generated:") else self.run_id
            
            self.lineage_dir = base_dir / date_str / clean_run_id
            self.lineage_dir.mkdir(parents=True, exist_ok=True)
            
            # Create directories under run_id
            (self.lineage_dir / "events").mkdir(exist_ok=True)
            (self.lineage_dir / "errors").mkdir(exist_ok=True)
            
            logger.info("lineage.storage_initialized", path=str(self.lineage_dir), run_id=clean_run_id)
        except Exception as e:
            logger.error("lineage.storage_init_failed", error=str(e))
            self.enabled = False

    def _extract_run_id(self, config: Dict[str, Any]) -> str:
        """
        Extract run ID using a hierarchical approach with fallbacks.
        Returns a string with a "generated:" prefix if we had to generate one.
        """
        # First check system namespace (highest priority)
        run_id = get_value(config, "system/runid")
        if run_id:
            return str(run_id)
            
        # Then check context parameters (second priority)
        if isinstance(config.get('workflow_run_id'), (str, uuid.UUID)):
            return str(config.get('workflow_run_id'))
            
        # Then check runtime configuration (third priority)
        runtime = config.get('runtime', {})
        if isinstance(runtime.get('workflow_run_id'), (str, uuid.UUID)):
            return str(runtime.get('workflow_run_id'))
        if isinstance(runtime.get('run_id'), (str, uuid.UUID)):
            return str(runtime.get('run_id'))
        
        # Finally fallback to workflow.id if present
        workflow = runtime.get('workflow', {})
        if isinstance(workflow.get('id'), (str, uuid.UUID)):
            return str(workflow.get('id'))
            
        # Generate a UUID as last resort, but prefix it to indicate it was generated
        return f"generated:{uuid.uuid4()}"

    def _serialize_value(self, value: Any) -> Any:
        """Serialize a single value with type handling"""
        if isinstance(value, (int, float, str, bool, type(None))):
            return value
        elif isinstance(value, Path):
            return str(value)
        elif isinstance(value, datetime):
            return value.isoformat()
        elif isinstance(value, (list, tuple)):
            return [self._serialize_value(v) for v in value]
        elif isinstance(value, dict):
            return {k: self._serialize_value(v) for k, v in value.items()}
        elif hasattr(value, 'to_dict'):
            return value.to_dict()
        else:
            return str(value)

    def _write_file_event(self, event: LineageEvent) -> None:
        """Write event to file system with basic serialization"""
        if not self.enabled or not self.lineage_dir:
            return
            
        try:
            event_id = uuid.uuid4()
            events_dir = self.lineage_dir / "events"
            event_file = events_dir / f"{event_id}.json"
            temp_file = events_dir / f"{event_id}.tmp"
            
            event_data = {
                "timestamp": event.timestamp.isoformat(),
                "agent": self.agent_name,
                "input_context": str(event.input_context),
                "messages": str(event.messages),
                "metrics": str(event.metrics),
                "run_id": self.run_id,
                "parent_run_id": event.parent_run_id,
                "error": event.error
            }

            with open(temp_file, 'w') as f:
                json.dump(event_data, f, indent=2)
                    
            temp_file.rename(event_file)
            
            logger.info("lineage.event_saved", path=str(event_file), agent=self.agent_name, run_id=self.run_id)
                
        except Exception as e:
            logger.error("lineage.write_failed", error=str(e), lineage_dir=str(self.lineage_dir), agent=self.agent_name)

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
            # Extract workflow_run_id from context if available
            parent_run_id = None
            if isinstance(context, dict):
                parent_run_id = context.get('workflow_run_id')
            
            event = LineageEvent(
                input_context=context,
                messages=messages,
                raw_output=response,
                metrics=metrics,
                parent_run_id=parent_run_id
            )
            
            if hasattr(self, 'client'):
                self._emit_marquez_event(event)
            else:
                self._write_file_event(event)
                
        except Exception as e:
            logger.error("lineage.track_failed", error=str(e), agent=self.agent_name)
            if not self.config.get("error_handling", {}).get("ignore_failures", True):
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