
import sys
import os
sys.path.insert(0, r"d:\HealthCare AI Modal")

from healthcare.report_parser import extract_text_from_image, TESSERACT_PATH

print("Testing OCR setup...")
print(f"Tesseract path configured: {TESSERACT_PATH}")
print(f"Tesseract path exists: {os.path.exists(TESSERACT_PATH)}")

# Check if pytesseract is available
try:
    import pytesseract
    print("\n✅ pytesseract is installed")
    
    # Try to get Tesseract version
    try:
        version = pytesseract.get_tesseract_version()
        print(f"✅ Tesseract version: {version}")
    except Exception as e:
        print(f"⚠️ Could not get Tesseract version: {type(e)} - {e}")
        print("   Please make sure Tesseract is installed and the path is correct!")
        
except ImportError as e:
    print(f"\n❌ pytesseract is NOT installed: {e}")

# Check if Pillow is available
try:
    from PIL import Image
    print("\n✅ Pillow is installed")
except ImportError as e:
    print(f"\n❌ Pillow is NOT installed: {e}")

# Test on an uploaded image
uploads_dir = os.path.join(r"d:\HealthCare AI Modal", "uploads", "1")
if os.path.exists(uploads_dir):
    files = os.listdir(uploads_dir)
    image_files = [f for f in files if os.path.splitext(f)[1].lower() in ['.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.tif']]
    
    if image_files:
        print(f"\nTesting OCR on {len(image_files)} image(s)...")
        for img_file in image_files[:1]:
            img_path = os.path.join(uploads_dir, img_file)
            print(f"\nProcessing: {img_file}")
            print(f"File exists: {os.path.exists(img_path)}")
            
            try:
                text = extract_text_from_image(img_path)
                print(f"Extract result:\n{text}")
            except Exception as e:
                print(f"ERROR extracting text: {type(e)} - {e}")
                import traceback
                traceback.print_exc()
    else:
        print("\nNo image files found in uploads/1 directory")
else:
    print(f"\nUploads directory not found: {uploads_dir}")
