import os
import asyncio
import logging
from services.telemetry import get_telemetry_service
from services.governance import get_governance_service

logger = logging.getLogger(__name__)

class ValidationAgent:
    def __init__(self):
        self.telemetry = get_telemetry_service()
        self.governance = get_governance_service()

    async def run(self, state: dict) -> dict:
        service = state.get("service")
        incident_id = state.get("id")
        
        # Enforce minimum wait time: max(10, VALIDATION_WAIT_SECONDS)
        wait_seconds = max(10, int(os.getenv("VALIDATION_WAIT_SECONDS", "60")))
        logger.info(f"ValidationAgent sleeping for {wait_seconds}s before checking recovery...")
        await asyncio.sleep(wait_seconds)

        # Check telemetry health status
        health = await self.telemetry.health_check(service)
        latency_threshold = float(os.getenv("LATENCY_THRESHOLD_MS", "2000"))
        
        # Connection failure or timeout returns status='degraded' and latency_ms=0 in telemetry mock
        is_telemetry_unavailable = (health.get("status") == "degraded" and health.get("latency_ms") == 0)
        demo_mode = os.getenv("DEMO_MODE", "false").lower() == "true"

        if is_telemetry_unavailable:
            if demo_mode:
                logger.info("DEMO_MODE: assumed healthy — no telemetry.")
                return {
                    "validation_status": "metrics_unavailable",
                    "status": "RESOLVED"
                }
            else:
                logger.warning("RECOVERY FAILED — manual intervention required. Telemetry unavailable.")
                await self.governance.log_validation(incident_id, False)
                return {
                    "validation_status": "failed",
                    "status": "ESCALATED",
                    "blocked": True
                }

        # Telemetry is available, check status and latency thresholds
        is_healthy = (health.get("status") == "healthy" and health.get("latency_ms") <= latency_threshold)

        if is_healthy:
            logger.info(f"Service '{service}' recovered successfully. Latency={health.get('latency_ms')}ms")
            return {
                "validation_status": "healthy",
                "status": "RESOLVED"
            }
        else:
            logger.warning("RECOVERY FAILED — manual intervention required.")
            await self.governance.log_validation(incident_id, False)
            return {
                "validation_status": "failed",
                "status": "ESCALATED",
                "blocked": True
            }
