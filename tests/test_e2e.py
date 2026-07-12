import sys
import os
import asyncio
from datetime import datetime

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv
load_dotenv()

from services.mongo import get_mongo_service
from services.groq_client import get_groq_client
from services.orchestrator import get_orchestrator

async def test_e2e():
    print("=== STARTING END-TO-END PIPELINE AND CREDENTIALS TEST ===\n")

    # 1. Test MongoDB connection and read/write
    print("1. Testing MongoDB connection...")
    mongo = get_mongo_service()
    mongo.connect()
    await mongo.create_indexes()
    
    test_id = "test-e2e-connectivity"
    try:
        # Cleanup past test runs
        await mongo.incidents.delete_many({"id": test_id})
        await mongo.governance_events.delete_many({})

        
        # Write verification document
        await mongo.incidents.insert_one({
            "id": test_id,
            "service": "test-service",
            "status": "OPEN",
            "created_at": datetime.utcnow()
        })
        
        # Read verification document
        doc = await mongo.incidents.find_one({"id": test_id})
        assert doc is not None, "Failed to read written document from MongoDB"
        print("OK: MongoDB connection, read, and write verified successfully!")
        
        # Cleanup
        await mongo.incidents.delete_many({"id": test_id})
    except Exception as e:
        print(f"FAILED: MongoDB connectivity test failed: {e}")
        return False

    # 2. Test Groq Client connectivity
    print("\n2. Testing Groq API connectivity...")
    groq = get_groq_client()
    try:
        messages = [{"role": "user", "content": "Say 'hello' and nothing else."}]
        text_res = groq.chat(messages, max_tokens=10)
        print(f"OK: Groq text completion response: '{text_res.strip()}'")
        
        json_system = "You are a test json assistant. Respond in JSON."
        json_messages = [{"role": "user", "content": 'Response structure: {"status": "ok"}'}]
        json_res = groq.chat_json(json_messages, system=json_system)
        assert json_res.get("status") == "ok", "Failed to parse JSON response correctly"
        print(f"OK: Groq JSON completion response parsed successfully: {json_res}")
    except Exception as e:
        print(f"FAILED: Groq API test failed: {e}")
        return False

    # 3. Test Orchestrator Pipeline Flow
    print("\n3. Testing End-to-End Orchestrator Pipeline Flow (Local Dry Run)...")
    # Set DEMO_MODE to true to bypass cooldowns and handle validation
    os.environ["DEMO_MODE"] = "true"
    
    orch = get_orchestrator()
    incident_id = await orch.start_pipeline("payment-service", "high_latency")
    print(f"OK: Pipeline triggered. Incident ID: {incident_id}")
    print("Waiting for pipeline execution tasks to complete (max 30s)...")
    
    # Poll incident status from MongoDB until completion
    attempts = 30
    pipeline_state = None
    for i in range(attempts):
        await asyncio.sleep(1)
        pipeline_state = await mongo.incidents.find_one({"id": incident_id})
        if pipeline_state and pipeline_state.get("status") in ["RESOLVED", "ESCALATED", "FAILED", "BLOCKED", "PENDING_APPROVAL"]:
            break
            
    if not pipeline_state:
        print("FAILED: Incident document was not created or found.")
        return False

    print(f"Final Pipeline Status: '{pipeline_state.get('status')}'")
    print(f"RCA Root Cause: '{pipeline_state.get('root_cause')}'")
    print(f"Remediation Action Proposed: '{pipeline_state.get('recommended_action')}'")
    print(f"Remediation Rationale: '{pipeline_state.get('rationale')}'")
    
    # Local check verification
    assert pipeline_state.get("root_cause") is not None, "Pipeline did not populate root cause"
    assert pipeline_state.get("recommended_action") is not None, "Pipeline did not populate recommended action"
    assert len(pipeline_state.get("reasoning_chain", [])) > 0, "Pipeline did not populate reasoning chain"
    
    print("\nOK: Orchestrator Pipeline completed local run successfully with state updates!")
    print("\n=== ALL SYSTEM TESTS PASSED SUCCESSFULLY! ===")
    return True

if __name__ == "__main__":
    asyncio.run(test_e2e())
