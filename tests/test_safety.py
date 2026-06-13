import sys
import os

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from agents.safety import SafetyAgent

def test_safety_rules():
    print("Testing Safety Agent rules...")
    safety = SafetyAgent()
    
    # 1. Low confidence test (R1)
    state = {
        "service": "payment-service",
        "action": "RESTART",
        "confidence": 0.5,
        "blast_radius": 1,
        "memory_match_used": False
    }
    res = safety.evaluate(state)
    assert res["blocked"] is True
    assert res["block_reason"] == "confidence_below_threshold"
    print("OK: Safety Rule R1 (Low confidence block) passed")

    # 2. Action not whitelisted (R2)
    state = {
        "service": "payment-service",
        "action": "DELETE",
        "confidence": 0.85,
        "blast_radius": 1,
        "memory_match_used": False
    }
    res = safety.evaluate(state)
    assert res["blocked"] is True
    assert res["block_reason"] == "action_not_whitelisted"
    print("OK: Safety Rule R2 (Unwhitelisted action block) passed")

    # 3. Protected service test (R3)
    os.environ["PROTECTED_SERVICES"] = "payment-service,order-service"
    state = {
        "service": "payment-service",
        "action": "RESTART",
        "confidence": 0.85,
        "blast_radius": 1,
        "memory_match_used": False
    }
    res = safety.evaluate(state)
    assert res["blocked"] is True
    assert res["block_reason"] == "protected_service"
    print("OK: Safety Rule R3 (Protected service block) passed")
    os.environ["PROTECTED_SERVICES"] = ""

    # 4. Green Zone auto-approve
    state = {
        "service": "payment-service",
        "action": "RESTART",
        "confidence": 0.85,
        "blast_radius": 1,
        "memory_match_used": False
    }
    res = safety.evaluate(state)
    assert res["approved"] is True
    assert res["zone"] == "GREEN"
    print("OK: Safety Zone GREEN (Restart auto-approve) passed")

    # 5. Yellow Gated Zone (ROLLBACK with medium confidence)
    state = {
        "service": "payment-service",
        "action": "ROLLBACK",
        "confidence": 0.80,
        "blast_radius": 1,
        "memory_match_used": False
    }
    res = safety.evaluate(state)
    assert res["approved"] is False
    assert res["requires_human_approval"] is True
    assert res["zone"] == "YELLOW_GATED"
    print("OK: Safety Zone YELLOW_GATED (Rollback human approval) passed")

    # 6. Yellow Auto Zone (ROLLBACK with high confidence and memory match)
    state = {
        "service": "payment-service",
        "action": "ROLLBACK",
        "confidence": 0.95,
        "blast_radius": 1,
        "memory_match_used": True
    }
    res = safety.evaluate(state)
    assert res["approved"] is True
    assert res["zone"] == "YELLOW_AUTO"
    print("OK: Safety Zone YELLOW_AUTO (Rollback memory match auto-approve) passed")

    print("\nAll Safety Agent unit tests completed successfully!")

if __name__ == "__main__":
    test_safety_rules()
