 import re

class ContentModerator:
    def __init__(self):
        """কন্টেন্ট মডারেশন সিস্টেম ইনিশিয়ালাইজেশন"""
        # প্রোডাকশনে এখানে আরও উন্নত ফিল্টার বা ব্ল্যাকলিস্ট যোগ করা যেতে পারে
        self.forbidden_keywords = [
            "malware_test_keyword", 
            "exploit_payload_sample"
        ]

    def check_content(self, text: str) -> dict:
        """ইনপুট টেক্সট বা প্রম্পট মারেডরেট বা স্ক্যান করার ফাংশন"""
        if not isinstance(text, str):
            return {"is_safe": True, "reason": "Invalid text type"}

        text_lower = text.lower()
        
        # নিষিদ্ধ শব্দ চেক করা
        for word in self.forbidden_keywords:
            if word in text_lower:
                return {
                    "is_safe": False,
                    "reason": f"Content blocked due to policy violation: restricted keyword detected."
                }

        # বেসিক সিকিউরিটি প্যাটার্ন চেক (যেমন স্ক্রিপ্ট ইনজেকশন বা ক্ষতিকর কমান্ড)
        dangerous_patterns = [r"<script>.*?</script>", r"rm\s+-rf\s+/"]
        for pattern in dangerous_patterns:
            if re.search(pattern, text_lower):
                return {
                    "is_safe": False,
                    "reason": "Content blocked due to potential security threat or unsafe script."
                }

        return {"is_safe": True, "reason": "Content is clean and safe."}

# গ্লোবাল ইনস্ট্যান্স
content_moderator = ContentModerator()
