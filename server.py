#!/usr/bin/env python3
"""
Aramaixo Porra — server.py
Zero dependentzia: Python stdlib soilik (sqlite3 + http.server)
Erabili: python3 server.py
"""

import json
import os
import sqlite3
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse

# ── Config ───────────────────────────────────────────────────────
BASE_DIR   = Path(__file__).parent
PUBLIC_DIR = BASE_DIR / "public"
SCHEMA     = BASE_DIR / "schema.sql"
PORT       = int(os.environ.get("PORT", 3000))

MIME = {
    ".html": "text/html; charset=utf-8",
    ".js":   "application/javascript; charset=utf-8",
    ".css":  "text/css; charset=utf-8",
    ".ico":  "image/x-icon",
}

# ── DB ───────────────────────────────────────────────────────────
def find_db() -> Path:
    if env := os.environ.get("DB_FILE"):
        return Path(env)
    for name in ("AramaixoPorra.db", "data.db"):
        p = BASE_DIR / name
        if p.exists():
            return p
    return BASE_DIR / "data.db"

DB_PATH = find_db()
print(f"DB: {DB_PATH}")

def get_db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con

def init_db():
    if not SCHEMA.exists():
        print("Warning: schema.sql not found"); return
    con = get_db()
    for stmt in (s.strip() for s in SCHEMA.read_text("utf-8").split(";") if s.strip()):
        try:
            con.execute(stmt)
        except sqlite3.OperationalError as e:
            if "already exists" not in str(e):
                print(f"Schema: {e}")
    con.commit(); con.close()

init_db()

def rows(con, sql, params=()):
    return [dict(r) for r in con.execute(sql, params).fetchall()]

# ── Request handler ──────────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        print(f"  {self.command} {self.path} → {args[1] if len(args)>1 else ''}")

    def send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def send_error_json(self, msg, status=500):
        self.send_json({"error": msg}, status)

    def read_json(self):
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length)) if length else {}

    # ── GET ──────────────────────────────────────────────────────
    def do_GET(self):
        path = urlparse(self.path).path

        if path == "/api/txapelketak":
            with get_db() as c:
                self.send_json(rows(c, 'SELECT * FROM "Txapelketak" ORDER BY Urtea DESC, Izena'))

        elif path == "/api/porralariak":
            with get_db() as c:
                self.send_json(rows(c, 'SELECT * FROM "Porralariak" ORDER BY Izena'))

        elif path == "/api/txirrindulariak":
            with get_db() as c:
                self.send_json(rows(c, 'SELECT * FROM "Txirrindulariak" ORDER BY Izena'))

        elif path == "/api/karrerak":
            with get_db() as c:
                self.send_json(rows(c, 'SELECT * FROM "Karrerak" ORDER BY Urtea DESC, Izena'))

        elif path == "/api/emaitzak/porralariak":
            with get_db() as c:
                self.send_json(rows(c, """
                    SELECT ep.Txapelketa_ID, ep.Ezizen_ID, ep.Posizioa, ep.Puntuak,
                           pez.Ezizena,
                           GROUP_CONCAT(p.Izena, ' / ') AS Porralaria_Izena
                    FROM "TxapelketaEmaitzaPorralariak" ep
                    JOIN "PorralariEzizenak" pez ON pez.Ezizen_ID = ep.Ezizen_ID
                    LEFT JOIN "EzizenPorralariak" ezp ON ezp.Ezizen_ID = ep.Ezizen_ID
                    LEFT JOIN "Porralariak" p ON p.Porralaria_ID = ezp.Porralaria_ID
                    GROUP BY ep.Txapelketa_ID, ep.Ezizen_ID
                    ORDER BY ep.Txapelketa_ID DESC, ep.Posizioa ASC
                """))

        elif path == "/api/emaitzak/txirrindulariak":
            with get_db() as c:
                self.send_json(rows(c, """
                    SELECT et.Txapelketa_ID, et.Txirrindularia_ID, et.Posizioa, et.Puntuak,
                           t.Izena
                    FROM "TxapelketaEmaitzaTxirrindulariak" et
                    JOIN "Txirrindulariak" t ON t.Txirrindularia_ID = et.Txirrindularia_ID
                    ORDER BY et.Txapelketa_ID DESC, et.Posizioa ASC
                """))

        elif path == "/api/sariak":
            with get_db() as c:
                self.send_json(rows(c,
                    'SELECT * FROM "Sariak" ORDER BY Txapelketa_ID DESC, Posizioa ASC'))

        else:
            file_path = PUBLIC_DIR / (path.lstrip("/") or "index.html")
            if not file_path.exists() or not file_path.is_file():
                file_path = PUBLIC_DIR / "index.html"
            try:
                content = file_path.read_bytes()
                mime = MIME.get(file_path.suffix, "application/octet-stream")
                self.send_response(200)
                self.send_header("Content-Type", mime)
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
            except Exception as e:
                self.send_error_json(str(e), 404)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    # ── POST ─────────────────────────────────────────────────────
    def do_POST(self):
        path = urlparse(self.path).path
        data = self.read_json()

        try:
            if path == "/api/txapelketak":
                izena = (data.get("Izena") or "").strip()
                urtea = data.get("Urtea")
                if not izena or not urtea:
                    return self.send_error_json("Missing Izena or Urtea", 400)
                with get_db() as c:
                    cur = c.execute(
                        'INSERT INTO "Txapelketak" (Izena, Urtea) VALUES (?, ?)',
                        [izena, int(urtea)])
                    row = dict(c.execute(
                        'SELECT * FROM "Txapelketak" WHERE Txapelketa_ID = ?',
                        [cur.lastrowid]).fetchone())
                self.send_json(row)

            elif path == "/api/porralariak":
                izena  = (data.get("Izena") or "").strip()
                zenbat = data.get("Zenbat_Porra", 1)
                if not izena:
                    return self.send_error_json("Missing Izena", 400)
                with get_db() as c:
                    cur = c.execute(
                        'INSERT INTO "Porralariak" (Izena, "Zenbat Porra") VALUES (?, ?)',
                        [izena, int(zenbat)])
                    row = dict(c.execute(
                        'SELECT * FROM "Porralariak" WHERE Porralaria_ID = ?',
                        [cur.lastrowid]).fetchone())
                self.send_json(row)

            elif path == "/api/txirrindulariak":
                izena = (data.get("Izena") or "").strip()
                if not izena:
                    return self.send_error_json("Missing Izena", 400)
                with get_db() as c:
                    cur = c.execute(
                        'INSERT INTO "Txirrindulariak" (Izena) VALUES (?)', [izena])
                    row = dict(c.execute(
                        'SELECT * FROM "Txirrindulariak" WHERE Txirrindularia_ID = ?',
                        [cur.lastrowid]).fetchone())
                self.send_json(row)

            elif path == "/api/karrerak":
                txap_id = data.get("Txapelketa_ID")
                izena   = (data.get("Izena") or "").strip()
                urtea   = data.get("Urtea")
                if not txap_id or not izena or not urtea:
                    return self.send_error_json("Missing fields", 400)
                with get_db() as c:
                    cur = c.execute(
                        'INSERT INTO "Karrerak" (Txapelketa_ID, Izena, Urtea) VALUES (?, ?, ?)',
                        [int(txap_id), izena, int(urtea)])
                    row = dict(c.execute(
                        'SELECT * FROM "Karrerak" WHERE Karrerak_ID = ?',
                        [cur.lastrowid]).fetchone())
                self.send_json(row)

            else:
                self.send_error_json("Not found", 404)

        except sqlite3.IntegrityError as e:
            self.send_error_json(str(e), 500)
        except Exception as e:
            self.send_error_json(str(e), 500)

# ── Main ─────────────────────────────────────────────────────────
if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"http://localhost:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nAgur!")
