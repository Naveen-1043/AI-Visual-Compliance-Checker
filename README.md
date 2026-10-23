# AI Visual Compliance Checker

A starter MVP for checking whether an uploaded photo satisfies a list of visual requirements.

## What it does

- Accepts an image and a checklist of requirements.
- Sends the image to a vision-capable Gemini model.
- Requests structured JSON using a Pydantic schema and Gemini's structured-output feature.
- Displays each requirement as `pass`, `fail`, or `uncertain`, with observations and suggested corrections.

**Important:** Structured output constrains the response format; it does not guarantee the visual judgment is correct. Treat uncertain results as requiring human review. This MVP does not train a custom model or independently prove every visual claim.

## Stack

- Frontend: React + Vite
- Backend: Python + FastAPI
- Vision + structured output: Google Gen AI Python SDK
- Schema validation: Pydantic

## 1. Requirements

- Python 3.10+
- Node.js 18+
- A Gemini API key from Google AI Studio

## 2. Start the backend

Open a terminal in `backend/`:

```bash
python -m venv .venv
```

Windows:
```powershell
.venv\Scripts\Activate.ps1
```

macOS/Linux:
```bash
source .venv/bin/activate
```

Install packages:
```bash
pip install -r requirements.txt
```

Copy `.env.example` to `.env` and add your API key:
```env
GEMINI_API_KEY=your_api_key_here
GEMINI_MODEL=gemini-2.5-flash
```

Run the server:
```bash
uvicorn main:app --reload
```

Backend runs at `http://127.0.0.1:8000`. API docs: `http://127.0.0.1:8000/docs`.

## 3. Start the frontend

Open a second terminal in `frontend/`:

```bash
npm install
npm run dev
```

Open the local URL Vite prints (usually `http://localhost:5173`).

## 4. Try the Bajaj checklist

Default requirements:
- Bajaj banner is visible and readable.
- Exactly two staff members are visible and both wear blue T-shirts.
- A Bajaj vehicle is visible.
- At least one customer is visible.

Upload a clear photo and click **Check photo**. You can edit the requirements before submitting.

## How constrained decoding is used here

The backend defines a Pydantic output schema with fixed status enums (`pass`, `fail`, `uncertain`) and fixed overall statuses. The Gemini API receives that schema as a structured-output constraint. Pydantic validates the returned data again in the application.

This is a practical structured-output MVP. If the goal is specifically to study constrained-decoding algorithms, a later research phase should compare provider-enforced constrained output against unconstrained generation and evaluate schema validity, semantic accuracy, latency, and cost.

## Troubleshooting

- **Missing API key:** check that `backend/.env` exists and contains `GEMINI_API_KEY=...`.
- **Quota / 429:** check the API project's quota and billing settings; do not put API keys in React.
- **CORS:** the backend allows localhost Vite ports for local development only.
- **Incorrect visual judgment:** use a sharper image, add clearer requirements, and keep `uncertain` results for human review. Brand/logo verification and exact person counts may need specialized computer-vision models or manual review.
