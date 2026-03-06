import os
import uuid
import json
from app import ingest_document, detect_structure, format_document, render_docx, validate_document

def test_phase_3():
    job_id = str(uuid.uuid4())
    filepath = "real_manuscript.docx"
    style = "IEEE"
    
    print(f"Starting Phase 3 Test for Job: {job_id}")
    
    # 1. Ingest
    ir = ingest_document(filepath, job_id)
    
    # 2. Detect Structure
    ir = detect_structure(ir)
    
    # 3. Format
    ir = format_document(ir, style)
    
    # 4. Validate (Phase 4)
    validation = validate_document(ir)
    ir['validation'] = validation
    
    # 5. Render
    output_path = render_docx(ir, job_id)
    
    # Log findings
    print("-" * 30)
    print(f"Compliance Score: {validation['score']}/100")
    print(f"Total Issues: {validation['total_issues']}")
    for issue in validation['issues']:
        print(f" - [{issue['severity'].upper()}] {issue['message']}")
    
    print("-" * 30)
    print(f"Style Applied: {ir.get('style_applied')}")
    print(f"Change Log Entries: {len(ir.get('change_log', []))}")
    for entry in ir.get('change_log', []):
        print(f"[{entry['type'].upper()}] {entry['before']} -> {entry['after']}")
    
    print(f"Output File: {output_path}")
    
    # Save IR for verification
    ir_path = f"uploads/{job_id}_ir_p3.json"
    with open(ir_path, "w") as f:
        json.dump(ir, f, indent=2)
    print(f"IR saved to {ir_path}")
    
    print("-" * 30)
    
    if os.path.exists(output_path):
        print("SUCCESS: Formatted document generated.")
    else:
        print("FAILURE: Formatted document not found.")

if __name__ == "__main__":
    test_phase_3()
