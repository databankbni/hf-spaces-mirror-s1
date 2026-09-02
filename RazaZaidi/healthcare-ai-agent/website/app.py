import sys
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

from website.database import save_chat, get_chat_history, clear_history, create_user, get_user
from website.database import save_medical_report, get_user_reports, get_report_by_id, delete_report
from website.database import save_health_profile, get_health_profile
from website.auth import hash_password, verify_password, create_token, verify_token
from healthcare.graph import chat
from healthcare.report_parser import (
    parse_medical_report,
    extract_vitals,
    analyze_report_health,
    detect_file_type,
)
from healthcare.nodes import build_report_fallback_response, detect_intent
import json
import shutil
from fastapi import UploadFile, File, Form

app = FastAPI(title="HealthCare AI Chatbot")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
STATIC_DIR = PROJECT_ROOT / "static"
TEMPLATES_DIR = PROJECT_ROOT / "website" / "templates"
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", str(PROJECT_ROOT / "uploads")))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def static_asset_version(*relative_parts: str) -> str:
    """Return a cache-busting version token based on file modification time."""
    try:
        path = STATIC_DIR.joinpath(*relative_parts)
        return str(int(path.stat().st_mtime))
    except OSError:
        return "1"

class ChatRequest(BaseModel):
    message: str
    token: Optional[str] = None

class RegisterRequest(BaseModel):
    username: str
    email: str
    password: str

class LoginRequest(BaseModel):
    username: str
    password: str


CHAT_UPLOAD_ALLOWED_TYPES = [
    "image/jpeg",
    "image/png",
    "image/bmp",
    "image/tiff",
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/plain",
]
CHAT_UPLOAD_ALLOWED_EXTENSIONS = {
    ".pdf",
    ".jpg",
    ".jpeg",
    ".png",
    ".bmp",
    ".tiff",
    ".tif",
    ".doc",
    ".docx",
    ".txt",
}


def build_uploaded_file_prompt(filename: str, extracted_text: str, vitals: dict, parse_error: str = None) -> str:
    """Build a structured prompt segment so the agent can answer from extracted file contents."""
    safe_text = (extracted_text or "").strip()
    if not safe_text:
        safe_text = "No readable text could be extracted from this file."

    lines = [
        f"[Attached File: {filename}]",
        "You are given extracted content from the user's uploaded file.",
        "Treat this extracted content as primary evidence for your answer.",
        "If the user asks whether the report is normal, explain the key findings, what looks reassuring, and what may need medical follow-up.",
        "If the extracted content looks incomplete or OCR is weak, say that clearly and answer cautiously.",
    ]

    if parse_error:
        lines.append(f"File extraction note: {parse_error}")
        lines.append(
            "If this note mentions missing OCR/PDF dependencies, explain which dependency is missing and how the user can fix it."
        )

    if vitals:
        lines.append("Detected vitals or report values:")
        lines.append(json.dumps(vitals, indent=2))

    lines.append("Extracted text:")
    lines.append(safe_text[:6000])
    return "\n".join(lines)


def get_file_extension(filename: str) -> str:
    return os.path.splitext(filename or "")[1].lower()


def is_allowed_upload(filename: str, content_type: str | None) -> bool:
    ext = get_file_extension(filename)
    normalized_type = (content_type or "").lower().strip()
    if normalized_type in CHAT_UPLOAD_ALLOWED_TYPES:
        return True
    if ext in CHAT_UPLOAD_ALLOWED_EXTENSIONS:
        return True
    return False


def choose_stored_file_type(file_path: str, original_content_type: str | None) -> str:
    """Prefer detected type, then original type, then extension fallback."""
    detected = detect_file_type(file_path)
    if detected and detected != "application/octet-stream":
        return detected
    normalized_type = (original_content_type or "").lower().strip()
    if normalized_type:
        return normalized_type
    return detect_file_type(file_path)


def build_unsupported_upload_error(filename: str, content_type: str | None, parse_error: str | None = None) -> str:
    """Return a clear error when a saved upload still can't be parsed as a supported file."""
    ext = get_file_extension(filename) or "(no extension)"
    normalized_type = (content_type or "").strip() or "(empty content type)"
    base = (
        "Unsupported file type for upload. "
        "Allowed: PDF, JPG, PNG, BMP, TIFF, DOC, DOCX, TXT."
    )
    details = f" Received extension: {ext}. Received content type: {normalized_type}."
    if parse_error:
        details += f" Parser note: {parse_error}"
    return base + details


def build_local_upload_analysis(message: str, filename: str, extracted_text: str, vitals: dict, parse_error: str = None) -> str:
    """Produce a dependable local analysis for uploaded files without requiring an external LLM."""
    combined = (message or "Please analyze my uploaded file.").strip()
    if combined:
        combined += "\n\n"
    combined += build_uploaded_file_prompt(
        filename=filename,
        extracted_text=extracted_text,
        vitals=vitals,
        parse_error=parse_error,
    )
    return build_report_fallback_response(combined)

@app.get("/")
async def home(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "request": request,
            "script_js_version": static_asset_version("script.js"),
            "upload_js_version": static_asset_version("upload.js"),
        }
    )

@app.post("/api/register")
async def register(req: RegisterRequest):
    try:
        hashed = hash_password(req.password)
        success = create_user(req.username, req.email, hashed)
        if not success:
            raise HTTPException(status_code=400, detail="Username or email already exists!")
        return {"message": "Registration successful!", "status": "ok"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/login")
async def login(req: LoginRequest):
    try:
        user = get_user(req.username)
        if not user or not verify_password(req.password, user["password"]):
            raise HTTPException(status_code=401, detail="Invalid username or password!")
        token = create_token({"user_id": user["id"], "username": user["username"]})
        return {"token": token, "username": user["username"], "status": "ok"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/chat")
async def chat_endpoint(req: ChatRequest):
    try:
        user_id = 1
        username = "guest"
        if req.token:
            payload = verify_token(req.token)
            if payload:
                user_id = payload.get("user_id", 1)
                username = payload.get("username", "guest")
        history = get_chat_history(user_id, limit=5)
        previous_intent = "general"
        if history:
            previous_intent = history[-1].get("intent", "general") or "general"
        intent = detect_intent(req.message, {"last_intent": previous_intent})
        response = chat(req.message, history)
        save_chat(user_id, req.message, response, intent)
        return {"response": response, "intent": intent, "username": username, "status": "ok"}
    except Exception as e:
        return {"response": "Sorry, please try again.", "intent": "error", "status": "error"}


@app.post("/api/chat-upload")
async def chat_upload(message: str = Form(None), token: str = Form(None), file: UploadFile = File(None)):
    """Chat endpoint that accepts an optional file upload. Saves and parses the file and includes parsed text in the chat context."""
    try:
        user_id = 1
        username = "guest"
        if token:
            payload = verify_token(token)
            if payload:
                user_id = payload.get("user_id", 1)
                username = payload.get("username", "guest")
        # If a file was uploaded, save and parse it
        parsed_text = None
        vitals = {}
        parse_error = None
        if file:
            file_bytes = await file.read()
            if len(file_bytes) > 10 * 1024 * 1024:
                raise HTTPException(status_code=400, detail="File size must be under 10MB")
            user_dir = UPLOAD_DIR / str(user_id)
            user_dir.mkdir(parents=True, exist_ok=True)
            filename = f"{user_id}_{file.filename.replace(' ', '_')}"
            file_path = user_dir / filename
            with open(file_path, "wb") as f:
                f.write(file_bytes)
            stored_file_type = choose_stored_file_type(str(file_path), file.content_type)
            parse_result = parse_medical_report(str(file_path))
            print(f"DEBUG parse_medical_report result: {parse_result}")
            if not is_allowed_upload(file.filename, stored_file_type):
                raise HTTPException(
                    status_code=400,
                    detail=build_unsupported_upload_error(file.filename, stored_file_type, parse_result.get("error"))
                )
            if parse_result["success"]:
                parsed_text = parse_result["text"]
                vitals = extract_vitals(parsed_text)
            else:
                parse_error = parse_result.get("error", "Parse failed")
                if "unsupported" in parse_error.lower():
                    raise HTTPException(
                        status_code=400,
                        detail=build_unsupported_upload_error(file.filename, stored_file_type, parse_error)
                    )
                parsed_text = ""
            # Save the report record (optional)
            from website.database import save_medical_report
            save_medical_report(
                user_id=user_id,
                filename=file.filename,
                file_path=str(file_path),
                file_type=stored_file_type,
                file_size=len(file_bytes),
                extracted_text=parsed_text,
                vitals_json=json.dumps(vitals),
                analysis_summary="", pages=parse_result.get("pages", 0)
            )
        # Build the combined message for the agent
        combined = message or ""
        if file:
            if combined:
                combined += "\n\n"
            else:
                combined = "Please analyze my uploaded file.\n\n"
            combined += build_uploaded_file_prompt(
                filename=file.filename,
                extracted_text=parsed_text,
                vitals=vitals,
                parse_error=parse_error
            )
        print(f"DEBUG combined message sent to chat: {repr(combined)}")
        if file:
            response = build_local_upload_analysis(
                message=message or "",
                filename=file.filename,
                extracted_text=parsed_text or "",
                vitals=vitals,
                parse_error=parse_error,
            )
        else:
            history = get_chat_history(user_id, limit=5)
            response = chat(combined, history)
        saved_message = message or (f"Analyze {file.filename}" if file else "")
        save_chat(user_id, saved_message, response, "upload")
        return {"status": "ok", "response": response, "intent": "upload"}
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        print(f"ERROR in /api/chat-upload: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/history")
async def get_history(token: str):
    try:
        payload = verify_token(token)
        if not payload:
            raise HTTPException(status_code=401, detail="Invalid token!")
        user_id = payload.get("user_id")
        history = get_chat_history(user_id, limit=50)
        return {"history": history, "status": "ok"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/clear")
async def clear(token: str):
    try:
        payload = verify_token(token)
        if not payload:
            raise HTTPException(status_code=401, detail="Invalid token!")
        user_id = payload.get("user_id")
        clear_history(user_id)
        return {"message": "History cleared!", "status": "ok"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/health")
async def health():
    return {"status": "healthy", "message": "HealthCare AI is running!"}

@app.post("/api/upload-report")
async def upload_report(token: str, file: UploadFile = File(...)):
    """Upload a medical report (image or PDF) for analysis"""
    try:
        # Verify user
        payload = verify_token(token)
        if not payload:
            raise HTTPException(status_code=401, detail="Invalid token!")
        user_id = payload.get("user_id")
        
        # Validate file type
        # Validate file size (max 10MB)
        file_bytes = await file.read()
        if len(file_bytes) > 10 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="File size must be under 10MB")
        
        # Create user upload directory
        user_dir = UPLOAD_DIR / str(user_id)
        user_dir.mkdir(parents=True, exist_ok=True)
        
        # Save file
        filename = f"{user_id}_{file.filename.replace(' ', '_')}"
        file_path = user_dir / filename
        with open(file_path, "wb") as f:
            f.write(file_bytes)
        stored_file_type = choose_stored_file_type(str(file_path), file.content_type)
        
        # Parse the report
        parse_result = parse_medical_report(str(file_path))
        if not is_allowed_upload(file.filename, stored_file_type):
            raise HTTPException(
                status_code=400,
                detail=build_unsupported_upload_error(file.filename, stored_file_type, parse_result.get("error"))
            )
        
        if not parse_result["success"]:
            raise HTTPException(
                status_code=400,
                detail=parse_result["error"] or build_unsupported_upload_error(file.filename, stored_file_type)
            )
        
        # Extract vitals and generate analysis
        vitals = extract_vitals(parse_result["text"])
        analysis = analyze_report_health(parse_result["text"], vitals)
        
        ai_analysis = build_local_upload_analysis(
            message="Please analyze this uploaded report and summarize the key findings.",
            filename=file.filename,
            extracted_text=parse_result["text"],
            vitals=vitals,
            parse_error=parse_result.get("error"),
        )
        
        # Save to database
        report_id = save_medical_report(
            user_id=user_id,
            filename=file.filename,
            file_path=str(file_path),
            file_type=stored_file_type,
            file_size=len(file_bytes),
            extracted_text=parse_result["text"],
            vitals_json=json.dumps(vitals),
            analysis_summary=f"{analysis}\n\nAI Analysis:\n{ai_analysis}",
            pages=parse_result["pages"]
        )
        
        return {
            "status": "ok",
            "report_id": report_id,
            "filename": file.filename,
            "pages": parse_result["pages"],
            "vitals": vitals,
            "analysis": ai_analysis,
            "message": "Report uploaded and analyzed successfully!"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/reports")
async def get_reports(token: str):
    """Get user's uploaded medical reports"""
    try:
        payload = verify_token(token)
        if not payload:
            raise HTTPException(status_code=401, detail="Invalid token!")
        user_id = payload.get("user_id")
        
        reports = get_user_reports(user_id, limit=20)
        return {"reports": reports, "status": "ok"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/report/{report_id}")
async def get_report(report_id: int, token: str):
    """Get detailed analysis of a specific report"""
    try:
        payload = verify_token(token)
        if not payload:
            raise HTTPException(status_code=401, detail="Invalid token!")
        user_id = payload.get("user_id")
        
        report = get_report_by_id(report_id, user_id)
        if not report:
            raise HTTPException(status_code=404, detail="Report not found")
        
        # Parse vitals JSON
        vitals = json.loads(report["vitals_json"]) if report["vitals_json"] else {}
        
        return {
            "status": "ok",
            "report": {
                "id": report["id"],
                "filename": report["filename"],
                "file_type": report["file_type"],
                "pages": report["pages"],
                "uploaded_at": report["uploaded_at"],
                "vitals": vitals,
                "analysis": report["analysis_summary"],
                "extracted_text_preview": report["extracted_text"][:500] + "..." if len(report["extracted_text"]) > 500 else report["extracted_text"]
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/report/{report_id}")
async def delete_report_endpoint(report_id: int, token: str):
    """Delete a medical report"""
    try:
        payload = verify_token(token)
        if not payload:
            raise HTTPException(status_code=401, detail="Invalid token!")
        user_id = payload.get("user_id")
        
        # Get report to delete file
        report = get_report_by_id(report_id, user_id)
        if report and os.path.exists(report["file_path"]):
            os.remove(report["file_path"])
        
        success = delete_report(report_id, user_id)
        if success:
            return {"status": "ok", "message": "Report deleted"}
        else:
            raise HTTPException(status_code=404, detail="Report not found")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/health-profile")
async def update_health_profile(token: str, profile: dict):
    """Update user's health profile (conditions, medications, allergies)"""
    try:
        payload = verify_token(token)
        if not payload:
            raise HTTPException(status_code=401, detail="Invalid token!")
        user_id = payload.get("user_id")
        
        save_health_profile(
            user_id=user_id,
            conditions=json.dumps(profile.get("conditions", [])),
            medications=json.dumps(profile.get("medications", [])),
            allergies=json.dumps(profile.get("allergies", [])),
            blood_type=profile.get("blood_type"),
            dob=profile.get("dob"),
            gender=profile.get("gender")
        )
        
        return {"status": "ok", "message": "Health profile updated"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/health-profile")
async def get_user_health_profile(token: str):
    """Get user's health profile"""
    try:
        payload = verify_token(token)
        if not payload:
            raise HTTPException(status_code=401, detail="Invalid token!")
        user_id = payload.get("user_id")
        
        profile = get_health_profile(user_id)
        if profile:
            # Parse JSON fields
            return {
                "status": "ok",
                "profile": {
                    "conditions": json.loads(profile["conditions"]) if profile["conditions"] else [],
                    "medications": json.loads(profile["medications"]) if profile["medications"] else [],
                    "allergies": json.loads(profile["allergies"]) if profile["allergies"] else [],
                    "blood_type": profile["blood_type"],
                    "dob": profile["dob"],
                    "gender": profile["gender"]
                }
            }
        return {"status": "ok", "profile": None}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
