"""Start a real loopback HTTP server, exercise V1/V2, save a reviewable trace, stop."""

import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
from replay_v2 import replay_record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="evaluation/evidence/http_smoke.json")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="supplychain-v2-http-") as directory:
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        env = {k: v for k, v in os.environ.items() if k not in {"LLM_API_KEY", "DEEPSEEK_API_KEY"}}
        env.update(
            AGENT_AUDIT_PATH=str(Path(directory) / "trace.sqlite3"),
            AGENT_BUSINESS_PATH=str(Path(directory) / "business.sqlite3"),
        )
        cmd = [
            sys.executable,
            "-m",
            "uvicorn",
            "supplychain_agent.api:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ]
        with (Path(directory) / "server.log").open("w+") as log:
            process = subprocess.Popen(cmd, env=env, stdout=log, stderr=subprocess.STDOUT)
            try:
                with httpx.Client(
                    base_url=f"http://127.0.0.1:{port}", trust_env=False, timeout=15
                ) as client:
                    for _ in range(100):
                        if process.poll() is not None:
                            raise RuntimeError("server_startup_failed")
                        try:
                            health = client.get("/v2/health")
                            if health.status_code == 200:
                                break
                        except httpx.TransportError:
                            pass
                        time.sleep(0.05)
                    else:
                        raise RuntimeError("server_readiness_timeout")
                    response = client.post(
                        "/v2/agent",
                        json={"message": "先查询库存，再预算9000元，电机不能缺货", "mode": "demo"},
                    )
                    response.raise_for_status()
                    body = response.json()
                    assert body["status"] == "completed" and body["result"]["validation"]["valid"]
                    trace = client.get("/v2/runs/" + body["request_id"]).json()
                    inventory = client.post(
                        "/v2/agent", json={"message": "查询库存：传感器"}
                    ).json()
                    optimize = client.post(
                        "/optimize", json={"parameters": {"budget": 0, "protected_skus": ["MOTOR"]}}
                    ).json()
                    v1 = client.post(
                        "/agent", json={"message": "生成补货方案", "mode": "rules"}
                    ).json()
                    assert inventory["status"] == v1["status"] == "completed"
                    assert optimize["status"] == "infeasible"
                    assert (
                        client.post("/v2/agent", json={"message": "x", "extra": 1}).status_code
                        == 422
                    )
                    result = {
                        "success": True,
                        "transport": "real loopback HTTP",
                        "api_keys_removed": True,
                        "health": health.json(),
                        "v1_status": v1["status"],
                        "inventory_status": inventory["status"],
                        "structured_status": optimize["status"],
                        "request_id_header": response.headers["X-Request-ID"],
                        "trace": trace,
                        "replay": replay_record(trace),
                    }
            finally:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            log.seek(0)
            result["server_log"] = log.read()
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        print(
            json.dumps(
                {
                    key: result[key]
                    for key in ("success", "transport", "api_keys_removed", "replay")
                },
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    main()
