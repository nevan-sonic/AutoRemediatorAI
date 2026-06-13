import logging
from datetime import datetime
from services.mongo import get_mongo_service

logger = logging.getLogger(__name__)

class GovernanceService:
    def __init__(self):
        self.mongo = get_mongo_service()

    async def log_decision(self, incident_id: str, service: str, action: str, confidence: float):
        event = {
            "incident_id": incident_id,
            "service": service,
            "action": action,
            "confidence": confidence,
            "timestamp": datetime.utcnow(),
            "outcome": None
        }
        await self.mongo.governance_events.insert_one(event)
        logger.info(f"Governance decision logged for incident {incident_id}")

    async def log_validation(self, incident_id: str, success: bool):
        outcome_val = "success" if success else "failure"
        result = await self.mongo.governance_events.update_one(
            {"incident_id": incident_id},
            {"$set": {"outcome": outcome_val}}
        )
        if result.modified_count > 0:
            logger.info(f"Governance validation logged for incident {incident_id} as {outcome_val}")
        else:
            logger.warning(f"No governance event found for incident_id {incident_id} to update validation")

    async def get_health_score(self) -> float:
        cursor = self.mongo.governance_events.find().sort("timestamp", -1).limit(20)
        events = await cursor.to_list(length=20)
        
        if not events:
            return 100.0  # Default to maximum health
            
        total_confidence = 0.0
        success_count = 0
        total_validations = 0
        
        for event in events:
            total_confidence += event.get("confidence", 0.0)
            outcome = event.get("outcome")
            if outcome is not None:
                total_validations += 1
                if outcome == "success":
                    success_count += 1
                    
        avg_confidence = total_confidence / len(events)
        success_rate = success_count / total_validations if total_validations > 0 else 1.0
        
        # Formula: (avg_confidence * 0.5 + success_rate * 0.5) * 100
        health_score = (avg_confidence * 0.5 + success_rate * 0.5) * 100
        return float(health_score)

    async def get_autonomy_level(self) -> str:
        score = await self.get_health_score()
        if score > 85:
            return "FULL"
        elif score >= 60:
            return "ASSISTED"
        else:
            return "ESCALATE_ALL"

    async def get_summary_metrics(self) -> dict:
        cursor = self.mongo.governance_events.find()
        events = await cursor.to_list(length=None)
        
        total_decisions = len(events)
        if total_decisions == 0:
            return {
                "avg_confidence": 0.0,
                "success_rate": 0.0,
                "drift_score": 0.0,
                "health_score": 100.0,
                "autonomy_level": "FULL",
                "total_decisions": 0
            }
            
        total_confidence = 0.0
        success_count = 0
        total_validations = 0
        
        for event in events:
            total_confidence += event.get("confidence", 0.0)
            outcome = event.get("outcome")
            if outcome is not None:
                total_validations += 1
                if outcome == "success":
                    success_count += 1
                    
        avg_confidence = total_confidence / total_decisions
        success_rate = success_count / total_validations if total_validations > 0 else 1.0
        
        health_score = await self.get_health_score()
        autonomy_level = await self.get_autonomy_level()
        
        # Drift score is the variance or shift in confidence over time (comparison of halves)
        drift_score = 0.0
        if total_decisions >= 4:
            mid = total_decisions // 2
            first_half = events[:mid]
            second_half = events[mid:]
            avg_first = sum(e.get("confidence", 0.0) for e in first_half) / len(first_half)
            avg_second = sum(e.get("confidence", 0.0) for e in second_half) / len(second_half)
            drift_score = abs(avg_first - avg_second)
            
        return {
            "avg_confidence": float(avg_confidence),
            "success_rate": float(success_rate),
            "drift_score": float(drift_score),
            "health_score": float(health_score),
            "autonomy_level": autonomy_level,
            "total_decisions": int(total_decisions)
        }

_governance_instance = None

def get_governance_service() -> GovernanceService:
    global _governance_instance
    if _governance_instance is None:
        _governance_instance = GovernanceService()
    return _governance_instance
