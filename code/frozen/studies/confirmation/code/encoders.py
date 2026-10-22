"""Pinned MiniLM inference skeleton; no model loading or data reads on import."""
from __future__ import annotations
from pathlib import Path
import hashlib
import json
try:
    from .guard import require_execution
except ImportError:
    from guard import require_execution

MODEL_ID = "sentence-transformers/all-MiniLM-L6-v2"
REVISION = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
SEQUENCE_LIMIT = 256
CONTENT_LIMIT = 254
DIMENSION = 384
WEIGHT_SHA256 = "53aa51172d142c89d9012cce15ae4d6cc0ca6895895114379cacb4fab128d9db"


def _digest(path, opened):
    opened(path, "hash_only", "encoder identity verification")
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1048576), b""):
            h.update(block)
    return h.hexdigest()


class FrozenMiniLM:
    def __init__(self, model_directory, lock_path, *, permit, opened):
        require_execution(permit)
        import numpy as np
        import torch
        from transformers import AutoModel, AutoTokenizer
        self.np, self.torch, self.permit = np, torch, permit
        directory = Path(model_directory)
        opened(lock_path, "text_read", "frozen encoder manifest")
        lock = json.loads(Path(lock_path).read_text())
        if lock["revision"] != REVISION or lock["content_token_budget"] != CONTENT_LIMIT:
            raise ValueError("encoder lock drift")
        for name, meta in lock["files"].items():
            if _digest(directory / name, opened) != meta["sha256"]:
                raise ValueError("encoder config/tokenizer drift: " + name)
        if _digest(directory / "model.safetensors", opened) != WEIGHT_SHA256:
            raise ValueError("encoder weights drift")
        torch.set_num_threads(1)
        self.tokenizer = AutoTokenizer.from_pretrained(directory, local_files_only=True, use_fast=True)
        self.model = AutoModel.from_pretrained(directory, local_files_only=True,
                                              torch_dtype=torch.float32).cpu().eval()
        if self.tokenizer.num_special_tokens_to_add(pair=False) != 2:
            raise ValueError("single-sequence special-token budget drift")
        if self.model.config.hidden_size != DIMENSION or self.model.config.max_position_embeddings != 512:
            raise ValueError("encoder architecture drift")
        self.chunk_cache = {}  # bounded by executor; keys preserve exact token block

    def _chunk(self, ids):
        key = hashlib.sha256(json.dumps(ids, separators=(",", ":")).encode()).hexdigest()
        if key in self.chunk_cache:
            return self.chunk_cache[key]
        if len(ids) > CONTENT_LIMIT:
            raise ValueError("chunk exceeds frozen content budget")
        tokens = self.tokenizer.prepare_for_model(ids, add_special_tokens=True,
            truncation=False, return_attention_mask=True, return_token_type_ids=True)
        tensors = {k: self.torch.tensor([v], dtype=self.torch.long) for k, v in tokens.items()
                   if k in ("input_ids", "attention_mask", "token_type_ids")}
        if tensors["input_ids"].shape[1] > SEQUENCE_LIMIT:
            raise ValueError("no silent truncation allowed")
        with self.torch.no_grad():
            hidden = self.model(**tensors).last_hidden_state
            mask = tensors["attention_mask"].unsqueeze(-1).float()
            pooled = (hidden * mask).sum(1) / mask.sum(1).clamp(min=1e-9)
            result = self.torch.nn.functional.normalize(pooled, p=2, dim=1)[0].numpy().astype("float32")
        # Persistent/cache eviction decisions may change speed only, never results.
        if len(self.chunk_cache) >= 10000:
            self.chunk_cache.pop(next(iter(self.chunk_cache)))
        self.chunk_cache[key] = result
        return result

    def encode_corpus(self, serialized, *, first_chunk_only=False):
        require_execution(self.permit)
        if not serialized:
            return self.np.zeros(DIMENSION, dtype="float32"), {"tokens": 0, "chunks": 0}
        ids = self.tokenizer.encode(serialized, add_special_tokens=False, truncation=False)
        pieces = [ids[i:i + CONTENT_LIMIT] for i in range(0, len(ids), CONTENT_LIMIT)]
        selected = pieces[:1] if first_chunk_only else pieces
        vectors = self.np.stack([self._chunk(block) for block in selected])
        vector = vectors.mean(axis=0, dtype="float32")
        norm = self.np.linalg.norm(vector)
        if norm:
            vector /= norm
        return vector.astype("float32"), {"tokens": len(ids), "chunks": len(pieces),
            "encoded_chunks": len(selected), "content_budget": CONTENT_LIMIT,
            "first_chunk_only": bool(first_chunk_only)}
