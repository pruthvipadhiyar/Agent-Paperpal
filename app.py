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

# --- Pipeline Stubs ---
def ingest_document(filepath):
    # Dummy implementation for now
    return {'text': f'Content of {filepath}', 'paragraphs': [], 'format': os.path.splitext(filepath)[1][1:]}

def detect_structure(ir):
    return ir

def format_document(ir, style):
    # This will eventually call Claude API
    return ir

def validate_document(ir):
    return {'score': 0.85, 'issues': ['Placeholder issue 1', 'Placeholder issue 2']}

def render_docx(ir, job_id):
    # Create a dummy docx for testing the download functionality
    output_path = os.path.join(app.config['OUTPUT_FOLDER'], f"{job_id}.docx")
    doc = docx.Document()
    doc.add_heading('Formatted Document', 0)
    doc.add_paragraph('This is a placeholder for the formatted content.')
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
            # Call pipeline stubs
            ir = ingest_document(filepath)
            ir = detect_structure(ir)
            ir = format_document(ir, style)
            validation = validate_document(ir)
            render_docx(ir, job_id)
            
            # Update job as complete
            update_job(job_id, 'completed', score=validation['score'], changes=5)
            
        except Exception as e:
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
