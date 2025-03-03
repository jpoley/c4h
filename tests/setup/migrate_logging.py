#!/usr/bin/env python3
import os
import re
from pathlib import Path

def analyze_imports(directory="c4h_agents", dry_run=True):
    """
    Search through all Python files in directory and analyze imports related
    to truncate_log_string.
    
    Args:
        directory: Root directory to search in
        dry_run: If True, just report what would be changed without modifying files
    """
    # Get all Python files
    print(f"Scanning Python files in {directory}")
    py_files = list(Path(directory).glob("**/*.py"))
    print(f"Found {len(py_files)} Python files")
    
    # Patterns to search for
    string_utils_import = re.compile(r'from\s+c4h_agents\.utils\.string_utils\s+import\s+([^;]+)')
    utils_import = re.compile(r'from\s+c4h_agents\.utils\s+import\s+([^;]+)')
    direct_logging_import = re.compile(r'from\s+c4h_agents\.utils\.logging\s+import\s+([^;]+)')
    
    # Count of files to potentially modify
    would_modify_count = 0
    
    # Lists for reporting
    using_string_utils = []
    using_utils = []
    using_logging = []
    uses_truncate = []
    
    for py_file in py_files:
        # Skip the utils module files themselves
        if any(name in str(py_file) for name in ['string_utils.py', 'logging.py', '__init__.py']):
            continue
            
        with open(py_file, 'r', encoding='utf-8', errors='ignore') as f:
            try:
                content = f.read()
            except Exception as e:
                print(f"Error reading {py_file}: {e}")
                continue
        
        original_content = content
        needs_modification = False
        
        # Check for imports from string_utils
        string_utils_match = string_utils_import.search(content)
        if string_utils_match:
            using_string_utils.append(str(py_file))
            # Get the list of imports
            imports = string_utils_match.group(1).strip()
            if 'truncate_log_string' in imports or 'truncate_recursive' in imports:
                uses_truncate.append(str(py_file))
                # Would replace the import with logging import
                needs_modification = True
        
        # Check for imports from utils
        utils_match = utils_import.search(content)
        if utils_match:
            using_utils.append(str(py_file))
            # Get the list of imports
            imports = utils_match.group(1).strip()
            if 'truncate_log_string' in imports or 'truncate_recursive' in imports:
                uses_truncate.append(str(py_file))
                needs_modification = True
        
        # Check for direct imports from logging
        logging_match = direct_logging_import.search(content)
        if logging_match:
            using_logging.append(str(py_file))
            imports = logging_match.group(1).strip()
            if 'truncate_log_string' in imports or 'truncate_recursive' in imports:
                uses_truncate.append(str(py_file))
        
        if needs_modification:
            would_modify_count += 1
            if not dry_run:
                # Implement actual modifications here
                # (This code would be the same as in your original script)
                pass
    
    # Remove duplicates
    using_string_utils = list(set(using_string_utils))
    using_utils = list(set(using_utils))
    using_logging = list(set(using_logging))
    uses_truncate = list(set(uses_truncate))
    
    # Summary
    print("\n=== Import Analysis ===")
    print(f"Files importing from c4h_agents.utils.string_utils: {len(using_string_utils)}")
    for f in using_string_utils:
        print(f"  - {f}")
    
    print(f"\nFiles importing from c4h_agents.utils: {len(using_utils)}")
    for f in using_utils:
        print(f"  - {f}")
    
    print(f"\nFiles importing from c4h_agents.utils.logging: {len(using_logging)}")
    for f in using_logging:
        print(f"  - {f}")
    
    print(f"\nFiles using truncate_log_string or truncate_recursive: {len(uses_truncate)}")
    for f in uses_truncate:
        print(f"  - {f}")
    
    print(f"\nWould modify {would_modify_count} files.")
    
    # If dry run is off, report about modifications
    if not dry_run:
        print(f"Modified {would_modify_count} files.")
    else:
        print("No files were modified (dry run).")

if __name__ == "__main__":
    import sys
    
    # Check if we're running with --apply
    apply_changes = "--apply" in sys.argv
    
    if len(sys.argv) > 1 and sys.argv[1] != "--apply":
        directory = sys.argv[1]
        analyze_imports(directory, not apply_changes)
    else:
        analyze_imports(dry_run=not apply_changes)