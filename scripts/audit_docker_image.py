"""Read every saved image layer; only counts and paths are recorded, never credentials.

Run from the project directory after building supplychain-agent:v2. The three tiny
ONNX Runtime wheel examples are classified separately from downloaded BGE weights.
The temporary archive is automatically removed.
"""

import json
import os
import subprocess
import tarfile
import tempfile
from pathlib import Path

keys = [
    os.environ[n].encode()
    for n in ("DEEPSEEK_API_KEY", "LLM_API_KEY", "HF_TOKEN")
    if len(os.getenv(n, "")) > 8
]
result = {
    "image": "supplychain-agent:v2",
    "configured_credentials_checked": len(keys),
    "secret_matches": 0,
    "forbidden_files": [],
    "layers": 0,
    "files": 0,
    "bundled_onnx_examples": [],
}
meta = json.loads(subprocess.check_output(["docker", "image", "inspect", result["image"]]))[0]
result.update(
    image_id=meta["Id"],
    architecture=meta["Architecture"],
    size_bytes=meta["Size"],
    user=meta["Config"]["User"],
    image_env_names=[x.split("=", 1)[0] for x in meta["Config"]["Env"]],
)
with tempfile.TemporaryFile() as tmp:
    subprocess.run(["docker", "save", result["image"]], stdout=tmp, check=True)
    tmp.seek(0)
    with tarfile.open(fileobj=tmp) as archive:
        manifest = json.load(archive.extractfile("manifest.json"))[0]
        config = archive.extractfile(manifest["Config"]).read()
        assert not any(k in config for k in keys)
        for name in manifest["Layers"]:
            result["layers"] += 1
            with tarfile.open(fileobj=archive.extractfile(name), mode="r|*") as layer:
                for item in layer:
                    if not item.isfile():
                        continue
                    result["files"] += 1
                    path = Path(item.name)
                    if item.name in {
                        "app/.venv/lib/python3.12/site-packages/onnxruntime/datasets/logreg_iris.onnx",
                        "app/.venv/lib/python3.12/site-packages/onnxruntime/datasets/mul_1.onnx",
                        "app/.venv/lib/python3.12/site-packages/onnxruntime/datasets/sigmoid.onnx",
                    }:
                        result["bundled_onnx_examples"].append(
                            {"path": item.name, "bytes": item.size}
                        )
                    elif path.name == ".env" or path.suffix in (
                        ".onnx",
                        ".safetensors",
                        ".sqlite3",
                    ):
                        result["forbidden_files"].append(item.name)
                    stream = layer.extractfile(item)
                    tail = b""
                    while block := stream.read(1024 * 1024):
                        data = tail + block
                        if any(k in data for k in keys):
                            result["secret_matches"] += 1
                        tail = data[-256:]
assert result["secret_matches"] == 0 and not result["forbidden_files"]
assert "DEEPSEEK_API_KEY" not in result["image_env_names"]
Path("evaluation/release/image_audit.json").write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps(result))
