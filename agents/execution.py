import logging
from datetime import datetime
from services.docker_service import execute_restart, execute_rollback, execute_scale

logger = logging.getLogger(__name__)

class ExecutionAgent:
    def __init__(self):
        pass

    async def run(self, state: dict) -> dict:
        # Guard 1: Safety assertion
        if not state.get("approved") or state.get("blocked"):
            raise RuntimeError("ExecutionAgent called without Safety approval")

        # Guard 2: Approval halt
        if state.get("requires_human_approval") and not state.get("human_approved"):
            logger.info("Requires human approval and not approved yet. Halting.")
            return {
                "status": "PENDING_APPROVAL",
                "execution_success": None
            }

        service = state.get("service")
        action = state.get("recommended_action") or state.get("action")
        replicas = int(state.get("replicas", 2))

        logger.info(f"ExecutionAgent running remediation action '{action}' on service '{service}'")

        # Record pre-action details
        pre_action_time = datetime.utcnow()

        # Execute action based on type
        if action == "RESTART":
            res = await execute_restart(service)
        elif action == "ROLLBACK":
            res = await execute_rollback(service)
        elif action == "SCALE":
            res = await execute_scale(service, replicas)
        else:
            res = {"success": False, "stderr": f"Unknown action '{action}'", "returncode": -1}

        # Check outcomes and enforce "no fake success"
        success = res.get("success", False)
        stdout = res.get("stdout", "")
        stderr = res.get("stderr", "")

        status = "EXECUTION_SUCCESS" if success else "FAILED"
        
        # Build audit trail entry
        audit_entry = {
            "timestamp": datetime.utcnow(),
            "action": action,
            "success": success,
            "pre_action_time": pre_action_time,
            "stdout": stdout,
            "stderr": stderr
        }

        # Retrieve current audit trail and append
        audit_trail = list(state.get("audit_trail", []))
        audit_trail.append(audit_entry)

        return {
            "execution_success": success,
            "execution_details": stdout if success else stderr,
            "status": status,
            "audit_trail": audit_trail
        }
