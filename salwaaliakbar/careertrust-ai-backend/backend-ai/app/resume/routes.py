from fastapi import APIRouter, File, UploadFile, Depends, HTTPException, Form
from app.config import require_api_key
from app.resume.parser import parse_resume_file
import traceback

router = APIRouter()


@router.post('/parse-resume', dependencies=[Depends(require_api_key)])
async def parse_resume(file: UploadFile = File(...),
    fullName: str = Form(""),
    email: str = Form("")
    ):
    contents = await file.read()
    filename = file.filename or "resume"

    try:
        # Parse using pyresume; pass filename so parser can detect PDFs/DOCX
        parsed = parse_resume_file(contents, filename=filename)

        print(f"Parsed resume for: {parsed.get('name')}")
        print("full name:", fullName)

        print("email:", email)
        print("parsed email:", parsed.get("email"))
        mismatches = {
        "name": parsed.get("name") != fullName,
        "email": parsed.get("email") != email,
        }

        return {
        "parsed": parsed,
        "mismatches": mismatches,
        }
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Parsing error: {str(e)}")
