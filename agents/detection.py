import asyncio
import os
import logging
from services.telemetry import get_telemetry_service
from services.mongo import get_mongo_service
from services.orchestrator import get_orchestrator

logger = logging.getLogger(__name__)

class DetectionAgent:
    def __init__(self):
        self.telemetry = get_telemetry_service()
        self.mongo = get_mongo_service()
        self.loop_task = None

    def start(self):
        if self.loop_task is None:
            self.loop_task = asyncio.create_task(self._poll_loop())
            logger.info("DetectionAgent polling loop started.")

    def stop(self):
        if self.loop_task:
            self.loop_task.cancel()
            self.loop_task = None
            logger.info("DetectionAgent polling loop stopped.")

    async def _poll_loop(self):
        # Default monitored services if not set in environment
        monitored_str = os.getenv("MONITORED_SERVICES", "payment-service,inventory-service,order-service")
        services = [s.strip() for s in monitored_str.split(",") if s.strip()]
        
        while True:
            try:
                latency_threshold = float(os.getenv("LATENCY_THRESHOLD_MS", "2000"))
                for service in services:
                    # Deduplication check: check if an active incident already exists
                    active_incident = await self.mongo.incidents.find_one({
                        "service": service,
                        "status": {"$in": ["OPEN", "PENDING_APPROVAL", "EXECUTION_IN_PROGRESS"]}
                    })
                    
                    if active_incident:
                        logger.debug(f"Incident {active_incident['id']} already active for {service}, skipping detection check.")
                        continue
                    
                    # Fetch direct health metrics
                    health = await self.telemetry.health_check(service)
                    latency_ms = health.get("latency_ms", 0)
                    status = health.get("status")
                    
                    # Ignore offline mock services (telemetry down) to prevent auto-flooding incident feed
                    if status == "degraded" and latency_ms == 0:
                        continue
                    
                    if latency_ms > latency_threshold or status == "degraded":
                        logger.warning(f"Anomaly detected for {service}: status={status}, latency={latency_ms}ms (threshold={latency_threshold}ms).")
                        
                        # Create and trigger pipeline
                        issue_type = "high_latency" if latency_ms > latency_threshold else "degraded_status"
                        orch = get_orchestrator()
                        await orch.start_pipeline(service, issue_type)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in DetectionAgent polling loop: {e}", exc_info=True)
                
            await asyncio.sleep(30)

_detection_agent = None

def get_detection_agent() -> DetectionAgent:
    global _detection_agent
    if _detection_agent is None:
        _detection_agent = DetectionAgent()
    return _detection_agent
