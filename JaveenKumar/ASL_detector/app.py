import os
import base64
import cv2
import numpy as np
import mediapipe as mp
import tensorflow as tf
from tensorflow import keras
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.concurrency import run_in_threadpool
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision as mp_vision
from threading import Lock
from pydantic import BaseModel

IMG_SIZE = 96
MODEL_PATH = "asl_model1.keras"
TASK_PATH = "hand_landmarker.task"
CLASS_NAMES_PATH = "class_names_model1.txt"
CONFIDENCE_THRESHOLD = 0.30
MAX_IMAGE_WIDTH = 960
TRAINED_HAND = "Right"  

app = FastAPI(
    title="ASL Hybrid API - Optimized Pipeline",
    description="ASL Sign Recognition API For FYP",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

print("Loading model...")
if not os.path.exists(MODEL_PATH):
    raise FileNotFoundError(f"Model file missing: {MODEL_PATH}")

model = keras.models.load_model(MODEL_PATH)

if os.path.exists(CLASS_NAMES_PATH):
    with open(CLASS_NAMES_PATH, "r", encoding="utf-8") as f:
        class_names = [line.strip() for line in f.readlines() if line.strip()]
else:
    class_names = [chr(i) for i in range(ord("A"), ord("Z") + 1)] + ["del", "nothing", "space"]

model.predict(
    [
        np.zeros((1, IMG_SIZE, IMG_SIZE, 3), dtype=np.float32),
        np.zeros((1, 42), dtype=np.float32)
    ],
    verbose=0
)
print(f"Model loaded successfully with {len(class_names)} classes.")

if not os.path.exists(TASK_PATH):
    raise FileNotFoundError(f"MediaPipe task file missing: {TASK_PATH}")

base_options = mp_python.BaseOptions(model_asset_path=TASK_PATH)
landmarker_options = mp_vision.HandLandmarkerOptions(
    base_options=base_options,
    num_hands=1
)
detector = mp_vision.HandLandmarker.create_from_options(landmarker_options)

model_lock = Lock()
detector_lock = Lock()

def extract_landmarks(hand_landmarks):
    """
    Normalizes coordinates relative to the wrist (landmark 0) and hand scale.
    Preserves finger proportions for C vs O and relative joint positions.
    """
    wrist = hand_landmarks[0]
    
    x_coords = [lm.x for lm in hand_landmarks]
    y_coords = [lm.y for lm in hand_landmarks]
    
    hand_scale = max(max(x_coords) - min(x_coords), max(y_coords) - min(y_coords))
    if hand_scale == 0:
        hand_scale = 1.0

    normalized = []
    for lm in hand_landmarks:
        norm_x = (lm.x - wrist.x) / hand_scale
        norm_y = (lm.y - wrist.y) / hand_scale
        normalized.extend([norm_x, norm_y])

    return np.array(normalized, dtype=np.float32)

def get_square_crop(frame_rgb, hand_lms, w, h):
    """
    Creates an aspect-ratio accurate square crop with 40% margin.
    Prevents distorting horizontal/vertical signs like H, P, X, and R.
    """
    x_coords = [int(lm.x * w) for lm in hand_lms]
    y_coords = [int(lm.y * h) for lm in hand_lms]

    x_min, x_max = min(x_coords), max(x_coords)
    y_min, y_max = min(y_coords), max(y_coords)

    box_w = x_max - x_min
    box_h = y_max - y_min
    max_dim = max(box_w, box_h)

    center_x = (x_min + x_max) // 2
    center_y = (y_min + y_max) // 2

    pad = int(max_dim * 0.40)
    half_size = (max_dim // 2) + pad

    x1 = max(0, center_x - half_size)
    y1 = max(0, center_y - half_size)
    x2 = min(w, center_x + half_size)
    y2 = min(h, center_y + half_size)

    crop = frame_rgb[y1:y2, x1:x2]

    if crop is None or crop.size == 0:
        crop = cv2.resize(frame_rgb, (IMG_SIZE, IMG_SIZE), interpolation=cv2.INTER_AREA)
    else:
        crop = cv2.resize(crop, (IMG_SIZE, IMG_SIZE), interpolation=cv2.INTER_AREA)

    return crop.astype(np.float32) / 255.0

def resize_for_processing(frame: np.ndarray, target_width: int = MAX_IMAGE_WIDTH) -> np.ndarray:
    h, w = frame.shape[:2]
    if w <= target_width:
        return frame
    scale = target_width / w
    return cv2.resize(frame, (target_width, int(h * scale)), interpolation=cv2.INTER_AREA)

def apply_rotation(frame: np.ndarray, rotation: int) -> np.ndarray:
    rotation = int(rotation) % 360
    if rotation == 90:
        return cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
    elif rotation == 180:
        return cv2.rotate(frame, cv2.ROTATE_180)
    elif rotation == 270:
        return cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
    return frame

def run_detection_and_predict(frame: np.ndarray, rotation: int = 0):
    frame = apply_rotation(frame, rotation)
    frame = resize_for_processing(frame)

    if frame is None or frame.size == 0:
        return {"success": False, "prediction": "Invalid Image", "confidence": 0.0, "hand_detected": False}

    h, w, _ = frame.shape
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)

    with detector_lock:
        result = detector.detect(mp_image)

    if not result.hand_landmarks:
        return {
            "success": True,
            "prediction": "No Hand",
            "confidence": 0.0,
            "hand_detected": False,
            "top5": []
        }

    detected_hand = result.handedness[0][0].category_name 

    if detected_hand != TRAINED_HAND:
        rgb = cv2.flip(rgb, 1)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        with detector_lock:
            result = detector.detect(mp_image)

        if not result.hand_landmarks:
            return {
                "success": True,
                "prediction": "No Hand",
                "confidence": 0.0,
                "hand_detected": False,
                "top5": []
            }

    hand = result.hand_landmarks[0]
    lm_input = extract_landmarks(hand)
    img_input = get_square_crop(rgb, hand, w, h)

    image_batch = np.expand_dims(img_input, axis=0)
    landmark_batch = np.expand_dims(lm_input, axis=0)

    with model_lock:
        prediction = model.predict([image_batch, landmark_batch], verbose=0)[0]

    idx = int(np.argmax(prediction))
    confidence = float(prediction[idx])

    top5_idx = np.argsort(prediction)[-5:][::-1]
    top5 = [{"label": class_names[int(i)], "score": round(float(prediction[i]), 4)} for i in top5_idx]

    if confidence < CONFIDENCE_THRESHOLD:
        return {
            "success": True,
            "prediction": "Uncertain",
            "confidence": round(confidence, 4),
            "hand_detected": True,
            "top5": top5
        }

    return {
        "success": True,
        "prediction": class_names[idx],
        "confidence": round(confidence, 4),
        "confidence_percent": round(confidence * 100, 2),
        "hand_detected": True,
        "top5": top5
    }

class Base64PredictRequest(BaseModel):
    image_base64: str
    rotation: int = 0

@app.get("/")
def home():
    return {"status": "ASL Hybrid API Running", "model": MODEL_PATH, "classes": len(class_names)}

@app.post("/predict")
async def predict(file: UploadFile = File(...), rotation: int = 0):
    try:
        image_bytes = await file.read()
        np_arr = np.frombuffer(image_bytes, np.uint8)
        frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)

        if frame is None:
            raise HTTPException(status_code=400, detail="Invalid image file")

        return await run_in_threadpool(run_detection_and_predict, frame, rotation)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/predict_base64")
async def predict_base64(payload: Base64PredictRequest):
    try:
        image_string = payload.image_base64
        if "," in image_string:
            image_string = image_string.split(",", 1)[1]

        image_bytes = base64.b64decode(image_string)
        np_arr = np.frombuffer(image_bytes, np.uint8)
        frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)

        if frame is None:
            raise HTTPException(status_code=400, detail="Invalid base64 payload")

        return await run_in_threadpool(run_detection_and_predict, frame, payload.rotation)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Processing error: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=False)