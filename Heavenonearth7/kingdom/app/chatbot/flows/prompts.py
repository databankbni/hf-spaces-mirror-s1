"""
Heaven on Earth CMS Backend — Field Prompts

Bilingual (English + Amharic) prompt strings for every slot across all
conversational action flows.  Each key maps to a dict with ``"en"`` and
``"am"`` entries so the ``action_flow_node`` can serve the appropriate
language without branching logic.

References
----------
- Req §8 (Conversational Action Flows), §9–§11 (flow field definitions)
- Design § "Bilingual Design (Amharic + English)"
- Arch §10 "Conversational Action Flows" → FIELD_PROMPTS
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# FIELD_PROMPTS
# ---------------------------------------------------------------------------
# Key pattern: "{flow}_{field}" or just "{field}" for shared prompts.
# Each value: {"en": "<English prompt>", "am": "<Amharic prompt>"}
# ---------------------------------------------------------------------------

FIELD_PROMPTS: dict[str, dict[str, str]] = {

    # -----------------------------------------------------------------------
    # Testimony flow slots
    # -----------------------------------------------------------------------

    "testimony_name": {
        "en": "I'd love to hear your testimony! Could you start by telling me your name?",
        "am": "ምስክርነትዎን ለማዳመጥ ደስ ይለኛል! ስምዎን ቢነግሩኝ ደስ ይለኛል።",
    },
    "testimony_title": {
        "en": "Wonderful! What would you like to title your testimony? (You can skip this by typing 'skip'.)",
        "am": "አስደናቂ ነው! ለምስክርነትዎ ምን ርዕስ ይሰጡታል? (ለማቆም 'skip' ብለው ይጻፉ።)",
    },
    "testimony_content": {
        "en": "Please share your testimony. What did God do for you?",
        "am": "እባክዎ ምስክርነትዎን ያካፍሉን። እግዚአብሔር ምን አደረገልዎ?",
    },
    "testimony_content_too_short": {
        "en": "Please share a little more about what God did for you. 🙏",
        "am": "እባክዎ እግዚአብሔር ስለ አደረጉልዎ ትንሽ ተጨማሪ ያካፍሉን። 🙏",
    },
    "testimony_category": {
        "en": (
            "Which category best describes your testimony?\n"
            "• healing\n• salvation\n• provision\n• deliverance\n• general"
        ),
        "am": (
            "ምስክርነትዎን በጣም የሚገልፅ ምድብ የቱ ነው?\n"
            "• ፈውስ (healing)\n• ድኅነት (salvation)\n• አቅርቦት (provision)\n"
            "• ነፃነት (deliverance)\n• አጠቃላይ (general)"
        ),
    },
    "testimony_category_invalid": {
        "en": (
            "Please choose one of the following categories: "
            "healing, salvation, provision, deliverance, general."
        ),
        "am": (
            "እባክዎ ከሚከተሉት ምድቦች አንዱን ይምረጡ፦ "
            "healing, salvation, provision, deliverance, general።"
        ),
    },
    "testimony_email": {
        "en": "Would you like to leave your email address? (Optional — type 'skip' to continue.)",
        "am": "የኢሜይል አድራሻዎን ማስቀመጥ ይፈልጋሉ? (አስፈላጊ አይደለም — ለቀጣዩ 'skip' ብለው ይጻፉ።)",
    },
    "testimony_phone": {
        "en": "Would you like to leave your phone number? (Optional — type 'skip' to continue.)",
        "am": "የስልክ ቁጥርዎን ማስቀመጥ ይፈልጋሉ? (አስፈላጊ አይደለም — ለቀጣዩ 'skip' ብለው ይጻፉ።)",
    },
    "testimony_location": {
        "en": "Where are you from? (Optional — type 'skip' to continue.)",
        "am": "ከምን ቦታ ናቸዎ? (አስፈላጊ አይደለም — ለቀጣዩ 'skip' ብለው ይጻፉ።)",
    },

    # -----------------------------------------------------------------------
    # Prayer request flow slots
    # -----------------------------------------------------------------------

    "prayer_is_anonymous": {
        "en": (
            "Our prayer team would be honoured to receive your request. Would you like to submit it anonymously? (Reply **yes** or **no**.)"
        ),
        "am": (
            "የጸሎት ቡድናችን ጥያቄዎን ለመቀበል ደስተኛ ናቸው። ጥያቄዎን ሳይታወቅ ማስገባት ይፈልጋሉ? (**አዎ** ወይም **አይ** ብለው ይምለሱ።)"
        ),
    },
    "prayer_name": {
        "en": "What is your name? (We'll add it to your prayer request.)",
        "am": "ስምዎ ምንድን ነው? (ለጸሎት ጥያቄዎ እናያይዛለን።)",
    },
    "prayer_request": {
        "en": "Please share your prayer request. How can we pray for you? (at least 10 characters)",
        "am": "የጸሎት ጥያቄዎን ያካፍሉን። እንዴት ልንጸልይልዎ እንችላለን? (ቢያንስ 10 ፊደላት)",
    },
    "prayer_request_too_short": {
        "en": "Please share a bit more detail about your prayer request (at least 10 characters). 🙏",
        "am": "ስለ ጸሎት ጥያቄዎ ትንሽ ተጨማሪ ዝርዝር ያካፍሉን (ቢያንስ 10 ፊደላት)። 🙏",
    },
    "prayer_email": {
        "en": "Would you like to leave your email so we can follow up? (Optional — type 'skip'.)",
        "am": "ለክትትል ኢሜይልዎን ማስቀመጥ ይፈልጋሉ? (አስፈላጊ አይደለም — 'skip' ይጻፉ።)",
    },
    "prayer_phone": {
        "en": "Would you like to leave your phone number? (Optional — type 'skip'.)",
        "am": "የስልክ ቁጥርዎን ማስቀመጥ ይፈልጋሉ? (አስፈላጊ አይደለም — 'skip' ይጻፉ።)",
    },

    # -----------------------------------------------------------------------
    # Partnership flow slots
    # -----------------------------------------------------------------------

    "partnership_name": {
        "en": "Welcome! We're glad you'd like to partner with us. What is your name?",
        "am": "እንኳን ደህና መጡ! ከእኛ ጋር ለመተባበር ፈቃደኛ ስለሆኑ ደስ ይለናል። ስምዎ ምንድን ነው?",
    },
    "partnership_name_invalid": {
        "en": "Please enter a name with at least 2 characters.",
        "am": "እባክዎ ቢያንስ 2 ፊደላት ያለው ስም ያስገቡ።",
    },
    "partnership_email": {
        "en": "What is your email address? (We'll use this to contact you.)",
        "am": "የኢሜይል አድራሻዎ ምንድን ነው? (ለመገናኛ እንጠቀምበታለን።)",
    },
    "partnership_email_invalid": {
        "en": "That doesn't look like a valid email address. Please enter a valid email (e.g. name@example.com).",
        "am": "ትክክለኛ የኢሜይል አድራሻ አይመስልም። ትክክለኛ ኢሜይል ያስገቡ (ለምሳሌ፦ name@example.com)።",
    },
    "partnership_phone": {
        "en": "What is your phone number? (Optional — type 'skip' to continue.)",
        "am": "የስልክ ቁጥርዎ ምንድን ነው? (አስፈላጊ አይደለም — ለቀጣዩ 'skip' ይጻፉ።)",
    },
    "partnership_type": {
        "en": (
            "How would you like to partner with us?\n"
            "• **financial** — Monetary giving / tithing\n"
            "• **volunteer** — Serving with your time and skills\n"
            "• **material** — Donating goods or resources"
        ),
        "am": (
            "ከእኛ ጋር እንዴት መተባበር ይፈልጋሉ?\n"
            "• **financial** — ገንዘባዊ ድጋፍ / ዐሥራት\n"
            "• **volunteer** — በጊዜዎና ችሎታዎ ማገልገል\n"
            "• **material** — እቃዎች ወይም ሀብቶችን መለገስ"
        ),
    },
    "partnership_type_invalid": {
        "en": "Please choose one of the following: **financial**, **volunteer**, or **material**.",
        "am": "እባክዎ ከሚከተሉት አንዱን ይምረጡ፦ **financial**, **volunteer**, ወይም **material**።",
    },
    "partnership_volunteer_areas": {
        "en": (
            "That's wonderful — thank you for offering your time! "
            "Which areas would you like to volunteer in? "
            "(e.g. worship, children's ministry, hospitality, media — "
            "you can list multiple areas separated by commas)"
        ),
        "am": (
            "አስደናቂ ነው — ጊዜዎን ለማቅረብ ምስጋና! "
            "በምን አካባቢዎች መሳተፍ ይፈልጋሉ? "
            "(ለምሳሌ፦ አምልኮ፣ የልጆች አገልግሎት፣ አቀባበል፣ ሚዲያ — "
            "ብዙ አካባቢዎች በሰንጠረዥ ይጻፉ)"
        ),
    },
    "partnership_financial_commitment": {
        "en": (
            "Thank you for your generosity! "
            "Please describe your financial commitment. "
            "(e.g. '100 monthly', '500 one-time', 'tithe')"
        ),
        "am": (
            "ለልግስናዎ ምስጋና! "
            "የገንዘብ ቁርጠኝነትዎን ይግለጹ። "
            "(ለምሳሌ፦ 'ወርሃዊ 100', 'አንድ ጊዜ 500', 'ዐሥራት')"
        ),
    },
    "partnership_material_items": {
        "en": (
            "Bless you for your generosity! "
            "What items would you like to donate? "
            "(List them separated by commas, e.g. 'chairs, sound equipment, Bibles')"
        ),
        "am": (
            "ለልግስናዎ ይባረኩ! "
            "ምን እቃዎችን ሊለግሱ ይፈልጋሉ? "
            "(በሰንጠረዥ ይዘርዝሩ፣ ለምሳሌ፦ 'ወንበሮች፣ ድምፅ መሳሪያ፣ መጽሐፍ ቅዱሳት')"
        ),
    },
    "partnership_message": {
        "en": (
            "Is there anything else you'd like us to know? "
            "(Optional — type 'skip' to finish.)"
        ),
        "am": "ሌላ ልናውቀው የሚፈልጉት ነገር አለ? (አስፈላጊ አይደለም — ለማጠናቀቅ 'skip' ይጻፉ።)",
    },

    # -----------------------------------------------------------------------
    # Shared / generic validator error prompts
    # -----------------------------------------------------------------------

    "generic_invalid": {
        "en": "That doesn't look right. Please try again.",
        "am": "ትክክል አይመስልም። እባክዎ እንደገና ይሞክሩ።",
    },
}
