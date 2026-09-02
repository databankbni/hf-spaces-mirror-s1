
import sys
import os

sys.path.insert(0, r"d:\HealthCare AI Modal")

try:
    from healthcare.report_parser import parse_medical_report, SUPPORTED_IMAGE_TYPES, SUPPORTED_PDF_TYPE
    print("Imported parse_medical_report successfully!")
except Exception as e:
    print(f"ERROR importing: {type(e)} - {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

uploads_dir = os.path.join(r"d:\HealthCare AI Modal", "uploads", "1")

if os.path.exists(uploads_dir):
    files = os.listdir(uploads_dir)
    print(f"\nFound {len(files)} files in {uploads_dir}")
    
    for filename in files:
        file_path = os.path.join(uploads_dir, filename)
        
        print(f"\n{'='*60}")
        print(f"Testing file: {filename}")
        print(f"Full path: {file_path}")
        print(f"Exists? {os.path.exists(file_path)}")
        print(f"Size: {os.path.getsize(file_path)} bytes")
        
        try:
            print("\nCalling parse_medical_report...")
            result = parse_medical_report(file_path)
            
            print(f"\nResult:")
            print(f"  Success: {result.get('success')}")
            print(f"  File type: {result.get('file_type')}")
            print(f"  Pages: {result.get('pages')}")
            print(f"  Error: {result.get('error')}")
            print(f"  Text length: {len(result.get('text', ''))}")
            if result.get('text'):
                print(f"  Text preview:\n{repr(result.get('text')[:500])}")
            
        except Exception as e:
            print(f"\nERROR parsing file: {type(e)} - {e}")
            import traceback
            traceback.print_exc()

