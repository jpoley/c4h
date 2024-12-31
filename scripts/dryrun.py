import shutil
from pathlib import Path
import os
import sys

def verify_source_content():
    """Verify source content and print findings"""
    source_root = Path.home() / "src/autogen/coder4h/intent_system/src"
    print(f"\nChecking source directory: {source_root}")
    print("Source directory exists:", source_root.exists())
    
    if source_root.exists():
        print("\nSource directory contents:")
        for path in source_root.rglob("*"):
            if path.is_file():
                print(f"  {path.relative_to(source_root)}")

def verify_target_content():
    """Verify target directories and print findings"""
    agents_root = Path.home() / "src/apps/c4h/c4h_agents"
    print(f"\nChecking agents directory: {agents_root}")
    print("Agents directory exists:", agents_root.exists())
    
    if agents_root.exists():
        print("\nAgents directory contents:")
        for path in agents_root.rglob("*"):
            if path.is_file():
                print(f"  {path.relative_to(agents_root)}")

def main():
    print("Starting verification...")
    verify_source_content()
    verify_target_content()

if __name__ == "__main__":
    main()
