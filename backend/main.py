import json
import os
from typing import Literal

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from google import genai
from google.genai import types
from pydantic import BaseModel, Field, ValidationError

load_dotenv()

app = FastAPI(title="AI Visual Compliance Checker", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

MAX_IMAGE_BYTES = 10 * 1024 * 1024
ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp"}


class Finding(BaseModel):
    requirement: str = Field(description="The requirement being checked.")
    status: Literal["pass", "fail", "uncertain"] = Field(
        description="pass only when clearly satisfied; fail when clearly not satisfied; uncertain when image evidence is inconclusive."
    )
    observed: str = Field(description="Short description of visible evidence. Do not invent details.")
    correction: str = Field(description="Actionable correction. If passed, use an empty string.")
    confidence: Literal["low", "medium", "high"] = Field(
        description="Qualitative confidence based on image clarity and evidence."
    )


class InspectionReport(BaseModel):
    overall_status: Literal["compliant", "not_compliant", "needs_review"]
    summary: str
    findings: list[Finding]


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


@app.post("/analyze", response_model=InspectionReport)
async def analyze_image(
    image: UploadFile = File(...),
    requirements: str = Form(...),
):
    if image.content_type not in ALLOWED_TYPES:
        raise HTTPException(status_code=415, detail="Upload a JPG, PNG, or WEBP image.")

    image_bytes = await image.read()
    if not image_bytes:
        raise HTTPException(status_code=400, detail="The uploaded image is empty.")
    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="Image is too large. Maximum size is 10 MB.")

    try:
        requirement_list = json.loads(requirements)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Requirements must be a JSON array of strings.")

    if not isinstance(requirement_list, list) or not requirement_list:
        raise HTTPException(status_code=400, detail="Add at least one requirement.")
    if not all(isinstance(item, str) and item.strip() for item in requirement_list):
        raise HTTPException(status_code=400, detail="Every requirement must be a non-empty string.")
    if len(requirement_list) > 20:
        raise HTTPException(status_code=400, detail="Use no more than 20 requirements at once.")

    prompt = f"""
You are a careful visual compliance inspector. Inspect the attached image against every requirement below.

Requirements:
{json.dumps(requirement_list, ensure_ascii=False)}

Rules:
- Return exactly one finding for every requirement, preserving the requirement text.
- Use status "pass" only when the requirement is clearly satisfied by visible evidence.
- Use "fail" only when the image clearly shows a violation or the required item is clearly absent in a sufficiently visible scene.
- Use "uncertain" when the image is blurry, cropped, occluded, too distant, or does not provide enough evidence.
- Do not infer hidden facts. Do not identify people by identity.
- For clothing color, report the apparent visible color and consider lighting when deciding confidence.
- For brand names/logos, only mark pass when the branding is visually legible enough to support the claim. If uncertain, say so.
- Corrections should be specific and practical. For a passing finding, correction must be an empty string.
- The overall status should be "needs_review" if any finding is uncertain; otherwise "not_compliant" if any finding fails; otherwise "compliant".
- This is a visual assessment, not a guarantee of authenticity or perfect detection.
"""

    try:
        client = get_client()
        response = client.models.generate_content(
            model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
            contents=[
                prompt,
                types.Part.from_bytes(data=image_bytes, mime_type=image.content_type),
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
            raise HTTPException(status_code=502, detail="The model returned an empty response.")

        # Recalculate overall status server-side so it cannot contradict the findings.
        statuses = [finding.status for finding in report.findings]
        if len(report.findings) != len(requirement_list):
            raise HTTPException(status_code=502, detail="The model did not return one finding per requirement. Please try again.")

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
        raise HTTPException(status_code=502, detail="The model response did not pass schema validation. Please try again.")
    except Exception as exc:
        # Avoid leaking secrets or internal provider details to the browser.
        print(f"Analysis error: {type(exc).__name__}: {exc}")
        raise HTTPException(
            status_code=502,
            detail="Image analysis failed. Check your API key, model access, quota, and backend terminal logs.",
        )
