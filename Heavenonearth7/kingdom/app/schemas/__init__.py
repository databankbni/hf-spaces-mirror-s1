"""
Heaven on Earth CMS Backend - Schemas Package

All Pydantic schemas for request/response validation.
"""

from app.schemas.admin import (
    AdminCreate,
    AdminUpdate,
    AdminResponse,
    AdminInDB,
    AdminInvite,
    AdminInviteAccept,
    AdminLogin,
    Token,
    TokenRefresh,
)
from app.schemas.event import (
    EventCreate,
    EventUpdate,
    EventResponse,
    EventList,
)
from app.schemas.ministry import (
    MinistryCreate,
    MinistryUpdate,
    MinistryResponse,
    MinistryList,
)
from app.schemas.gallery import (
    GalleryItemCreate,
    GalleryItemUpdate,
    GalleryItemResponse,
    GalleryItemList,
)
from app.schemas.prayer import (
    PrayerRequestCreate,
    PrayerRequestUpdate,
    PrayerRequestResponse,
    PrayerRequestList,
)
from app.schemas.testimonial import (
    TestimonialCreate,
    TestimonialUpdate,
    TestimonialResponse,
    TestimonialList,
)
from app.schemas.partnership import (
    PartnershipCreate,
    PartnershipUpdate,
    PartnershipResponse,
    PartnershipList,
)
from app.schemas.common import (
    PaginationParams,
    PaginatedResponse,
    MessageResponse,
    HealthResponse,
)

__all__ = [
    # Admin
    "AdminCreate",
    "AdminUpdate",
    "AdminResponse",
    "AdminInDB",
    "AdminInvite",
    "AdminInviteAccept",
    "AdminLogin",
    "Token",
    "TokenRefresh",
    # Event
    "EventCreate",
    "EventUpdate",
    "EventResponse",
    "EventList",
    # Ministry
    "MinistryCreate",
    "MinistryUpdate",
    "MinistryResponse",
    "MinistryList",
    # Gallery
    "GalleryItemCreate",
    "GalleryItemUpdate",
    "GalleryItemResponse",
    "GalleryItemList",
    # Prayer
    "PrayerRequestCreate",
    "PrayerRequestUpdate",
    "PrayerRequestResponse",
    "PrayerRequestList",
    # Testimonial
    "TestimonialCreate",
    "TestimonialUpdate",
    "TestimonialResponse",
    "TestimonialList",
    # Partnership
    "PartnershipCreate",
    "PartnershipUpdate",
    "PartnershipResponse",
    "PartnershipList",
    # Common
    "PaginationParams",
    "PaginatedResponse",
    "MessageResponse",
    "HealthResponse",
]
