const path = require('path');
const fs = require('fs');
const Database = require('better-sqlite3');

const DB_PATH = path.join(__dirname, '..', 'data.db');
const SCHEMA_PATH = path.join(__dirname, '..', 'schema.sql');

const db = new Database(DB_PATH);

// Initialize DB from schema.sql (CREATE TABLE IF NOT EXISTS is safe to run repeatedly)
if (fs.existsSync(SCHEMA_PATH)) {
  const schema = fs.readFileSync(SCHEMA_PATH, 'utf8');
  db.exec(schema);
} else {
  console.warn('schema.sql not found at', SCHEMA_PATH);
}

module.exports = db;
