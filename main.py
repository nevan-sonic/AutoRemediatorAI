import time
import os
import uuid
import logging
from fastapi import FastAPI, Request, Response, status, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from services.mongo import get_mongo_service
from services.governance import get_governance_service
from services.orchestrator import get_orchestrator
from agents.detection import get_detection_agent
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

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

# Serve Frontend Dashboard
from fastapi.staticfiles import StaticFiles
frontend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "frontend"))
app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")

