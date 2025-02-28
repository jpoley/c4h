"""
Orchestrator for managing team-based workflow execution.
Path: c4h_services/src/orchestration/orchestrator.py
"""

from typing import Dict, Any, List, Optional, Set
import structlog
from pathlib import Path
import yaml
import uuid
from datetime import datetime, timezone

from c4h_agents.config import create_config_node, deep_merge
from c4h_services.src.intent.impl.prefect.models import AgentTaskConfig
from c4h_services.src.orchestration.team import Team
from c4h_services.src.intent.impl.prefect.factories import (
    create_discovery_task,
    create_solution_task,
    create_coder_task
)

logger = structlog.get_logger()

class Orchestrator:
    """
    Manages execution of team-based workflows using Prefect.
    Handles team loading, chaining, and execution.
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize orchestrator with configuration.
        
        Args:
            config: Complete configuration dictionary
        """
        self.config = config
        self.config_node = create_config_node(config)
        self.teams = {}
        self.loaded_teams = set()
        
        # Load team configurations
        self._load_teams()
        
        logger.info("orchestrator.initialized", 
                  teams_loaded=len(self.teams),
                  team_ids=list(self.teams.keys()))
    
    def _load_teams(self) -> None:
        """
        Load team configurations from config.
        Creates Team instances for each team configuration.
        """
        teams_config = self.config_node.get_value("orchestration.teams") or {}
        
        if not teams_config:
            logger.warning("orchestrator.no_teams_found")
            # Load default teams for backward compatibility
            self._load_default_teams()
            return
            
        for team_id, team_config in teams_config.items():
            try:
                # Get basic team info
                name = team_config.get("name", team_id)
                
                # Get task configurations
                tasks = []
                for task_config in team_config.get("tasks", []):
                    agent_class = task_config.get("agent_class")
                    if not agent_class:
                        logger.error("orchestrator.missing_agent_class", team_id=team_id, task=task_config)
                        continue
                        
                    # Create task config
                    agent_config = AgentTaskConfig(
                        agent_class=agent_class,
                        config=deep_merge(self.config, task_config.get("config", {})),
                        task_name=task_config.get("name"),
                        requires_approval=task_config.get("requires_approval", False),
                        max_retries=task_config.get("max_retries", 3),
                        retry_delay_seconds=task_config.get("retry_delay_seconds", 30)
                    )
                    
                    tasks.append(agent_config)
                
                # Create team
                self.teams[team_id] = Team(
                    team_id=team_id,
                    name=name,
                    tasks=tasks,
                    config=team_config
                )
                logger.info("orchestrator.team_loaded", team_id=team_id, name=name, tasks=len(tasks))
                
            except Exception as e:
                logger.error("orchestrator.team_load_failed", team_id=team_id, error=str(e))
    
    def _load_default_teams(self) -> None:
        """
        Load default teams for backward compatibility.
        Creates default discovery, solution, and coder teams.
        """
        # Create discovery team
        discovery_task = create_discovery_task(self.config)
        self.teams["discovery"] = Team(
            team_id="discovery",
            name="Discovery Team",
            tasks=[discovery_task],
            config={
                "routing": {
                    "default": "solution"
                }
            }
        )
        
        # Create solution team
        solution_task = create_solution_task(self.config)
        self.teams["solution"] = Team(
            team_id="solution",
            name="Solution Design Team",
            tasks=[solution_task],
            config={
                "routing": {
                    "default": "coder"
                }
            }
        )
        
        # Create coder team
        coder_task = create_coder_task(self.config)
        self.teams["coder"] = Team(
            team_id="coder",
            name="Coder Team",
            tasks=[coder_task],
            config={
                "routing": {
                    "default": None  # End of flow
                }
            }
        )
        
        logger.info("orchestrator.default_teams_loaded", 
                  teams=["discovery", "solution", "coder"])
    
    def execute_workflow(
        self, 
        entry_team: str = "discovery",
        context: Dict[str, Any] = None,
        max_teams: int = 10
    ) -> Dict[str, Any]:
        """
        Execute a workflow starting from the specified team.
        
        Args:
            entry_team: ID of the team to start execution with
            context: Initial context for execution
            max_teams: Maximum number of teams to execute (prevent infinite loops)
            
        Returns:
            Final workflow result
        """
        if entry_team not in self.teams:
            raise ValueError(f"Entry team {entry_team} not found")
            
        # Initialize context if needed
        if context is None:
            context = {}
            
        # Generate workflow ID if not provided
        workflow_run_id = context.get("workflow_run_id") or str(uuid.uuid4())
        if "system" not in context:
            context["system"] = {}
        context["system"]["runid"] = workflow_run_id
        context["workflow_run_id"] = workflow_run_id
        
        logger.info("orchestrator.workflow_starting", 
                  entry_team=entry_team,
                  workflow_run_id=workflow_run_id)
        
        # Track execution path
        execution_path = []
        team_results = {}
        workflow_data = {}
        
        # Initial setup
        current_team_id = entry_team
        team_count = 0
        final_result = {
            "status": "success",
            "workflow_run_id": workflow_run_id,
            "execution_id": workflow_run_id,
            "execution_path": [],
            "team_results": {},
            "data": {}
        }
        
        # Execute teams in sequence
        while current_team_id and team_count < max_teams:
            if current_team_id not in self.teams:
                logger.error("orchestrator.team_not_found", team_id=current_team_id)
                final_result["status"] = "error"
                final_result["error"] = f"Team {current_team_id} not found"
                break
                
            team = self.teams[current_team_id]
            logger.info("orchestrator.executing_team", 
                      team_id=current_team_id,
                      step=team_count + 1)
                      
            # Track this team in the execution path
            execution_path.append(current_team_id)
            
            # Clone context to avoid mutations affecting other teams
            team_context = context.copy()
            
            # Prepare the context based on workflow sequence
            if current_team_id == "solution" and workflow_data:
                # Structure data according to solution_designer expectations
                if "input_data" not in team_context:
                    team_context["input_data"] = {}
                
                # Check if we have discovery_data to pass along
                if "discovery_data" in workflow_data:
                    team_context["input_data"]["discovery_data"] = workflow_data["discovery_data"]
                    
                # Ensure intent is passed to solution designer
                if "intent" in context and "intent" not in team_context["input_data"]:
                    team_context["input_data"]["intent"] = context["intent"]
            
            elif current_team_id == "coder" and workflow_data:
                # If we have result from solution designer, pass it through as input_data
                if "result_data" in workflow_data:
                    team_context["input_data"] = workflow_data["result_data"]
                    
            # Execute the team
            team_result = team.execute(team_context)
            
            # Store team result
            team_results[current_team_id] = team_result
            
            # Update workflow data based on team results
            if team_result.get("success", False) and "data" in team_result:
                # Store team-specific data for next teams
                if current_team_id == "discovery":
                    workflow_data["discovery_data"] = team_result["data"]
                elif current_team_id == "solution":
                    workflow_data["result_data"] = team_result["data"]
                
                # Also update the final result data
                final_result["data"].update(team_result["data"])
            
            # Check for failure
            if not team_result.get("success", False):
                logger.warning("orchestrator.team_execution_failed",
                             team_id=current_team_id,
                             error=team_result.get("error"))
                final_result["status"] = "error"
                final_result["error"] = team_result.get("error")
                break
                
            # Get next team
            current_team_id = team_result.get("next_team")
            team_count += 1
            
            # Check if we've reached the end
            if not current_team_id:
                logger.info("orchestrator.workflow_completed",
                          teams_executed=team_count,
                          final_team=team.team_id)
                break
        
        # Check if we hit the team limit
        if team_count >= max_teams:
            logger.warning("orchestrator.max_teams_reached", max_teams=max_teams)
            final_result["status"] = "error"
            final_result["error"] = f"Exceeded maximum team limit of {max_teams}"
        
        # Build final result
        final_result["execution_path"] = execution_path
        final_result["team_results"] = team_results
        final_result["teams_executed"] = team_count
        final_result["timestamp"] = datetime.now(timezone.utc).isoformat()
        
        logger.info("orchestrator.workflow_result", 
                  status=final_result["status"],
                  teams_executed=team_count,
                  execution_path=execution_path)
                  
        return final_result