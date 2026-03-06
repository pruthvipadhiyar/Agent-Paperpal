import docx

def check_docx(path):
    doc = docx.Document(path)
    print(f"Checking {path}...")
    
    in_references = False
    for p in doc.paragraphs:
        if "References" in p.text or "Works Cited" in p.text:
            in_references = True
            print(f"Found Reference Header: {p.text}")
            continue
            
        if in_references and p.text.strip():
            left = p.paragraph_format.left_indent
            first = p.paragraph_format.first_line_indent
            l_val = left.inches if left else 0
            f_val = first.inches if first else 0
            print(f"REF: {p.text[:30]}... | Left: {l_val:.2f} | First: {f_val:.2f}")

if __name__ == "__main__":
    check_docx("outputs/76f4f465-81c4-4b3d-913a-ececcfaf4684_formatted.docx")
