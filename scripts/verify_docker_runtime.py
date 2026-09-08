"""Exercise a built image through real HTTP, with fresh SQLite and a prepared model volume.

Uses only host stdlib + Docker CLI. No host source/venv/database is mounted. The
probe is sent over stdin; the application is imported from the installed wheel.
All created containers are removed, and the dedicated audit volume is deleted.
The caller-owned image/model volume is retained. Never inspect container Env.
"""

import argparse
import hashlib
import json
import os
import subprocess
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROBE = r"""
import hashlib, importlib.metadata, json, os, platform, sys, time, urllib.request
from pathlib import Path

def request(path, body=None):
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode()
    req = urllib.request.Request('http://127.0.0.1:8765' + path, data=data,
                                 headers={'Content-Type': 'application/json'})
    start = time.perf_counter()
    with urllib.request.urlopen(req, timeout=90) as response:
        return {'http_status': response.status,
                'wall_ms': (time.perf_counter()-start)*1000,
                'body': json.load(response)}

mode = sys.argv[1]
out = {'mode': mode, 'health': request('/health'), 'readiness': request('/v2/health')}
assert out['readiness']['body']['retrieval']['backend'] == 'hybrid'
if mode == 'embedding':
    import numpy as np
    import supplychain_agent
    from supplychain_agent.v2.embeddings import BGEEncoder
    from supplychain_agent.v2.database import BusinessStore
    from supplychain_agent.v2.semantic_retrieval import create_retriever
    encoder = BGEEncoder(os.environ['AGENT_EMBEDDING_MODEL_DIR'])
    vector = encoder.encode(['采购预算和供应商资质'], query=True)
    assert vector.shape == (1, 512) and np.isfinite(vector).all()
    assert np.allclose(np.linalg.norm(vector, axis=1), 1)
    out['embedding'] = {'manifest': encoder.manifest(), 'shape': list(vector.shape),
        'norm': float(np.linalg.norm(vector)), 'providers': encoder.session.get_providers()}
    docs = BusinessStore(os.environ['AGENT_BUSINESS_PATH']).policies()
    out['retrieval'] = {}
    for backend in ('lexical', 'semantic', 'hybrid'):
        retriever = create_retriever(docs, backend, os.environ['AGENT_EMBEDDING_MODEL_DIR'])
        result = retriever.search('采购预算和供应商资质', 3)
        assert len(result['hits']) == 3
        out['retrieval'][backend] = result
    for hit in out['retrieval']['hybrid']['hits']:
        assert abs(hit['score'] - sum(1/(60+c['rank'])
            for c in hit['components'].values())) < 1e-12
    package = Path(supplychain_agent.__file__).parent
    out['installed_source_sha256'] = {str(p.relative_to(package)):
        hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(package.rglob('*'))
        if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc'}
    out['versions'] = {name: importlib.metadata.version(name) for name in
        ('fastapi','pydantic','scipy','numpy','faiss-cpu','onnxruntime','tokenizers')}
    out['runtime'] = {'machine': platform.machine(), 'python': platform.python_version(),
                      'uid': os.getuid(), 'key_present': bool(os.getenv('DEEPSEEK_API_KEY'))}
    assert out['runtime']['uid'] == 10001 and not out['runtime']['key_present']
elif mode in ('offline', 'restart'):
    assert not os.getenv('DEEPSEEK_API_KEY') and not os.getenv('LLM_API_KEY')
    out['inventory'] = request('/v2/agent', {'message':'查询库存：电机', 'mode':'demo'})
    out['optimization'] = request('/optimize', {'parameters':{'budget':9000}})
    assert out['inventory']['body']['status'] == 'completed'
    out['runs'] = request('/v2/runs')
elif mode == 'live':
    out['input'] = {'message':'先查询库存，再预算9000元，电机不能缺货', 'mode':'llm'}
    out['optimization'] = request('/v2/agent', out['input'])
else:
    raise ValueError(mode)
if 'optimization' in out:
    response = out['optimization']['body']
    out['summary'] = {'http_status': out['optimization']['http_status'],
        'outcome': response['status'], 'solver': (response['result'] or {}).get('status'),
        'validation': (response['result'] or {}).get('validation'),
        'tools': [e['name'] for e in response['trace'] if e['kind'] == 'tool'],
        'llm_calls': response['llm_calls'], 'http_attempts': response['http_attempts'],
        'elapsed_ms': response['elapsed_ms'], 'model': response['model'],
        'request_id': response['request_id']}
    out['saved_trace'] = request('/v2/runs/' + response['request_id'])
print(json.dumps(out, ensure_ascii=False))
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="supplychain-agent:v2")
    parser.add_argument("--model-volume", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    commands = []
    secrets = [
        os.environ[n]
        for n in ("DEEPSEEK_API_KEY", "LLM_API_KEY", "HF_TOKEN")
        if len(os.getenv(n, "")) > 8
    ]

    def save(name, value):
        data = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
        assert not any(secret in data for secret in secrets), "secret_in_evidence"
        (args.output / name).write_text(data)

    def docker(*command, stdin=None, timeout=120, check=True):
        result = subprocess.run(
            ["docker", *command],
            input=stdin,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        commands.append({"command": ["docker", *command], "exit_code": result.returncode})
        save("commands.json", commands)
        if check and result.returncode:
            # Preserve safe command/exits, never raw daemon environment or errors.
            raise RuntimeError("docker_command_failed:" + command[0])
        return result

    def readiness(name):
        for _ in range(60):
            result = docker(
                "exec",
                name,
                "python",
                "-c",
                "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/v2/health')",
                check=False,
            )
            if result.returncode == 0:
                return
            time.sleep(1)
        raise RuntimeError("container_not_ready")

    def probe(name, mode):
        result = docker("exec", "-i", name, "python", "-", mode, stdin=PROBE)
        value = json.loads(result.stdout)
        save(mode + ".json", value)  # Save unsuccessful live outcomes before assertions.
        if "optimization" in value:
            summary = value["summary"]
            assert summary["outcome"] == "completed", summary["outcome"]
            assert summary["solver"] == "optimal"
            assert summary["validation"]["valid"] is True
            required = {
                "inventory_query",
                "supplier_query",
                "policy_retrieval",
                "replenishment_optimizer",
                "solution_validator",
            }
            assert required.issubset(summary["tools"])
            assert (summary["llm_calls"] > 0) == (mode == "live")
        return value

    tag = "supplychain-release-" + uuid.uuid4().hex[:10]
    volume, offline, live = tag + "-db", tag + "-offline", tag + "-live"
    created = []
    summary = {"success": False, "live": "not_run"}
    try:
        summary["image_id"] = docker(
            "image", "inspect", args.image, "--format", "{{.Id}}"
        ).stdout.strip()
        docker("volume", "inspect", args.model_volume)
        docker("volume", "create", volume)
        run = [
            "run",
            "-d",
            "-v",
            volume + ":/app/.runtime",
            "-v",
            args.model_volume + ":/models/bge:ro",
            "-e",
            "AGENT_EMBEDDING_MODEL_DIR=/models/bge",
        ]
        docker(*run, "--network", "none", "--name", offline, args.image)
        created.append(offline)
        readiness(offline)
        first = probe(offline, "offline")
        embedding = probe(offline, "embedding")
        sources = {
            str(p.relative_to(ROOT / "src/supplychain_agent")): hashlib.sha256(
                p.read_bytes()
            ).hexdigest()
            for p in (ROOT / "src/supplychain_agent").rglob("*")
            if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"
        }
        assert sources == embedding["installed_source_sha256"], "image_source_mismatch"
        docker("stop", offline)
        docker("start", offline)
        readiness(offline)
        restarted = probe(offline, "restart")
        assert first["readiness"]["body"] == restarted["readiness"]["body"]
        previous_id = first["summary"]["request_id"]
        assert previous_id in json.dumps(restarted["runs"]), "sqlite_trace_not_persisted"
        docker("stop", offline)
        if os.getenv("DEEPSEEK_API_KEY"):
            docker(
                *run,
                "-p",
                "127.0.0.1::8765",
                "--env",
                "DEEPSEEK_API_KEY",
                "--name",
                live,
                args.image,
            )
            created.append(live)
            readiness(live)
            port = docker("port", live, "8765/tcp").stdout.strip()
            import urllib.request

            with urllib.request.urlopen("http://" + port + "/health", timeout=10) as response:
                assert response.status == 200
            result = probe(live, "live")
            summary["live"] = result["summary"]
        else:
            summary["live"] = "blocked_missing_DEEPSEEK_API_KEY"
        summary.update(
            success=True,
            offline_network="none",
            restart=True,
            persisted_sqlite=True,
            image_source_matches=True,
        )
    finally:
        for name in created:
            docker("rm", "-f", name, check=False)
        docker("volume", "rm", volume, check=False)
        save("summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
