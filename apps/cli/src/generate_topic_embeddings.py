"""Generate query embeddings for fixed topics and save as JSON.

Usage:
    cd apps/cli && uv run src/generate_topic_embeddings.py

Output:
    ../../apps/app-backoffice/src/data/topic_embeddings.json
"""

import json
import sys
from pathlib import Path

from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
load_dotenv(REPO_ROOT / ".env")

MODELS_DIR = Path(r"D:\files\models")
EMBEDDING_MODEL = "intfloat/multilingual-e5-large"

TOPICS = [
    {"id": "risas", "query": "risas, carcajadas, riendo mucho, momento gracioso"},
    {"id": "baile", "query": "bailando, baile, moviendo el cuerpo, dance"},
    {"id": "bromas", "query": "broma, chiste, burla, trolleando, humor"},
    {"id": "reflexion", "query": "reflexión, momento profundo, consejo de vida, pensamiento serio"},
    {"id": "guinos", "query": "guiño, gesto coqueto, guiñando el ojo, mirada pícara"},
    {"id": "besos", "query": "beso a la cámara, mandando besos, besito, muah"},
]

OUT_PATH = REPO_ROOT / "apps" / "app-backoffice" / "src" / "data" / "topic_embeddings.json"


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    print(f"Loading model {EMBEDDING_MODEL} ...", flush=True)
    model = SentenceTransformer(EMBEDDING_MODEL, cache_folder=str(MODELS_DIR))

    queries = [f"query: {t['query']}" for t in TOPICS]
    print(f"Embedding {len(queries)} topics ...", flush=True)
    embeddings = model.encode(queries, normalize_embeddings=True)

    result = {}
    for i, topic in enumerate(TOPICS):
        result[topic["id"]] = {
            "query": topic["query"],
            "embedding": embeddings[i].tolist(),
        }
        print(f"  {topic['id']}: dim={len(embeddings[i])}")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f)

    print(f"\nSaved to {OUT_PATH}")
    print(f"File size: {OUT_PATH.stat().st_size / 1024:.1f} KB")


if __name__ == "__main__":
    main()
