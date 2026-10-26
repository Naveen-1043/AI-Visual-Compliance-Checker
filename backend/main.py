
import json
import os
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from google import genai
from google.genai import types
from pydantic import BaseModel, Field, ValidationError

import image_search as image_search_service

load_dotenv()

app = FastAPI(title="AI Visual Compliance Checker", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

MAX_IMAGE_BYTES = 10 * 1024 * 1024
ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp"}


class Finding(BaseModel):
    requirement: str = Field(description="The requirement being checked.")
    status: Literal["pass", "fail", "uncertain"] = Field(
        description="pass only when clearly satisfied; fail when clearly not satisfied; uncertain when evidence is inconclusive."
    )
    observed: str = Field(description="Short description of visible evidence.")
    correction: str = Field(description="Actionable correction, or empty string if passed.")
    confidence: Literal["low", "medium", "high"] = Field(
        description="Qualitative confidence based on image clarity and evidence."
    )


class InspectionReport(BaseModel):
    overall_status: Literal["compliant", "not_compliant", "needs_review"]
    summary: str
    findings: list[Finding]


class IndexFolderRequest(BaseModel):
    folder_path: str = Field(
        min_length=1,
        description="Absolute path to a local image folder.",
    )


def get_client():
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=500,
            detail="GEMINI_API_KEY is missing. Add it to backend/.env and restart the server.",
        )
    return genai.Client(api_key=api_key)


@app.get("/")
def root():
    return {"message": "AI Visual Compliance Checker API is running"}


@app.get("/health")
def health():
    return {"status": "ok"}


# ---------------- EXISTING COMPLIANCE CHECKER ----------------

@app.post("/analyze", response_model=InspectionReport)
async def analyze_image(
    image: UploadFile = File(...),
    requirements: str = Form(...),
):
    if image.content_type not in ALLOWED_TYPES:
        raise HTTPException(
            status_code=415,
            detail="Upload a JPG, PNG, or WEBP image.",
        )

    image_bytes = await image.read()

    if not image_bytes:
        raise HTTPException(status_code=400, detail="The uploaded image is empty.")

    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise HTTPException(
            status_code=413,
            detail="Image is too large. Maximum size is 10 MB.",
        )

    try:
        requirement_list = json.loads(requirements)
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=400,
            detail="Requirements must be a JSON array of strings.",
        )

    if not isinstance(requirement_list, list) or not requirement_list:
        raise HTTPException(status_code=400, detail="Add at least one requirement.")

    if not all(isinstance(item, str) and item.strip() for item in requirement_list):
        raise HTTPException(
            status_code=400,
            detail="Every requirement must be a non-empty string.",
        )

    if len(requirement_list) > 20:
        raise HTTPException(
            status_code=400,
            detail="Use no more than 20 requirements at once.",
        )

    prompt = f"""
You are a careful visual compliance inspector. Inspect the attached image against every requirement below.

Requirements:
{json.dumps(requirement_list, ensure_ascii=False)}

Rules:
- Return exactly one finding for every requirement, preserving the requirement text.
- Use status "pass" only when clearly satisfied by visible evidence.
- Use "fail" only when a violation or required item's absence is clearly visible.
- Use "uncertain" when evidence is insufficient, blurry, cropped, occluded, or too distant.
- Do not infer hidden facts or identify people by identity.
- For clothing color, report the apparent visible color and consider lighting.
- For brand names/logos, only pass when branding is legible enough to support the claim.
- Corrections should be practical. For a passing finding, correction must be empty.
- Overall status must be "needs_review" if any finding is uncertain; otherwise "not_compliant" if any fails; otherwise "compliant".
- This is a visual assessment, not a guarantee of perfect detection.
"""

    try:
        client = get_client()
        response = client.models.generate_content(
            model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
            contents=[
                prompt,
                types.Part.from_bytes(
                    data=image_bytes,
                    mime_type=image.content_type,
                ),
            ],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=InspectionReport,
                temperature=0.1,
            ),
        )

        if getattr(response, "parsed", None) is not None:
            report = InspectionReport.model_validate(response.parsed)
        elif response.text:
            report = InspectionReport.model_validate_json(response.text)
        else:
            raise HTTPException(
                status_code=502,
                detail="The model returned an empty response.",
            )

        statuses = [finding.status for finding in report.findings]

        if len(report.findings) != len(requirement_list):
            raise HTTPException(
                status_code=502,
                detail="The model did not return one finding per requirement. Please try again.",
            )

        if "uncertain" in statuses:
            report.overall_status = "needs_review"
        elif "fail" in statuses:
            report.overall_status = "not_compliant"
        else:
            report.overall_status = "compliant"

        return report

    except HTTPException:
        raise
    except ValidationError:
        raise HTTPException(
            status_code=502,
            detail="The model response did not pass schema validation. Please try again.",
        )
    except Exception as exc:
        print(f"Analysis error: {type(exc).__name__}: {exc}")
        raise HTTPException(
            status_code=502,
            detail="Image analysis failed. Check your API key, model access, quota, and backend terminal logs.",
        )


# ---------------- BULK IMAGE SEARCH ----------------

@app.get("/images/status")
def image_search_status():
    service = image_search_service

    return {
        "indexed_images": len(service.image_paths),
        "index_ready": (
            service.index is not None
            and service.index.ntotal > 0
        ),
    }


@app.post("/images/index-folder")
def index_image_folder(request: IndexFolderRequest):
    try:
        result = image_search_service.index_folder(request.folder_path)

        return {
            "message": "Folder indexing completed.",
            **result,
        }

    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        print(f"Image indexing error: {type(exc).__name__}: {exc}")
        raise HTTPException(
            status_code=500,
            detail="Image indexing failed. Check the backend terminal.",
        )


@app.get("/images/search")
def search_image_collection(q: str, limit: int = 20):
    query = q.strip()

    if not query:
        raise HTTPException(status_code=400, detail="Enter a search query.")

    if not 1 <= limit <= 100:
        raise HTTPException(
            status_code=400,
            detail="Limit must be between 1 and 100.",
        )

    results = image_search_service.search_images(query, limit)

    for result in results:
        result["image_url"] = f"/images/file/{result['image_id']}"

    return {
        "query": query,
        "count": len(results),
        "results": results,
    }


@app.get("/images/file/{image_id}")
def get_indexed_image(image_id: int):
    service = image_search_service

    if image_id < 0 or image_id >= len(service.image_paths):
        raise HTTPException(status_code=404, detail="Image not found.")

    image_path = Path(service.image_paths[image_id])

    if not image_path.is_file():
        raise HTTPException(
            status_code=404,
            detail="Image file no longer exists.",
        )

    return FileResponse(image_path)
