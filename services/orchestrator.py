import asyncio
import logging
import uuid
from datetime import datetime
from services.mongo import get_mongo_service
from services.governance import get_governance_service
from agents.safety import SafetyAgent

logger = logging.getLogger(__name__)

class Orchestrator:
    def __init__(self):
        self.mongo = get_mongo_service()
        self.governance = get_governance_service()
        self.safety = SafetyAgent()
        self._investigation = None
        self._decision = None
        self._execution = None
        self._validation = None
        self._rca = None

    def get_investigation_agent(self):
        if self._investigation is None:
            from agents.investigation import InvestigationAgent
            self._investigation = InvestigationAgent()
        return self._investigation

    def get_decision_agent(self):
        if self._decision is None:
            from agents.decision import DecisionAgent
            self._decision = DecisionAgent()
        return self._decision

    def get_execution_agent(self):
        if self._execution is None:
            from agents.execution import ExecutionAgent
            self._execution = ExecutionAgent()
        return self._execution

    def get_validation_agent(self):
        if self._validation is None:
            from agents.validation import ValidationAgent
            self._validation = ValidationAgent()
        return self._validation

    def get_rca_agent(self):
        if self._rca is None:
            from agents.rca_agent import RcaAgent
            self._rca = RcaAgent()
        return self._rca

    async def start_pipeline(self, service: str, issue_type: str) -> str:
        incident_id = str(uuid.uuid4())
        incident = {
            "id": incident_id,
            "service": service,
            "issue_type": issue_type,
            "status": "OPEN",
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
            "human_approved": False,
            "audit_trail": []
        }
        await self.mongo.incidents.insert_one(incident)
        logger.info(f"Triggered pipeline for incident {incident_id} ({service} - {issue_type})")
        
        asyncio.create_task(self.run_pipeline_with_timeout(incident_id))
        return incident_id

    async def resume_pipeline(self, incident_id: str) -> bool:
        incident = await self.mongo.incidents.find_one({"id": incident_id})
        if not incident:
            logger.error(f"Incident {incident_id} not found, cannot resume pipeline")
            return False
            
        if incident.get("status") != "PENDING_APPROVAL":
            logger.warning(f"Incident {incident_id} is in status {incident.get('status')}, cannot resume")
            return False
            
        await self.mongo.incidents.update_one(
            {"id": incident_id},
            {
                "$set": {
                    "human_approved": True,
                    "status": "OPEN",
                    "updated_at": datetime.utcnow()
                }
            }
        )
        logger.info(f"Resuming pipeline for incident {incident_id} (human approved = True)")
        
        asyncio.create_task(self.run_pipeline_with_timeout(incident_id))
        return True

    async def run_pipeline_with_timeout(self, incident_id: str):
        try:
            # 600 second hard timeout limit for the entire pipeline
            await asyncio.wait_for(self._execute_pipeline_flow(incident_id), timeout=600.0)
        except asyncio.TimeoutError:
            logger.error(f"Incident {incident_id} execution TIMEOUT after 600s.")
            await self.mongo.incidents.update_one(
                {"id": incident_id},
                {
                    "$set": {
                        "status": "TIMEOUT",
                        "updated_at": datetime.utcnow()
                    }
                }
            )
        except Exception as e:
            logger.error(f"Pipeline crashed for incident {incident_id}: {e}", exc_info=True)
            await self.mongo.incidents.update_one(
                {"id": incident_id},
                {
                    "$set": {
                        "status": "FAILED",
                        "updated_at": datetime.utcnow(),
                        "error_details": str(e)
                    }
                }
            )

    async def _execute_pipeline_flow(self, incident_id: str):
        state = await self.mongo.incidents.find_one({"id": incident_id})
        if not state:
            return
            
        # 1. Autonomy Gate Check
        autonomy = await self.governance.get_autonomy_level()
        if autonomy == "ESCALATE_ALL":
            logger.warning(f"Autonomy is ESCALATE_ALL. Halting execution of pipeline for {incident_id} immediately.")
            await self.mongo.incidents.update_one(
                {"id": incident_id},
                {
                    "$set": {
                        "status": "ESCALATED",
                        "validation_status": "failed",
                        "updated_at": datetime.utcnow()
                    }
                }
            )
            # Log dummy failure to governance
            action = state.get("recommended_action") or state.get("action") or "NONE"
            await self.governance.log_decision(incident_id, state.get("service"), action, 0.0)
            await self.governance.log_validation(incident_id, False)
            return

        # 2. Parallel Investigation Swarm
        if not state.get("root_cause"):
            logger.info(f"Running Swarm Investigation for incident {incident_id}...")
            inv_agent = self.get_investigation_agent()
            inv_res = await inv_agent.run(state.get("service"), state.get("issue_type"))
            state.update(inv_res)
            await self.mongo.incidents.update_one(
                {"id": incident_id},
                {"$set": {**inv_res, "updated_at": datetime.utcnow()}}
            )

        # 3. Decision Agent
        action = state.get("recommended_action") or state.get("action")
        if not action:
            logger.info(f"Running Decision Agent for incident {incident_id}...")
            dec_agent = self.get_decision_agent()
            dec_res = await dec_agent.run(state)
            state.update(dec_res)
            await self.mongo.incidents.update_one(
                {"id": incident_id},
                {"$set": {**dec_res, "updated_at": datetime.utcnow()}}
            )
            action = state.get("recommended_action") or state.get("action")

        # 4. Safety Gate Check
        logger.info(f"Running Safety Agent for incident {incident_id}...")
        safety_res = self.safety.evaluate(state)
        state.update(safety_res)
        await self.mongo.incidents.update_one(
            {"id": incident_id},
            {"$set": {**safety_res, "updated_at": datetime.utcnow()}}
        )

        # Log decision to governance events table (once)
        existing_event = await self.mongo.governance_events.find_one({"incident_id": incident_id})
        if not existing_event:
            confidence = state.get("confidence", 0.0)
            await self.governance.log_decision(incident_id, state.get("service"), action, confidence)

        if state.get("blocked"):
            logger.warning(f"Incident {incident_id} was BLOCKED by Safety rules. Reason: {state.get('block_reason')}")
            await self.mongo.incidents.update_one(
                {"id": incident_id},
                {"$set": {"status": "BLOCKED", "updated_at": datetime.utcnow()}}
            )
            await self.governance.log_validation(incident_id, False)
            return

        if state.get("requires_human_approval") and not state.get("human_approved"):
            logger.info(f"Incident {incident_id} requires human approval. Halting.")
            await self.mongo.incidents.update_one(
                {"id": incident_id},
                {"$set": {"status": "PENDING_APPROVAL", "updated_at": datetime.utcnow()}}
            )
            return

        # 5. Execution Agent
        logger.info(f"Running Execution Agent for incident {incident_id}...")
        exec_agent = self.get_execution_agent()
        exec_res = await exec_agent.run(state)
        state.update(exec_res)
        await self.mongo.incidents.update_one(
            {"id": incident_id},
            {
                "$set": {
                    **exec_res,
                    "status": state.get("status"),
                    "updated_at": datetime.utcnow()
                }
            }
        )

        if state.get("status") == "FAILED" or not state.get("execution_success"):
            logger.error(f"Execution failed for incident {incident_id}.")
            await self.governance.log_validation(incident_id, False)
            return

        # 6. Validation Agent
        logger.info(f"Running Validation Agent for incident {incident_id}...")
        val_agent = self.get_validation_agent()
        val_res = await val_agent.run(state)
        state.update(val_res)
        await self.mongo.incidents.update_one(
            {"id": incident_id},
            {
                "$set": {
                    **val_res,
                    "status": state.get("status"),
                    "updated_at": datetime.utcnow()
                }
            }
        )

        # Log validation outcome to governance
        success = state.get("status") == "RESOLVED"
        await self.governance.log_validation(incident_id, success)

        # 7. Postmortem RCA Report (Fire and forget async task)
        if state.get("status") == "RESOLVED":
            logger.info(f"Running RCA Postmortem Agent for incident {incident_id}...")
            rca_agent = self.get_rca_agent()
            asyncio.create_task(rca_agent.run(incident_id))

_orchestrator_instance = None

def get_orchestrator() -> Orchestrator:
    global _orchestrator_instance
    if _orchestrator_instance is None:
        _orchestrator_instance = Orchestrator()
    return _orchestrator_instance
