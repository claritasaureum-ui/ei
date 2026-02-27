/**
 * JBsn Backend Server
 * Financial file upload and management system
 * Supports: XLSX, CSV, OFX, PDF files
 */

const express = require('express');
const multer = require('multer');
const path = require('path');
const fs = require('fs');
const crypto = require('crypto');
const cors = require('cors');
const mime = require('mime-types');

const app = express();
const PORT = 8080;

// Configuration
const UPLOAD_DIR = path.join(__dirname, 'uploads');
const DATA_DIR = path.join(__dirname, 'data');
const DB_PATH = path.join(DATA_DIR, 'jbsn.db');

// Allowed file extensions
const ALLOWED_EXTENSIONS = {
    '.xlsx': 'spreadsheet',
    '.xls': 'spreadsheet',
    '.csv': 'spreadsheet',
    '.ofx': 'ofx',
    '.pdf': 'pdf'
};

const MAX_FILE_SIZE = 50 * 1024 * 1024; // 50MB

// Ensure directories exist
if (!fs.existsSync(UPLOAD_DIR)) fs.mkdirSync(UPLOAD_DIR, { recursive: true });
if (!fs.existsSync(DATA_DIR)) fs.mkdirSync(DATA_DIR, { recursive: true });

// Simple SQLite-like database using JSON file (no external dependencies needed)
const dbPath = path.join(DATA_DIR, 'files.json');
if (!fs.existsSync(dbPath)) {
    fs.writeFileSync(dbPath, JSON.stringify({ files: [], nextId: 1 }, null, 2));
}

// Database helpers
const db = {
    read() {
        try {
            return JSON.parse(fs.readFileSync(dbPath, 'utf8'));
        } catch {
            return { files: [], nextId: 1 };
        }
    },
    write(data) {
        fs.writeFileSync(dbPath, JSON.stringify(data, null, 2));
    },
    addFile(fileInfo) {
        const data = this.read();
        const file = {
            id: data.nextId++,
            ...fileInfo,
            uploadDate: new Date().toISOString(),
            status: 'uploaded'
        };
        data.files.push(file);
        this.write(data);
        return file;
    },
    getFiles() {
        return this.read().files.sort((a, b) => new Date(b.uploadDate) - new Date(a.uploadDate));
    },
    getFileById(id) {
        return this.read().files.find(f => f.id === parseInt(id));
    },
    deleteFile(id) {
        const data = this.read();
        const index = data.files.findIndex(f => f.id === parseInt(id));
        if (index > -1) {
            const file = data.files.splice(index, 1)[0];
            this.write(data);
            return file;
        }
        return null;
    },
    getStats() {
        const files = this.getFiles();
        const stats = {
            totalFiles: files.length,
            totalSize: files.reduce((sum, f) => sum + (f.size || 0), 0),
            byType: {}
        };
        files.forEach(f => {
            stats.byType[f.type] = (stats.byType[f.type] || 0) + 1;
        });
        return stats;
    }
};

// Configure multer for file uploads
const storage = multer.diskStorage({
    destination: (req, file, cb) => {
        cb(null, UPLOAD_DIR);
    },
    filename: (req, file, cb) => {
        const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
        const safeName = file.originalname.replace(/[^a-zA-Z0-9._-]/g, '_');
        cb(null, `${timestamp}_${safeName}`);
    }
});

const fileFilter = (req, file, cb) => {
    const ext = path.extname(file.originalname).toLowerCase();
    if (ALLOWED_EXTENSIONS[ext]) {
        cb(null, true);
    } else {
        cb(new Error(`File type ${ext} is not allowed`), false);
    }
};

const upload = multer({
    storage,
    fileFilter,
    limits: { fileSize: MAX_FILE_SIZE }
});

// Middleware
app.use(cors());
app.use(express.json());
app.use(express.urlencoded({ extended: true }));

// Serve static files
app.use(express.static(path.join(__dirname)));

// Helper to get file hash
function getFileHash(filepath) {
    const fileBuffer = fs.readFileSync(filepath);
    return crypto.createHash('md5').update(fileBuffer).digest('hex');
}

// API Routes

// Get all files
app.get('/api/files', (req, res) => {
    try {
        const files = db.getFiles();
        res.json({ success: true, files });
    } catch (error) {
        res.status(500).json({ success: false, error: error.message });
    }
});

// Get file statistics
app.get('/api/stats', (req, res) => {
    try {
        const stats = db.getStats();
        res.json({ success: true, stats });
    } catch (error) {
        res.status(500).json({ success: false, error: error.message });
    }
});

// Upload files
app.post('/api/upload', upload.array('files', 20), (req, res) => {
    try {
        if (!req.files || req.files.length === 0) {
            return res.status(400).json({
                success: false,
                error: 'No files uploaded'
            });
        }

        const notes = req.body.notes || '';
        const uploadedFiles = [];
        const errors = [];

        req.files.forEach(file => {
            try {
                const ext = path.extname(file.originalname).toLowerCase();
                const fileHash = getFileHash(file.path);

                const fileInfo = {
                    filename: file.filename,
                    originalName: file.originalname,
                    type: ALLOWED_EXTENSIONS[ext] || 'unknown',
                    size: file.size,
                    hash: fileHash,
                    notes: notes,
                    path: file.path
                };

                const savedFile = db.addFile(fileInfo);
                uploadedFiles.push(savedFile);
            } catch (err) {
                errors.push({
                    filename: file.originalname,
                    error: err.message
                });
            }
        });

        res.json({
            success: uploadedFiles.length > 0,
            uploaded: uploadedFiles,
            errors,
            message: `Successfully uploaded ${uploadedFiles.length} file(s)`
        });
    } catch (error) {
        res.status(500).json({ success: false, error: error.message });
    }
});

// Download file
app.get('/api/download/:id', (req, res) => {
    try {
        const file = db.getFileById(req.params.id);
        if (!file) {
            return res.status(404).json({ success: false, error: 'File not found' });
        }

        const filePath = path.join(UPLOAD_DIR, file.filename);
        if (!fs.existsSync(filePath)) {
            return res.status(404).json({ success: false, error: 'File not found on disk' });
        }

        const mimeType = mime.lookup(filePath) || 'application/octet-stream';
        res.setHeader('Content-Type', mimeType);
        res.setHeader('Content-Disposition', `attachment; filename="${file.originalName}"`);
        res.download(filePath, file.originalName);
    } catch (error) {
        res.status(500).json({ success: false, error: error.message });
    }
});

// Delete file
app.delete('/api/files/:id', (req, res) => {
    try {
        const file = db.deleteFile(req.params.id);
        if (!file) {
            return res.status(404).json({ success: false, error: 'File not found' });
        }

        // Delete from filesystem
        const filePath = path.join(UPLOAD_DIR, file.filename);
        if (fs.existsSync(filePath)) {
            fs.unlinkSync(filePath);
        }

        res.json({ success: true, message: 'File deleted successfully' });
    } catch (error) {
        res.status(500).json({ success: false, error: error.message });
    }
});

// Serve index.html for root
app.get('/', (req, res) => {
    res.sendFile(path.join(__dirname, 'index.html'));
});

// Error handling
app.use((err, req, res, next) => {
    if (err instanceof multer.MulterError) {
        if (err.code === 'LIMIT_FILE_SIZE') {
            return res.status(400).json({
                success: false,
                error: 'File too large. Maximum size is 50MB.'
            });
        }
    }
    res.status(500).json({ success: false, error: err.message });
});

// Start server
app.listen(PORT, () => {
    console.log(`
╔══════════════════════════════════════════════════════════╗
║  JBsn Server - Getting the Job Done                      ║
╠══════════════════════════════════════════════════════════╣
║  Server running at: http://localhost:${PORT}               ║
║  Upload endpoint:   POST /api/upload                     ║
║  Files endpoint:    GET  /api/files                      ║
║  Stats endpoint:    GET  /api/stats                      ║
║  Upload directory:  ${UPLOAD_DIR.padEnd(36)}║
╚══════════════════════════════════════════════════════════╝
    `);
});
