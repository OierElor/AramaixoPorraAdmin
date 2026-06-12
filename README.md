# Aramaixo Porra — Local Admin

Lightweight local admin to view and insert rows into the provided SQLite schema.

Prerequisites
- Node.js (16+ recommended)

Install and run

```bash
cd /home/oier/AramaixoPorraAdmin
npm install
npm start
```

Then open http://localhost:3000 in your browser. The server will create `data.db` in the project root and apply `schema.sql` on first run.

Notes
- The server exposes simple JSON endpoints under `/api/*` for `Txapelketak`, `Porralariak`, `Txirrindulariak`, and `Karrerak`.
- This is a minimal admin UI served statically from the server at `/`.
