from sqlalchemy.orm import Session
from datetime import datetime
from app.models import WorkerSession
from app.utils.ids import generate_id

class WorkerSessionService:
    @staticmethod
    def register_worker(db: Session, worker_id: str, status: str, message: str = None) -> WorkerSession:
        """Registers a new worker or updates an existing worker session."""
        session = db.query(WorkerSession).filter(WorkerSession.worker_id == worker_id).first()
        
        if not session:
            session = WorkerSession(
                id=generate_id("ws"),
                worker_id=worker_id,
                status=status,
                started_at=datetime.utcnow(),
                last_heartbeat_at=datetime.utcnow(),
                message=message
            )
            db.add(session)
        else:
            session.status = status
            session.last_heartbeat_at = datetime.utcnow()
            session.message = message
            session.stopped_at = None  # reset stopped
        
        db.commit()
        db.refresh(session)
        return session

    @staticmethod
    def heartbeat(db: Session, worker_id: str, status: str, current_job_id: str = None, message: str = None) -> WorkerSession:
        """Updates worker session heartbeat and status details."""
        session = db.query(WorkerSession).filter(WorkerSession.worker_id == worker_id).first()
        if not session:
            # Auto-register if not found
            return WorkerSessionService.register_worker(db, worker_id, status, message)
        
        session.status = status
        session.last_heartbeat_at = datetime.utcnow()
        session.current_job_id = current_job_id
        session.message = message
        db.commit()
        db.refresh(session)
        return session

    @staticmethod
    def shutdown_worker(db: Session, worker_id: str, reason: str) -> WorkerSession:
        """Sets the worker status to stopped and records the stopped timestamp."""
        session = db.query(WorkerSession).filter(WorkerSession.worker_id == worker_id).first()
        if session:
            session.status = "stopped"
            session.stopped_at = datetime.utcnow()
            session.message = f"Shutdown requested. Reason: {reason}"
            session.current_job_id = None
            db.commit()
            db.refresh(session)
        return session
