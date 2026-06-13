import logging
from services.groq_client import get_groq_client
from services.memory import get_memory_service

logger = logging.getLogger(__name__)

class DecisionAgent:
    def __init__(self):
        self.memory = get_memory_service()
        self.groq = get_groq_client()

    async def run(self, state: dict) -> dict:
        service = state.get("service")
        root_cause = state.get("root_cause", "")
        reasoning_chain = state.get("reasoning_chain", [])
        
        logger.info(f"Running Decision Agent for service {service}")

        # 1. MongoDB Fast Path:
        # Check if memory has resolved incidents for this service with high confidence (> 0.90)
        past_incidents = await self.memory.find_similar_incidents(service, limit=3)
        for incident in past_incidents:
            past_conf = incident.get("confidence", 0.0)
            past_action = incident.get("recommended_action") or incident.get("action")
            val_status = incident.get("validation_status")
            
            if past_conf >= 0.90 and past_action in ["RESTART", "ROLLBACK", "SCALE"] and val_status == "healthy":
                logger.info(f"Fast path triggered: using past action '{past_action}' with confidence {past_conf}")
                # Blast radius rules: RESTART=1, ROLLBACK=1, SCALE=1-3
                blast_radius = 1
                return {
                    "recommended_action": past_action,
                    "action": past_action,
                    "blast_radius": blast_radius,
                    "rationale": f"Fast-path MongoDB memory match found. Reused successful past action '{past_action}' from incident with confidence {past_conf}.",
                    "confidence_in_decision": past_conf,
                    "confidence": past_conf,
                    "memory_match_used": True
                }

        # 2. LLM Action Ranking:
        # Fetch past action success rates
        success_rates = await self.memory.get_action_success_rates(service)
        
        system = (
            "You are the incident remediation Decision Agent. Your goal is to rank candidate remediation actions "
            "(RESTART, ROLLBACK, SCALE) for the service incident. "
            "Select the best action, determine the blast_radius (integer: number of services affected. "
            "RESTART=1, ROLLBACK=1, SCALE=1-3 based on replicas/scope), and provide a concise rationale. "
            "Respond in valid JSON with fields: 'recommended_action' (string, must be one of RESTART, ROLLBACK, SCALE), "
            "'blast_radius' (integer), 'rationale' (string), and 'confidence_in_decision' (float 0.0 to 1.0)."
        )
        
        user = (
            f"Incident details:\n"
            f"Service: {service}\n"
            f"Root cause: {root_cause}\n"
            f"Reasoning chain: {', '.join(reasoning_chain)}\n\n"
            f"Historical remediation success rates for '{service}':\n"
            f"{success_rates}\n\n"
            f"Candidate Actions:\n"
            f"- RESTART: Cycle service containers (blast_radius = 1)\n"
            f"- ROLLBACK: Reset service to previous stable version (blast_radius = 1)\n"
            f"- SCALE: Scale service containers to handle load (blast_radius = 1 to 3 depending on replicas needed)"
        )
        
        try:
            res = self.groq.chat_json([{"role": "user", "content": user}], system=system)
            rec_action = res.get("recommended_action", "RESTART").upper()
            if rec_action not in ["RESTART", "ROLLBACK", "SCALE"]:
                rec_action = "RESTART"
                
            blast_radius = int(res.get("blast_radius", 1))
            # Validate blast radius constraints
            if rec_action in ["RESTART", "ROLLBACK"]:
                blast_radius = 1
            else:
                blast_radius = max(1, min(blast_radius, 3))
                
            conf = float(res.get("confidence_in_decision", 0.70))
            
            return {
                "recommended_action": rec_action,
                "action": rec_action,
                "blast_radius": blast_radius,
                "rationale": res.get("rationale", "Selected default RESTART action due to LLM parsing fallback."),
                "confidence_in_decision": conf,
                "confidence": conf,
                "memory_match_used": False
            }
        except Exception as e:
            logger.error(f"Decision agent LLM call failed: {e}")
            return {
                "recommended_action": "RESTART",
                "action": "RESTART",
                "blast_radius": 1,
                "rationale": f"Fallback to RESTART due to decision error: {e}",
                "confidence_in_decision": 0.5,
                "confidence": 0.5,
                "memory_match_used": False
            }
