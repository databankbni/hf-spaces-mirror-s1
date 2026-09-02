"""
Heaven on Earth CMS Backend - CRUD Package

Database operations for all models.
"""

from app.crud.admin import (
    get_admin_by_id,
    get_admin_by_email,
    get_admins,
    create_admin,
    update_admin,
    delete_admin,
    create_initial_admin,
)
from app.crud.event import (
    get_event_by_id,
    get_events,
    create_event,
    update_event,
    delete_event,
)
from app.crud.ministry import (
    get_ministry_by_id,
    get_ministry_by_key,
    get_ministries,
    create_ministry,
    update_ministry,
    delete_ministry,
)
from app.crud.gallery import (
    get_gallery_item_by_id,
    get_gallery_items,
    create_gallery_item,
    update_gallery_item,
    delete_gallery_item,
)
from app.crud.prayer import (
    get_prayer_request_by_id,
    get_prayer_requests,
    create_prayer_request,
    update_prayer_request,
    delete_prayer_request,
)
from app.crud.testimonial import (
    get_testimonial_by_id,
    get_testimonials,
    create_testimonial,
    update_testimonial,
    delete_testimonial,
)
from app.crud.partnership import (
    get_partnership_by_id,
    get_partnerships,
    create_partnership,
    update_partnership,
    delete_partnership,
)

__all__ = [
    # Admin
    "get_admin_by_id",
    "get_admin_by_email",
    "get_admins",
    "create_admin",
    "update_admin",
    "delete_admin",
    "create_initial_admin",
    # Event
    "get_event_by_id",
    "get_events",
    "create_event",
    "update_event",
    "delete_event",
    # Ministry
    "get_ministry_by_id",
    "get_ministry_by_key",
    "get_ministries",
    "create_ministry",
    "update_ministry",
    "delete_ministry",
    # Gallery
    "get_gallery_item_by_id",
    "get_gallery_items",
    "create_gallery_item",
    "update_gallery_item",
    "delete_gallery_item",
    # Prayer
    "get_prayer_request_by_id",
    "get_prayer_requests",
    "create_prayer_request",
    "update_prayer_request",
    "delete_prayer_request",
    # Testimonial
    "get_testimonial_by_id",
    "get_testimonials",
    "create_testimonial",
    "update_testimonial",
    "delete_testimonial",
    # Partnership
    "get_partnership_by_id",
    "get_partnerships",
    "create_partnership",
    "update_partnership",
    "delete_partnership",
]
