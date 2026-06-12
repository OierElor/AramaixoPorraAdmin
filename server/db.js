const path = require('path');
const fs = require('fs');
const Database = require('better-sqlite3');

const SCHEMA_PATH = path.join(__dirname, '..', 'schema.sql');

// Determine DB filename: 1) env DB_FILE 2) existing AramaixoPorra.db 3) fallback data.db
const DEFAULT_CANDIDATES = ['AramaixoPorra.db', 'data.db'];
const chosen = process.env.DB_FILE
  || DEFAULT_CANDIDATES.find(f => fs.existsSync(path.join(__dirname, '..', f)))
  || 'data.db';

const DB_PATH = path.join(__dirname, '..', chosen);
const db = new Database(DB_PATH);
console.log('Using SQLite DB at', DB_PATH);

// Initialize DB from schema.sql: run statements one-by-one and ignore "already exists" errors
if (fs.existsSync(SCHEMA_PATH)) {
  const schema = fs.readFileSync(SCHEMA_PATH, 'utf8');
  // Split on semicolons; tolerate trailing semicolon/newlines
  const statements = schema
    .split(/;\s*(?:\n|$)/)
    .map(s => s.trim())
    .filter(Boolean);

  for (const stmt of statements) {
    try {
      db.exec(stmt + ';');
    } catch (err) {
      // Ignore errors about existing tables/indexes
      if (/already exists/i.test(err.message)) {
        console.info('Schema: ignored existing object —', err.message);
        continue;
      }
      console.warn('Schema statement failed:', err.message);
    }
  }
} else {
  console.warn('schema.sql not found at', SCHEMA_PATH);
}

module.exports = db;
