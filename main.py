import time
import os
import uuid
import logging
import asyncio
import json
from datetime import datetime, timezone
from fastapi import FastAPI, Request, Response, status, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from services.mongo import get_mongo_service
from services.governance import get_governance_service
from services.orchestrator import get_orchestrator
from agents.detection import get_detection_agent
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

# Set up OpenTelemetry distributed tracing to Jaeger
provider = TracerProvider()
otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://jaeger:4317")
otlp_exporter = OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True)
provider.add_span_processor(BatchSpanProcessor(otlp_exporter))
trace.set_tracer_provider(provider)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

# Initialize FastAPI App
app = FastAPI(
    title="AutoRemediator AI - Backend API",
    description="Autonomous incident detection, safety governance, and remediation pipeline API.",
    version="1.0.0"
)
FastAPIInstrumentor.instrument_app(app)


# CORS configuration
allowed_origins_str = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000")
origins = [origin.strip() for origin in allowed_origins_str.split(",") if origin.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Request ID Middleware
@app.middleware("http")
async def add_request_id_middleware(request: Request, call_next):
    req_id = str(uuid.uuid4())
    request.state.request_id = req_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = req_id
    return response

# Payload Models
class InjectPayload(BaseModel):
    service: str
    issue_type: str

# Module-level rate limiting cache
_rate_limits = {}

def is_rate_limited(ip: str) -> bool:
    now = time.time()
    last_request = _rate_limits.get(ip, 0.0)
    if now - last_request < 10.0:
        return True
    _rate_limits[ip] = now
    return False

@app.on_event("startup")
async def startup_event():
    # 1. Connect to MongoDB and build collection indexes
    mongo = get_mongo_service()
    mongo.connect()
    await mongo.create_indexes()
    
    # 2. Boot background anomaly detection poller
    detection = get_detection_agent()
    detection.start()
    logger.info("AutoRemediator AI Backend started successfully.")

@app.on_event("shutdown")
def shutdown_event():
    # Stop background anomaly detection poller
    detection = get_detection_agent()
    detection.stop()
    logger.info("AutoRemediator AI Backend shut down cleanly.")

# Endpoints
@app.post("/inject", status_code=status.HTTP_201_CREATED)
async def inject_failure(payload: InjectPayload, request: Request):
    """
    Simulates injecting a failure/anomaly on a microservice.
    Triggers the autonomous remediation orchestrator pipeline.
    Rate limited to 1 execution per IP every 10 seconds.
    """
    client_ip = request.client.host if request.client else "unknown"
    if is_rate_limited(client_ip):
        logger.warning(f"Rate limit hit on /inject from IP={client_ip}")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Only 1 injection request allowed every 10 seconds."
        )

    orch = get_orchestrator()
    incident_id = await orch.start_pipeline(payload.service, payload.issue_type)
    return {"incident_id": incident_id, "status": "pipeline_started"}

@app.get("/incidents")
async def list_incidents():
    """
    Lists all incidents logged in MongoDB, sorted newest to oldest.
    """
    mongo = get_mongo_service()
    cursor = mongo.incidents.find({}, {"_id": 0}).sort("created_at", -1)
    return await cursor.to_list(length=100)

@app.get("/incidents/{id}")
async def get_incident(id: str):
    """
    Retrieves execution details for a single incident ID.
    """
    mongo = get_mongo_service()
    incident = await mongo.incidents.find_one({"id": id}, {"_id": 0})
    if not incident:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Incident with ID {id} not found."
        )
    return incident

@app.post("/incidents/{id}/approve")
async def approve_incident(id: str):
    """
    Provides human approval to resume an incident halted in the PENDING_APPROVAL state.
    Sets human_approved=True and resumes pipeline execution.
    """
    orch = get_orchestrator()
    success = await orch.resume_pipeline(id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Could not approve/resume incident {id}. Verify status is PENDING_APPROVAL."
        )
    return {"success": True, "message": "Incident approved. Orchestrator resumed."}

@app.post("/incidents/{id}/reject")
async def reject_incident(id: str):
    """
    Rejects the proposed mitigation.
    Sets status=RESOLVED (or REJECTED), stopping execution.
    """
    mongo = get_mongo_service()
    result = await mongo.incidents.update_one(
        {"id": id, "status": "PENDING_APPROVAL"},
        {"$set": {"status": "BLOCKED", "blocked": True, "block_reason": "Human Rejected", "updated_at": datetime.utcnow(timezone.utc)}}
    )
    if result.modified_count == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Could not reject incident {id}. Verify status is PENDING_APPROVAL."
        )
    governance = get_governance_service()
    await governance.log_validation(id, False)
    return {"success": True, "message": "Incident rejected."}

@app.get("/incidents/{id}/rca")
async def get_incident_rca(id: str):
    """
    Fetches the 5-section postmortem RCA report. Only available if the incident status is RESOLVED.
    """
    mongo = get_mongo_service()
    incident = await mongo.incidents.find_one({"id": id})
    if not incident:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Incident with ID {id} not found."
        )

    if incident.get("status") != "RESOLVED":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="RCA postmortem report is only available for RESOLVED incidents."
        )

    rca = incident.get("rca")
    if not rca:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="RCA postmortem has not been generated or saved yet."
        )
    return rca

@app.get("/agent-health")
async def agent_health():
    """
    Exposes aggregate health metrics of the autonomous pipeline (Arize replacement).
    """
    governance = get_governance_service()
    metrics = await governance.get_summary_metrics()
    return metrics


@app.get("/agent-health/agents")
async def agent_health_per_agent():
    """
    Returns per-agent health breakdown derived from incident state and governance events.
    Each agent in the pipeline is represented with health score, avg confidence,
    avg latency, success rate, current status, and autonomy level.
    """
    mongo = get_mongo_service()
    # Pull the last 50 incidents to derive per-agent metrics
    cursor = mongo.incidents.find({}, {"_id": 0}).sort("created_at", -1).limit(50)
    incidents_list = await cursor.to_list(length=50)

    total = len(incidents_list)
    resolved = sum(1 for i in incidents_list if i.get("status") == "RESOLVED")
    failed = sum(1 for i in incidents_list if i.get("status") in ("FAILED", "ESCALATED", "TIMEOUT"))
    blocked = sum(1 for i in incidents_list if i.get("status") == "BLOCKED")
    pending = sum(1 for i in incidents_list if i.get("status") == "PENDING_APPROVAL")
    active = total - resolved - failed - blocked - pending

    avg_conf = 0.0
    if total > 0:
        avg_conf = sum(float(i.get("confidence", 0.0)) for i in incidents_list) / total

    # Derive success rate from resolved / (resolved + failed)
    completed = resolved + failed
    success_rate = (resolved / completed) if completed > 0 else 1.0

    governance = get_governance_service()
    gov_metrics = await governance.get_summary_metrics()
    health_score = gov_metrics.get("health_score", 100.0)
    autonomy = gov_metrics.get("autonomy_level", "FULL")

    # Status label
    def agent_status(base_success: float) -> str:
        if base_success >= 0.85:
            return "NOMINAL"
        elif base_success >= 0.60:
            return "DEGRADED"
        return "CRITICAL"

    agents = [
        {
            "name": "Investigation Agent",
            "role": "Root Cause Analysis Swarm",
            "health_score": round(min(100.0, avg_conf * 100 * 1.1), 1),
            "avg_confidence": round(avg_conf, 3),
            "avg_latency_ms": 1200,
            "success_rate": round(success_rate, 3),
            "status": agent_status(success_rate),
            "autonomy_level": autonomy
        },
        {
            "name": "Decision Agent",
            "role": "Remediation Decision",
            "health_score": round(min(100.0, health_score), 1),
            "avg_confidence": round(avg_conf, 3),
            "avg_latency_ms": 850,
            "success_rate": round(success_rate, 3),
            "status": agent_status(success_rate),
            "autonomy_level": autonomy
        },
        {
            "name": "Safety Agent",
            "role": "Safety Gate Enforcement",
            "health_score": round(min(100.0, health_score * 1.05), 1),
            "avg_confidence": 1.0,
            "avg_latency_ms": 25,
            "success_rate": 1.0 if total == 0 else round((total - blocked) / total, 3),
            "status": "NOMINAL",
            "autonomy_level": autonomy
        },
        {
            "name": "Execution Agent",
            "role": "Remediation Execution",
            "health_score": round(min(100.0, success_rate * 100), 1),
            "avg_confidence": round(avg_conf, 3),
            "avg_latency_ms": 3500,
            "success_rate": round(success_rate, 3),
            "status": agent_status(success_rate),
            "autonomy_level": autonomy
        },
        {
            "name": "Validation Agent",
            "role": "Post-Execution Validation",
            "health_score": round(min(100.0, success_rate * 100 * 0.98), 1),
            "avg_confidence": round(avg_conf * 0.95, 3),
            "avg_latency_ms": 60000,
            "success_rate": round(success_rate, 3),
            "status": agent_status(success_rate),
            "autonomy_level": autonomy
        }
    ]
    return {"agents": agents, "summary": gov_metrics}


@app.get("/system-overview")
async def system_overview():
    """
    Returns system-level KPI metrics for the dashboard overview cards.
    """
    mongo = get_mongo_service()
    cursor = mongo.incidents.find({}, {"_id": 0}).sort("created_at", -1).limit(200)
    all_incidents = await cursor.to_list(length=200)

    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    open_count = sum(1 for i in all_incidents if i.get("status") not in ("RESOLVED", "FAILED", "TIMEOUT", "BLOCKED", "ESCALATED"))
    resolved_today = 0
    mttr_seconds_list = []

    for inc in all_incidents:
        if inc.get("status") == "RESOLVED":
            created = inc.get("created_at")
            updated = inc.get("updated_at")
            if created and updated:
                # Handle both datetime and string
                if isinstance(created, str):
                    created = datetime.fromisoformat(created.replace("Z", "+00:00"))
                if isinstance(updated, str):
                    updated = datetime.fromisoformat(updated.replace("Z", "+00:00"))
                # Make timezone-aware if naive
                if created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)
                if updated.tzinfo is None:
                    updated = updated.replace(tzinfo=timezone.utc)
                if updated >= today_start:
                    resolved_today += 1
                mttr_seconds = (updated - created).total_seconds()
                if mttr_seconds > 0:
                    mttr_seconds_list.append(mttr_seconds)

    avg_mttr_seconds = sum(mttr_seconds_list) / len(mttr_seconds_list) if mttr_seconds_list else 0
    avg_mttr_minutes = round(avg_mttr_seconds / 60, 1)

    governance = get_governance_service()
    gov_metrics = await governance.get_summary_metrics()

    # Healthy services: 3 mock services minus those with active open incidents
    services_with_issues = set(i.get("service") for i in all_incidents if i.get("status") not in ("RESOLVED", "FAILED", "TIMEOUT", "BLOCKED", "ESCALATED"))
    total_services = 3
    healthy_services = max(0, total_services - len(services_with_issues))

    return {
        "healthy_services": healthy_services,
        "total_services": total_services,
        "open_incidents": open_count,
        "resolved_today": resolved_today,
        "avg_mttr_minutes": avg_mttr_minutes,
        "agent_health_score": gov_metrics.get("health_score", 100.0),
        "autonomy_mode": gov_metrics.get("autonomy_level", "FULL")
    }


@app.get("/incidents/{id}/timeline")
async def get_incident_timeline(id: str):
    """
    Derives a 7-stage timeline for an incident based on its current state
    and available timestamps stored in the document.
    """
    mongo = get_mongo_service()
    incident = await mongo.incidents.find_one({"id": id}, {"_id": 0})
    if not incident:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Incident with ID {id} not found."
        )

    created_at = incident.get("created_at")
    updated_at = incident.get("updated_at")
    inc_status = incident.get("status", "OPEN")

    def fmt(dt):
        if dt is None:
            return None
        if isinstance(dt, str):
            return dt
        return dt.isoformat() + "Z"

    # Build timeline stages based on what fields are populated
    stages = [
        {
            "stage": "DETECTED",
            "label": "Detected",
            "status": "completed",
            "timestamp": fmt(created_at),
            "description": f"Anomaly detected on {incident.get('service')} — {incident.get('issue_type')}"
        },
        {
            "stage": "INVESTIGATION",
            "label": "Investigation",
            "status": "completed" if incident.get("root_cause") else ("active" if inc_status == "OPEN" else "pending"),
            "timestamp": fmt(created_at),
            "description": incident.get("root_cause", "Swarm investigation running...") if incident.get("root_cause") else "Parallel subagent analysis in progress"
        },
        {
            "stage": "DECISION",
            "label": "Decision",
            "status": "completed" if incident.get("recommended_action") else ("active" if incident.get("root_cause") and not incident.get("recommended_action") else "pending"),
            "timestamp": fmt(updated_at) if incident.get("recommended_action") else None,
            "description": f"Action: {incident.get('recommended_action')}" if incident.get("recommended_action") else "Decision agent evaluating options"
        },
        {
            "stage": "SAFETY",
            "label": "Safety Gate",
            "status": "completed" if incident.get("zone") else ("active" if incident.get("recommended_action") and not incident.get("zone") else "pending"),
            "timestamp": fmt(updated_at) if incident.get("zone") else None,
            "description": f"Zone: {incident.get('zone')} | {'APPROVED' if incident.get('approved') else 'BLOCKED' if incident.get('blocked') else 'GATED'}" if incident.get("zone") else "Awaiting safety evaluation"
        },
        {
            "stage": "EXECUTION",
            "label": "Execution",
            "status": "completed" if incident.get("execution_success") is not None else (
                "active" if inc_status == "EXECUTION_IN_PROGRESS" else (
                "pending" if inc_status in ("PENDING_APPROVAL", "BLOCKED") else (
                "completed" if inc_status in ("RESOLVED", "FAILED") else "pending"
            ))),
            "timestamp": fmt(updated_at) if incident.get("execution_success") is not None else None,
            "description": f"Execution {'succeeded' if incident.get('execution_success') else 'failed'}" if incident.get("execution_success") is not None else "Remediation execution pending"
        },
        {
            "stage": "VALIDATION",
            "label": "Validation",
            "status": "completed" if incident.get("validation_status") else (
                "active" if inc_status == "EXECUTION_SUCCESS" else "pending"
            ),
            "timestamp": fmt(updated_at) if incident.get("validation_status") else None,
            "description": f"Validation: {incident.get('validation_status', '').upper()}" if incident.get("validation_status") else "Post-execution health check pending"
        },
        {
            "stage": "RESOLVED",
            "label": "Resolved",
            "status": "completed" if inc_status == "RESOLVED" else (
                "failed" if inc_status in ("FAILED", "ESCALATED", "TIMEOUT", "BLOCKED") else "pending"
            ),
            "timestamp": fmt(updated_at) if inc_status == "RESOLVED" else None,
            "description": "Incident fully resolved" if inc_status == "RESOLVED" else (
                f"Incident ended with status: {inc_status}" if inc_status in ("FAILED", "ESCALATED", "TIMEOUT", "BLOCKED") else "Resolution pending"
            )
        }
    ]
    return {"incident_id": id, "stages": stages}


@app.get("/incidents/stream")
async def incidents_stream(request: Request):
    """
    Server-Sent Events endpoint that pushes incident updates every 3 seconds.
    Clients that cannot use SSE should fall back to polling /incidents.
    """
    async def event_generator():
        while True:
            if await request.is_disconnected():
                break
            mongo = get_mongo_service()
            cursor = mongo.incidents.find({}, {"_id": 0}).sort("created_at", -1).limit(50)
            incidents_list = await cursor.to_list(length=50)
            # Serialize datetimes
            def default_serializer(obj):
                if isinstance(obj, datetime):
                    return obj.isoformat() + "Z"
                raise TypeError(f"Object of type {type(obj)} is not JSON serializable")
            payload = json.dumps(incidents_list, default=default_serializer)
            yield f"data: {payload}\n\n"
            await asyncio.sleep(3)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no"
        }
    )

# Serve Frontend Dashboard
from fastapi.staticfiles import StaticFiles
frontend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "frontend"))
app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")

