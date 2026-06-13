import asyncio
import logging
import json
from services.groq_client import get_groq_client
from services.telemetry import get_telemetry_service
from services.memory import get_memory_service

logger = logging.getLogger(__name__)

class InvestigationAgent:
    def __init__(self):
        self.telemetry = get_telemetry_service()
        self.memory = get_memory_service()
        self.groq = get_groq_client()

    async def _run_log_subagent(self, service_name: str) -> dict:
        logs = await self.telemetry.get_logs(service_name, limit=20)
        if not logs:
            return {"error_patterns": [], "stack_traces": []}
            
        system = (
            "You are an expert log analyzer. Analyze the provided logs for the service. "
            "Extract any recurring error patterns and stack traces. Respond in valid JSON "
            "with fields: 'error_patterns' (list of strings) and 'stack_traces' (list of strings)."
        )
        user = f"Logs for service '{service_name}':\n{json.dumps(logs, indent=2)}"
        try:
            res = self.groq.chat_json([{"role": "user", "content": user}], system=system)
            return {
                "error_patterns": res.get("error_patterns", []),
                "stack_traces": res.get("stack_traces", [])
            }
        except Exception as e:
            logger.warning(f"Log subagent LLM call failed: {e}")
            return {"error_patterns": [], "stack_traces": []}

    async def _run_trace_subagent(self, service_name: str) -> dict:
        traces = await self.telemetry.get_traces(service_name, limit=5)
        if not traces:
            return {"bottleneck_service": "none", "max_latency_ms": 0.0}
            
        system = (
            "You are an expert trace analyzer. Analyze the Jaeger trace data. "
            "Find the bottleneck service causing issues and the maximum latency. "
            "Respond in valid JSON with fields: 'bottleneck_service' (string) and "
            "'max_latency_ms' (float or int)."
        )
        user = f"Traces for service '{service_name}':\n{json.dumps(traces, indent=2)}"
        try:
            res = self.groq.chat_json([{"role": "user", "content": user}], system=system)
            return {
                "bottleneck_service": res.get("bottleneck_service", "none"),
                "max_latency_ms": float(res.get("max_latency_ms", 0.0))
            }
        except Exception as e:
            logger.warning(f"Trace subagent LLM call failed: {e}")
            return {"bottleneck_service": "none", "max_latency_ms": 0.0}

    async def _run_deploy_subagent(self, service_name: str) -> dict:
        deployments = await self.telemetry.get_deployments(service_name)
        if not deployments:
            return {"correlation_score": 0.0}
            
        system = (
            "You are a deployment analyst. Correlate recent container deployments or restarts "
            "with the current incident. Determine a correlation score between 0.0 (no correlation) "
            "and 1.0 (high correlation). Respond in valid JSON with fields: 'correlation_score' (float)."
        )
        user = f"Deployments for service '{service_name}':\n{json.dumps(deployments, indent=2)}"
        try:
            res = self.groq.chat_json([{"role": "user", "content": user}], system=system)
            return {"correlation_score": float(res.get("correlation_score", 0.0))}
        except Exception as e:
            logger.warning(f"Deploy subagent LLM call failed: {e}")
            return {"correlation_score": 0.0}

    async def _run_memory_subagent(self, service_name: str) -> dict:
        past_incidents = await self.memory.find_similar_incidents(service_name, limit=3)
        if not past_incidents:
            return {
                "past_root_cause": "none",
                "past_action": "none",
                "past_confidence": 0.0
            }
            
        system = (
            "You are an incident memory analyzer. Review these similar past resolved incidents. "
            "Summarize the past root cause, past action taken, and past confidence. "
            "Respond in valid JSON with fields: 'past_root_cause' (string), 'past_action' (string), "
            "and 'past_confidence' (float)."
        )
        user = f"Past resolved incidents for '{service_name}':\n{json.dumps(past_incidents, indent=2)}"
        try:
            res = self.groq.chat_json([{"role": "user", "content": user}], system=system)
            return {
                "past_root_cause": res.get("past_root_cause", "none"),
                "past_action": res.get("past_action", "none"),
                "past_confidence": float(res.get("past_confidence", 0.0))
            }
        except Exception as e:
            logger.warning(f"Memory subagent LLM call failed: {e}")
            return {
                "past_root_cause": "none",
                "past_action": "none",
                "past_confidence": 0.0
            }

    async def run(self, service_name: str, issue_type: str) -> dict:
        logger.info(f"Triggering parallel Swarm subagents for {service_name}...")
        
        # Fire all 4 subagents in parallel using asyncio.gather
        log_res, trace_res, deploy_res, mem_res = await asyncio.gather(
            self._run_log_subagent(service_name),
            self._run_trace_subagent(service_name),
            self._run_deploy_subagent(service_name),
            self._run_memory_subagent(service_name)
        )
        
        logger.info("Swarm investigation complete. Running Root Cause fusion LLM call...")
        
        # Lead RCA Agent fuses outputs
        system_fuse = (
            f"You are the lead Root Cause Analysis Agent. Review the findings from the Log, "
            f"Trace, Deploy, and Memory subagents for the incident on service '{service_name}' "
            f"(issue type: '{issue_type}'). Fuse these inputs to determine the primary root cause, "
            f"a confidence score (float 0.0 to 1.0), a step-by-step reasoning chain, and concrete evidence. "
            f"Respond in valid JSON with fields: 'root_cause' (string), 'confidence' (float), "
            f"'reasoning_chain' (list of strings), and 'evidence' (list of strings)."
        )
        
        user_fuse = (
            f"Subagent Findings for Incident on service '{service_name}':\n\n"
            f"1. Log Subagent (Error patterns & Stack traces):\n{json.dumps(log_res, indent=2)}\n\n"
            f"2. Trace Subagent (Latency bottleneck):\n{json.dumps(trace_res, indent=2)}\n\n"
            f"3. Deploy Subagent (Restart correlation):\n{json.dumps(deploy_res, indent=2)}\n\n"
            f"4. Memory Subagent (Similar past incidents):\n{json.dumps(mem_res, indent=2)}"
        )
        
        try:
            res = self.groq.chat_json([{"role": "user", "content": user_fuse}], system=system_fuse)
            return {
                "root_cause": res.get("root_cause", "Unknown anomaly"),
                "confidence": float(res.get("confidence", 0.5)),
                "reasoning_chain": res.get("reasoning_chain", ["No telemetry data available"]),
                "evidence": res.get("evidence", ["Empty telemetry metrics"])
            }
        except Exception as e:
            logger.error(f"Root cause fusion failed: {e}")
            return {
                "root_cause": f"Failed to perform RCA fusion: {e}",
                "confidence": 0.0,
                "reasoning_chain": ["LLM fusion error"],
                "evidence": []
            }
