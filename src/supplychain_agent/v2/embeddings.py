"""Pinned BGE inference. Loading and encoding are strictly local; no auto-download."""

import hashlib
from pathlib import Path

import numpy as np

MODEL_ID = "BAAI/bge-small-zh-v1.5"
ARTIFACT_REPO = "Xenova/bge-small-zh-v1.5"
REVISION = "75c43b069aac4d136ba6bc1122f995fedcfd2781"
DEFAULT_MODEL_DIR = Path(".runtime/models/bge-small-zh-v1.5")
DIMENSIONS = 512
QUERY_INSTRUCTION = "为这个句子生成表示以用于检索相关文章："
# The ONNX SHA is also the publisher's LFS SHA; small-file hashes were checked
# from the same immutable revision. Never load remote Python / pickle code.
MODEL_FILES = {
    "onnx/model.onnx": {
        "size": 94851877,
        "sha256": "69a0b846f4f116b5e6aabf9546ea6754d02264f3211a13a1bd69b31b8040749a",
    },
    "tokenizer.json": {
        "size": 439125,
        "sha256": "48cea5d44424912a6fd1ea647bf4fe50b55ab8b1e5879c3275f80e339e8fae26",
    },
    "config.json": {
        "size": 716,
        "sha256": "d4193ead3a810fd694fa8a31d7fc72fbaebc0668b603e398734bf2f6538ff42f",
    },
}


class EmbeddingUnavailable(RuntimeError):
    """Missing dependencies, absent files or corrupt artifacts; never fallback."""


def file_sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify_model_files(directory):
    for name, expected in MODEL_FILES.items():
        path = Path(directory) / name
        if not path.is_file():
            raise EmbeddingUnavailable(
                f"embedding_file_missing:{name}; run scripts/prepare_embeddings.py explicitly"
            )
        if path.stat().st_size != expected["size"] or file_sha256(path) != expected["sha256"]:
            raise EmbeddingUnavailable(f"embedding_file_hash_mismatch:{name}")
    return {name: dict(record) for name, record in MODEL_FILES.items()}


def normalize_embeddings(matrix, rows, dimensions):
    matrix = np.array(matrix, dtype="float32", order="C", copy=True)
    if matrix.shape != (rows, dimensions) or not np.isfinite(matrix).all():
        raise ValueError("invalid_embedding_shape_or_values")
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    if np.any(norms <= 0) or not np.isfinite(norms).all():
        raise ValueError("invalid_embedding_norm")
    return matrix / norms


class BGEEncoder:
    dimensions = DIMENSIONS

    def __init__(self, model_dir=DEFAULT_MODEL_DIR):
        self.files = verify_model_files(model_dir)
        try:
            import onnxruntime as ort
            from tokenizers import Tokenizer
        except ImportError as exc:
            raise EmbeddingUnavailable("install_semantic_extra: uv sync --extra semantic") from exc
        self.tokenizer = Tokenizer.from_file(str(Path(model_dir) / "tokenizer.json"))
        self.tokenizer.enable_truncation(max_length=512)
        self.tokenizer.enable_padding(pad_id=0, pad_token="[PAD]")
        options = ort.SessionOptions()
        options.intra_op_num_threads = 1
        options.inter_op_num_threads = 1
        self.session = ort.InferenceSession(
            str(Path(model_dir) / "onnx/model.onnx"),
            sess_options=options,
            providers=["CPUExecutionProvider"],
        )
        self.input_names = {item.name for item in self.session.get_inputs()}
        if self.input_names != {"input_ids", "attention_mask", "token_type_ids"}:
            raise EmbeddingUnavailable("unexpected_onnx_inputs")

    def encode(self, texts, *, query=False):
        if not texts or any(not isinstance(t, str) or not t.strip() for t in texts):
            raise ValueError("empty_embedding_input")
        result = []
        # Bound peak token-state memory independently of caller batch size.
        for start in range(0, len(texts), 8):
            batch = texts[start : start + 8]
            inputs = [QUERY_INSTRUCTION + text for text in batch] if query else batch
            encoded = self.tokenizer.encode_batch(inputs)
            feed = {
                "input_ids": np.array([e.ids for e in encoded], dtype="int64"),
                "attention_mask": np.array([e.attention_mask for e in encoded], dtype="int64"),
                "token_type_ids": np.array([e.type_ids for e in encoded], dtype="int64"),
            }
            hidden = self.session.run(["last_hidden_state"], feed)[0]
            result.append(normalize_embeddings(hidden[:, 0, :], len(batch), self.dimensions))
        return np.concatenate(result)

    def manifest(self):
        return {
            "model": MODEL_ID,
            "artifact_repo": ARTIFACT_REPO,
            "revision": REVISION,
            "files": self.files,
            "dimensions": self.dimensions,
            "precision": "FP32 (not quantized)",
            "pooling": "last_hidden_state[:, 0, :] (CLS)",
            "normalization": "L2",
            "query_instruction": QUERY_INSTRUCTION,
            "document_instruction": "",
            "max_sequence_tokens": 512,
            "truncation": "right, including special tokens and query instruction",
            "batch_size": 8,
            "runtime": "onnxruntime / CPUExecutionProvider",
            "intra_op_threads": 1,
            "inter_op_threads": 1,
            "network_during_inference": False,
        }
