import os
from dotenv import load_dotenv
load_dotenv()

DB_URL = os.getenv("DB_URL", "sqlite:///fashion.db")
DATA_ROOT = os.getenv("DATA_ROOT", "./data")
IMAGES_ROOT = os.getenv("IMAGES_ROOT", "./data/images")

CLIP_MODEL = os.getenv("CLIP_MODEL", "ViT-B-32")
CLIP_PRETRAIN = os.getenv("CLIP_PRETRAIN", "openai")
DEVICE = os.getenv("DEVICE", "cpu")

COLOR_PALETTE = {
    "black": (0,0,0), "white": (255,255,255), "gray": (128,128,128),
    "beige": (220,200,170), "brown": (120,72,48), "navy": (10,20,60),
    "blue": (30,100,200), "green": (40,150,90), "yellow": (240,220,70),
    "orange": (240,150,60), "red": (200,40,50), "pink": (240,150,170), "purple": (130,60,170)
}
