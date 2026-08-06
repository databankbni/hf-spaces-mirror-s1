from pydantic import BaseModel, HttpUrl
from typing import Optional
from datetime import datetime, date
from enum import Enum


class IncidentCategory(str, Enum):
    corruption = "corruption"
    murders = "murders"
    sexual_assault = "sexual_assault"
    crimes_women_kids = "crimes_women_kids"
    censorship = "censorship"
    credit_stealing = "credit_stealing"
    governance = "governance"
    police_excess = "police_excess"
    drug_menace = "drug_menace"
    media_blackout = "media_blackout"
    tenders = "tenders"
    fake_news = "fake_news"
    alcohol_menace = "alcohol_menace"
    other = "other"


class IncidentStatus(str, Enum):
    pending_review = "pending_review"
    approved = "approved"
    rejected = "rejected"


class PromiseStatus(str, Enum):
    pending = "pending"
    kept = "kept"
    broken = "broken"
    partial = "partial"


# --- Incidents ---

class IncidentCreate(BaseModel):
    title: str
    summary: str
    category: str  # Free-form — broader than IncidentCategory enum (legacy)
    incident_date: date
    location: Optional[str] = None
    source_urls: list[str] = []
    member_ids: list[str] = []
    tags: Optional[list[str]] = None
    is_credit_steal: bool = False
    original_credit: Optional[str] = None  # e.g. "DMK scheme from 2023"
    related_dmk_scheme: Optional[str] = None
    ai_confidence: float = 0.0
    severity: int = 1  # 1-5


class IncidentOut(IncidentCreate):
    id: str
    status: IncidentStatus
    created_at: datetime
    ai_raw: Optional[dict] = None


class IncidentUpdate(BaseModel):
    title: Optional[str] = None
    summary: Optional[str] = None
    category: Optional[str] = None
    status: Optional[IncidentStatus] = None
    is_credit_steal: Optional[bool] = None
    original_credit: Optional[str] = None
    severity: Optional[int] = None
    tags: Optional[list[str]] = None


# --- Promises ---

class PromiseCreate(BaseModel):
    text: str
    category: str
    made_date: date
    deadline: Optional[date] = None
    status: PromiseStatus = PromiseStatus.pending
    evidence_url: Optional[str] = None
    source: str = "manifesto"


class PromiseOut(PromiseCreate):
    id: str
    created_at: datetime


class PromiseUpdate(BaseModel):
    status: Optional[PromiseStatus] = None
    evidence_url: Optional[str] = None
    notes: Optional[str] = None


# --- Members ---

class MemberCreate(BaseModel):
    name: str
    role: str
    constituency: Optional[str] = None
    party: str = "TVK"
    photo_url: Optional[str] = None
    wiki_url: Optional[str] = None


class MemberOut(MemberCreate):
    id: str
    incident_count: int = 0
    created_at: datetime


# --- Stats summary ---

class DashboardStats(BaseModel):
    govt_day: int
    corruption_count: int
    murders_count: int
    sexual_assault_count: int
    crimes_women_kids_count: int
    credit_steal_count: int
    promises_kept: int
    promises_total: int
    total_incidents: int


# --- Apify webhook payload ---

class ApifyWebhookItem(BaseModel):
    url: str
    title: str
    text: str
    published_at: Optional[str] = None
    source: Optional[str] = None
    tier: Optional[str] = None
    image_urls: list[str] = []


class ApifyWebhookPayload(BaseModel):
    actorId: str
    datasetId: str
    items: list[ApifyWebhookItem] = []
