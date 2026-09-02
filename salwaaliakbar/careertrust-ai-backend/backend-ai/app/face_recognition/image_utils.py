import insightface
import numpy as np
import cv2

# Initialize InsightFace app with detection and recognition modules
app = insightface.app.FaceAnalysis(providers=['CPUExecutionProvider'])
app.prepare(ctx_id=0, det_size=(640, 640))

def read_and_detect_face_and_get_embedding(image_bytes):
    npimg = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(npimg, cv2.IMREAD_COLOR)
    if img is None:
        return None, None

    faces = app.get(img)

    # Ensure exactly one face detected
    if len(faces) != 1:
        return None, None

    face = faces[0]
    # Normalized embedding vector
    embedding = face.embedding / np.linalg.norm(face.embedding)

    # Crop detected face (optional, if you want to process or save face image)
    x1, y1, x2, y2 = map(int, face.bbox.flatten())
    cropped_face = img[y1:y2, x1:x2]

    return cropped_face, embedding
