import logging
from services.mongo import get_mongo_service

logger = logging.getLogger(__name__)

class MemoryService:
    def __init__(self):
        self.mongo = get_mongo_service()

    async def find_similar_incidents(self, service: str, limit: int = 3) -> list[dict]:
        try:
            # Query: incidents where service matches + status=RESOLVED
            # Projection: root_cause, recommended_action (alias as action), confidence, validation_status only
            cursor = self.mongo.incidents.find(
                {"service": service, "status": "RESOLVED"},
                {
                    "_id": 0,
                    "root_cause": 1,
                    "recommended_action": 1,
                    "action": 1,
                    "confidence": 1,
                    "validation_status": 1
                }
            ).sort("created_at", -1).limit(limit)
            
            results = await cursor.to_list(length=limit)
            
            # Post-process to ensure we match fields and restrict token usage (max ~120 tokens per result or total)
            formatted_results = []
            for doc in results:
                # Support both naming conventions
                action = doc.get("recommended_action") or doc.get("action") or "UNKNOWN"
                root_cause = doc.get("root_cause", "")
                
                # Truncate root_cause text if too long to save tokens
                if len(root_cause) > 300:
                    root_cause = root_cause[:300] + "..."
                
                formatted_results.append({
                    "root_cause": root_cause,
                    "recommended_action": action,
                    "action": action,
                    "confidence": doc.get("confidence", 0.0),
                    "validation_status": doc.get("validation_status", "unknown")
                })
            return formatted_results
        except Exception as e:
            logger.error(f"Error finding similar incidents: {e}")
            return []

    async def get_action_success_rates(self, service: str) -> dict:
        try:
            # Query all finished incidents for the service
            cursor = self.mongo.incidents.find(
                {"service": service, "status": {"$in": ["RESOLVED", "ESCALATED"]}},
                {"_id": 0, "recommended_action": 1, "action": 1, "status": 1, "validation_status": 1}
            )
            incidents = await cursor.to_list(length=None)
            
            action_stats = {}
            for inc in incidents:
                action = inc.get("recommended_action") or inc.get("action")
                if not action:
                    continue
                
                status = inc.get("status")
                val_status = inc.get("validation_status")
                
                # Success if resolved and not failed validation
                is_success = (status == "RESOLVED" and val_status != "failed")
                
                if action not in action_stats:
                    action_stats[action] = {"success": 0, "total": 0}
                
                action_stats[action]["total"] += 1
                if is_success:
                    action_stats[action]["success"] += 1
            
            # Compute success rates
            rates = {}
            for action, stats in action_stats.items():
                rates[action] = round(stats["success"] / stats["total"], 2) if stats["total"] > 0 else 0.0
                
            # Fallback defaults for standard actions if not present in history
            defaults = {"ROLLBACK": 1.0, "RESTART": 1.0, "SCALE": 1.0}
            for act, val in defaults.items():
                if act not in rates:
                    rates[act] = val
                    
            return rates
        except Exception as e:
            logger.error(f"Error calculating action success rates: {e}")
            return {"ROLLBACK": 1.0, "RESTART": 1.0, "SCALE": 1.0}

    async def create_indexes(self):
        await self.mongo.create_indexes()

_memory_instance = None

def get_memory_service() -> MemoryService:
    global _memory_instance
    if _memory_instance is None:
        _memory_instance = MemoryService()
    return _memory_instance
