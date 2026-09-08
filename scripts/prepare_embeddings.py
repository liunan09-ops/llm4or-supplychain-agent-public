"""Explicit, resumable-by-file public artifact download; no credentials required."""

import argparse
import json
import tempfile
from pathlib import Path

import httpx

from supplychain_agent.v2.embeddings import (
    ARTIFACT_REPO,
    DEFAULT_MODEL_DIR,
    MODEL_FILES,
    REVISION,
    EmbeddingUnavailable,
    file_sha256,
    verify_model_files,
)


def prepare(directory):
    directory = Path(directory)
    for name, expected in MODEL_FILES.items():
        target = directory / name
        if target.exists():
            if (
                target.stat().st_size != expected["size"]
                or file_sha256(target) != expected["sha256"]
            ):
                raise EmbeddingUnavailable(f"existing_embedding_file_corrupt:{name}")
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        url = f"https://huggingface.co/{ARTIFACT_REPO}/resolve/{REVISION}/{name}"
        print(f"Downloading pinned artifact: {name}", flush=True)
        with tempfile.NamedTemporaryFile(dir=target.parent, suffix=".part", delete=False) as stream:
            temporary = Path(stream.name)
            try:
                with httpx.stream("GET", url, follow_redirects=True, timeout=60) as response:
                    response.raise_for_status()
                    size = 0
                    for block in response.iter_bytes(1024 * 1024):
                        size += len(block)
                        if size > expected["size"]:
                            raise EmbeddingUnavailable(f"embedding_download_size_mismatch:{name}")
                        stream.write(block)
                stream.flush()
                if size != expected["size"] or file_sha256(temporary) != expected["sha256"]:
                    raise EmbeddingUnavailable(f"embedding_download_hash_mismatch:{name}")
                temporary.replace(target)
            finally:
                temporary.unlink(missing_ok=True)
    return verify_model_files(directory)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, default=DEFAULT_MODEL_DIR)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    try:
        files = verify_model_files(args.model_dir) if args.verify_only else prepare(args.model_dir)
    except (EmbeddingUnavailable, OSError, httpx.HTTPError) as exc:
        # Exception messages from signed CDN URLs can contain query-string tokens.
        parser.exit(1, f"Embedding preparation blocked ({type(exc).__name__}); no fallback.\n")
    print(json.dumps({"revision": REVISION, "verified_files": files}, indent=2))


if __name__ == "__main__":
    main()
