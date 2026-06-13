import sys
import os
from unittest.mock import MagicMock, AsyncMock

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Set dummy env variables for test startup
os.environ["MONGODB_URI"] = "mongodb://localhost:27017"
os.environ["GROQ_API_KEY"] = "fake-api-key"

from fastapi.testclient import TestClient

def test_endpoints():
    print("Testing API Endpoints with TestClient and mocked dependencies...")
    
    # Proactively mock mongo client before import/startup triggers
    from services.mongo import get_mongo_service
    mongo = get_mongo_service()
    mongo.connect = MagicMock()
    mongo.create_indexes = AsyncMock()
    
    # Mock incident collection
    mock_cursor = MagicMock()
    async def mock_to_list(length=None):
        return [{"id": "test-uuid", "service": "payment-service", "status": "RESOLVED"}]
    mock_cursor.sort.return_value.to_list = mock_to_list
    
    # Override properties to avoid accessing None db client
    type(mongo).incidents = MagicMock()
    mongo.incidents.find.return_value = mock_cursor

    from main import app
    from services.governance import get_governance_service
    gov = get_governance_service()
    
    gov.get_summary_metrics = AsyncMock(return_value={
        "avg_confidence": 0.85,
        "success_rate": 0.90,
        "drift_score": 0.05,
        "health_score": 88.0,
        "autonomy_level": "FULL",
        "total_decisions": 10
    })

    client = TestClient(app)

    # 1. Test /agent-health GET
    response = client.get("/agent-health")
    assert response.status_code == 200
    data = response.json()
    assert data["health_score"] == 88.0
    assert data["autonomy_level"] == "FULL"
    assert data["drift_score"] == 0.05
    print("OK: GET /agent-health returns correct metrics structure")

    # 2. Test /incidents GET
    response = client.get("/incidents")
    assert response.status_code == 200
    incidents = response.json()
    assert len(incidents) == 1
    assert incidents[0]["id"] == "test-uuid"
    print("OK: GET /incidents returns correct list shape")

    # 3. Test /inject POST and Rate Limiting
    from services.orchestrator import get_orchestrator
    orch = get_orchestrator()
    orch.start_pipeline = AsyncMock(return_value="new-incident-uuid")
    
    response = client.post("/inject", json={"service": "payment-service", "issue_type": "high_latency"})
    assert response.status_code == 201
    assert response.json()["incident_id"] == "new-incident-uuid"
    print("OK: POST /inject starts pipeline successfully")

    # Trigger second request to check rate limiter (returns 429)
    response_rate_limit = client.post("/inject", json={"service": "payment-service", "issue_type": "high_latency"})
    assert response_rate_limit.status_code == 429
    print("OK: POST /inject rate limiter blocks second request within 10s window")

    print("\nAPI endpoints shape verification completed successfully!")

if __name__ == "__main__":
    test_endpoints()
