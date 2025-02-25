"""
Path: c4h_services/examples/debug_lineage.py
Debug tool to identify issues with lineage configuration
"""
#!/usr/bin/env python3

import sys
import os
from pathlib import Path
import json
import yaml
import argparse
import logging

logging.basicConfig(level=logging.INFO, 
                   format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('lineage_debug')

def check_directories():
    """Check if required directories exist and are writable"""
    dirs_to_check = [
        'workspaces',
        'workspaces/lineage',
        'workspaces/workflows',
        'workspaces/backups'
    ]
    
    results = {}
    cwd = Path.cwd()
    logger.info(f"Current working directory: {cwd}")
    
    for dir_path in dirs_to_check:
        full_path = cwd / dir_path
        exists = full_path.exists()
        is_dir = full_path.is_dir() if exists else False
        writable = os.access(full_path, os.W_OK) if exists else False
        
        # Try to create if doesn't exist
        created = False
        if not exists:
            try:
                full_path.mkdir(parents=True, exist_ok=True)
                created = True
                exists = True
                is_dir = True
                writable = os.access(full_path, os.W_OK)
            except Exception as e:
                logger.error(f"Failed to create directory {full_path}: {e}")
        
        results[dir_path] = {
            'full_path': str(full_path),
            'exists': exists,
            'is_dir': is_dir,
            'writable': writable,
            'created': created
        }
        
        logger.info(f"Directory {dir_path}: exists={exists}, is_dir={is_dir}, writable={writable}, created={created}")
    
    return results

def check_config_file(config_path):
    """Check if config file exists and has lineage configuration"""
    if not Path(config_path).exists():
        logger.error(f"Configuration file not found: {config_path}")
        return None
    
    try:
        with open(config_path) as f:
            config = yaml.safe_load(f)
            
        # Check for lineage configuration
        lineage_config = config.get('runtime', {}).get('lineage', {})
        logger.info(f"Lineage config found: {bool(lineage_config)}")
        if lineage_config:
            logger.info(f"Lineage enabled: {lineage_config.get('enabled', False)}")
            logger.info(f"Lineage backend: {lineage_config.get('backend', {}).get('type', 'file')}")
            logger.info(f"Lineage path: {lineage_config.get('backend', {}).get('path', 'workspaces/lineage')}")
        
        return config
    except Exception as e:
        logger.error(f"Error reading config file: {e}")
        return None

def try_writing_lineage_record():
    """Try to manually write a test lineage record"""
    lineage_dir = Path('workspaces/lineage')
    
    # Create basic directory structure
    try:
        today_dir = lineage_dir / 'debug_test'
        today_dir.mkdir(parents=True, exist_ok=True)
        events_dir = today_dir / 'events'
        events_dir.mkdir(exist_ok=True)
        
        # Create a test event
        test_event = {
            'timestamp': '2024-02-21T12:00:00Z',
            'agent': 'debug_agent',
            'input_context': {'test': True},
            'messages': {'system': 'test', 'user': 'test'},
            'metrics': {'test_metric': 100},
            'parent_run_id': None,
            'error': None
        }
        
        test_file = events_dir / 'debug_test.json'
        with open(test_file, 'w') as f:
            json.dump(test_event, f, indent=2)
            
        logger.info(f"Successfully wrote test lineage record to {test_file}")
        return True
    except Exception as e:
        logger.error(f"Failed to write test lineage record: {e}")
        return False

def check_imports():
    """Check if required imports are available"""
    import_results = {}
    
    # Check OpenLineage
    try:
        import openlineage.client
        import_results['openlineage'] = True
    except ImportError:
        logger.warning("OpenLineage client not installed - run: pip install openlineage-python")
        import_results['openlineage'] = False
    
    # Check other dependencies
    for package in ['structlog', 'yaml', 'json', 'pathlib']:
        try:
            __import__(package)
            import_results[package] = True
        except ImportError:
            logger.warning(f"{package} not installed")
            import_results[package] = False
    
    return import_results

def main():
    parser = argparse.ArgumentParser(description="Debug lineage tracking issues")
    parser.add_argument("--config", default="c4h_services/examples/config/workflow_coder_01.yml", 
                       help="Path to workflow configuration")
    parser.add_argument("--fix", action="store_true", help="Attempt to fix issues")
    
    args = parser.parse_args()
    
    logger.info("Starting lineage debug")
    
    # Step 1: Check directories
    logger.info("==== Checking Directories ====")
    dir_results = check_directories()
    
    # Step 2: Check configuration
    logger.info("==== Checking Configuration ====")
    config = check_config_file(args.config)
    
    # Step 3: Check imports
    logger.info("==== Checking Imports ====")
    import_results = check_imports()
    
    # Step 4: Try writing a test record
    logger.info("==== Testing Write Access ====")
    write_success = try_writing_lineage_record()
    
    # Fix issues if requested
    if args.fix and config:
        logger.info("==== Applying Fixes ====")
        # Add lineage configuration if missing
        if not config.get('runtime', {}).get('lineage', {}).get('enabled'):
            if 'runtime' not in config:
                config['runtime'] = {}
            if 'lineage' not in config['runtime']:
                config['runtime']['lineage'] = {}
            
            config['runtime']['lineage'] = {
                'enabled': True,
                'namespace': 'c4h_workflow',
                'backend': {
                    'type': 'file',
                    'path': 'workspaces/lineage'
                },
                'error_handling': {
                    'ignore_failures': True
                }
            }
            
            # Write updated config
            with open(args.config, 'w') as f:
                yaml.dump(config, f, sort_keys=False)
            logger.info(f"Updated configuration in {args.config}")
    
    # Show summary
    logger.info("==== Debug Summary ====")
    logger.info(f"Directories OK: {all(r['exists'] and r['writable'] for r in dir_results.values())}")
    logger.info(f"Configuration OK: {bool(config and config.get('runtime', {}).get('lineage', {}).get('enabled'))}")
    logger.info(f"Imports OK: {all(import_results.values())}")
    logger.info(f"Write test OK: {write_success}")
    
    if write_success:
        logger.info("Lineage system appears to be operational. Try running a workflow again.")
    else:
        logger.info("Issues detected with lineage system. Please review the log and fix the issues.")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())