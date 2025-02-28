"""
Path: c4h_services/examples/check_lineage.py
Simple tool to verify lineage records were created
"""
#!/usr/bin/env python3

import sys
from pathlib import Path
import json
import argparse
from datetime import datetime, timedelta

def find_lineage_records(lineage_dir: Path, hours: int = 24):
    """Find lineage records created in the last N hours"""
    if not lineage_dir.exists():
        print(f"Lineage directory not found: {lineage_dir}")
        return []
        
    # Get the cutoff time
    cutoff = datetime.now() - timedelta(hours=hours)
    
    # Find all lineage directories
    found_records = []
    date_dirs = sorted([d for d in lineage_dir.iterdir() if d.is_dir()], reverse=True)
    
    for date_dir in date_dirs:
        run_dirs = [d for d in date_dir.iterdir() if d.is_dir()]
        for run_dir in run_dirs:
            events_dir = run_dir / "events"
            if not events_dir.exists():
                continue
                
            event_files = list(events_dir.glob("*.json"))
            if not event_files:
                continue
                
            # Get the most recent event file
            newest_event = max(event_files, key=lambda p: p.stat().st_mtime)
            mtime = datetime.fromtimestamp(newest_event.stat().st_mtime)
            
            if mtime >= cutoff:
                # Check basic event structure
                try:
                    with open(newest_event) as f:
                        event_data = json.load(f)
                    found_records.append({
                        "run_id": run_dir.name,
                        "events": len(event_files),
                        "latest_event": newest_event.name,
                        "timestamp": mtime.isoformat(),
                        "event_types": list(set(str(ef.stem).split('_')[0] for ef in event_files)),
                        "agent": event_data.get("agent", "unknown")
                    })
                except Exception as e:
                    print(f"Error reading event {newest_event}: {e}")
    
    return found_records

def main():
    parser = argparse.ArgumentParser(description="Check for lineage records")
    parser.add_argument("--dir", default="workspaces/lineage", help="Lineage directory")
    parser.add_argument("--hours", type=int, default=24, help="Hours to look back")
    
    args = parser.parse_args()
    lineage_dir = Path(args.dir)
    
    records = find_lineage_records(lineage_dir, args.hours)
    
    if not records:
        print(f"No lineage records found in {lineage_dir} from the last {args.hours} hours")
        return 1
        
    print(f"Found {len(records)} lineage records:")
    for record in records:
        print(f"Run ID: {record['run_id']}")
        print(f"  Agent: {record['agent']}")
        print(f"  Events: {record['events']}")
        print(f"  Event types: {', '.join(record['event_types'])}")
        print(f"  Latest event: {record['latest_event']}")
        print(f"  Timestamp: {record['timestamp']}")
        print()
        
    return 0

if __name__ == "__main__":
    sys.exit(main())