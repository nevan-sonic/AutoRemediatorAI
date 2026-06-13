import asyncio
import time
import logging

logger = logging.getLogger(__name__)

# Module-level dictionary tracking last execution timestamp per service
_last_execution = {}

def get_last_execution_time(service_name: str) -> float:
    return _last_execution.get(service_name, 0.0)

def set_last_execution_time(service_name: str, timestamp: float):
    _last_execution[service_name] = timestamp

async def run_command(cmd: str, timeout: float = 30.0) -> dict:
    logger.info(f"Executing command: {cmd}")
    try:
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            stdout_str = stdout.decode().strip()
            stderr_str = stderr.decode().strip()
            returncode = proc.returncode
            if returncode == 0:
                return {
                    "success": True, 
                    "returncode": 0, 
                    "stdout": stdout_str, 
                    "stderr": stderr_str
                }
            else:
                logger.warning(f"Command '{cmd}' returned non-zero exit code {returncode}: {stderr_str}")
                return {
                    "success": False, 
                    "returncode": returncode, 
                    "stdout": stdout_str, 
                    "stderr": stderr_str
                }
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            logger.error(f"Command '{cmd}' timed out after {timeout} seconds.")
            return {
                "success": False, 
                "stderr": f"Command timed out after {timeout}s", 
                "returncode": -1
            }
    except Exception as e:
        logger.error(f"Failed to execute command '{cmd}': {e}")
        return {
            "success": False, 
            "stderr": str(e), 
            "returncode": -2
        }

async def execute_restart(service_name: str) -> dict:
    cmd = f"docker compose restart {service_name}"
    res = await run_command(cmd, timeout=30.0)
    if res["success"]:
        _last_execution[service_name] = time.time()
    return res

async def execute_rollback(service_name: str) -> dict:
    # Simulates rollback by scaling to 0, then back to 1
    cmd_down = f"docker compose up -d --scale {service_name}=0"
    res_down = await run_command(cmd_down, timeout=30.0)
    if not res_down["success"]:
        return res_down
        
    cmd_up = f"docker compose up -d --scale {service_name}=1"
    res_up = await run_command(cmd_up, timeout=30.0)
    if res_up["success"]:
        _last_execution[service_name] = time.time()
    return res_up

async def execute_scale(service_name: str, replicas: int) -> dict:
    cmd = f"docker compose up -d --scale {service_name}={replicas}"
    res = await run_command(cmd, timeout=30.0)
    if res["success"]:
        _last_execution[service_name] = time.time()
    return res
