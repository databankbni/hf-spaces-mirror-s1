"""
Heaven on Earth CMS Backend - Partnership Model

Database model for partnership applications.
"""

from datetime import datetime, timezone
from typing import Optional
import uuid

from sqlalchemy import Boolean, DateTime, String, Text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Partnership(Base):
    """
    Partnership model for partnership applications.
    
    Tracks financial, volunteer, and material partnership requests.
    """
    
    __tablename__ = "partnerships"
    
    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    
    # Applicant information
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    email: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
    )
    phone: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
    )
    
    # Partnership type
    partnership_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
    )  # financial, volunteer, material
    
    # Message/interests
    message: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    
    # For volunteer: areas of interest
    volunteer_areas: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True,
        comment="Selected volunteer areas",
    )
    
    # For financial: commitment details
    financial_commitment: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True,
        comment="Financial commitment details (amount, frequency)",
    )
    
    # For material: items offered
    material_items: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True,
        comment="List of material items offered",
    )
    
    # Submission source
    source: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="form",
        server_default="form",
    )  # form, chatbot

    # Status tracking
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="pending",
        index=True,
    )  # pending, contacted, active, inactive, declined
    
    # Admin handling
    assigned_to_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    admin_notes: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    
    # Contact tracking
    last_contacted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    contact_count: Mapped[int] = mapped_column(
        default=0,
        nullable=False,
    )
    
    # Follow-up scheduling
    follow_up_date: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    
    # Audit fields
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    
    def __repr__(self) -> str:
        return f"<Partnership(id={self.id}, name={self.name}, type={self.partnership_type})>"
