const express = require('express');
const path = require('path');
const cors = require('cors');
const db = require('./db');

const app = express();
app.use(cors());
app.use(express.json());

const PORT = process.env.PORT || 3000;

app.use(express.static(path.join(__dirname, '..', 'public')));

// Helper to run queries safely
function all(query, params = []) {
  return db.prepare(query).all(params);
}

function run(query, params = []) {
  const info = db.prepare(query).run(params);
  return info;
}

// Txapelketak
app.get('/api/txapelketak', (req, res) => {
  const rows = all('SELECT * FROM "Txapelketak" ORDER BY Urtea DESC, Izena');
  res.json(rows);
});

app.post('/api/txapelketak', (req, res) => {
  const { Izena, Urtea } = req.body;
  if (!Izena || !Urtea) return res.status(400).json({ error: 'Missing Izena or Urtea' });
  try {
    const info = run('INSERT INTO "Txapelketak" (Izena, Urtea) VALUES (?, ?)', [Izena, Urtea]);
    const row = db.prepare('SELECT * FROM "Txapelketak" WHERE Txapelketa_ID = ?').get(info.lastInsertRowid);
    res.json(row);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// Porralariak
app.get('/api/porralariak', (req, res) => {
  const rows = all('SELECT * FROM "Porralariak" ORDER BY Izena');
  res.json(rows);
});

app.post('/api/porralariak', (req, res) => {
  const { Izena, Zenbat_Porra } = req.body;
  if (!Izena) return res.status(400).json({ error: 'Missing Izena' });
  try {
    const info = run('INSERT INTO "Porralariak" (Izena, "Zenbat Porra") VALUES (?, ?)', [Izena, Zenbat_Porra || 1]);
    const row = db.prepare('SELECT * FROM "Porralariak" WHERE Porralaria_ID = ?').get(info.lastInsertRowid);
    res.json(row);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// Txirrindulariak
app.get('/api/txirrindulariak', (req, res) => {
  const rows = all('SELECT * FROM "Txirrindulariak" ORDER BY Izena');
  res.json(rows);
});

app.post('/api/txirrindulariak', (req, res) => {
  const { Izena } = req.body;
  if (!Izena) return res.status(400).json({ error: 'Missing Izena' });
  try {
    const info = run('INSERT INTO "Txirrindulariak" (Izena) VALUES (?)', [Izena]);
    const row = db.prepare('SELECT * FROM "Txirrindulariak" WHERE Txirrindularia_ID = ?').get(info.lastInsertRowid);
    res.json(row);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// Karrerak
app.get('/api/karrerak', (req, res) => {
  const rows = all('SELECT * FROM "Karrerak" ORDER BY Urtea DESC, Izena');
  res.json(rows);
});

app.post('/api/karrerak', (req, res) => {
  const { Txapelketa_ID, Izena, Urtea } = req.body;
  if (!Txapelketa_ID || !Izena || !Urtea) return res.status(400).json({ error: 'Missing fields' });
  try {
    const info = run('INSERT INTO "Karrerak" (Txapelketa_ID, Izena, Urtea) VALUES (?, ?, ?)', [Txapelketa_ID, Izena, Urtea]);
    const row = db.prepare('SELECT * FROM "Karrerak" WHERE Karrerak_ID = ?').get(info.lastInsertRowid);
    res.json(row);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

app.listen(PORT, () => {
  console.log(`Server running on http://localhost:${PORT}`);
});
