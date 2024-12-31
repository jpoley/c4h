"""
Migration script for copying unchanged files to new structure.
Path: scripts/migrate_files.py
"""

import shutil
from pathlib import Path
import os
import sys

def get_project_paths():
    """Get absolute paths for all project directories"""
    paths = {
        'SOURCE_ROOT': Path.home() / "src/autogen/coder4h/intent_system/src",
        'CONFIG_ROOT': Path.home() / "src/autogen/coder4h/intent_system",
        'AGENTS_ROOT': Path.home() / "src/apps/c4h/c4h_agents",
        'SERVICES_ROOT': Path.home() / "src/apps/c4h/c4h_services"
    }
    
    # Verify all source paths exist
    missing_paths = []
    for name, path in paths.items():
        if not path.exists():
            missing_paths.append(f"{name}: {path}")
    
    if missing_paths:
        print("Error: Required source directories not found:")
        for path in missing_paths:
            print(f"  {path}")
        sys.exit(1)
        
    return paths

# Rest of the file mappings remain the same as before
AGENTS_FILES = {
    # Core agents
    "agents/base.py": "src/agents/base.py",
    # ... rest of the mappings ...
}

TEST_FILES = {
    "testharness.py": "examples/testharness.py",
}

CONFIG_FILES = {
    "system_config.yml": "examples/configs/system_config.yml",
    # ... rest of the configs ...
}

def copy_files(source_root: Path, dest_root: Path, file_mapping: dict, description: str):
    """Copy files from source to destination maintaining structure"""
    print(f"\nCopying {description}...")
    print(f"From: {source_root}")
    print(f"To: {dest_root}\n")
    
    for src, dest in file_mapping.items():
        src_path = source_root / src
        dest_path = dest_root / dest
        
        # Create destination directories
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        
        try:
            if src_path.exists():
                shutil.copy2(src_path, dest_path)
                print(f"✓ Copied: {src} -> {dest}")
            else:
                print(f"✗ Warning: Source file not found: {src_path}")
        except Exception as e:
            print(f"✗ Error copying {src}: {str(e)}")

def main():
    print("Starting file migration...\n")
    
    # Get and verify all paths
    paths = get_project_paths()
    
    print("Using paths:")
    for name, path in paths.items():
        print(f"{name}: {path}")
    
    # Confirm with user
    response = input("\nProceed with migration? [y/N]: ")
    if response.lower() != 'y':
        print("Migration cancelled.")
        return
    
    # Copy files with descriptive messages
    copy_files(paths['SOURCE_ROOT'], paths['AGENTS_ROOT'], AGENTS_FILES, "agents and skills")
    copy_files(paths['SOURCE_ROOT'], paths['AGENTS_ROOT'], TEST_FILES, "test harness")
    copy_files(paths['CONFIG_ROOT'], paths['AGENTS_ROOT'], CONFIG_FILES, "config files")
    
    print("\nMigration complete!")

if __name__ == "__main__":
    main()
