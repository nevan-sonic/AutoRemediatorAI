import os
import sys
import subprocess
import time
import threading

def main():
    print("=================================================================")
    print("      AutoRemediator AI - Local Process Orchestrator")
    print("=================================================================")
    
    # Verify .env exists
    if not os.path.exists(".env"):
        print("ERROR: .env file is missing! Please configure .env first.")
        sys.exit(1)

    # Port config
    services = [
        {"name": "payment-service", "port": "8001"},
        {"name": "inventory-service", "port": "8002"},
        {"name": "order-service", "port": "8003"}
    ]
    
    processes = []
    
    try:
        # Start target mock microservices
        for svc in services:
            print(f"Starting {svc['name']} on http://localhost:{svc['port']}...")
            env = os.environ.copy()
            env["SERVICE_NAME"] = svc["name"]
            
            # Start process
            p = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "mock_services.main:app", "--port", svc["port"], "--host", "127.0.0.1"],
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )
            processes.append((svc["name"], p))
            
        # Give mock services a second to start up
        time.sleep(1)
        
        # Start backend service
        print("Starting main backend service on http://localhost:8000...")
        backend_p = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "main:app", "--port", "8000", "--host", "127.0.0.1"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )
        processes.append(("backend", backend_p))
        
        print("\nAll services launched successfully!")
        print("Press Ctrl+C to terminate all services.\n")
        
        # Stream logs in background threads
        def stream_output(name, process):
            for line in iter(process.stdout.readline, ''):
                print(f"[{name.upper()}] {line.strip()}", flush=True)
                
        threads = []
        for name, p in processes:
            t = threading.Thread(target=stream_output, args=(name, p), daemon=True)
            t.start()
            threads.append(t)
            
        # Keep main thread alive and monitor process states
        while True:
            time.sleep(0.5)
            # Check if any process died
            for name, p in processes:
                poll = p.poll()
                if poll is not None:
                    print(f"\n[ORCHESTRATOR] Process '{name}' terminated with exit status {poll}.")
                    raise KeyboardInterrupt()
                    
    except KeyboardInterrupt:
        print("\n[ORCHESTRATOR] Interrupted. Stopping all processes...")
    finally:
        for name, p in processes:
            print(f"[ORCHESTRATOR] Stopping '{name}'...")
            try:
                p.terminate()
                p.wait(timeout=3)
            except subprocess.TimeoutExpired:
                print(f"[ORCHESTRATOR] Force killing '{name}'...")
                p.kill()
            except Exception as e:
                print(f"[ORCHESTRATOR] Error stopping '{name}': {e}")
        print("[ORCHESTRATOR] Clean shutdown complete.")

if __name__ == "__main__":
    main()
