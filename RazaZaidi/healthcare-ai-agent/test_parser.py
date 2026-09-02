import sys
sys.path.insert(0, "d:\\HealthCare AI Modal")

from healthcare.report_parser import parse_medical_report
import os

# List all files in uploads
uploads_dir = "d:\\HealthCare AI Modal\\uploads\\1"
if os.path.exists(uploads_dir):
    print("Files in uploads/1:")
    for file in os.listdir(uploads_dir):
        file_path = os.path.join(uploads_dir, file)
        print(f"\nTesting: {file}")
        result = parse_medical_report(file_path)
        print(f"Success: {result['success']}")
        if result.get('error'):
            print(f"Error: {result['error']}")
        print(f"File type detected: {result['file_type']}")
        print(f"Extracted text length: {len(result['text'])}")
        print("Extracted text (preview):", repr(result['text'][:300]))
