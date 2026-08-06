"""
Dental Clinic Python Service
FastAPI service for PDF generation, sync queue, validation, notifications, and analytics.
"""

from fastapi import FastAPI, HTTPException, Response, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import date, datetime
from contextlib import asynccontextmanager
import asyncpg
import os
import uuid
import time
from dotenv import load_dotenv

from app.services.pdf_generator import PDFGenerator
from app.services.sync_queue import sync_queue, SyncStatus
from app.services.validation import validation_service, ValidationResult
from app.services.notification import notification_service, NotificationType
from app.services.analytics import analytics_service

load_dotenv()

# Shared PDF generator singleton.
# PDFGenerator.__init__ builds the whole reportlab stylesheet on every call,
# which is expensive (CPU + RAM churn) under load. Instantiating it once and
# reusing it across requests saves the repeated style-setup work.
_pdf_generator = PDFGenerator()
# In-memory TTL cache for monthly reports (the heaviest PDF).
# Key = md5(year-month + patient data) so repeated generation of the same
# month returns instantly; entries expire after _MONTHLY_CACHE_TTL seconds.
import hashlib
import json
import threading

_monthly_report_cache: Dict[str, tuple] = {}
_MONTHLY_CACHE_TTL = 600  # 10 minutes
_MONTHLY_CACHE_MAX_ENTRIES = 30
_monthly_cache_lock = threading.Lock()

# Database pool
db_pool = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage database connection pool lifecycle"""
    global db_pool
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        try:
            db_pool = await asyncpg.create_pool(
                database_url,
                min_size=1,  # Kept low to limit DB connections
                max_size=3,  # PDF service rarely needs multiple connections
                command_timeout=60
            )
            print("✅ Connected to PostgreSQL")
        except Exception as e:
            print(f"⚠️ Failed to connect to database: {e}")
            print("⚠️ Service will start without database connection")
    yield
    if db_pool:
        await db_pool.close()
        print("Database connection closed")

app = FastAPI(
    title="Dental Clinic Python Service",
    description="PDF generation, sync queue, validation, notifications, and analytics",
    version="2.0.0",
    lifespan=lifespan
)

# CORS
cors_origin = os.getenv("CORS_ORIGIN", "http://localhost:4200")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[cors_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============ Pydantic Models ============

class PatientVisitData(BaseModel):
    """Patient visit data for PDF generation"""
    nama_pasien: str = Field(..., alias="namaPasien")
    no_rm: str = Field(..., alias="noRm")
    tanggal_kunjungan: str = Field(..., alias="tanggalKunjungan")
    kelamin: str
    biaya: str
    tindakan: List[str] = Field(default_factory=list)
    lainnya: Optional[str] = None
    
    class Config:
        populate_by_name = True

class ReceiptData(BaseModel):
    """Receipt data for PDF generation"""
    nama_pasien: str = Field(..., alias="namaPasien")
    no_rm: str = Field(..., alias="noRm")
    tanggal: str
    tindakan: List[str] = Field(default_factory=list)
    total_biaya: int = Field(..., alias="totalBiaya")
    metode_pembayaran: str = Field(..., alias="metodePembayaran")
    
    class Config:
        populate_by_name = True

class PrescriptionData(BaseModel):
    """Prescription data for PDF generation"""
    nama_pasien: str = Field(..., alias="namaPasien")
    tanggal: str
    obat: List[dict] = Field(default_factory=list)
    catatan: Optional[str] = None
    
    class Config:
        populate_by_name = True

class MonthlyReportRequest(BaseModel):
    """Request for monthly report PDF generation"""
    year: int
    month: int = Field(ge=1, le=12)
    patients: List[Dict[str, Any]]
    summary: Dict[str, Any]
    count: int

# ============ Endpoints ============

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "python-pdf-service",
        "time": datetime.now().isoformat()
    }

@app.post("/api/documents/medical-record")
async def create_medical_record(data: PatientVisitData) -> Response:
    """
    Generate medical record PDF from patient visit data
    
    Returns PDF file as binary response
    """
    try:
        pdf_bytes = _pdf_generator.generate_medical_record({
            "patient_name": data.nama_pasien,
            "medical_record_number": data.no_rm,
            "visit_date": data.tanggal_kunjungan,
            "gender": data.kelamin,
            "payment_type": data.biaya,
            "actions": data.tindakan,
            "other_actions": data.lainnya
        })
        
        filename = f"rekam_medis_{data.no_rm}_{data.tanggal_kunjungan}.pdf"
        
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"'
            }
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/documents/medical-record/{visit_id}")
async def get_medical_record_by_visit(visit_id: str) -> Response:
    """
    Fetch visit data from database and generate PDF
    """
    if not db_pool:
        raise HTTPException(status_code=500, detail="Database not connected")
    
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT 
                p.name as patient_name,
                p.medical_record_number,
                p.gender,
                v.visit_date,
                v.payment_type,
                v.actions,
                v.other_actions
            FROM core.visits v
            JOIN core.patients p ON v.patient_id = p.id
            WHERE v.id = $1
        """, visit_id)
        
        if not row:
            raise HTTPException(status_code=404, detail="Visit not found")
        
        pdf_data = dict(row)
        pdf_data["visit_date"] = row["visit_date"].strftime("%Y-%m-%d")
        
        # Parse JSON actions
        import json
        if isinstance(pdf_data["actions"], str):
            pdf_data["actions"] = json.loads(pdf_data["actions"])
        
        pdf_bytes = _pdf_generator.generate_medical_record(pdf_data)
        
        filename = f"rekam_medis_{row['medical_record_number']}.pdf"
        
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"'
            }
        )

@app.post("/api/documents/receipt")
async def create_receipt(data: ReceiptData) -> Response:
    """Generate receipt/kwitansi PDF"""
    try:
        pdf_bytes = _pdf_generator.generate_receipt({
            "patient_name": data.nama_pasien,
            "medical_record_number": data.no_rm,
            "date": data.tanggal,
            "actions": data.tindakan,
            "total_amount": data.total_biaya,
            "payment_method": data.metode_pembayaran
        })
        
        filename = f"kwitansi_{data.no_rm}_{data.tanggal}.pdf"
        
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"'
            }
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/documents/prescription")
async def create_prescription(data: PrescriptionData) -> Response:
    """Generate prescription/resep PDF"""
    try:
        pdf_bytes = _pdf_generator.generate_prescription({
            "patient_name": data.nama_pasien,
            "date": data.tanggal,
            "medications": data.obat,
            "notes": data.catatan
        })
        
        filename = f"resep_{data.tanggal}.pdf"
        
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"'
            }
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/documents/monthly-report")
async def generate_monthly_report(data: MonthlyReportRequest) -> Response:
    """
    Generate monthly report PDF from visit data.
    Called via Go Core API proxy at /api/documents/monthly-report.
    """
    payload = data.model_dump()

    # Cache key: month + full patient data. Re-generating the same month
    # (e.g. user re-opens the report) returns the cached PDF instantly
    # instead of burning HF Space CPU on reportlab layout again.
    key = hashlib.md5(
        f"{data.year}-{data.month}-{data.count}-"
        f"{json.dumps(payload['patients'], sort_keys=True, default=str)}".encode()
    ).hexdigest()

    now = time.time()
    with _monthly_cache_lock:
        cached = _monthly_report_cache.get(key)
        if cached and now - cached[0] < _MONTHLY_CACHE_TTL:
            return _build_monthly_pdf_response(cached[1], data, cache_hit=True)

    try:
        pdf_bytes = _pdf_generator.generate_monthly_report(payload)

        with _monthly_cache_lock:
            if len(_monthly_report_cache) >= _MONTHLY_CACHE_MAX_ENTRIES:
                _monthly_report_cache.clear()
            _monthly_report_cache[key] = (now, pdf_bytes)

        return _build_monthly_pdf_response(pdf_bytes, data, cache_hit=False)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _build_monthly_pdf_response(pdf_bytes, data: MonthlyReportRequest, cache_hit: bool) -> Response:
    month_name = [
        '', 'Januari', 'Februari', 'Maret', 'April', 'Mei', 'Juni',
        'Juli', 'Agustus', 'September', 'Oktober', 'November', 'Desember'
    ][data.month]
    filename = f"Laporan_Bulanan_{data.year}_{str(data.month).zfill(2)}.pdf"

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{filename}"',
            "X-PDF-Cache": "HIT" if cache_hit else "MISS"
        }
    )


# ============ SYNC QUEUE ENDPOINTS ============

class SyncQueueRequest(BaseModel):
    """Request to add item to sync queue"""
    data: Dict[str, Any]
    entity_type: str = "patient"
    operation: str = "create"


@app.post("/api/sync/queue")
async def add_to_sync_queue(request: SyncQueueRequest):
    """Add item to background sync queue"""
    item_id = f"sync-{uuid.uuid4().hex[:8]}"
    item = await sync_queue.add_to_queue(
        item_id=item_id,
        data=request.data,
        entity_type=request.entity_type,
        operation=request.operation
    )
    return {
        "success": True,
        "message": "Item added to sync queue",
        "item_id": item_id,
        "status": item.status.value
    }


@app.get("/api/sync/status/{item_id}")
async def get_sync_status(item_id: str):
    """Get status of a sync item"""
    item = sync_queue.get_item(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    return item.to_dict()


@app.get("/api/sync/pending")
async def get_pending_syncs():
    """Get all pending sync items"""
    items = sync_queue.get_pending_items()
    return {
        "count": len(items),
        "items": [item.to_dict() for item in items]
    }


@app.get("/api/sync/all")
async def get_all_syncs():
    """Get all sync items including dead letter"""
    return sync_queue.get_all_items()


@app.post("/api/sync/retry/{item_id}")
async def retry_sync(item_id: str):
    """Manually retry a failed sync item"""
    item = await sync_queue.retry_item(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    return {
        "success": True,
        "message": "Item moved to retry queue",
        "item": item.to_dict()
    }


@app.get("/api/sync/stats")
async def get_sync_stats():
    """Get sync queue statistics"""
    return sync_queue.get_stats()


# ============ VALIDATION ENDPOINTS ============

class ValidatePatientRequest(BaseModel):
    """Patient data to validate"""
    data: Dict[str, Any]


@app.post("/api/validate/patient")
async def validate_patient(request: ValidatePatientRequest):
    """Validate patient data"""
    result = validation_service.validate_patient(request.data)
    return {
        "valid": result.valid,
        "errors": [err.dict() for err in result.errors],
        "sanitized_data": result.sanitized_data
    }


@app.get("/api/validate/rm/{no_rm}")
async def check_rm_available(no_rm: str, exclude_id: Optional[str] = None):
    """Check if RM number is available"""
    # Update validation service with db pool
    validation_service.db_pool = db_pool
    is_unique = await validation_service.check_rm_unique(no_rm, exclude_id)
    return {
        "no_rm": no_rm,
        "available": is_unique
    }


# ============ NOTIFICATION ENDPOINTS ============

@app.get("/api/notifications")
async def get_notifications(limit: int = 20, unread_only: bool = False):
    """Get recent notifications"""
    return {
        "notifications": notification_service.get_notifications(limit, unread_only),
        "unread_count": notification_service.get_unread_count()
    }


@app.post("/api/notifications/{notification_id}/read")
async def mark_notification_read(notification_id: str):
    """Mark a notification as read"""
    success = notification_service.mark_as_read(notification_id)
    return {"success": success}


@app.post("/api/notifications/read-all")
async def mark_all_notifications_read():
    """Mark all notifications as read"""
    count = notification_service.mark_all_read()
    return {"success": True, "marked_count": count}


@app.websocket("/api/notifications/ws")
async def notification_websocket(websocket: WebSocket):
    """WebSocket endpoint for real-time notifications"""
    await websocket.accept()
    notification_service.register_client(websocket)
    try:
        while True:
            # Keep connection alive, wait for client messages
            data = await websocket.receive_text()
            # Can handle ping/pong or other client commands here
    except WebSocketDisconnect:
        notification_service.unregister_client(websocket)


# ============ ANALYTICS ENDPOINTS ============

@app.get("/api/analytics/sync")
async def get_sync_analytics(hours: int = 24):
    """Get sync performance analytics"""
    return analytics_service.get_sync_stats(hours)


@app.get("/api/analytics/daily")
async def get_daily_report(days: int = 7):
    """Get daily sync report"""
    return {
        "days": days,
        "report": analytics_service.get_daily_report(days)
    }


@app.get("/api/analytics/errors")
async def get_error_breakdown(limit: int = 10):
    """Get breakdown of sync errors"""
    return {
        "errors": analytics_service.get_error_breakdown(limit)
    }


@app.get("/api/analytics/entities")
async def get_entity_breakdown():
    """Get sync breakdown by entity type"""
    return analytics_service.get_entity_breakdown()


@app.get("/api/analytics/recent")
async def get_recent_sync_events(limit: int = 20):
    """Get recent sync events"""
    return {
        "events": analytics_service.get_recent_events(limit)
    }


# ============ INTEGRATED SYNC ENDPOINT ============

@app.post("/api/sync/patient")
async def sync_patient_data(request: ValidatePatientRequest):
    """
    Full sync flow: validate -> queue -> process
    This is the main endpoint called by the frontend.
    """
    start_time = time.time()
    item_id = f"patient-{uuid.uuid4().hex[:8]}"
    
    # 1. Validate data
    validation_result = validation_service.validate_patient(request.data)
    if not validation_result.valid:
        analytics_service.record_sync_attempt(
            item_id=item_id,
            entity_type="patient",
            operation="create",
            success=False,
            error="Validation failed"
        )
        return {
            "success": False,
            "stage": "validation",
            "errors": [err.dict() for err in validation_result.errors]
        }
    
    # 2. Add to sync queue
    await sync_queue.add_to_queue(
        item_id=item_id,
        data=validation_result.sanitized_data,
        entity_type="patient",
        operation="create"
    )
    
    # 3. Try immediate sync to database
    if db_pool:
        try:
            async with db_pool.acquire() as conn:
                data = validation_result.sanitized_data
                import json
                
                # Build actions array
                actions = []
                for action in ["Obat", "Cabut Anak", "Cabut Dewasa", 
                               "Tambal Sementara", "Tambal Tetap", "Scaling", "Rujuk"]:
                    if data.get(action) == "Ya":
                        actions.append(action)
                
                await conn.execute("""
                    INSERT INTO data_entries 
                    (date, patient_name, medical_record_number, gender, payment_type, actions, other_actions)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                """,
                    data.get("Tanggal Kunjungan"),
                    data.get("Nama Pasien"),
                    data.get("No.RM"),
                    data.get("Kelamin"),
                    data.get("Biaya"),
                    json.dumps(actions),
                    data.get("Lainnya")
                )
                
                # Success - remove from queue
                await sync_queue.mark_success(item_id)
                duration = (time.time() - start_time) * 1000
                analytics_service.record_sync_attempt(
                    item_id=item_id,
                    entity_type="patient",
                    operation="create",
                    success=True,
                    duration_ms=duration
                )
                
                await notification_service.notify_sync_success(item_id)
                
                return {
                    "success": True,
                    "item_id": item_id,
                    "synced": True,
                    "duration_ms": round(duration, 2)
                }
                
        except Exception as e:
            # Failed - mark for retry
            await sync_queue.mark_failed(item_id, str(e))
            await notification_service.notify_sync_failed(item_id, str(e), 1)
            analytics_service.record_sync_attempt(
                item_id=item_id,
                entity_type="patient",
                operation="create",
                success=False,
                error=str(e)
            )
            
            return {
                "success": True,  # Still success for user (optimistic)
                "item_id": item_id,
                "synced": False,
                "queued": True,
                "message": "Data queued for retry"
            }
    
    # No database connection - keep in queue
    return {
        "success": True,
        "item_id": item_id,
        "synced": False,
        "queued": True,
        "message": "Data queued for sync"
    }


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8081))
    uvicorn.run(app, host="0.0.0.0", port=port)


