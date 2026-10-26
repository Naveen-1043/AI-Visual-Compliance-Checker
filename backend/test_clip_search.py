
import torch
import faiss
import numpy as np
from PIL import Image
from transformers import CLIPModel, CLIPProcessor

MODEL_NAME = "openai/clip-vit-base-patch32"

print("Loading CLIP model...")

processor = CLIPProcessor.from_pretrained(MODEL_NAME)
model = CLIPModel.from_pretrained(MODEL_NAME)
model.eval()

# Add your own image path here.
image_path = input("Enter image path: ").strip().strip('"')

image = Image.open(image_path).convert("RGB")

image_inputs = processor(
    images=image,
    return_tensors="pt"
)

with torch.no_grad():
    image_features = model.get_image_features(**image_inputs)

# Handle CLIP output across Transformers versions.
if hasattr(image_features, "pooler_output"):
    image_features = image_features.pooler_output
elif hasattr(image_features, "image_embeds"):
    image_features = image_features.image_embeds

image_vector = image_features.cpu().numpy().astype("float32")
faiss.normalize_L2(image_vector)

# Create a FAISS index for cosine similarity via normalized vectors.
dimension = image_vector.shape[1]
index = faiss.IndexFlatIP(dimension)
index.add(image_vector)

query = input("Enter a search query: ").strip()

text_inputs = processor(
    text=[query],
    return_tensors="pt",
    padding=True,
    truncation=True
)

with torch.no_grad():
    text_features = model.get_text_features(**text_inputs)

if hasattr(text_features, "pooler_output"):
    text_features = text_features.pooler_output
elif hasattr(text_features, "text_embeds"):
    text_features = text_features.text_embeds

query_vector = text_features.cpu().numpy().astype("float32")
faiss.normalize_L2(query_vector)

scores, ids = index.search(query_vector, k=1)

print("\nSearch result:")
print("Image:", image_path)
print("Query:", query)
print("Similarity score:", round(float(scores[0][0]), 4))
print("Matched image index:", int(ids[0][0]))
