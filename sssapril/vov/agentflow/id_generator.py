import time
import random
import string
from datetime import datetime


class IDGenerator:
    @staticmethod
    def generate_packet_id(sender_id: str, packet_type: str) -> str:
        timestamp = int(time.time() * 1000)
        random_str = ''.join(random.choices(string.ascii_lowercase + string.digits, k=6))
        return f"{sender_id}_{packet_type}_{timestamp}_{random_str}"
    
    @staticmethod
    def generate_sender_id(name: str) -> str:
        created_time = int(time.time() * 1000)
        random_str = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
        return f"{name}_{created_time}_{random_str}"
    
    @staticmethod
    def generate_chain_id() -> str:
        timestamp = int(time.time() * 1000)
        random_str = ''.join(random.choices(string.ascii_lowercase + string.digits, k=12))
        return f"chain_{timestamp}_{random_str}"
