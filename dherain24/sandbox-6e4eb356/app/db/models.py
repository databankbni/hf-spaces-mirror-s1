import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Column,
    String,
    Float,
    Integer,
    Boolean,
    DateTime,
    ForeignKey,
    JSON,
    Text,
)
from sqlalchemy.orm import relationship
from app.db.session import Base

def generate_uuid() -> str:
    return str(uuid.uuid4())

def utc_now():
    return datetime.now(timezone.utc)

class Merchant(Base):
    __tablename__ = "merchants"

    id = Column(String(64), primary_key=True, default=generate_uuid)
    name = Column(String(128), nullable=False)
    email = Column(String(128), nullable=False, unique=True)
    webhook_secret = Column(String(128), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now)

    customers = relationship("Customer", back_populates="merchant", cascade="all, delete-orphan")
    cases = relationship("RecoveryCase", back_populates="merchant", cascade="all, delete-orphan")


class Customer(Base):
    __tablename__ = "customers"

    id = Column(String(64), primary_key=True)
    merchant_id = Column(String(64), ForeignKey("merchants.id"), nullable=False)
    name = Column(String(128), nullable=False)
    email = Column(String(128), nullable=False)
    phone = Column(String(32), nullable=True)
    tenure_days = Column(Integer, default=0)
    historical_success_rate = Column(Float, default=1.0)
    created_at = Column(DateTime(timezone=True), default=utc_now)

    merchant = relationship("Merchant", back_populates="customers")
    cases = relationship("RecoveryCase", back_populates="customer", cascade="all, delete-orphan")


class RecoveryCase(Base):
    __tablename__ = "recovery_cases"

    id = Column(String(64), primary_key=True)  # e.g. RR-000101
    merchant_id = Column(String(64), ForeignKey("merchants.id"), nullable=False)
    customer_id = Column(String(64), ForeignKey("customers.id"), nullable=False)
    source_type = Column(String(64), nullable=False)  # payment_failed, subscription_payment_failed
    source_id = Column(String(128), nullable=False, index=True)  # Razorpay payment_id / subscription_id
    amount_at_risk = Column(Float, nullable=False)
    currency = Column(String(8), default="INR")
    failure_reason = Column(String(128), nullable=False)
    raw_decline_code = Column(String(128), nullable=True)
    status = Column(String(32), nullable=False, default="DETECTED", index=True)
    priority = Column(Integer, default=50)  # 0 to 100
    created_at = Column(DateTime(timezone=True), default=utc_now)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    merchant = relationship("Merchant", back_populates="cases")
    customer = relationship("Customer", back_populates="cases")
    actions = relationship("RecoveryAction", back_populates="case", cascade="all, delete-orphan")
    outcomes = relationship("ActionOutcome", back_populates="case", cascade="all, delete-orphan")
    audit_logs = relationship("AuditLog", back_populates="case", cascade="all, delete-orphan")


class RecoveryAction(Base):
    __tablename__ = "recovery_actions"

    id = Column(String(64), primary_key=True, default=generate_uuid)
    case_id = Column(String(64), ForeignKey("recovery_cases.id"), nullable=False, index=True)
    action_type = Column(String(64), nullable=False)  # retry, delayed_retry, payment_link, no_action, escalate_human
    parameters = Column(JSON, default=dict)
    expected_recovery = Column(Float, default=0.0)
    policy_status = Column(String(32), default="PENDING")  # PENDING, APPROVED, REJECTED
    approval_required = Column(Boolean, default=False)
    execution_status = Column(String(32), default="READY")  # READY, EXECUTING, EXECUTED, FAILED
    executed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now)

    case = relationship("RecoveryCase", back_populates="actions")
    outcome = relationship("ActionOutcome", back_populates="action", uselist=False)


class ActionOutcome(Base):
    __tablename__ = "action_outcomes"

    id = Column(String(64), primary_key=True, default=generate_uuid)
    case_id = Column(String(64), ForeignKey("recovery_cases.id"), nullable=False, index=True)
    action_id = Column(String(64), ForeignKey("recovery_actions.id"), nullable=False, index=True)
    recovered = Column(Boolean, nullable=False, default=False)
    recovered_amount = Column(Float, default=0.0)
    time_to_recovery = Column(Float, default=0.0)  # in hours
    failure_reason = Column(String(256), nullable=True)
    verified_at = Column(DateTime(timezone=True), default=utc_now)

    case = relationship("RecoveryCase", back_populates="outcomes")
    action = relationship("RecoveryAction", back_populates="outcome")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(String(64), primary_key=True, default=generate_uuid)
    case_id = Column(String(64), ForeignKey("recovery_cases.id"), nullable=False, index=True)
    agent_run_id = Column(String(64), nullable=True)
    event_type = Column(String(64), nullable=False, index=True)  # STATE_TRANSITION, POLICY_CHECK, ACTION_EXECUTED, etc.
    payload = Column(JSON, default=dict)
    created_at = Column(DateTime(timezone=True), default=utc_now)

    case = relationship("RecoveryCase", back_populates="audit_logs")
