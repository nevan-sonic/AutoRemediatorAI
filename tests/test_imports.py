import sys
import os

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

def test_imports():
    print("Testing module imports...")
    try:
        from services.groq_client import get_groq_client
        print("OK: services/groq_client.py imported successfully")
        
        from services.mongo import get_mongo_service
        print("OK: services/mongo.py imported successfully")
        
        from services.telemetry import get_telemetry_service
        print("OK: services/telemetry.py imported successfully")
        
        from services.governance import get_governance_service
        print("OK: services/governance.py imported successfully")
        
        from services.memory import get_memory_service
        print("OK: services/memory.py imported successfully")
        
        from services.docker_service import execute_restart, execute_rollback, execute_scale
        print("OK: services/docker_service.py imported successfully")
        
        from agents.safety import SafetyAgent
        print("OK: agents/safety.py imported successfully")
        
        from agents.detection import get_detection_agent
        print("OK: agents/detection.py imported successfully")
        
        from agents.investigation import InvestigationAgent
        print("OK: agents/investigation.py imported successfully")
        
        from agents.decision import DecisionAgent
        print("OK: agents/decision.py imported successfully")
        
        from agents.execution import ExecutionAgent
        print("OK: agents/execution.py imported successfully")
        
        from agents.validation import ValidationAgent
        print("OK: agents/validation.py imported successfully")
        
        from agents.rca_agent import RcaAgent
        print("OK: agents/rca_agent.py imported successfully")
        
        from services.orchestrator import get_orchestrator
        print("OK: services/orchestrator.py imported successfully")
        
        print("\nAll imports completed successfully!")
    except Exception as e:
        print(f"\nERROR: Import test failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    test_imports()
