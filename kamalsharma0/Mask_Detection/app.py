from flask import Flask, render_template, request, jsonify
import cv2
import numpy as np
import tensorflow as tf
import base64
import os

app = Flask(__name__)

# --- LOAD MODELS ---
print("Loading models...")
# Mask Model
model = tf.keras.models.load_model('mask_detector.h5')

# Face Detector (Haar Cascade)
face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/process_frame', methods=['POST'])
def process_frame():
    try:
        # 1. JavaScript se Image Data lo
        data = request.json['image']
        header, encoded = data.split(",", 1)
        binary_data = base64.b64decode(encoded)
        
        # 2. Image ko OpenCV format mein convert karo
        nparr = np.frombuffer(binary_data, np.uint8)
        frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        # 3. Detection Logic
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = face_cascade.detectMultiScale(gray, 1.1, 5, minSize=(60, 60))

        results = []
        for (x, y, w, h) in faces:
            face_img = frame[y:y+h, x:x+w]
            try:
                # Resize & Preprocess
                face_img = cv2.resize(face_img, (224, 224))
                face_img = tf.keras.preprocessing.image.img_to_array(face_img)
                face_img = tf.keras.applications.mobilenet_v2.preprocess_input(face_img)
                face_img = np.expand_dims(face_img, axis=0)

                # Predict
                (mask, withoutMask) = model.predict(face_img, verbose=0)[0]
                label = "Mask" if mask > withoutMask else "No Mask"
                prob = float(max(mask, withoutMask) * 100)
                
                # Result list mein daalo
                results.append({
                    'x': int(x), 'y': int(y), 'w': int(w), 'h': int(h),
                    'label': label,
                    'prob': round(prob, 2)
                })
            except: pass
        
        # 4. Result wapis bhejo
        return jsonify(results)

    except Exception as e:
        print(f"Error: {e}")
        return jsonify([])

if __name__ == "__main__":
    # Hugging Face sirf 7860 par sunta hai
    app.run(host='0.0.0.0', port=7860)