import os
from fastapi import APIRouter, HTTPException
from database.chroma import list_documents, delete_document

router = APIRouter()

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploads")

@router.get("/documents")
async def get_all_documents():
    try:
        docs = list_documents()
        return docs
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch documents: {str(e)}")

@router.delete("/documents/{document_id}")
async def remove_document(document_id: str):
    try:
        # Delete from ChromaDB
        delete_document(document_id)
        
        # Delete from uploads folder
        if os.path.exists(UPLOAD_DIR):
            for file_name in os.listdir(UPLOAD_DIR):
                if file_name.startswith(document_id):
                    file_path = os.path.join(UPLOAD_DIR, file_name)
                    try:
                        os.remove(file_path)
                    except Exception:
                        pass
                        
        return {"message": "Document and chunks successfully deleted"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete document: {str(e)}")
