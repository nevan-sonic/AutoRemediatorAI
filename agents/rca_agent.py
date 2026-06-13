import logging
from datetime import datetime
from services.mongo import get_mongo_service
from services.groq_client import get_groq_client

logger = logging.getLogger(__name__)

class RcaAgent:
    def __init__(self):
        self.mongo = get_mongo_service()
        self.groq = get_groq_client()

    async def run(self, incident_id: str):
        try:
            logger.info(f"Generating RCA postmortem report for incident {incident_id}...")
            # Query incident details
            incident = await self.mongo.incidents.find_one({"id": incident_id})
            if not incident:
                logger.error(f"Incident {incident_id} not found to generate RCA.")
                return

            # Construct timeline points
            timeline_points = [f"Incident detected at {incident.get('created_at')}"]
            for audit in incident.get("audit_trail", []):
                t = audit.get("timestamp") or audit.get("pre_action_time")
                timeline_points.append(
                    f"Action '{audit.get('action')}' executed at {t} (success: {audit.get('success')})"
                )
            
            system = (
                "You are an expert incident reporter. Your task is to write a detailed, professional "
                "5-section postmortem for the resolved incident. The output must be valid JSON "
                "with the following fields:\n"
                "- 'summary' (string)\n"
                "- 'timeline' (list of strings)\n"
                "- 'root_cause_analysis' (string)\n"
                "- 'resolution_taken' (string)\n"
                "- 'prevention_recommendations' (list of strings, MUST contain exactly 3 items)."
            )
            
            user = (
                f"Incident Context:\n"
                f"- Service Name: {incident.get('service')}\n"
                f"- Issue Type: {incident.get('issue_type')}\n"
                f"- Swarm Root Cause: {incident.get('root_cause')}\n"
                f"- Remediation Action: {incident.get('recommended_action') or incident.get('action')}\n"
                f"- Execution Output: {incident.get('execution_details')}\n"
                f"- Validation Result: {incident.get('validation_status')}\n"
                f"- System Events Timeline: {timeline_points}"
            )
            
            postmortem = self.groq.chat_json([{"role": "user", "content": user}], system=system)
            
            # Guarantee exactly 3 prevention recommendations
            recs = postmortem.get("prevention_recommendations", [])
            if len(recs) != 3:
                default_recs = [
                    "Implement proactive health checks and auto-scaling rules.",
                    "Optimize memory profiling and leak detection mechanisms.",
                    "Increase rate limiting and validation boundaries at ingress."
                ]
                if len(recs) < 3:
                    recs.extend(default_recs[len(recs):])
                else:
                    recs = recs[:3]
                postmortem["prevention_recommendations"] = recs
                
            # Persist RCA to DB
            await self.mongo.incidents.update_one(
                {"id": incident_id},
                {"$set": {"rca": postmortem, "updated_at": datetime.utcnow()}}
            )
            logger.info(f"RCA postmortem report saved successfully for incident {incident_id}")
        except Exception as e:
            logger.error(f"Failed to generate RCA report for incident {incident_id}: {e}", exc_info=True)
