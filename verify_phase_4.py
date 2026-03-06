import os
import uuid
import json
from app import ingest_document, detect_structure, format_document, render_docx, validate_document

def final_success_check():
    job_id = str(uuid.uuid4())
    # This manuscript was created in a previous step and has multiple headings
    filepath = "real_manuscript.docx" 
    style = "IEEE"
    
    print(f"--- FINAL PHASE 4 SUCCESS CHECK ---")
    print(f"Target Style: {style}")
    print(f"Input File: {filepath}")
    
    # 1. Pipeline Execution
    ir = ingest_document(filepath, job_id)
    ir = detect_structure(ir)
    ir = format_document(ir, style)
    validation = validate_document(ir)
    ir['validation'] = validation
    output_path = render_docx(ir, job_id)
    
    # 2. Results Verification
    print(f"\n[1] COMPLIANCE SCORE: {validation['score']}/100")
    
    print("\n[2] CATEGORY SCORES:")
    for cat, score in validation['category_scores'].items():
        bar = "█" * (score // 10) + "░" * (10 - (score // 10))
        print(f" {cat:12}: [{bar}] {score}%")
        
    print(f"\n[3] CHANGE LOG ({len(ir['change_log'])} entries):")
    for i, change in enumerate(ir['change_log'][:5]):
        print(f" {i+1}. {change['type'].upper()}: {change['before']} -> {change['after']} (Rule: {change['rule']})")
        
    print(f"\n[4] DOWNLOADABLE FILE:")
    if os.path.exists(output_path):
        print(f" SUCCESS: {output_path} generated ({os.path.getsize(output_path)} bytes)")
    else:
        print(f" FAILURE: Output file not found at {output_path}")
        
    # 5. Requirement Check
    passed = True
    if not (50 <= validation['score'] <= 100): 
        print(" ! Score check failed")
        passed = False
    if len(validation['category_scores']) < 2: 
        print(" ! Category bars check failed")
        passed = False
    if len(ir['change_log']) < 3: 
        print(" ! Change log rows check failed")
        passed = False
        
    if passed:
        print("\n>>> ALL PHASE 4 SUCCESS CRITERIA MET <<<")
    else:
        print("\n>>> SUCCESS CRITERIA NOT FULLY MET <<<")

if __name__ == "__main__":
    final_success_check()
