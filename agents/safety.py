import os
import time
import logging
from services.docker_service import get_last_execution_time

logger = logging.getLogger(__name__)

class SafetyAgent:
    def __init__(self):
        pass

    def evaluate(self, state: dict) -> dict:
        """
        Evaluates safety rules on the given state dictionary.
        Modifies and returns a safety outcome dictionary.
        """
        # Load safety settings dynamically from environment
        min_confidence = float(os.getenv("MIN_CONFIDENCE", "0.70"))
        
        protected_str = os.getenv("PROTECTED_SERVICES", "")
        protected_services = [s.strip() for s in protected_str.split(",") if s.strip()]
        
        cooldown_seconds = float(os.getenv("COOLDOWN_SECONDS", "300"))
        max_blast_radius = int(os.getenv("MAX_BLAST_RADIUS", "3"))
        demo_mode = os.getenv("DEMO_MODE", "false").lower() == "true"

        service = state.get("service")
        action = state.get("recommended_action") or state.get("action")
        confidence = float(state.get("confidence", 0.0))
        blast_radius = int(state.get("blast_radius", 1))
        memory_match_used = bool(state.get("memory_match_used", False))

        logger.info(f"Safety evaluation for service={service}, action={action}, confidence={confidence}, blast_radius={blast_radius}")

        # Layer 1: Deterministic Hard Rules
        # R1: Confidence too low
        if confidence < min_confidence:
            return {
                "approved": False,
                "blocked": True,
                "requires_human_approval": False,
                "block_reason": "confidence_below_threshold",
                "zone": "BLACK"
            }

        # R2: Action not whitelisted
        whitelist = ["ROLLBACK", "RESTART", "SCALE"]
        if action not in whitelist:
            return {
                "approved": False,
                "blocked": True,
                "requires_human_approval": False,
                "block_reason": "action_not_whitelisted",
                "zone": "BLACK"
            }

        # R3: Protected service
        if service in protected_services:
            return {
                "approved": False,
                "blocked": True,
                "requires_human_approval": False,
                "block_reason": "protected_service",
                "zone": "BLACK"
            }

        # R4: Cooldown check (skipped in DEMO_MODE only)
        if not demo_mode:
            last_exec = get_last_execution_time(service)
            if last_exec > 0 and (time.time() - last_exec) < cooldown_seconds:
                return {
                    "approved": False,
                    "blocked": True,
                    "requires_human_approval": False,
                    "block_reason": "cooldown_active",
                    "zone": "BLACK"
                }

        # R5: Blast radius exceeded
        if blast_radius > max_blast_radius:
            return {
                "approved": False,
                "blocked": True,
                "requires_human_approval": False,
                "block_reason": "blast_radius_exceeded",
                "zone": "BLACK"
            }

        # Layer 2: Three-Zone Classification
        # Green Zone
        if action == "RESTART" and confidence >= 0.70 and blast_radius <= 1:
            return {
                "approved": True,
                "blocked": False,
                "requires_human_approval": False,
                "block_reason": None,
                "zone": "GREEN"
            }

        # Yellow Auto Zone (ROLLBACK with memory match and high confidence)
        if action == "ROLLBACK" and confidence >= 0.90 and memory_match_used:
            return {
                "approved": True,
                "blocked": False,
                "requires_human_approval": False,
                "block_reason": None,
                "zone": "YELLOW_AUTO"
            }

        # Yellow Gated Zone (ROLLBACK with medium confidence)
        if action == "ROLLBACK" and 0.70 <= confidence <= 0.89:
            return {
                "approved": False,
                "blocked": False,
                "requires_human_approval": True,
                "block_reason": None,
                "zone": "YELLOW_GATED"
            }

        # Yellow Zone (SCALE with blast_radius <= 2)
        if action == "SCALE" and blast_radius <= 2:
            return {
                "approved": True,
                "blocked": False,
                "requires_human_approval": False,
                "block_reason": None,
                "zone": "YELLOW"
            }

        # Red Zone (Any other combination)
        return {
            "approved": False,
            "blocked": False,
            "requires_human_approval": True,
            "block_reason": None,
            "zone": "RED"
        }
