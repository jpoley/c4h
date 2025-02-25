"""
Lineage tracking implementation leveraging existing workflow event storage.
Path: c4h_agents/agents/base_lineage.py
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List, Tuple
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
from c4h_agents.config import create_config_node

logger = structlog.get_logger()

@dataclass
class LineageEvent:
    """Complete lineage event for LLM interaction"""
    event_id: str
    agent_name: str
    agent_type: str
    run_id: str
    parent_id: Optional[str]
    input_context: Dict[str, Any]
    messages: LLMMessages
    raw_output: Any
    metrics: Optional[Dict] = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    error: Optional[str] = None
    step: Optional[int] = None
    execution_path: Optional[List[str]] = None
    input_hash: Optional[str] = None
    output_hash: Optional[str] = None

class BaseLineage:
    """OpenLineage tracking implementation"""
    def __init__(self, namespace: str, agent_name: str, config: Dict[str, Any]):
        """Initialize lineage tracking"""
        self.namespace = namespace
        self.agent_name = agent_name
        self.agent_type = agent_name.split('.')[-1] if '.' in agent_name else agent_name
        self.enabled = False
        
        # Create a configuration node for hierarchical access
        self.config_node = create_config_node(config or {})
        
        # Debug log the configuration structure
        logger.debug(f"{agent_name}.lineage_init", 
                     has_system=self.config_node.get_value("system") is not None,
                     has_workflow_run_id=self.config_node.get_value("workflow_run_id") is not None,
                     has_runtime=self.config_node.get_value("runtime") is not None)
        
        # Get lineage config using path query
        lineage_config = self.config_node.get_value("llm_config.agents.lineage") or {}
        if not lineage_config:
            # Try runtime path as fallback
            lineage_config = self.config_node.get_value("runtime.lineage") or {}
            
        if not lineage_config:
            logger.info(f"{agent_name}.lineage_disabled", reason="no_config")
            return
            
        # Extract run ID using hierarchical path queries
        self.run_id = self._extract_run_id(self.config_node)
        logger.debug(f"{agent_name}.using_run_id", run_id=self.run_id)

        # Set minimal defaults for lineage configuration
        self.config = {
            "enabled": lineage_config.get("enabled", False),
            "namespace": lineage_config.get("namespace", self.namespace),
            "backend": lineage_config.get("backend", {
                "type": "file",
                "path": "workspaces/lineage"
            }),
            "event_detail_level": lineage_config.get("event_detail_level", "full"),
            "separate_input_output": lineage_config.get("separate_input_output", False)
        }
        
        self.enabled = self.config["enabled"]
        if not self.enabled:
            logger.info(f"{agent_name}.lineage_disabled", reason="not_enabled")
            return

        # Setup storage directory
        try:
            base_dir = Path(self.config["backend"]["path"])
            date_str = datetime.now().strftime('%Y%m%d')
            self.lineage_dir = base_dir / date_str / self.run_id
            self.lineage_dir.mkdir(parents=True, exist_ok=True)
            
            # Create directories under run_id
            (self.lineage_dir / "events").mkdir(exist_ok=True)
            (self.lineage_dir / "errors").mkdir(exist_ok=True)
            (self.lineage_dir / "inputs").mkdir(exist_ok=True)
            (self.lineage_dir / "outputs").mkdir(exist_ok=True)
            
            logger.info("lineage.storage_initialized", path=str(self.lineage_dir), run_id=self.run_id)
        except Exception as e:
            logger.error("lineage.storage_init_failed", error=str(e))
            self.enabled = False

    def _extract_run_id(self, config_node) -> str:
        """
        Extract run ID using hierarchical path queries.
        Returns a stable run ID from the first available source.
        """
        # Query potential run ID locations in priority order
        run_id = (
            # 1. System namespace (highest priority)
            config_node.get_value("system.runid") or
            # 2. Direct context parameter
            config_node.get_value("workflow_run_id") or 
            # 3. Runtime configuration
            config_node.get_value("runtime.workflow_run_id") or
            config_node.get_value("runtime.run_id") or
            # 4. Workflow section
            config_node.get_value("runtime.workflow.id")
        )
        
        if run_id:
            return str(run_id)
            
        # Generate new UUID as fallback
        generated_id = str(uuid.uuid4())
        logger.warning("lineage.missing_run_id", agent=self.agent_name, generated_id=generated_id)
        return generated_id
    
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

    def _extract_lineage_metadata(self, context: Dict[str, Any]) -> Tuple[str, Optional[str], Optional[int], Optional[List[str]]]:
        """
        Extract lineage tracking metadata from context.
        Returns tuple of (event_id, parent_id, step, execution_path)
        """
        # Create configuration node for hierarchical access
        context_node = create_config_node(context)
        
        # Generate unique event ID if not provided
        event_id = context_node.get_value("agent_execution_id") or str(uuid.uuid4())
        
        # Extract parent ID in priority order
        parent_id = (
            context_node.get_value("parent_id") or  # Explicit parent ID
            context_node.get_value("parent_run_id") or  # Alternative parent ID
            (None if context_node.get_value("workflow_run_id") == self.run_id else context_node.get_value("workflow_run_id"))  # Use workflow ID as parent if different
        )
        
        # Extract step number
        step = context_node.get_value("step") or context_node.get_value("sequence") or None
        
        # Extract or build execution path
        path = context_node.get_value("execution_path") or []
        if isinstance(path, str):
            try:
                path = json.loads(path)
            except:
                path = [path]
        
        if not path:
            path = []
        
        # Add self to path
        path = path + [f"{self.agent_type}:{event_id[:8]}"]
        
        return event_id, parent_id, step, path

    # In file: c4h_agents/agents/base_lineage.py
    # Replace or modify the _write_file_event method

    def _write_file_event(self, event: LineageEvent) -> None:
        """Write event to file system with basic serialization"""
        if not self.enabled or not self.lineage_dir:
            return
            
        try:
            events_dir = self.lineage_dir / "events"
            event_file = events_dir / f"{event.event_id}.json"
            temp_file = events_dir / f"{event.event_id}.tmp"
            
            # Determine how much data to include based on event detail level
            detail_level = self.config.get("event_detail_level", "full")
            
            # Build event data dict
            event_data = {
                "event_id": event.event_id,
                "timestamp": event.timestamp.isoformat(),
                "agent": event.agent_name,
                "agent_type": event.agent_type,
                "input_context": self._serialize_value(event.input_context),
                "messages": {
                    "system": event.messages.system if hasattr(event.messages, "system") else None,
                    "user": event.messages.user if hasattr(event.messages, "user") else None,
                    "formatted_request": event.messages.formatted_request if hasattr(event.messages, "formatted_request") else None,
                    "timestamp": event.messages.timestamp.isoformat() if hasattr(event.messages, "timestamp") else None
                },
                "metrics": self._serialize_value(event.metrics),
                "run_id": event.run_id,
                "parent_id": event.parent_id,
                "error": event.error,
                "step": event.step,
                "execution_path": event.execution_path,
                "input_hash": event.input_hash,
                "output_hash": event.output_hash
            }
            
            # Include raw output unless storing separately
            if not self.config.get("separate_input_output", False):
                event_data["raw_output"] = self._serialize_value(event.raw_output)
            
            # Write main event file
            with open(temp_file, 'w') as f:
                json.dump(event_data, f, indent=2)
                    
            temp_file.rename(event_file)
            
            # If configured, write full input/output to separate files
            if self.config.get("separate_input_output", False):
                # Save input messages
                input_file = self.lineage_dir / "inputs" / f"{event.event_id}_input.json"
                with open(input_file, 'w') as f:
                    json.dump({
                        "event_id": event.event_id,
                        "system": event.messages.system if hasattr(event.messages, "system") else None,
                        "user": event.messages.user if hasattr(event.messages, "user") else None,
                    }, f, indent=2)
                
                # Save output
                output_file = self.lineage_dir / "outputs" / f"{event.event_id}_output.json"
                with open(output_file, 'w') as f:
                    json.dump({
                        "event_id": event.event_id,
                        "raw_output": self._serialize_value(event.raw_output),
                    }, f, indent=2)
            
            logger.info("lineage.event_saved", 
                    path=str(event_file), 
                    agent=event.agent_name, 
                    run_id=event.run_id,
                    event_size=event_file.stat().st_size,
                    event_id=event.event_id,
                    parent_id=event.parent_id)
                
        except Exception as e:
            logger.error("lineage.write_failed", 
                        error=str(e), 
                        lineage_dir=str(self.lineage_dir), 
                        agent=event.agent_name,
                        event_id=event.event_id)

    # In file: c4h_agents/agents/base_lineage.py
    # Replace or modify the track_llm_interaction method

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
            # Extract event_id, parent_id, and other lineage metadata
            event_id = context.get("agent_execution_id", str(uuid.uuid4()))
            parent_id = context.get("parent_id")
            agent_type = context.get("agent_type", self.agent_type)
            step = context.get("step")
            
            # Extract execution path
            execution_path = []
            if "lineage_metadata" in context and "execution_path" in context["lineage_metadata"]:
                execution_path = context["lineage_metadata"]["execution_path"]
            
            # Create the lineage event
            event = LineageEvent(
                event_id=event_id,
                agent_name=self.agent_name,
                agent_type=agent_type,
                run_id=self.run_id,
                parent_id=parent_id,
                input_context=context,
                messages=messages,
                raw_output=response,
                metrics=metrics,
                step=step,
                execution_path=execution_path
            )
            
            # Track in appropriate backend
            self._write_file_event(event)
            
            logger.info("lineage.event_saved", 
                    agent=self.agent_name, 
                    event_id=event_id,
                    parent_id=parent_id,
                    path_length=len(execution_path) if execution_path else 0)
                    
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
                    "runId": event.event_id,
                    "facets": {
                        "parent": ParentRunFacet(run={
                            "runId": event.parent_id
                        }) if event.parent_id else None,
                        "documentation": DocumentationJobFacet(description=f"Agent: {event.agent_name}")
                    }
                },
                job={
                    "namespace": self.namespace,
                    "name": event.agent_name
                },
                inputs=[InputDataset(
                    namespace=self.namespace,
                    name=f"{event.agent_name}_input",
                    facets={"context": self._serialize_value(event.input_context)}
                )],
                outputs=[OutputDataset(
                    namespace=self.namespace,
                    name=f"{event.agent_name}_output",
                    facets={
                        "metrics": event.metrics or {},
                        "output": self._serialize_value(event.raw_output)
                    }
                )]
            )
            self.client.emit(ol_event)
            logger.info("lineage.marquez_event_emitted", event_id=event.event_id)
        except Exception as e:
            logger.error("lineage.marquez_event_failed", error=str(e), event_id=event.event_id)