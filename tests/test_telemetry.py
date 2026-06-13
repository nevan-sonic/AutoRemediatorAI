import sys
import os
import asyncio

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from services.telemetry import get_telemetry_service

async def test_telemetry():
    print("Testing Telemetry service fallback (without Prometheus/Loki)...")
    telemetry = get_telemetry_service()
    
    # 1. Test get_metrics fallback
    metrics = await telemetry.get_metrics("payment-service")
    assert "memory" in metrics
    assert "cpu" in metrics
    assert metrics["memory"]["points"] == []
    print("OK: get_metrics fallback passed")

    # 2. Test get_logs fallback
    logs = await telemetry.get_logs("payment-service")
    assert logs == []
    print("OK: get_logs fallback passed")

    # 3. Test get_traces fallback
    traces = await telemetry.get_traces("payment-service")
    assert traces == []
    print("OK: get_traces fallback passed")

    # 4. Test health_check fallback
    health = await telemetry.health_check("payment-service")
    assert health["status"] == "degraded"
    assert health["latency_ms"] == 0
    print("OK: health_check fallback passed")

    print("\nTelemetry fallback tests completed successfully!")

if __name__ == "__main__":
    asyncio.run(test_telemetry())
