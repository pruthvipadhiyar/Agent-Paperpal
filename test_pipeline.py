import os
import uuid
import json
from app import ingest_document, detect_structure

def test_pipeline():
    job_id = str(uuid.uuid4())
    filepath = "test_manuscript.docx"
    
    # Run pipeline
    ir = ingest_document(filepath, job_id)
    ir = detect_structure(ir)
    
    # Log findings
    print("-" * 30)
    print(f"Job ID: {job_id}")
    print(f"Detected Style: {ir['detected_style']}")
    print(f"Title: {ir['title']}")
    print(f"Sections Detected: {len(ir['sections'])}")
    print(f"Citations Found: {len(ir['citations_raw'])}")
    print(f"References Found: {len(ir['references_raw'])}")
    print("-" * 30)
    
    # Save for verification
    os.makedirs('uploads', exist_ok=True)
    ir_path = os.path.join('uploads', f"{job_id}_ir.json")
    with open(ir_path, 'w', encoding='utf-8') as f:
        json.dump(ir, f, indent=2)
    print(f"Saved IR to {ir_path}")

if __name__ == "__main__":
    test_pipeline()
