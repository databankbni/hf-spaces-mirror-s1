import os
from cryptography.fernet import Fernet
from dotenv import load_dotenv

# পরিবেশের ভেরিয়েবল লোড করা
load_dotenv()

# .env ফাইল থেকে মাস্টার কি সংগ্রহ করা, না থাকলে অটো জেনারেট হবে
MASTER_KEY = os.getenv("MASTER_KEY")

if not MASTER_KEY:
    # ডেভেলপমেন্টের সুবিধার জন্য স্বয়ংক্রিয়ভাবে একটি কি তৈরি করা (প্রোডাকশনে .env-এ স্থায়ী কি ব্যবহার করা ভালো)
    MASTER_KEY = Fernet.generate_key().decode()

class EncryptionManager:
    def __init__(self, key: str = MASTER_KEY):
        """এনক্রিপশন ম্যানেজার ইনিশিয়ালাইজ করা"""
        self.cipher = Fernet(key.encode() if isinstance(key, str) else key)

    def encrypt(self, data: str) -> str:
        """যেকোনো টেক্সট বা স্ট্রিং এনক্রিপ্ট করার ফাংশন"""
        if not isinstance(data, str):
            raise TypeError("Data to encrypt must be a string.")
        encrypted_bytes = self.cipher.encrypt(data.encode('utf-8'))
        return encrypted_bytes.decode('utf-8')

    def decrypt(self, token: str) -> str:
        """এনক্রিপ্ট করা টোকেন বা ডেটা ডিক্রিপ্ট করার ফাংশন"""
        if not isinstance(token, str):
            raise TypeError("Token to decrypt must be a string.")
        try:
            decrypted_bytes = self.cipher.decrypt(token.encode('utf-8'))
            return decrypted_bytes.decode('utf-8')
        except Exception as e:
            raise ValueError(f"Decryption failed: Token is invalid or corrupted. Error: {e}")

# পুরো প্রজেক্টে সহজে ব্যবহারের জন্য একটি গ্লোবাল ইনস্ট্যান্স
encryption_manager = EncryptionManager()