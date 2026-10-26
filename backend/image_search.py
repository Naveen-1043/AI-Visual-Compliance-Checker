import os
from pathlib import Path

import json
import re

from google import genai
from google.genai import types

import faiss
import numpy as np
import torch
from PIL import Image
from transformers import CLIPModel, CLIPProcessor

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

BASE_DIR = Path(__file__).resolve().parent
UPLOADS_DIR = BASE_DIR / "uploads"
INDEX_PATH = BASE_DIR / "faiss.index"
PATHS_FILE = BASE_DIR / "indexed_images.txt"

METADATA_PATH = BASE_DIR / "image_metadata.json"
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

metadata = {}

MODEL_NAME = "openai/clip-vit-base-patch32"
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
DEFAULT_THRESHOLD = 0.23
SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}

UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

print(f"Loading CLIP on {DEVICE}...")
processor = CLIPProcessor.from_pretrained(MODEL_NAME)
model = CLIPModel.from_pretrained(
    MODEL_NAME,
    use_safetensors=True,
).to(DEVICE)
model.eval()

index = None
image_paths = []

def load_metadata():
    global metadata

    if not METADATA_PATH.exists():
        metadata = {}
        return

    try:
        metadata = json.loads(
            METADATA_PATH.read_text(encoding="utf-8")
        )
    except Exception as exc:
        print(f"Metadata load error: {exc}")
        metadata = {}


def save_metadata():
    METADATA_PATH.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

def describe_image(image_path):
    api_key = os.getenv("GEMINI_API_KEY")
    print("Gemini API key loaded:", bool(api_key))

    if not api_key:
        print("GEMINI_API_KEY missing.")
        return None

    path = Path(image_path)

    mime_types = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
    }

    mime_type = mime_types.get(path.suffix.lower())

    if not mime_type:
        return None

    prompt = """
    Describe this image for visual search.
    Return JSON with string fields:
    description, objects, colors, people, text_or_brand.
    Mention visible vehicles, colors, objects and people count.
    Only report brands when clearly visible.
    Do not identify people or guess hidden details.
    """

    try:
        client = genai.Client(api_key=api_key)

        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=[
                prompt,
                types.Part.from_bytes(
                    data=path.read_bytes(),
                    mime_type=mime_type,
                ),
            ],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.1,
            ),
        )

        data = json.loads(response.text or "{}")

        fields = {
            key: str(data.get(key, ""))
            for key in (
                "description",
                "objects",
                "colors",
                "people",
                "text_or_brand",
            )
        }

        fields["search_text"] = " ".join(fields.values())
        fields["status"] = "ready"

        return fields

    except Exception as exc:
        print(f"Gemini description failed for {path.name}: {type(exc).__name__}: {exc}")
        return None


def load_saved_index():
    global index, image_paths
    load_metadata()

    if not INDEX_PATH.exists() or not PATHS_FILE.exists():
        index = None
        image_paths = []
        return

    try:
        loaded_index = faiss.read_index(str(INDEX_PATH))
        loaded_paths = PATHS_FILE.read_text(encoding="utf-8").splitlines()

        if loaded_index.ntotal != len(loaded_paths):
            print(
                "Warning: FAISS index/path count mismatch. "
                "Starting with an empty in-memory index."
            )
            index = None
            image_paths = []
            return

        index = loaded_index
        image_paths = loaded_paths
        print(f"Loaded {len(image_paths)} indexed images.")
    except Exception as exc:
        print(f"Could not load saved FAISS index: {exc}")
        index = None
        image_paths = []


def save_index():
    if index is not None:
        faiss.write_index(index, str(INDEX_PATH))
    PATHS_FILE.write_text("\n".join(image_paths), encoding="utf-8")

    save_metadata()

def _get_feature_vector(features):
    if hasattr(features, "image_embeds"):
        features = features.image_embeds
    elif hasattr(features, "text_embeds"):
        features = features.text_embeds
    elif hasattr(features, "pooler_output"):
        features = features.pooler_output
    elif hasattr(features, "last_hidden_state"):
        features = features.last_hidden_state[:, 0, :]

    vector = features.detach().cpu().numpy().astype("float32")
    faiss.normalize_L2(vector)
    return vector


def embed_image(image_path: Path):
    with Image.open(image_path) as source:
        image = source.convert("RGB")

    inputs = processor(images=image, return_tensors="pt")
    inputs = {key: value.to(DEVICE) for key, value in inputs.items()}

    with torch.no_grad():
        features = model.get_image_features(**inputs)

    return _get_feature_vector(features)


def embed_text(query: str):
    inputs = processor(
        text=[query],
        return_tensors="pt",
        padding=True,
        truncation=True,
    )
    inputs = {key: value.to(DEVICE) for key, value in inputs.items()}

    with torch.no_grad():
        features = model.get_text_features(**inputs)

    return _get_feature_vector(features)


def index_folder(folder_path: str):
    global index, image_paths

    folder = Path(folder_path).expanduser().resolve()
    if not folder.is_dir():
        raise ValueError("The provided path is not a valid folder.")

    existing = {str(Path(p).resolve()) for p in image_paths}
    new_paths = [
        path
        for path in folder.rglob("*")
        if path.is_file()
        and path.suffix.lower() in SUPPORTED_EXTENSIONS
        and str(path.resolve()) not in existing
    ]

    added = 0
    skipped = 0
    descriptions_created = 0

    # First, index any images that are not already in FAISS.
    for path in new_paths:
        try:
            vector = embed_image(path)
            if index is None:
                index = faiss.IndexFlatIP(vector.shape[1])

            index.add(vector)
            resolved_path = str(path.resolve())
            image_paths.append(resolved_path)
            added += 1
        except Exception as exc:
            print(f"Skipping image {path.name}: {type(exc).__name__}: {exc}")
            skipped += 1

    # Then generate missing descriptions for both old and newly indexed images.
    # Existing successful descriptions are reused; API failure doesn't break CLIP search.
    for image_path in image_paths:
        key = str(Path(image_path).resolve())
        if metadata.get(key, {}).get("status") == "ready":
            continue

        print(f"Generating description for: {Path(key).name}")
        description = describe_image(key)

        if description:
            metadata[key] = description
            descriptions_created += 1
            save_metadata()
        else:
            metadata.setdefault(
                key,
                {"status": "pending", "search_text": ""},
            )
            save_metadata()
            print("Description generation stopped; see Gemini error above.")
            break

    save_index()

    descriptions_pending = sum(
        1
        for path in image_paths
        if metadata.get(str(Path(path).resolve()), {}).get("status") != "ready"
    )

    return {
        "added": added,
        "skipped": skipped,
        "total": len(image_paths),
        "descriptions_created": descriptions_created,
        "descriptions_pending": descriptions_pending,
    }


def _get_tokens(text):
    return set(re.findall(r"[a-z0-9]+", (text or "").lower()))


def _metadata_score(query, item):
    query_tokens = _get_tokens(query)
    description_tokens = _get_tokens(item.get("search_text", ""))

    if not query_tokens or not description_tokens:
        return 0.0

    return len(query_tokens & description_tokens) / len(query_tokens)


def search_images(
    query: str,
    limit: int = 10,
    threshold: float = DEFAULT_THRESHOLD,
):
    if index is None or index.ntotal == 0:
        return []

    query = query.strip()
    if not query:
        return []

    limit = max(1, min(int(limit), 50))
    threshold = max(-1.0, min(float(threshold), 1.0))

    vector = embed_text(query)
    scores, ids = index.search(vector, index.ntotal)

    results = []

    for score, image_id in zip(scores[0], ids[0]):
        if image_id < 0:
            continue

        path = Path(image_paths[int(image_id)])
        key = str(path.resolve())
        item = metadata.get(key, {})

        clip_score = float(score)
        metadata_score = _metadata_score(query, item)

        # CLIP retrieves candidates; saved descriptions can improve ranking.
        if clip_score < threshold and metadata_score < 0.5:
            continue

        combined_score = (
            0.75 * clip_score
            + 0.25 * metadata_score
        )

        results.append({
            "image_id": int(image_id),
            "path": str(path),
            "filename": path.name,
            "score": round(clip_score, 4),
            "metadata_score": round(metadata_score, 4),
            "combined_score": round(combined_score, 4),
            "description": item.get("description", ""),
            "verified": False,
        })

    results.sort(
        key=lambda result: result["combined_score"],
        reverse=True,
    )

    print(
        f"Search query={query!r}, "
        f"results={len(results)}, threshold={threshold}"
    )

    return results[:limit]


load_saved_index()
