"""
Migration script for copying unchanged files to new structure.
Path: scripts/migrate_files.py
"""

import shutil
from pathlib import Path
import os
import sys
from typing import Dict, Set

def verify_source_files(source_root: Path, file_mapping: Dict[str, str]) -> Set[str]:
    """Verify source files exist and return missing files"""
    missing = set()
    for src in file_mapping.keys():
        if not (source_root / src).exists():
            missing.add(src)
    return missing

def verify_paths():
    """Verify and return all required paths"""
    paths = {
        'SOURCE_ROOT': Path.home() / "src/autogen/coder4h/intent_system/src",
        'CONFIG_ROOT': Path.home() / "src/autogen/coder4h/intent_system",
        'AGENTS_ROOT': Path.home() / "src/apps/c4h/c4h_agents",
        'SERVICES_ROOT': Path.home() / "src/apps/c4h/c4h_services"
    }
    
    for name, path in paths.items():
        print(f"Checking {name}: {path}")
        print(f"Exists: {path.exists()}")
    
    return paths

def copy_with_verification(source_root: Path, dest_root: Path, file_mapping: Dict[str, str], 
                         description: str, dry_run: bool = False):
    """Copy files with verification and detailed logging"""
    print(f"\nProcessing {description}...")
    print(f"From: {source_root}")
    print(f"To: {dest_root}")
    
    # Check source files
    missing = verify_source_files(source_root, file_mapping)
    if missing:
        print("\nMissing source files:")
        for file in missing:
            print(f"  {source_root / file}")
    
    # Copy files
    copied = []
    failed = []
    
    for src, dest in file_mapping.items():
        src_path = source_root / src
        dest_path = dest_root / dest
        
        try:
            if src_path.exists():
                if not dry_run:
                    dest_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src_path, dest_path)
                copied.append((src, dest))
                print(f"{'Would copy' if dry_run else 'Copied'}: {src} -> {dest}")
            else:
                failed.append((src, "Source file not found"))
        except Exception as e:
            failed.append((src, str(e)))
            print(f"Error copying {src}: {e}")
    
    return copied, failed

def main():
    # Verify paths first
    paths = verify_paths()
    
    # Define all file mappings
    AGENTS_FILES = {
        "agents/base.py": "src/agents/base.py",
        "agents/discovery.py": "src/agents/discovery.py",
        "agents/solution_designer.py": "src/agents/solution_designer.py",
        "agents/coder.py": "src/agents/coder.py",
        "agents/assurance.py": "src/agents/assurance.py",
        
        "skills/semantic_iterator.py": "src/skills/semantic_iterator.py",
        "skills/semantic_merge.py": "src/skills/semantic_merge.py",
        "skills/semantic_extract.py": "src/skills/semantic_extract.py",
        "skills/asset_manager.py": "src/skills/asset_manager.py",
        "skills/_semantic_fast.py": "src/skills/_semantic_fast.py",
        "skills/_semantic_slow.py": "src/skills/_semantic_slow.py",
        
        "skills/shared/types.py": "src/skills/shared/types.py",
        "skills/shared/markdown_utils.py": "src/skills/shared/markdown_utils.py",
    }
    
    # First do a dry run
    print("\nPerforming dry run...")
    copied, failed = copy_with_verification(
        paths['SOURCE_ROOT'], 
        paths['AGENTS_ROOT'], 
        AGENTS_FILES,
        "core files",
        dry_run=True
    )
    
    print("\nDry run summary:")
    print(f"Files to be copied: {len(copied)}")
    print(f"Expected failures: {len(failed)}")
    
    if failed:
        print("\nExpected failures:")
        for src, error in failed:
            print(f"  {src}: {error}")
    
    response = input("\nProceed with actual copy? [y/N]: ")
    if response.lower() != 'y':
        print("Migration cancelled.")
        return
    
    # Perform actual copy
    copied, failed = copy_with_verification(
        paths['SOURCE_ROOT'], 
        paths['AGENTS_ROOT'], 
        AGENTS_FILES,
        "core files"
    )
    
    print("\nFinal Results:")
    print(f"Successfully copied: {len(copied)}")
    print(f"Failed: {len(failed)}")
    
    if failed:
        print("\nFailed copies:")
        for src, error in failed:
            print(f"  {src}: {error}")

if __name__ == "__main__":
    main()
