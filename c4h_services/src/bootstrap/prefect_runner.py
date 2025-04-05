#!/usr/bin/env python3
"""
Streamlined runner focused exclusively on API service and client interactions.
Path: c4h_services/src/bootstrap/prefect_runner.py
"""

from pathlib import Path
import sys
import os
import uuid
import requests
import time
import json

# Add the project root to the Python path
script_path = Path(__file__).resolve()
project_root = script_path.parent.parent.parent.parent  # Go up to the project root
sys.path.append(str(project_root))

import uvicorn
from c4h_services.src.utils.logging import get_logger
import argparse
from enum import Enum
import yaml
from typing import Dict, Any, Optional, List
from datetime import datetime

logger = get_logger()

class LogMode(str, Enum):
    """Logging modes supported by runner"""
    DEBUG = "debug"
    NORMAL = "normal"

def load_configs(app_config_path: Optional[str] = None, system_config_paths: Optional[List[str]] = None) -> Dict[str, Any]:
    """Load and merge configurations in proper order"""
    try:
        app_config = {}
        
        if app_config_path:
            with open(app_config_path) as f:
                app_config = yaml.safe_load(f) or {}
                
            logger.info("config.content.loaded",
                      app_config_keys=list(app_config.keys()),
                      project_path=app_config.get('project', {}).get('path', None),
                      has_intent=('intent' in app_config))
        
        merged_config = {}
        
        if system_config_paths:
            for sys_path in system_config_paths:
                path = Path(sys_path)
                if not path.exists():
                    logger.warning("config.system_config.not_found", path=str(path))
                    continue
                with open(path) as f:
                    sys_config = yaml.safe_load(f) or {}
                    logger.debug("config.merge.system_config",
                                path=str(path),
                                config_keys=list(sys_config.keys()))
                    if merged_config:
                        from c4h_agents.config import deep_merge
                        merged_config = deep_merge(merged_config, sys_config)
                    else:
                        merged_config = sys_config
                    
        elif not merged_config and app_config_path:  # Only look for default config if app config is provided
            default_paths = [
                Path("config/system_config.yml"),
                Path("../config/system_config.yml"),
                project_root / "config" / "system_config.yml"
            ]
            logger.info("config.paths.search", 
                cwd=str(Path.cwd()),
                root_dir=str(project_root),
                sys_paths=[str(p) for p in default_paths],
                config_path=app_config_path
            )
            for path in default_paths:
                if path.exists():
                    with open(path) as f:
                        sys_config = yaml.safe_load(f) or {}
                        logger.debug("config.merge.default_system",
                                    path=str(path),
                                    config_keys=list(sys_config.keys()))
                        if merged_config:
                            from c4h_agents.config import deep_merge
                            merged_config = deep_merge(merged_config, sys_config)
                        else:
                            merged_config = sys_config
                    break
                    
        if app_config and merged_config:
            from c4h_agents.config import deep_merge
            final_config = deep_merge(merged_config, app_config)
        else:
            final_config = app_config or merged_config or {}
        
        # For service mode only - ensure minimal config structure exists
        if app_config_path and 'llm_config' not in final_config and not any(key in final_config for key in ['workorder', 'team', 'runtime']):
            logger.warning("config.no_llm_config_found",
                         final_keys=list(final_config.keys()))
            final_config['llm_config'] = {}
            
        # For service mode only - ensure orchestration is enabled
        if 'orchestration' in final_config:
            final_config['orchestration']['enabled'] = True
            
        return final_config

    except Exception as e:
        logger.error("config.load_failed", error=str(e))
        if app_config_path:  # Only raise if a config file was explicitly requested
            raise
        return {}

def send_workflow_request(host: str, port: int, project_path: str, intent_desc: Dict[str, Any],
                          app_config: Optional[Dict[str, Any]] = None,
                          system_config: Optional[Dict[str, Any]] = None,
                          lineage_file: Optional[str] = None,
                          stage: Optional[str] = None,
                          keep_runid: bool = True) -> Dict[str, Any]:
    """
    Send workflow request to server and return the response.
    
    Args:
        host: Server hostname or IP address
        port: Server port number
        project_path: Path to the project
        intent_desc: Intent description dictionary
        app_config: Application configuration (optional)
        system_config: System configuration (optional)
        lineage_file: Path to lineage file (optional)
        stage: Target stage to execute (optional)
        keep_runid: Whether to keep the original run ID from the lineage file
        
    Returns:
        Response data from the server
    """
    url = f"http://{host}:{port}/api/v1/workflow"
    
    # Prepare request data
    request_data = {
        "project_path": project_path,
        "intent": intent_desc,
        "app_config": app_config,
        "system_config": system_config
    }
    
    # Add lineage information if provided
    if lineage_file and stage:
        request_data["lineage_file"] = lineage_file
        request_data["stage"] = stage
        request_data["keep_runid"] = keep_runid
    
    # Log request details
    logger.info("client.sending_workflow_request",
               url=url,
               project_path=project_path,
               has_intent=bool(intent_desc),
               has_app_config=bool(app_config),
               has_system_config=bool(system_config),
               lineage_file=lineage_file,
               stage=stage,
               keep_runid=keep_runid)
    
    # Send request
    try:
        response = requests.post(url, json=request_data)
        response.raise_for_status()  # Raise exception for HTTP errors
        result = response.json()
        
        logger.info("client.request_success",
                  workflow_id=result.get("workflow_id"),
                  status=result.get("status"))
                  
        return result
    except requests.RequestException as e:
        logger.error("client.request_failed", error=str(e))
        return {
            "status": "error",
            "error": f"Request failed: {str(e)}",
            "workflow_id": None
        }

def send_job_request(host: str, port: int, config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Send job request to server and return the response.
    
    This function directly passes the configuration as a job request.
    No client-side conversion between job and workflow formats is performed.
    
    Args:
        host: Server hostname or IP address
        port: Server port number
        config: Job configuration with workorder, team, and runtime sections
        
    Returns:
        Response data from the server
    """
    url = f"http://{host}:{port}/api/v1/jobs"

    # Log request details
    logger.info("client.sending_job_request",
               url=url,
               config_keys=list(config.keys()),
               has_workorder=bool(config.get('workorder')),
               has_team=bool(config.get('team')),
               has_runtime=bool(config.get('runtime')))

    # Send request
    try:
        response = requests.post(url, json=config)
        
        # Log response code
        logger.debug("client.job_response_received", 
                   status_code=response.status_code,
                   content_length=len(response.content))
        
        # Raise for HTTP errors
        response.raise_for_status()
        result = response.json()

        logger.info("client.job_request_success",
                  job_id=result.get("job_id"),
                  status=result.get("status"))

        return result
    except requests.HTTPError as e:
        # Try to get error details from response
        err_msg = str(e)
        try:
            error_data = e.response.json()
            if "detail" in error_data:
                err_msg = f"{e.response.status_code}: {error_data['detail']}"
        except:
            pass
        
        logger.error("client.job_request_http_error", 
                   status_code=e.response.status_code if hasattr(e, 'response') else 'unknown',
                   error=err_msg)
        return {
            "status": "error",
            "error": f"HTTP error: {err_msg}",
            "job_id": None
        }
    except requests.RequestException as e:
        logger.error("client.job_request_failed", error=str(e))
        return {
            "status": "error",
            "error": f"Request failed: {str(e)}",
            "job_id": None
        }

def get_status(host: str, port: int, url_path: str, id_value: str) -> Dict[str, Any]:
    """
    Get status of a workflow or job from the server.
    
    Args:
        host: Server hostname or IP address
        port: Server port number
        url_path: API path segment (workflow or jobs)
        id_value: ID of the workflow or job to check
        
    Returns:
        Status data from the server
    """
    url = f"http://{host}:{port}/api/v1/{url_path}/{id_value}"
    
    try:
        logger.debug("client.status_checking", id=id_value, url=url)
        response = requests.get(url)
        response.raise_for_status()
        result = response.json()
        
        logger.debug("client.status_check",
                   id=id_value,
                   status=result.get("status"))
                   
        return result
    except requests.HTTPError as e:
        # Try to get error details from response
        err_msg = str(e)
        try:
            error_data = e.response.json()
            if "detail" in error_data:
                err_msg = f"{e.response.status_code}: {error_data['detail']}"
        except:
            pass
        
        logger.error("client.status_http_error", 
                   id=id_value,
                   status_code=e.response.status_code if hasattr(e, 'response') else 'unknown',
                   error=err_msg)
        return {
            "status": "error",
            "error": f"HTTP error: {err_msg}"
        }
    except requests.RequestException as e:
        logger.error("client.status_check_failed",
                   id=id_value,
                   error=str(e))
        return {
            "status": "error",
            "error": f"Status check failed: {str(e)}"
        }

def get_workflow_status(host: str, port: int, workflow_id: str) -> Dict[str, Any]:
    """Get status of a workflow from the server."""
    return get_status(host, port, "workflow", workflow_id)

def get_job_status(host: str, port: int, job_id: str) -> Dict[str, Any]:
    """Get status of a job from the server."""
    return get_status(host, port, "jobs", job_id)

def poll_status(host: str, port: int, url_path: str, id_value: str, 
               poll_interval: int = 5, max_polls: int = 60) -> Dict[str, Any]:
    """
    Poll status until completion or timeout.
    
    Args:
        host: Server hostname or IP address
        port: Server port number
        url_path: API path segment (workflow or jobs)
        id_value: ID of the workflow or job to check
        poll_interval: Seconds between status checks
        max_polls: Maximum number of polls before timeout
        
    Returns:
        Final status from the server
    """
    logger.info("client.polling_status", 
              id=id_value, 
              url_path=url_path,
              poll_interval=poll_interval, 
              max_polls=max_polls)
              
    poll_count = 0
    terminal_statuses = ["success", "error", "complete", "failed"]
    
    for poll_count in range(max_polls):
        # Get current status
        result = get_status(host, port, url_path, id_value)
        status = result.get("status")
        
        # Check if job has completed (success or error)
        if status in terminal_statuses:
            logger.info("client.polling_complete", 
                      id=id_value, 
                      status=status, 
                      polls=poll_count+1)
            return result
            
        # Log polling progress
        if poll_count % 5 == 0 or poll_count < 2:  # Log first few and then every 5th poll
            logger.info("client.polling", 
                      id=id_value, 
                      status=status, 
                      poll_count=poll_count+1, 
                      max_polls=max_polls)
                      
        # Wait before next poll
        time.sleep(poll_interval)
    
    # If we get here, we've reached the polling limit
    logger.warning("client.polling_timeout", 
                 id=id_value, 
                 polls=max_polls, 
                 last_status=result.get("status"))
                 
    return {
        "status": "timeout", 
        "error": f"Polling timed out after {max_polls} attempts", 
        "id": id_value
    }

def poll_workflow_status(host: str, port: int, workflow_id: str, poll_interval: int = 5, max_polls: int = 60) -> Dict[str, Any]:
    """Poll workflow status until completion or timeout."""
    return poll_status(host, port, "workflow", workflow_id, poll_interval, max_polls)

def poll_job_status(host: str, port: int, job_id: str, poll_interval: int = 5, max_polls: int = 60) -> Dict[str, Any]:
    """Poll job status until completion or timeout."""
    return poll_status(host, port, "jobs", job_id, poll_interval, max_polls)

# Path: c4h_services/src/bootstrap/prefect_runner.py

def build_job_config(config_path: Optional[str], project_path: Optional[str], 
                    intent_file: Optional[str], lineage_file: Optional[str] = None, 
                    stage: Optional[str] = None, keep_runid: bool = True) -> Dict[str, Any]:
    """
    Build job configuration from config file, project path, intent file, and lineage parameters.
    """
    # Load the base config
    job_config = {}
    if config_path:
        try:
            with open(config_path) as f:
                job_config = yaml.safe_load(f) or {}
        except Exception as e:
            logger.error("config.load_failed", error=str(e), path=config_path)
            raise ValueError(f"Failed to load config: {str(e)}")
    
    # If already in job format, use it directly
    if any(key in job_config for key in ['workorder', 'team', 'runtime']):
        logger.info("job_config.already_in_job_format", 
                  keys=list(job_config.keys()))
    
    # If not in job format, create job structure
    else:
        # Create workorder section if needed
        if 'workorder' not in job_config:
            job_config['workorder'] = {}
        
        # Add project if provided as argument
        if project_path:
            if 'project' not in job_config['workorder']:
                job_config['workorder']['project'] = {}
            job_config['workorder']['project']['path'] = project_path
        # Or extract from config
        elif 'project' in job_config:
            if 'project' not in job_config['workorder']:
                job_config['workorder']['project'] = {}
            job_config['workorder']['project']['path'] = job_config['project'].get('path')
        
        # Load intent from file if provided
        if intent_file:
            try:
                with open(intent_file) as f:
                    if intent_file.endswith('.json'):
                        intent_data = json.load(f)
                    else:
                        intent_data = yaml.safe_load(f)
                
                # Set intent in workorder
                job_config['workorder']['intent'] = intent_data
            except Exception as e:
                logger.error("intent.load_failed", error=str(e), path=intent_file)
                raise ValueError(f"Failed to load intent file: {str(e)}")
        # Or use intent from config
        elif 'intent' in job_config:
            job_config['workorder']['intent'] = job_config['intent']
        
        # Move LLM config to team section
        if 'llm_config' in job_config:
            if 'team' not in job_config:
                job_config['team'] = {}
            job_config['team']['llm_config'] = job_config['llm_config']
        
        # Move orchestration config to team section
        if 'orchestration' in job_config:
            if 'team' not in job_config:
                job_config['team'] = {}
            job_config['team']['orchestration'] = job_config['orchestration']
        
        # Move runtime-related configs to runtime section
        if 'runtime' not in job_config:
            job_config['runtime'] = {}
            
        # Move logging config to runtime section
        if 'logging' in job_config:
            job_config['runtime']['logging'] = job_config['logging']
            
        # Move backup config to runtime section
        if 'backup' in job_config:
            job_config['runtime']['backup'] = job_config['backup']
    
    # Add lineage information if provided
    if lineage_file or stage:
        # Ensure runtime.runtime exists
        if 'runtime' not in job_config:
            job_config['runtime'] = {}
        if 'runtime' not in job_config['runtime']:
            job_config['runtime']['runtime'] = {}
        
        # Add lineage parameters
        if lineage_file:
            job_config['runtime']['runtime']['lineage_file'] = lineage_file
        if stage:
            job_config['runtime']['runtime']['stage'] = stage
        # Only add keep_runid if it's explicitly set to False (since True is default)
        if not keep_runid:
            job_config['runtime']['runtime']['keep_runid'] = keep_runid
    
    # Validate job config has required sections
    if 'workorder' not in job_config:
        raise ValueError("Job config must have a workorder section")
    
    if 'project' not in job_config['workorder'] or 'path' not in job_config['workorder']['project']:
        raise ValueError("Job config must specify workorder.project.path")
        
    if 'intent' not in job_config['workorder']:
        raise ValueError("Job config must specify workorder.intent")
    
    return job_config

def handle_client_mode(args: argparse.Namespace) -> None:
    """Handle client mode for workflow API"""
    # Load and merge configurations
    config = load_configs(args.config, args.system_configs)
    
    # Check if project path is available
    project_path = args.project_path
    if not project_path:
        if 'project' in config and 'path' in config['project']:
            project_path = config['project']['path']
        else:
            print("Error: --project-path is required when not defined in config")
            sys.exit(1)
    
    # Get intent from file or config
    intent_desc = {}
    
    if args.intent_file:
        try:
            with open(args.intent_file) as f:
                if args.intent_file.endswith('.json'):
                    intent_desc = json.load(f)
                else:
                    intent_desc = yaml.safe_load(f)
        except Exception as e:
            print(f"Error: Failed to load intent file: {str(e)}")
            sys.exit(1)
    elif 'intent' in config:
        intent_desc = config.get('intent', {})
        logger.info("client.using_intent_from_config",
                    intent_keys=list(intent_desc.keys()) if intent_desc else {})
    else:
        print("Error: --intent-file is required when intent is not defined in config")
        sys.exit(1)
        
    # Send workflow request to server
    result = send_workflow_request(
        host=args.host,
        port=args.port,
        project_path=project_path,
        intent_desc=intent_desc,
        app_config=config,
        lineage_file=args.lineage_file,
        stage=args.stage,
        keep_runid=args.keep_runid
    )
    
    # Check result and display
    if result.get("status") == "error":
        print(f"Error: {result.get('error')}")
        sys.exit(1)
        
    workflow_id = result.get("workflow_id")
    print(f"Workflow submitted successfully. Workflow ID: {workflow_id}")
    print(f"Initial status: {result.get('status')}")
    
    # Poll for completion if requested
    if args.poll and workflow_id:
        print(f"Polling for completion every {args.poll_interval} seconds (max {args.max_polls} polls)...")
        status = poll_workflow_status(args.host, args.port, workflow_id, args.poll_interval, args.max_polls)
        print(f"Final status: {status.get('status', 'unknown')}")
        if status.get("status") != "success":
            sys.exit(1)
    sys.exit(0)

def handle_jobs_mode(args: argparse.Namespace) -> None:
    """Handle jobs mode for jobs API"""
    try:
        # Build job configuration in the correct format
        job_config = build_job_config(
            args.config, 
            args.project_path, 
            args.intent_file,
            args.lineage_file,
            args.stage,
            args.keep_runid
        )
        
        # Send job request to server
        result = send_job_request(
            host=args.host,
            port=args.port,
            config=job_config
        )
        
        # Check result and display
        if result.get("status") == "error":
            print(f"Error: {result.get('error')}")
            sys.exit(1)
            
        job_id = result.get("job_id")
        if not job_id:
            print("Error: No job ID returned from server")
            sys.exit(1)
            
        print(f"Job submitted successfully. Job ID: {job_id}")
        print(f"Initial status: {result.get('status')}")
        
        # Poll for completion if requested
        if args.poll and job_id:
            print(f"Polling for completion every {args.poll_interval} seconds (max {args.max_polls} polls)...")
            
            # Start polling with progress display
            print("Job status:", end=" ", flush=True)
            status = poll_job_status(args.host, args.port, job_id, args.poll_interval, args.max_polls)
            print(f"\nFinal status: {status.get('status', 'unknown')}")
            
            # Print changes if available
            if status.get("changes"):
                print("\nChanges:")
                for change in status.get("changes", []):
                    file_path = change.get("file", "unknown")
                    change_type = change.get("change", {})
                    
                    # Format change type for display
                    if isinstance(change_type, dict):
                        change_type_str = next(iter(change_type.keys()), "unknown")
                        details = change_type.get(change_type_str)
                        if details:
                            change_type_str = f"{change_type_str}: {details}"
                    else:
                        change_type_str = str(change_type)
                    
                    print(f"  {change_type_str}: {file_path}")
            
            # Show error if present
            if status.get("error"):
                print(f"\nError: {status.get('error')}")
            
            # Exit with appropriate status code
            if status.get("status") != "success":
                sys.exit(1)
        
        sys.exit(0)
    except ValueError as e:
        print(f"Error: {str(e)}")
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error: {str(e)}")
        sys.exit(1)

def handle_service_mode(args: argparse.Namespace) -> None:
    """Handle service mode to run API server"""
    try:
        # Import here to avoid circular imports
        from c4h_services.src.api.service import create_app
        
        # Create FastAPI app with default config
        config = load_configs(args.config, args.system_configs)
        app = create_app(default_config=config)
        print(f"Service mode enabled, running on port {args.port}")
        uvicorn.run(app, host="0.0.0.0", port=args.port)
    except Exception as e:
        print(f"Service startup failed: {str(e)}")
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description="API service and client for workflow and job operations")
    parser.add_argument("mode", type=str, nargs="?", choices=["service", "client", "jobs"],
                        default="service", help="Run mode (service, client, or jobs)")
    parser.add_argument("-P", "--port", type=int, default=8000, help="Port number for API service mode or client communication")
    
    # Config parameters
    parser.add_argument("--config", help="Path to application config file")
    parser.add_argument("--system-configs", nargs="+", help="Optional system config files in merge order")
    
    # Project and intent parameters
    parser.add_argument("--project-path", help="Path to the project (optional if defined in config)")
    parser.add_argument("--intent-file", help="Path to intent JSON file (optional if intent defined in config)")
    
    # Lineage parameters (for client mode)
    parser.add_argument("--lineage-file", help="Path to lineage file for workflow continuation")
    parser.add_argument("--stage", choices=["discovery", "solution_designer", "coder"], help="Stage to execute from lineage")
    parser.add_argument("--keep-runid", action="store_true", help="Keep original run ID when continuing from lineage file")
    
    # Client parameters
    parser.add_argument("--host", default="localhost", help="Host for client mode")
    parser.add_argument("--poll", action="store_true", help="Poll for completion in client mode")
    parser.add_argument("--poll-interval", type=int, default=5, help="Seconds between status checks in client mode")
    parser.add_argument("--max-polls", type=int, default=60, help="Maximum number of status checks in client mode")
    
    parser.add_argument(
        "--log",
        type=LogMode,
        choices=list(LogMode),
        default=LogMode.NORMAL,
        help="Logging level"
    )

    args = parser.parse_args()

    try:
        if args.mode == "service":
            handle_service_mode(args)
        elif args.mode == "client":
            handle_client_mode(args)
        elif args.mode == "jobs":
            handle_jobs_mode(args)
        else:
            # This should never happen due to argparse choices, but just in case
            print(f"Error: Unsupported mode: {args.mode}")
            sys.exit(1)
    except Exception as e:
        print(f"Unexpected error: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()