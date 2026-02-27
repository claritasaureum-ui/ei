#!/usr/bin/env python3
"""
JBsn Backend Server
Financial file upload and management system
Supports: XLSX, CSV, OFX, PDF files
"""

import os
import json
import shutil
import sqlite3
import hashlib
import mimetypes
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import cgi

# Configuration
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UPLOAD_DIR = os.path.join(BASE_DIR, 'uploads')
DATABASE_PATH = os.path.join(BASE_DIR, 'data', 'jbsn.db')
FRONTEND_DIR = BASE_DIR

ALLOWED_EXTENSIONS = {
    '.xlsx': 'spreadsheet',
    '.xls': 'spreadsheet',
    '.csv': 'spreadsheet',
    '.ofx': 'ofx',
    '.pdf': 'pdf'
}

MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB

def init_database():
    """Initialize SQLite database for file metadata"""
    os.makedirs(os.path.dirname(DATABASE_PATH), exist_ok=True)
    
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            original_name TEXT NOT NULL,
            file_type TEXT NOT NULL,
            file_size INTEGER NOT NULL,
            file_hash TEXT NOT NULL,
            upload_date TEXT NOT NULL,
            status TEXT DEFAULT 'uploaded',
            metadata TEXT,
            notes TEXT
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS file_tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_id INTEGER NOT NULL,
            tag TEXT NOT NULL,
            FOREIGN KEY (file_id) REFERENCES files (id)
        )
    ''')
    
    conn.commit()
    conn.close()

def get_file_hash(filepath):
    """Calculate MD5 hash of file"""
    hash_md5 = hashlib.md5()
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(4096), b''):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()

def get_file_type(filename):
    """Determine file type from extension"""
    ext = os.path.splitext(filename)[1].lower()
    return ALLOWED_EXTENSIONS.get(ext, 'unknown')

def save_file(file_item, upload_dir):
    """Save uploaded file and return metadata"""
    filename = file_item.filename
    file_type = get_file_type(filename)
    
    if file_type == 'unknown':
        return None, "File type not allowed"
    
    # Generate unique filename
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    safe_name = ''.join(c if c.isalnum() or c in '._-' else '_' for c in filename)
    unique_filename = f"{timestamp}_{safe_name}"
    
    filepath = os.path.join(upload_dir, unique_filename)
    
    # Save file
    with open(filepath, 'wb') as f:
        shutil.copyfileobj(file_item.file, f)
    
    # Get file info
    file_size = os.path.getsize(filepath)
    file_hash = get_file_hash(filepath)
    
    return {
        'filename': unique_filename,
        'original_name': filename,
        'file_type': file_type,
        'file_size': file_size,
        'file_hash': file_hash,
        'upload_date': datetime.now().isoformat()
    }, None

def add_file_to_db(file_info, notes=None):
    """Add file metadata to database"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT INTO files (filename, original_name, file_type, file_size, file_hash, upload_date, status, notes)
        VALUES (?, ?, ?, ?, ?, ?, 'uploaded', ?)
    ''', (
        file_info['filename'],
        file_info['original_name'],
        file_info['file_type'],
        file_info['file_size'],
        file_info['file_hash'],
        file_info['upload_date'],
        notes
    ))
    
    file_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    return file_id

def get_all_files():
    """Get all files from database"""
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT id, filename, original_name, file_type, file_size, 
               file_hash, upload_date, status, notes
        FROM files
        ORDER BY upload_date DESC
    ''')
    
    files = [dict(row) for row in cursor.fetchall()]
    conn.close()
    
    return files

def get_file_by_id(file_id):
    """Get file by ID"""
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT id, filename, original_name, file_type, file_size, 
               file_hash, upload_date, status, notes
        FROM files WHERE id = ?
    ''', (file_id,))
    
    row = cursor.fetchone()
    conn.close()
    
    return dict(row) if row else None

def delete_file(file_id):
    """Delete file from database and filesystem"""
    file_info = get_file_by_id(file_id)
    if not file_info:
        return False, "File not found"
    
    # Delete from filesystem
    filepath = os.path.join(UPLOAD_DIR, file_info['filename'])
    if os.path.exists(filepath):
        os.remove(filepath)
    
    # Delete from database
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute('DELETE FROM files WHERE id = ?', (file_id,))
    cursor.execute('DELETE FROM file_tags WHERE file_id = ?', (file_id,))
    conn.commit()
    conn.close()
    
    return True, None

def get_stats():
    """Get upload statistics"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    cursor.execute('SELECT COUNT(*) FROM files')
    total_files = cursor.fetchone()[0]
    
    cursor.execute('SELECT COALESCE(SUM(file_size), 0) FROM files')
    total_size = cursor.fetchone()[0]
    
    cursor.execute('''
        SELECT file_type, COUNT(*) as count 
        FROM files 
        GROUP BY file_type
    ''')
    by_type = {row[0]: row[1] for row in cursor.fetchall()}
    
    conn.close()
    
    return {
        'total_files': total_files,
        'total_size': total_size,
        'by_type': by_type
    }


class JBsnRequestHandler(BaseHTTPRequestHandler):
    """Custom request handler for JBsn API"""
    
    def log_message(self, format, *args):
        """Override to customize logging"""
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {args[0]}")
    
    def send_json(self, data, status=200):
        """Send JSON response"""
        response = json.dumps(data).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', len(response))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
        self.wfile.write(response)
    
    def send_file_response(self, filepath, filename):
        """Send file download response"""
        if not os.path.exists(filepath):
            self.send_error(404, 'File not found')
            return
        
        mime_type, _ = mimetypes.guess_type(filepath)
        if not mime_type:
            mime_type = 'application/octet-stream'
        
        file_size = os.path.getsize(filepath)
        
        self.send_response(200)
        self.send_header('Content-Type', mime_type)
        self.send_header('Content-Length', file_size)
        self.send_header('Content-Disposition', f'attachment; filename="{filename}"')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        
        with open(filepath, 'rb') as f:
            shutil.copyfileobj(f, self.wfile)
    
    def do_OPTIONS(self):
        """Handle CORS preflight requests"""
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
    
    def do_GET(self):
        """Handle GET requests"""
        parsed_path = urlparse(self.path)
        path = parsed_path.path
        query = parse_qs(parsed_path.query)
        
        # API Routes
        if path == '/api/files':
            files = get_all_files()
            self.send_json({'success': True, 'files': files})
            return
        
        if path == '/api/stats':
            stats = get_stats()
            self.send_json({'success': True, 'stats': stats})
            return
        
        if path.startswith('/api/download/'):
            try:
                file_id = int(path.split('/')[-1])
                file_info = get_file_by_id(file_id)
                if file_info:
                    filepath = os.path.join(UPLOAD_DIR, file_info['filename'])
                    self.send_file_response(filepath, file_info['original_name'])
                else:
                    self.send_json({'success': False, 'error': 'File not found'}, 404)
            except ValueError:
                self.send_json({'success': False, 'error': 'Invalid file ID'}, 400)
            return
        
        if path.startswith('/api/delete/'):
            try:
                file_id = int(path.split('/')[-1])
                success, error = delete_file(file_id)
                if success:
                    self.send_json({'success': True, 'message': 'File deleted'})
                else:
                    self.send_json({'success': False, 'error': error}, 404)
            except ValueError:
                self.send_json({'success': False, 'error': 'Invalid file ID'}, 400)
            return
        
        # Serve static files
        if path == '/' or path == '/index.html':
            filepath = os.path.join(FRONTEND_DIR, 'index.html')
        else:
            filepath = os.path.join(FRONTEND_DIR, path.lstrip('/'))
        
        if os.path.exists(filepath) and os.path.isfile(filepath):
            self.send_file_response(filepath, os.path.basename(filepath))
        else:
            self.send_error(404, 'File not found')
    
    def do_POST(self):
        """Handle POST requests"""
        parsed_path = urlparse(self.path)
        path = parsed_path.path
        
        if path == '/api/upload':
            content_type = self.headers.get('Content-Type', '')
            
            if not content_type.startswith('multipart/form-data'):
                self.send_json({'success': False, 'error': 'Expected multipart/form-data'}, 400)
                return
            
            try:
                form = cgi.FieldStorage(
                    fp=self.rfile,
                    headers=self.headers,
                    environ={
                        'REQUEST_METHOD': 'POST',
                        'CONTENT_TYPE': content_type
                    }
                )
                
                uploaded_files = []
                errors = []
                
                # Handle single or multiple files
                file_items = form['files'] if 'files' in form else []
                if not isinstance(file_items, list):
                    file_items = [file_items]
                
                notes = form.getvalue('notes', '')
                
                for item in file_items:
                    if item.filename:
                        file_info, error = save_file(item, UPLOAD_DIR)
                        
                        if error:
                            errors.append({'filename': item.filename, 'error': error})
                        else:
                            file_id = add_file_to_db(file_info, notes)
                            file_info['id'] = file_id
                            uploaded_files.append(file_info)
                
                response = {
                    'success': len(uploaded_files) > 0,
                    'uploaded': uploaded_files,
                    'errors': errors,
                    'message': f'Successfully uploaded {len(uploaded_files)} file(s)'
                }
                
                status = 200 if uploaded_files else 400
                self.send_json(response, status)
                
            except Exception as e:
                self.send_json({'success': False, 'error': str(e)}, 500)
        else:
            self.send_json({'success': False, 'error': 'Unknown endpoint'}, 404)


def main():
    """Start the JBsn server"""
    # Create necessary directories
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    os.makedirs(os.path.join(BASE_DIR, 'data'), exist_ok=True)
    
    # Initialize database
    init_database()
    
    # Start server
    server_address = ('', 8080)
    httpd = HTTPServer(server_address, JBsnRequestHandler)
    
    print(f"""
╔══════════════════════════════════════════════════════════╗
║  JBsn Server - Getting the Job Done                      ║
╠══════════════════════════════════════════════════════════╣
║  Server running at: http://localhost:8080                ║
║  Upload endpoint:   POST /api/upload                     ║
║  Files endpoint:    GET  /api/files                      ║
║  Stats endpoint:    GET  /api/stats                      ║
║  Upload directory:  {UPLOAD_DIR:<36} ║
╚══════════════════════════════════════════════════════════╝
    """)
    
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down JBsn server...")
        httpd.shutdown()


if __name__ == '__main__':
    main()
