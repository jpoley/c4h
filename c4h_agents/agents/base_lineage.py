"""OpenLineage integration for agent operations.
Path: c4h_agents/agents/base_lineage.py
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
from pathlib import Path
import json
import uuid
import structlog
from openlineage.client import OpenLineageClient, set_producer
from openlineage.client.run import RunEvent, RunState, InputDataset, OutputDataset
from openlineage.client.facet import ParentRunFacet, DocumentationJobFacet
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
    """OpenLineage tracking implementation"""

    def __init__(self, namespace: str, agent_name: str, config: Dict[str, Any]):
        """Initialize lineage tracking"""
        self.namespace = namespace
        self.agent_name = agent_name
        self.run_id = str(uuid.uuid4())
        self.config = config.get('runtime', {}).get('lineage', {})
        
        # Configure backend
        backend = self.config.get('backend', {})
        if backend.get('type') == 'marquez':
            self.client = OpenLineageClient(url=backend['url'])
        else:
            lineage_dir = Path(backend.get('path', 'workspaces/lineage'))
            self.lineage_dir = lineage_dir / datetime.now().strftime('%Y%m%d')
            self.lineage_dir.mkdir(parents=True, exist_ok=True)
            self.client = None
            
        # Set producer information
        set_producer('c4h_agents', agent_name)
        
        logger.info("lineage.initialized",
                    namespace=namespace,
                    agent=agent_name,
                    run_id=self.run_id,
                    backend_type=backend.get('type', 'file'))

    def track_llm_interaction(self,
                             context: Dict[str, Any],
                             messages: LLMMessages,
                             response: Any,
                             metrics: Optional[Dict] = None) -> None:
        """Track complete LLM interaction"""
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
            logger.error("lineage.track_failed", error=str(e))

    def create_lineage_event(self,
                            state: RunState,
                            inputs: Dict[str, Any],
                            outputs: Optional[Dict] = None) -> RunEvent:
        """Create OpenLineage run event"""
        event = RunEvent(
            eventType=state,
            eventTime=datetime.now(timezone.utc).isoformat(),
            run={
                "runId": self.run_id,
                "facets": {
                    "parent": ParentRunFacet(run_id=inputs.get('workflow_run_id')),
                    "documentation": DocumentationJobFacet(
                        description=f"Agent: {self.agent_name}"
                    )
                }
            },
            job={
                "namespace": self.namespace,
                "name": self.agent_name
            },
            inputs=[InputDataset(
                namespace=self.namespace,
                name=f"{self.agent_name}_input",
                facets=inputs
            )],
            outputs=[OutputDataset(
                namespace=self.namespace,
                name=f"{self.agent_name}_output",
                facets=outputs or {}
            )]
        )
        return event

    def emit_start(self, context: Dict[str, Any]) -> None:
        """Emit start event"""
        event = self.create_lineage_event(
            state=RunState.START,
            inputs=context
        )
        self._emit_event(event)

    def emit_complete(self, context: Dict[str, Any], result: Dict[str, Any]) -> None:
        """Emit completion event"""
        event = self.create_lineage_event(
            state=RunState.COMPLETE,
            inputs=context,
            outputs=result
        )
        self._emit_event(event)

    def emit_failed(self, context: Dict[str, Any], error: str) -> None:
        """Emit failure event"""
        event = self.create_lineage_event(
            state=RunState.FAIL,
            inputs=context,
            outputs={"error": error}
        )
        self._emit_event(event)

    def _emit_event(self, event: RunEvent) -> None:
        """Emit event to configured backend"""
        try:
            if self.client:
                self.client.emit(event)
            else:
                self._write_file_event(event)
        except Exception as e:
            if not self.config.get('error_handling', {}).get('ignore_failures', True):
                raise
            logger.error("lineage.emit_failed", error=str(e))

    def _write_file_event(self, event: Any) -> None:
        """Write event to file system"""
        try:
            event_dir = self.lineage_dir / self.run_id / "events"
            event_dir.mkdir(parents=True, exist_ok=True)
            
            event_file = event_dir / f"{uuid.uuid4()}.json"
            temp_file = event_file.with_suffix('.tmp')
            
            with open(temp_file, 'w') as f:
                if isinstance(event, LineageEvent):
                    json.dump({
                        "timestamp": event.timestamp.isoformat(),
                        "input_context": event.input_context,
                        "messages": event.messages.to_dict(),
                        "metrics": event.metrics,
                        "parent_run_id": event.parent_run_id,
                        "error": event.error
                    }, f, indent=2)
                else:
                    json.dump(event.to_dict(), f, indent=2)
                    
            temp_file.rename(event_file)
            
        except Exception as e:
            logger.error("lineage.write_failed", error=str(e))
            raise