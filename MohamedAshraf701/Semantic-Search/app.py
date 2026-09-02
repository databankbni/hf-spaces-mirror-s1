from fastapi import FastAPI, Query
from pydantic import BaseModel
from sentence_transformers import SentenceTransformer, util
from datasets import load_dataset
from typing import List
import numpy as np
import base64
from PIL import Image
from io import BytesIO

app = FastAPI()

@app.get("/")
def root():
    return {"message": "Welcome to the Product Search API!"}
def encode_image_to_base64(image):
    """
    Converts a PIL Image or an image-like object to a Base64-encoded string.
    """
    if isinstance(image, Image.Image):
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        return base64.b64encode(buffer.getvalue()).decode("utf-8")
    return None
# Initialize FastAPI

# Load Dataset
dataset = load_dataset("ashraq/fashion-product-images-small", split="train")

# Define fields for embedding
fields_for_embedding = [
    "productDisplayName",
    "usage",
    "season",
    "baseColour",
    "articleType",
    "subCategory",
    "masterCategory",
    "gender",
]

# Prepare Data
data = []
for item in dataset:
    data.append({
        "productDisplayName": item["productDisplayName"],
        "usage": item["usage"],
        "season": item["season"],
        "baseColour": item["baseColour"],
        "articleType": item["articleType"],
        "subCategory": item["subCategory"],
        "masterCategory": item["masterCategory"],
        "gender": item["gender"],
        "year": item["year"],
        "image": item["image"],
    })

# Load Sentence Transformer Model
model = SentenceTransformer("sentence-transformers/multi-qa-MiniLM-L6-cos-v1")

# Generate Embeddings
def create_combined_text(item):
    return " ".join([str(item[field]) for field in fields_for_embedding if item[field]])

texts = [create_combined_text(item) for item in data]
embeddings = model.encode(texts, convert_to_tensor=True)

# Response Model
class ProductResponse(BaseModel):
    productDisplayName: str
    usage: str
    season: str
    baseColour: str
    articleType: str
    subCategory: str
    masterCategory: str
    gender: str
    year: int
    image: str  # Base64 encoded string



@app.get("/products")
def search_products(
    query: str = Query("", title="Search Query", description="Search term for products"),
    page: int = Query(1, ge=1, title="Page Number"),
    items_per_page: int = Query(10, ge=1, le=100, title="Items Per Page"),
):
    # Perform Search
    if query:
        query_embedding = model.encode(query, convert_to_tensor=True)
        scores = util.cos_sim(query_embedding, embeddings).squeeze().tolist()
        ranked_indices = np.argsort(scores)[::-1]
    else:
        ranked_indices = np.arange(len(data))

    # Pagination
    total_items = len(ranked_indices)
    total_pages = (total_items + items_per_page - 1) // items_per_page
    start_idx = (page - 1) * items_per_page
    end_idx = start_idx + items_per_page
    paginated_indices = ranked_indices[start_idx:end_idx]

    # Prepare Response
    results = []
    for idx in paginated_indices:
        item = data[idx]
        results.append({
            "productDisplayName": item["productDisplayName"],
            "usage": item["usage"],
            "season": item["season"],
            "baseColour": item["baseColour"],
            "articleType": item["articleType"],
            "subCategory": item["subCategory"],
            "masterCategory": item["masterCategory"],
            "gender": item["gender"],
            "year": item["year"],
            "image": encode_image_to_base64(item["image"]),
        })

    # Construct the API response
    return {
        "status": 200,
        "data": results,
        "totalpages": total_pages,
        "currentpage": page
    }