# AutoRemediator AI - Tactical Command

AutoRemediator AI is an autonomous incident response system. When a microservice degrades, it detects the anomaly, investigates the root cause using a parallel multi-agent swarm, decides on a remediation action, executes it safely (restart/rollback/scale), validates recovery, and generates an RCA postmortem.

---

## 🛠️ Member 1 Implementation (Completed)

We have built the entire Python backend core, the agent orchestration layer, and the static command dashboard UI.

### **1. Services Layer (`services/`)**
- `groq_client.py`: Shared LLM completion utility mapping to `llama-3.3-70b-versatile` on Groq, supporting text and structured JSON responses.
- `mongo.py`: Asynchronous MongoDB wrapper handling database connectivity and index creations on start.
- `telemetry.py`: Observability proxy fetching Prometheus metrics, Loki logs, Jaeger traces, and health checks. Built with connection fallbacks to prevent crashes when services are offline.
- `governance.py`: Logs decisions, updates validation success metrics, and computes live health scores `(avg_confidence * 0.5 + success_rate * 0.5) * 100` to adjust autonomy.
- `memory.py`: Database query projector retrieving past resolved incident states.
- `docker_service.py`: Replaces the legacy `kubernetes_mcp` with async `docker compose` subprocess controllers to restart, scale, or cycle containers.

### **2. Agent Swarm Layer (`agents/` & `services/orchestrator.py`)**
- `detection.py`: Background poller that monitors target service latency/health and triggers the orchestrator. Contains checks to ignore offline local services to prevent flooding during development.
- `investigation.py`: Fires 4 subagents (Logs, Traces, Deployments, Memory) concurrently via `asyncio.gather` and fuses outputs using a Lead RCA model.
- `decision.py`: Remediates incidents using historical fast-paths or ranked recommendations from Groq.
- `safety.py`: Enforces Layer 1 hard blocks (confidence, cooldowns, whitelists, protected services, blast radius) and Layer 2 zone routing (Green, Yellow Auto/Gated, Red).
- `execution.py`: Dispatches remediation actions to Docker Compose after verifying safety credentials.
- `validation.py`: Waits (min 10s) and validates recovery via telemetry health checks.
- `rca_agent.py`: Generates 5-section postmortems containing exactly three recommendations.
- `orchestrator.py`: Controls the execution pipeline, 10m timeouts, autonomy overrides, and manual approval gates.

### **3. API and Dashboard UI**
- `main.py`: FastAPI server serving API endpoints (`/inject`, `/incidents`, `/agent-health`, `/incidents/{id}/approve`, `/incidents/{id}/rca`) and hosting the static directory.
- `frontend/`: Single-page tactical dashboard UI built with CSS grids, clock tickers, circular metrics gauges, live feed polling, and postmortem TXT exporters.

---

## 🚀 Member 2 Instructions (Teammate's Build)

Your job is to containerize the application, set up the microservice targets, wire the observability stack, and complete the full Docker Compose environment.

### **Step 1: Setup the Local Environment**
1. Clone the repository:
   ```bash
   git clone https://github.com/nevan-sonic/AutoRemediatorAI.git
   cd AutoRemediatorAI
   ```
2. Copy `.env.example` to `.env` and fill in the required keys (MongoDB URI, Groq API Key, and Monitored Services).
3. Install dependencies inside a virtual environment and verify imports:
   ```bash
   pip install -r requirements.txt
   python tests/test_imports.py
   ```

### **Step 2: Build the Microservice Targets**
Create three simple FastAPI microservices in `microservices/payment/`, `microservices/inventory/`, and `microservices/order/`:
- Expose `/health` returning `{"status": "healthy", "latency_ms": 12}`.
- Expose `/metrics` returning standard Prometheus-client metrics.
- Expose `/inject-failure` (POST) which sets an internal flag degrading the service `/health` status (latency spike > 3000ms, memory usage > 90%) for 5 minutes.
- Write a Dockerfile for each microservice.

### **Step 3: Setup Prometheus Observability**
Create `prometheus.yml` in the root folder. Configure it to scrape metrics from the three microservices every 15 seconds:
```yaml
global:
  scrape_interval: 15s

scrape_configs:
  - job_name: 'payment-service'
    static_configs:
      - targets: ['payment-service:8001']
  - job_name: 'inventory-service'
    static_configs:
      - targets: ['inventory-service:8002']
  - job_name: 'order-service'
    static_configs:
      - targets: ['order-service:8003']
```

### **Step 4: Dockerize the Backend**
Create a `Dockerfile.backend` in the root folder:
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### **Step 5: Assemble the Master `docker-compose.yml`**
Connect all 9 services inside a single network bridge:
1. `backend`: Built from `Dockerfile.backend`. Exposes port `8000`. Shares `.env`.
2. `payment-service`: Exposes port `8001`.
3. `inventory-service`: Exposes port `8002`.
4. `order-service`: Exposes port `8003`.
5. `prometheus`: Image `prom/prometheus:latest`, mounts `prometheus.yml`. Exposes port `9090`.
6. `loki`: Image `grafana/loki:2.9.0`. Exposes port `3100`.
7. `jaeger`: Image `jaegertracing/all-in-one:1.51`. Exposes port `16686`.
8. `frontend` (Optional): If wrapping React dashboard, otherwise served directly from `backend` at port `8000`.

*Verify that all container ports map correctly to the backend `.env` variables (`PROMETHEUS_URL=http://prometheus:9090`, etc.).*
