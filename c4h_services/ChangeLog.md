# ChangeLog

## 0.2.0 - Jobs API Client

### Added
- New `jobs` client mode in prefect_runner.py that interacts with the Jobs API
- Support for sending job requests with structured configuration
- Support for polling job status and retrieving changes
- Appropriate configuration mapping between flat workflow config and structured job config

### Changed
- Updated CLI argument parser to accept `jobs` as a valid mode
- Enhanced configuration processing to map between formats

### Fixed
- Ensured full configuration preservation during translation between formats

## 0.1.0 - Initial Release

### Added
- Team-based workflow execution
- Prefect integration for task management
- API service for workflow submission and status checking
- Client mode for workflow execution
- Lineage tracking for workflow continuations