import os
import time
import logging
import httpx

logger = logging.getLogger(__name__)

class TelemetryService:
    def __init__(self):
        self.prometheus_url = os.getenv("PROMETHEUS_URL", "http://localhost:9090").rstrip('/')
        self.loki_url = os.getenv("LOKI_URL", "http://localhost:3100").rstrip('/')
        self.jaeger_url = os.getenv("JAEGER_URL", "http://localhost:16686").rstrip('/')
        
        self.port_map = {
            "payment-service": 8001,
            "inventory-service": 8002,
            "order-service": 8003
        }

    def _get_service_base_url(self, service_name: str) -> str:
        port = self.port_map.get(service_name)
        if not port:
            return f"http://{service_name}"
        
        # If Prometheus is local, map service to localhost for M1 testing
        is_local = "localhost" in self.prometheus_url or "127.0.0.1" in self.prometheus_url
        if is_local:
            return f"http://localhost:{port}"
        return f"http://{service_name}:{port}"

    async def get_metrics(self, service_name: str) -> dict:
        default_val = {"memory": {"points": []}, "cpu": {"points": []}}
        try:
            # Simple check/query to Prometheus
            async with httpx.AsyncClient(timeout=3.0) as client:
                # Query memory and cpu query range
                now = int(time.time())
                start = now - 600  # 10 minutes ago
                
                # We perform range queries for memory and cpu usage
                mem_query = f'memory_usage_percent{{job="{service_name}"}}'
                cpu_query = f'cpu_usage_percent{{job="{service_name}"}}'
                
                # Fetch memory
                mem_res = await client.get(
                    f"{self.prometheus_url}/api/v1/query_range",
                    params={"query": mem_query, "start": start, "end": now, "step": "15s"}
                )
                # Fetch cpu
                cpu_res = await client.get(
                    f"{self.prometheus_url}/api/v1/query_range",
                    params={"query": cpu_query, "start": start, "end": now, "step": "15s"}
                )
                
                result = {"memory": {"points": []}, "cpu": {"points": []}}
                
                if mem_res.status_code == 200:
                    data = mem_res.json()
                    if data.get("status") == "success":
                        result["memory"]["points"] = data.get("data", {}).get("result", [])
                        
                if cpu_res.status_code == 200:
                    data = cpu_res.json()
                    if data.get("status") == "success":
                        result["cpu"]["points"] = data.get("data", {}).get("result", [])
                        
                return result
        except Exception as e:
            logger.warning(f"Failed to fetch Prometheus metrics for {service_name}: {e}")
            return default_val

    async def get_logs(self, service_name: str, limit: int = 20) -> list[str]:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                # Query Loki range logs
                # LogQL: {app="service_name"}
                query = f'{{app="{service_name}"}}'
                response = await client.get(
                    f"{self.loki_url}/loki/api/v1/query_range",
                    params={"query": query, "limit": limit}
                )
                if response.status_code == 200:
                    data = response.json()
                    # Loki returns results in streams -> values
                    logs = []
                    streams = data.get("data", {}).get("result", [])
                    for stream in streams:
                        for val in stream.get("values", []):
                            # Loki values are [timestamp_ns, log_string]
                            if len(val) >= 2:
                                logs.append(val[1])
                    return logs[:limit]
                return []
        except Exception as e:
            logger.warning(f"Failed to fetch Loki logs for {service_name}: {e}")
            return []

    async def get_traces(self, service_name: str, limit: int = 5) -> list[dict]:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                # Query Jaeger traces
                response = await client.get(
                    f"{self.jaeger_url}/api/traces",
                    params={"service": service_name, "limit": limit}
                )
                if response.status_code == 200:
                    data = response.json()
                    return data.get("data", [])
                return []
        except Exception as e:
            logger.warning(f"Failed to fetch Jaeger traces for {service_name}: {e}")
            return []

    async def get_deployments(self, service_name: str) -> list[dict]:
        try:
            # Returns recent container restarts / deployment correlation in last 2h
            # In local environment, returns empty list gracefully
            return []
        except Exception as e:
            logger.warning(f"Failed to fetch deployments for {service_name}: {e}")
            return []

    async def health_check(self, service_name: str) -> dict:
        base_url = self._get_service_base_url(service_name)
        start_time = time.time()
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                res = await client.get(f"{base_url}/health")
                latency = int((time.time() - start_time) * 1000)
                if res.status_code == 200:
                    data = res.json()
                    # Normally returns {"status": "healthy" | "degraded"}
                    return {
                        "status": data.get("status", "healthy"),
                        "latency_ms": data.get("latency_ms", latency)
                    }
                else:
                    return {"status": "degraded", "latency_ms": latency}
        except Exception as e:
            logger.warning(f"Health check failed for {service_name} at {base_url}: {e}")
            return {"status": "degraded", "latency_ms": 0}

_telemetry_instance = None

def get_telemetry_service() -> TelemetryService:
    global _telemetry_instance
    if _telemetry_instance is None:
        _telemetry_instance = TelemetryService()
    return _telemetry_instance
