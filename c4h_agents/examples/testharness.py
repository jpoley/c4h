"""
Primary coder agent implementation with improved data handling.
Path: c4h_agents/agents/coder.py
"""

class Coder(BaseAgent):
    def _get_required_keys(self) -> List[str]:
        """Define keys required by coder agent."""
        return ['input_data']  # We expect the full input data object

    def process(self, context: Dict[str, Any]) -> AgentResponse:
        """Process code changes using semantic extraction"""
        logger.info("coder.process_start", context_keys=list(context.keys()))
        logger.debug("coder.input_data", data=context)

        try:
            # Get required data using inheritance
            data = self._get_data(context)
            input_data = data.get('input_data', {})
            
            # Handle both string and dict response formats
            response_data = input_data.get('response', input_data)
            if isinstance(response_data, str):
                try:
                    response_data = json.loads(response_data)
                except json.JSONDecodeError:
                    logger.error("coder.json_parse_failed", 
                               error="Invalid JSON in response")
                    return AgentResponse(success=False, 
                                      data={}, 
                                      error="Invalid JSON in response")

            # Extract changes array
            changes = response_data.get('changes', [])
            if not isinstance(changes, list):
                logger.error("coder.invalid_changes",
                           error="Changes must be an array")
                return AgentResponse(success=False,
                                  data={},
                                  error="Changes must be an array")

            logger.debug("coder.processing_changes", count=len(changes))
            
            # Process changes
            results = []
            for change in changes:
                logger.debug("coder.processing_change", change=change)
                result = self.asset_manager.process_action(change)
                
                if result.success:
                    logger.info("coder.change_applied",
                              file=str(result.path))
                    self.operation_metrics.successful_changes += 1
                else:
                    logger.error("coder.change_failed", 
                               file=str(result.path),
                               error=result.error)
                    self.operation_metrics.failed_changes += 1
                    self.operation_metrics.error_count += 1
                
                self.operation_metrics.total_changes += 1
                results.append(result)

            # Return results
            success = bool(results) and any(r.success for r in results)
            
            return AgentResponse(
                success=success,
                data={
                    "changes": [
                        {
                            "file": str(r.path),
                            "success": r.success,
                            "error": r.error,
                            "backup": str(r.backup_path) if r.backup_path else None
                        }
                        for r in results
                    ],
                    "metrics": vars(self.operation_metrics)
                },
                error=None if success else "No changes were successful"
            )

        except Exception as e:
            logger.error("coder.process_failed", error=str(e))
            self.operation_metrics.error_count += 1
            return AgentResponse(success=False, data={}, error=str(e))