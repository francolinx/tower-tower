"""bge-small-en-v1.5 embeddings on CUDA, loaded from a local path only (no network)."""

import os

os.environ.setdefault("HF_HUB_OFFLINE", "1")

from tower.store import BGE_QUERY_PREFIX  # noqa: E402

_model = None


def model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer

        path = os.environ.get("EMBED_MODEL_PATH", "/home/darkstar90/models/bge-small-en-v1.5")
        _model = SentenceTransformer(path, device="cuda", local_files_only=True)
    return _model


def embed_passage(text: str) -> list[float]:
    return model().encode(text, normalize_embeddings=True).tolist()


def embed_query(q: str) -> list[float]:
    return model().encode(BGE_QUERY_PREFIX + q, normalize_embeddings=True).tolist()
