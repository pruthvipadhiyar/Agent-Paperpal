from flask import Flask, request, render_template, send_file, jsonify, redirect, url_for
from anthropic import Anthropic
import docx, fitz, os, uuid, json, sqlite3, re
from datetime import datetime
from pathlib import Path
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['OUTPUT_FOLDER'] = 'outputs'
app.config['MAX_CONTENT_LENGTH'] = 20 * 1024 * 1024  # 20MB
app.secret_key = 'super-secret-key-for-flashing-messages'

# Handle missing API key gracefully for development
anthropic_key = os.environ.get('ANTHROPIC_API_KEY')
ANTHROPIC_CLIENT = Anthropic(api_key=anthropic_key) if anthropic_key else None

ALLOWED_EXTENSIONS = {'.docx', '.pdf', '.txt'}

# --- Database Setup ---
DB_PATH = 'jobs.db'

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            filename TEXT,
            status TEXT,
            style TEXT,
            compliance_score REAL,
            total_changes INTEGER,
            error_message TEXT,
            created_at TEXT
        )
    ''')
    conn.commit()
    conn.close()

# --- Utility Functions ---
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def allowed_file(filename):
    return '.' in filename and \
           os.path.splitext(filename)[1].lower() in ALLOWED_EXTENSIONS

def save_job(job_id, filename, style):
    conn = get_db()
    conn.execute(
        'INSERT INTO jobs (id, filename, status, style, created_at) VALUES (?, ?, ?, ?, ?)',
        (job_id, filename, 'processing', style, datetime.now().isoformat())
    )
    conn.commit()
    conn.close()

def update_job(job_id, status, score=None, changes=None, error=None):
    conn = get_db()
    conn.execute(
        'UPDATE jobs SET status = ?, compliance_score = ?, total_changes = ?, error_message = ? WHERE id = ?',
        (status, score, changes, error, job_id)
    )
    conn.commit()
    conn.close()

def get_job(job_id):
    conn = get_db()
    job = conn.execute('SELECT * FROM jobs WHERE id = ?', (job_id,)).fetchone()
    conn.close()
    return dict(job) if job else None

# --- Document Processing Engine ---

# --- In-Memory Job Store (Demo Only) ---
JOBS_IR = {}

# --- Document Processing Engine ---

def ingest_document(filepath, job_id):
    """Router for different file types into a structured IR dict."""
    ext = os.path.splitext(filepath)[1].lower()
    
    ir = {
        'job_id': job_id,
        'source_format': ext[1:],
        'paragraphs': [],
        'tables': [],
        'raw_text': '',
        'word_count': 0,
        'title': None,
        'abstract': None,
        'sections': [],
        'citations_raw': [],
        'references_raw': [],
        'detected_style': None
    }

    if ext == '.docx':
        ir = ingest_docx(filepath, ir)
    elif ext == '.pdf':
        ir = ingest_pdf(filepath, ir)
    elif ext == '.txt':
        ir = ingest_txt(filepath, ir)
    else:
        raise ValueError(f"Unsupported file extension: {ext}")

    # Common metrics
    ir['raw_text'] = ' '.join([p['text'] for p in ir['paragraphs']])
    ir['word_count'] = len(ir['raw_text'].split())
    
    return ir

def ingest_docx(filepath, ir):
    """Extracts structured content from .docx files including formatting metadata."""
    doc = docx.Document(filepath)
    
    # 1. Extract Paragraphs
    for i, para in enumerate(doc.paragraphs):
        text = para.text.strip()
        if not text:
            continue
            
        bold = any(run.bold for run in para.runs)
        font_size = None
        if para.runs and para.runs[0].font.size:
            font_size = para.runs[0].font.size.pt
            
        ir['paragraphs'].append({
            'id': f'p_{i}',
            'text': text,
            'style': para.style.name,
            'is_bold': bold,
            'font_size': font_size,
            'type': 'unknown',
            'heading_level': 0
        })

    # 2. Extract Tables
    for table in doc.tables:
        rows = []
        for row in table.rows:
            rows.append([cell.text.strip() for cell in row.cells])
        ir['tables'].append({'caption': '', 'rows': rows})
        
    return ir

def ingest_pdf(filepath, ir):
    """Extracts text from PDF files using PyMuPDF (fitz) with reading order sorting."""
    doc = fitz.open(filepath)
    all_blocks = []
    
    for page_num, page in enumerate(doc):
        # Extract blocks: (x0, y0, x1, y1, text, block_no, block_type)
        blocks = page.get_text('blocks')
        for b in blocks:
            if b[6] == 0: # text block
                text = b[4].strip()
                if text:
                    all_blocks.append({
                        'page': page_num,
                        'y0': b[1],
                        'text': text
                    })
    
    # Sort blocks by page and then y-coordinate (reading order)
    all_blocks.sort(key=lambda x: (x['page'], x['y0']))
    
    for i, block in enumerate(all_blocks):
        text = block['text']
        
        # Estimate headings based on properties
        is_heading_candidate = len(text) < 100 and (text.isupper() or (text[-1].isalnum() and not text.endswith('.')))
        
        ir['paragraphs'].append({
            'id': f'p_{i}',
            'text': text,
            'style': 'Normal' if not is_heading_candidate else 'Heading Estimated',
            'is_bold': False, # fitz requires more logic for bold detection
            'font_size': None,
            'type': 'unknown',
            'heading_level': 0
        })
        
    return ir

def ingest_txt(filepath, ir):
    """Simple text ingestion splitting by double newline."""
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    paras = content.split('\n\n')
    for i, text in enumerate(paras):
        if text.strip():
            ir['paragraphs'].append({
                'id': f'p_{i}',
                'text': text.strip(),
                'style': 'Normal',
                'is_bold': False,
                'font_size': None,
                'type': 'unknown',
                'heading_level': 0
            })
    return ir

def detect_structure(ir):
    """
    Annotates each paragraph with its structural role using heuristics.
    """
    has_title = False
    in_references = False
    
    # Regex Patterns
    APA_PAT = r'\([A-Z][a-z]+(?:(?:\s+&\s+|,\s+)[A-Z][a-z]+)*,?\s+\d{4}(?:,\s+p\.?\s*\d+)?\)'
    IEEE_PAT = r'\[\d+(?:,\s*\d+)*\]'

    apa_count = 0
    num_count = 0

    for i, para in enumerate(ir['paragraphs']):
        text = para['text']
        text_lower = text.lower()
        font_size = para.get('font_size') or 0
        style = para.get('style', '')

        # 1. TITLE detection
        if not has_title:
            if (font_size > 14 or 'Title' in style) or (text.isupper() and len(text) < 150):
                ir['title'] = text
                para['type'] = 'title'
                has_title = True
                continue

        # 2. ABSTRACT detection
        if not ir['abstract']:
            words = text.split()
            if text_lower.startswith('abstract'):
                ir['abstract'] = text
                para['type'] = 'abstract'
                continue
            elif has_title and 100 <= len(words) <= 400 and not any(s['paragraph_id'] == para['id'] for s in ir['sections']):
                # Paragraph after title/before headings that looks like an abstract
                ir['abstract'] = text
                para['type'] = 'abstract'
                continue

        # 3. SECTION HEADINGS
        is_heading = False
        level = 0
        if 'Heading' in style:
            match = re.search(r'\d', style)
            level = int(match.group()) if match else 1
            is_heading = True
        elif (font_size >= 13 and len(text) < 100 and not text.endswith('.')) or (text.isupper() and len(text) < 80):
            level = 1
            is_heading = True

        if is_heading:
            para['type'] = 'heading'
            para['heading_level'] = level
            ir['sections'].append({
                'title': text,
                'level': level,
                'paragraph_id': para['id']
            })
            
            # 4. REFERENCE LIST detection
            if any(kw in text_lower for kw in ['references', 'bibliography', 'works cited']):
                in_references = True
            continue

        # 5. REFERENCE paragraphs
        if in_references:
            para['type'] = 'reference'
            ir['references_raw'].append(text)
            continue

        # 6. CITATION detection (Body scans)
        apa_matches = re.findall(APA_PAT, text)
        ieee_matches = re.findall(IEEE_PAT, text)
        
        ir['citations_raw'].extend(apa_matches)
        ir['citations_raw'].extend(ieee_matches)
        
        apa_count += len(apa_matches)
        num_count += len(ieee_matches)

        # Default to Body
        para['type'] = 'body'

    # DETECTED STYLE
    if apa_count > num_count:
        ir['detected_style'] = 'APA'
    elif num_count > 0:
        ir['detected_style'] = 'Vancouver'
    else:
        ir['detected_style'] = 'Unknown'

    return ir


def format_document(ir, style):
    """
    Orchestrates the AI-driven transformation sections of the manuscript.
    Uses section-by-section processing to handle long documents.
    """
    if not ANTHROPIC_CLIENT:
        print("Warning: Anthropic client not initialized. Skipping AI formatting.")
        ir['formatted_by'] = f"{style} (SIMULATED)"
        return ir

    formatted_paras = []
    
    # Process paragraphs in small batches (sections)
    batch_size = 5
    for i in range(0, len(ir['paragraphs']), batch_size):
        batch = ir['paragraphs'][i:i + batch_size]
        batch_text = "\n\n".join([f"[{p['type'].upper()}] {p['text']}" for p in batch])
        
        system_prompt = f"""
        You are a professional academic editor and expert in {style} formatting.
        Your task is to reformat the provided manuscript snippet to perfectly match {style} guidelines.
        
        RULES:
        1. Maintain all factual content, data, and author intended meaning.
        2. Adjust tone to be formal, academic, and objective.
        3. Correct in-text citations if they deviate from {style}.
        4. Fix grammar, spelling, and sentence structure for clarity.
        5. Return ONLY the reformatted text. Do not include meta-comments or 'Here is your text'.
        """
        
        try:
            response = ANTHROPIC_CLIENT.messages.create(
                model="claude-3-haiku-20240307",
                max_tokens=2000,
                system=system_prompt,
                messages=[
                    {"role": "user", "content": f"Reformat this academic snippet:\n\n{batch_text}"}
                ]
            )
            
            reformatted_text = response.content[0].text
            
            # Update the first paragraph with the reformatted content
            for j, para in enumerate(batch):
                if j == 0:
                    para['text'] = reformatted_text
                else:
                    para['text'] = "" 
                
            formatted_paras.extend(batch)
            
        except Exception as e:
            print(f"AI Formatting Error for batch {i}: {e}")
            formatted_paras.extend(batch)

    ir['paragraphs'] = [p for p in formatted_paras if p['text'].strip()]
    ir['formatted_by'] = style
    return ir


def validate_document(ir):
    """Calculates a simulated compliance score for the intermediate representation."""
    return {'score': 0.92, 'issues': ['Manual review recommended for reference links']}

def render_docx(ir, job_id):
    """Renders the IR back into a high-quality .docx file."""
    output_filename = f"{job_id}.docx"
    output_path = os.path.join(app.config['OUTPUT_FOLDER'], output_filename)
    
    doc = docx.Document()
    
    # Add a title if identified
    if ir.get('title'):
        doc.add_heading(ir['title'], 0)
    else:
        doc.add_heading('Agent Paperpal - Formatted Manuscript', 0)

    for para in ir['paragraphs']:
        if para['type'] == 'title':
            continue 
            
        if para['type'] == 'heading':
            doc.add_heading(para['text'], level=para.get('heading_level', 1))
        else:
            p = doc.add_paragraph(para['text'])
            # Additional style-specific logic can be added here
            
    doc.save(output_path)
    return output_path


# --- Flask Routes ---
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload():
    if 'file' not in request.files:
        return redirect(url_for('index'))
    
    file = request.files['file']
    style = request.form.get('style', 'APA 7th Edition')
    
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        job_id = str(uuid.uuid4())
        
        # Ensure directories exist
        Path(app.config['UPLOAD_FOLDER']).mkdir(exist_ok=True)
        Path(app.config['OUTPUT_FOLDER']).mkdir(exist_ok=True)
        
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], f"{job_id}_{filename}")
        file.save(filepath)
        
        # Initialize job in DB
        save_job(job_id, filename, style)
        
        try:
            # 2. ingest_document and 3. detect_structure
            ir = ingest_document(filepath, job_id)
            ir = detect_structure(ir)
            
            # 4. Save ir as JSON for debugging
            ir_path = os.path.join(app.config['UPLOAD_FOLDER'], f"{job_id}_ir.json")
            with open(ir_path, 'w', encoding='utf-8') as f:
                json.dump(ir, f, indent=2)
            
            # 5. Store in-memory
            JOBS_IR[job_id] = ir
            
            print(f"DEBUG: Job {job_id} - Detected Style: {ir['detected_style']}")

            # 6. Continue to format_document
            ir = format_document(ir, style)
            validation = validate_document(ir)
            render_docx(ir, job_id)
            
            # Update job as complete
            update_job(job_id, 'completed', score=validation['score'], changes=len(ir['citations_raw']))
            
        except Exception as e:
            print(f"Pipeline Error: {e}")
            update_job(job_id, 'failed', error=str(e))
            
        return redirect(url_for('result', job_id=job_id))
    
    return redirect(url_for('index'))

@app.route('/result/<job_id>')
def result(job_id):
    job = get_job(job_id)
    if not job:
        return "Job not found", 404
    return render_template('result.html', job=job)

@app.route('/download/<job_id>')
def download(job_id):
    job = get_job(job_id)
    if not job:
        return "Job not found", 404
        
    output_filename = f"{job_id}.docx"
    output_path = os.path.abspath(os.path.join(app.config['OUTPUT_FOLDER'], output_filename))
    
    if not os.path.exists(output_path):
        return "File not found", 404
        
    return send_file(output_path, as_attachment=True, download_name=f"formatted_{job['filename']}.docx")

@app.route('/health')
def health():
    return jsonify({'status': 'ok', 'version': '1.0'})

# --- Main Block ---
if __name__ == '__main__':
    # Setup directories
    Path(app.config['UPLOAD_FOLDER']).mkdir(exist_ok=True)
    Path(app.config['OUTPUT_FOLDER']).mkdir(exist_ok=True)
    
    # Initialize database
    init_db()
    
    # Run application
    app.run(debug=True, port=5000)
