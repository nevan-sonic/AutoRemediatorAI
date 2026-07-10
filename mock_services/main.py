import os
import time
import asyncio
import logging
from fastapi import FastAPI, Response
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST, Gauge

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title=os.getenv("SERVICE_NAME", "mock-service"))

# Simulated state
state = {
    "is_degraded": False,
    "degraded_until": 0
}

# Prometheus Metrics
cpu_gauge = Gauge("cpu_usage_percent", "Simulated CPU Usage")
mem_gauge = Gauge("memory_usage_percent", "Simulated Memory Usage")

# Base usage
BASE_CPU = 15.0
BASE_MEM = 45.0

def update_metrics():
    if state["is_degraded"] and time.time() < state["degraded_until"]:
        # Spike metrics
        cpu_gauge.set(95.0)
        mem_gauge.set(88.0)
    else:
        state["is_degraded"] = False
        cpu_gauge.set(BASE_CPU)
        mem_gauge.set(BASE_MEM)

@app.middleware("http")
async def simulate_latency(request, call_next):
    if state["is_degraded"] and time.time() < state["degraded_until"]:
        await asyncio.sleep(2.5) # Simulate 2.5s latency
    response = await call_next(request)
    return response

@app.get("/health")
async def health():
    update_metrics()
    if state["is_degraded"]:
        return {"status": "degraded", "latency_ms": 2500}
    return {"status": "healthy", "latency_ms": 15}

@app.get("/metrics")
async def metrics():
    update_metrics()
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

@app.post("/inject-failure")
async def inject_failure():
    logger.warning("Failure injected. Degraded state initiated for 300 seconds.")
    state["is_degraded"] = True
    state["degraded_until"] = time.time() + 300
    update_metrics()
    return {"status": "failure_injected", "duration_seconds": 300}
