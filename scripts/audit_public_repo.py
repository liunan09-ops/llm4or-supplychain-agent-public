"""Scan project Git index, reachable project blobs and the same working files.

Stage an explicitly reviewed project file list first. No secret values are
printed. Pattern scans complement, rather than replace, the documented human
review of synthetic seed data and test-only placeholders.
"""

import argparse
import json
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = {
    "provider_token": rb"\b(?:sk-[A-Za-z0-9_-]{16,}|hf_[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}|AKIA[A-Z0-9]{16})\b",
    "private_key": rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
    "personal_path": rb"/(?:Users|home)/[A-Za-z0-9_.-]+/",
    "email": rb"[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}",
    "phone_candidate": rb"(?<![\w.])1[3-9]\d{9}(?![\w.])",
}
FAKE_EMAILS = {
    b"user@custom.invalid",
    b"api.deepseek.com@other.invalid",
    b"password@api.deepseek.com",
}


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT.parent)


def scan(data, keys):
    found = {name: len(re.findall(pattern, data)) for name, pattern in PATTERNS.items()}
    emails = re.findall(PATTERNS["email"], data)
    found["email"] = sum(value not in FAKE_EMAILS for value in emails)
    found["test_fake_email"] = sum(value in FAKE_EMAILS for value in emails)
    found["configured_secret"] = sum(key in data for key in keys)
    return {name: count for name, count in found.items() if count}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    keys = [
        os.environ[name].encode()
        for name in ("DEEPSEEK_API_KEY", "LLM_API_KEY", "HF_TOKEN", "OPENAI_API_KEY")
        if len(os.getenv(name, "")) > 8
    ]
    names = git("ls-files", "-z", "--", "supplychain-agent").decode().split("\0")[:-1]
    findings = {"index": {}, "working": {}, "history": {}}
    differences = []
    forbidden = []
    for name in names:
        path = ROOT.parent / name
        if path.is_symlink():
            forbidden.append(name)
            continue
        if (
            any(
                part in {".runtime", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache"}
                for part in path.parts
            )
            or path.suffix in {".zip", ".pdf", ".onnx", ".sqlite3", ".pyc"}
            or (path.name.startswith(".env") and path.name != ".env.example")
        ):
            forbidden.append(name)
        indexed = git("show", ":" + name)
        working = path.read_bytes()
        if indexed != working:
            differences.append(name)
        for kind, data in (("index", indexed), ("working", working)):
            hit = scan(data, keys)
            if hit:
                findings[kind][name.removeprefix("supplychain-agent/")] = hit
    objects = git("rev-list", "--objects", "HEAD", "--", "supplychain-agent").decode().splitlines()
    checked = 0
    for row in objects:
        sha, _, name = row.partition(" ")
        if not name.startswith("supplychain-agent/"):
            continue
        if git("cat-file", "-t", sha).strip() != b"blob":
            continue
        checked += 1
        hit = scan(git("cat-file", "blob", sha), keys)
        if hit:
            findings["history"][sha] = {"path": name.removeprefix("supplychain-agent/"), **hit}
    blockers = []
    for kind in ("index", "working", "history"):
        for name, hit in findings[kind].items():
            categories = {
                "provider_token",
                "private_key",
                "configured_secret",
                "email",
                "phone_candidate",
            }
            if kind != "history":
                categories.add("personal_path")
            if any(hit.get(key, 0) for key in categories):
                blockers.append({"scope": kind, "file_or_blob": name})
    result = {
        "public_release_snapshot_safe": not blockers and not forbidden and not differences,
        "scope": "project index and matching working tree; history scanned for credentials",
        "tracked_files": len(names),
        "reachable_project_blobs": checked,
        "configured_credentials_checked": len(keys),
        "blockers": blockers,
        "forbidden_files": forbidden,
        "unstaged_differences": differences,
        "findings": findings,
        "history_privacy": "Old dataset paths remain in historical blobs. Publish a clean "
        "project snapshot; existing history is not privacy-cleaned.",
        "human_review": "See PUBLIC_REPO_SAFETY_AUDIT.md for fake credentials and business data.",
    }
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "findings"}, ensure_ascii=False))
    if not result["public_release_snapshot_safe"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
