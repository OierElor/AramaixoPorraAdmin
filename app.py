#!/usr/bin/env python3
"""
Aramaixo Porra backend.
Zero dependentzia: Python stdlib soilik (sqlite3 + http.server)
"""

import json
import os
import sqlite3
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

BASE_DIR = Path(__file__).parent
SCHEMA   = BASE_DIR / "schema.sql"
PORT     = int(os.environ.get("PORT", 3000))

# ─── Undo / Redo stack ───────────────────────────────────────────────────────
_undo_stack: list[dict] = []
_redo_stack: list[dict] = []
MAX_STACK = 20

CSV_PROFILES = {
    "porralariak": {
        "label": "Porralariak",
        "target": "Porralariak",
        "fields": ["Izena"],
        "required": ["Izena"],
        "identity": ["Porralaria_ID"],
    },
    "txirrindulariak": {
        "label": "Txirrindulariak",
        "target": "Txirrindulariak",
        "fields": ["Izena"],
        "required": ["Izena"],
        "identity": ["Txirrindularia_ID"],
    },
    "txapelketak": {
        "label": "Txapelketak",
        "target": "Txapelketak",
        "fields": ["Izena", "Urtea"],
        "required": ["Izena", "Urtea"],
        "identity": ["Txapelketa_ID"],
    },
    "karrerak": {
        "label": "Karrerak",
        "target": "Karrerak",
        "fields": ["Izena", "Urtea"],
        "context_fields": ["Txapelketa_ID"],
        "required": ["Txapelketa_ID", "Izena", "Urtea"],
        "identity": ["Karrerak_ID"],
    },
    "txirrindulari_emaitzak": {
        "label": "Txirrindulari emaitzak (txapelketa)",
        "target": "TxapelketaEmaitzaTxirrindulariak",
        "fields": ["Posizioa", "Txirrindularia", "Puntuak"],
        "context_fields": ["Txapelketa_ID"],
        "required": ["Txapelketa_ID", "Posizioa", "Txirrindularia", "Puntuak"],
        "identity": ["Txapelketa_ID", "Txirrindularia_ID"],
    },
    "porralari_emaitzak": {
        "label": "Porralari emaitzak (txapelketa)",
        "target": "TxapelketaEmaitzaPorralariak",
        "fields": ["Posizioa", "Ezizena", "Puntuak"],
        "context_fields": ["Txapelketa_ID"],
        "required": ["Txapelketa_ID", "Posizioa", "Ezizena", "Puntuak"],
        "identity": ["Txapelketa_ID", "Ezizen_ID"],
    },
    "karrera_txirrindulari_emaitzak": {
        "label": "Txirrindulari emaitzak (karrera)",
        "target": "KarreraSailkapena",
        "fields": ["Txirrindularia", "Puntuak", "Dortsala"],
        "context_fields": ["Karrera_ID"],
        "required": ["Karrera_ID", "Txirrindularia", "Puntuak", "Dortsala"],
        "identity": ["Karrera_ID", "Txirrindularia_ID"],
    },
}

FIELD_ALIASES = {
    "Txapelketa_ID": ["Txapelketa_ID", "Txapelketa", "Competition", "Competition_ID"],
    "Karrera_ID": ["Karrera_ID", "Karrerak_ID", "Karrera", "Race", "Race_ID"],
    "Karrerak_ID": ["Karrerak_ID", "Karrera_ID"],
    "Ezizena": ["Ezizena", "Porralaria", "Porralari", "Nickname"],
    "Txirrindularia": ["Txirrindularia", "Txirrindulari", "Izena", "Rider", "Cyclist", "Name", "Nombre"],
    "Porralaria": ["Porralaria", "Ezizena", "Porralari"],
    "Posizioa": ["Posizioa", "Sailkapena", "Sailkapen", "Postua", "Rank", "Pos", "Position", "#"],
    "Puntuak": ["Puntuak", "Puntu", "Points", "Pts", "Ptos"],
    "Urtea": ["Urtea", "Year", "Año"],
    "Izena": ["Izena", "Name", "Title", "Nombre"],
    "Dortsala": ["Dortsala", "Dorsala", "Bib", "Dorsal", "Dors"],
}

# ─── DB helpers ───────────────────────────────────────────────────────────────

def find_db() -> Path:
    if env := os.environ.get("DB_FILE"):
        return Path(env)
    for name in ("AramaixoPorra.db", "data.db"):
        p = BASE_DIR / name
        if p.exists():
            return p
    return BASE_DIR / "AramaixoPorra.db"

DB_PATH = find_db()
print(f"DB: {DB_PATH.resolve()}")

def get_db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con

def init_db():
    if not SCHEMA.exists():
        print("Warning: schema.sql not found")
        return
    con = get_db()
    for stmt in (s.strip() for s in SCHEMA.read_text("utf-8").split(";") if s.strip()):
        try:
            con.execute(stmt)
        except sqlite3.OperationalError as e:
            if "already exists" not in str(e):
                print(f"Schema: {e}")
    con.commit()
    con.close()

init_db()

def rows(con, sql, params=()):
    return [dict(r) for r in con.execute(sql, params).fetchall()]

def _profile_spec(profile_id: str) -> dict | None:
    return CSV_PROFILES.get(profile_id)

def _first_match(raw: dict, names: list[str]):
    # Lehenengo pasada: zuzeneko match (espazio eta kasu ezikusi)
    for wanted in names:
        for key, value in raw.items():
            if str(key).strip().lower() == wanted.strip().lower():
                return value if value != "" else None
    # Bigarren pasada: partzial match (key-ak wanted-a dauka)
    for wanted in names:
        for key, value in raw.items():
            k = str(key).strip().lower()
            w = wanted.strip().lower()
            if w in k or k in w:
                return value if value != "" else None
    return None

def _resolve_raw_value(raw: dict, mapping: dict, logical_key: str):
    if logical_key in mapping:
        csv_col = mapping.get(logical_key)
        if not csv_col:
            return None
        for key, value in raw.items():
            if str(key).strip().lower() == str(csv_col).strip().lower():
                return value
        return None
    aliases = FIELD_ALIASES.get(logical_key, [logical_key])
    value = _first_match(raw, aliases)
    if value is not None:
        return value
    return _first_match(raw, [logical_key])

def _to_int(value):
    if value is None:
        return None
    if isinstance(value, int):
        return value
    text = str(value).strip()
    if text == "":
        return None
    return int(text)

def _find_txirrindularia_id(con, name: str):
    # 1. Match zehatza
    row = con.execute(
        'SELECT Txirrindularia_ID FROM "Txirrindulariak" WHERE Izena = ?', [name],
    ).fetchone()
    if row:
        return row[0]
    # 2. Herrialdea kendu eta saiatu berriro: "ROGLIC Primož (Esl)" -> "ROGLIC Primož"
    stripped = _strip_country(name)
    if stripped != name:
        row = con.execute(
            'SELECT Txirrindularia_ID FROM "Txirrindulariak" WHERE Izena = ?', [stripped],
        ).fetchone()
        if row:
            return row[0]
    # 3. Normalizatuta bilatu (kasu eta azentu ezikusi)
    norm_name = _normalize_name(name)
    all_rows = con.execute(
        'SELECT Txirrindularia_ID, Izena FROM "Txirrindulariak"'
    ).fetchall()
    for r in all_rows:
        if _normalize_name(r["Izena"]) == norm_name:
            return r["Txirrindularia_ID"]
    # 4. Token-ak ordenatu gabe konparatu (Izena-Abizena vs Abizena-Izena)
    norm_tokens = frozenset(_normalize_name(name).split())
    for r in all_rows:
        if frozenset(_normalize_name(r["Izena"]).split()) == norm_tokens:
            return r["Txirrindularia_ID"]
    return None


def _normalize_name(name: str) -> str:
    """Izena normalizatu: minuskulak, azentuak kendu, espazio soilik."""
    import unicodedata, re
    # Parentesi arteko edukia kendu: "ROGLIC Primoz (Esl)" -> "ROGLIC Primoz"
    n = re.sub(r"\(.*?\)", "", name).strip()
    # Normalizatu: minuskulak + azentuak kendu
    n = unicodedata.normalize("NFD", n.lower())
    n = "".join(c for c in n if unicodedata.category(c) != "Mn")
    n = re.sub(r"\s+", " ", n).strip()
    return n


def _strip_country(name: str) -> str:
    """Herrialdea kendu: 'ROGLIC Primož (Esl)' -> 'ROGLIC Primož'"""
    import re
    return re.sub(r"\s*\(.*?\)\s*$", "", name.strip()).strip()


def _name_tokens(name: str) -> set:
    return set(_normalize_name(name).split())


def _fuzzy_name_score(a: str, b: str) -> int:
    """0-100 antzekotasun-puntuazioa bi izenen artean."""
    na, nb = _normalize_name(a), _normalize_name(b)
    if na == nb:
        return 100
    # Token-ak ordenatu eta konparatu (abizena-izena vs izena-abizena)
    ta, tb = _name_tokens(a), _name_tokens(b)
    if ta == tb:
        return 98  # Token berdinak, ordena desberdina
    inter = ta & tb
    union = ta | tb
    if not union:
        return 0
    jaccard = len(inter) / len(union)
    # Ia token guztiak bat badatoz puntuazio altua
    if len(inter) >= min(len(ta), len(tb)):
        return max(85, int(jaccard * 100))
    # Bigram similarity
    def bigrams(s):
        return set(s[i:i+2] for i in range(len(s)-1))
    ba, bb = bigrams(na), bigrams(nb)
    denom = len(ba) + len(bb)
    if denom == 0:
        return 0
    common = len(ba & bb)
    bigram_score = int(2 * common / denom * 100)
    return max(int(jaccard * 70), bigram_score)


def _find_fuzzy_matches(con, name: str, threshold: int = 60) -> list:
    """DB-ko txirrindulari antzekoak bilatu."""
    all_riders = con.execute(
        'SELECT Txirrindularia_ID, Izena FROM "Txirrindulariak"'
    ).fetchall()
    matches = []
    for row in all_riders:
        score = _fuzzy_name_score(name, row["Izena"])
        if score >= threshold:
            matches.append({
                "Txirrindularia_ID": row["Txirrindularia_ID"],
                "Izena": row["Izena"],
                "score": score,
            })
    matches.sort(key=lambda x: -x["score"])
    return matches[:5]


def csv_fuzzy_check(payload) -> dict:
    """
    CSV lerro guztietarako txirrindulari-izen bakoitzaren antzekoak bilatu.
    Itzultzen du: zerrenda bat {csv_name, exact_match, suggestions}
    """
    profile = payload.get("profile", "")
    mapping = payload.get("mapping", {})
    raw     = payload.get("rows", [])
    context = payload.get("context", {})

    if profile not in ("txirrindulari_emaitzak", "karrera_txirrindulari_emaitzak"):
        return {"checks": []}

    results = []
    seen_names = set()

    with get_db() as con:
        for raw_row in raw:
            norm = _normalize_row(profile, mapping, raw_row, context, con, create_missing=False)
            if norm is None:
                continue
            csv_name = norm.get("Txirrindularia", "")
            if not csv_name or csv_name in seen_names:
                continue
            seen_names.add(csv_name)

            exact_id = _find_txirrindularia_id(con, csv_name)
            if exact_id:
                # Bat-etortze zehatza edo normalizatua: ez proposatu
                continue

            # Fuzzy matcherari ere herrialdea kendutako bertsioa pasa
            clean_name = _strip_country(csv_name)
            suggestions = _find_fuzzy_matches(con, clean_name, threshold=55)
            results.append({
                "csv_name": csv_name,
                "suggestions": suggestions,
            })

    return {"checks": results}

def _ensure_txirrindularia_id(con, name: str) -> int:
    tid = _find_txirrindularia_id(con, name)
    if tid is not None:
        return int(tid)
    cur = con.execute('INSERT INTO "Txirrindulariak" (Izena) VALUES (?)', [name])
    return int(cur.lastrowid)

def _find_ezizen_id(con, txapelketa_id: int, ezizena: str):
    row = con.execute(
        'SELECT Ezizen_ID FROM "PorralariEzizenak" WHERE Txapelketa_ID = ? AND Ezizena = ?',
        [txapelketa_id, ezizena],
    ).fetchone()
    return row[0] if row else None

def _ensure_ezizen_id(con, txapelketa_id: int, ezizena: str) -> int:
    eid = _find_ezizen_id(con, txapelketa_id, ezizena)
    if eid is not None:
        return int(eid)
    cur = con.execute(
        'INSERT INTO "PorralariEzizenak" (Txapelketa_ID, Ezizena) VALUES (?, ?)',
        [txapelketa_id, ezizena],
    )
    return int(cur.lastrowid)

def _delete_rows_by_identity(con, table: str, identity_fields: list[str], identities: list[dict]):
    if not identity_fields or not identities:
        return 0
    if len(identity_fields) == 1:
        field = identity_fields[0]
        values = [identity[field] for identity in identities if field in identity]
        if not values:
            return 0
        placeholders = ",".join("?" * len(values))
        con.execute(f'DELETE FROM "{table}" WHERE "{field}" IN ({placeholders})', values)
        return len(values)
    clause_parts = []
    params = []
    for identity in identities:
        if not all(field in identity for field in identity_fields):
            continue
        clause_parts.append("(" + " AND ".join(f'"{field}" = ?' for field in identity_fields) + ")")
        params.extend(identity[field] for field in identity_fields)
    if not clause_parts:
        return 0
    sql = f'DELETE FROM "{table}" WHERE ' + " OR ".join(clause_parts)
    con.execute(sql, params)
    return len(clause_parts)

def _normalize_row(profile_id, mapping, raw, context=None, con=None, create_missing=False):
    spec = _profile_spec(profile_id)
    if not spec:
        return None
    context = context or {}
    context_fields = set(spec.get("context_fields", []))

    def get(logical_key):
        if logical_key in context_fields:
            value = context.get(logical_key)
        else:
            value = _resolve_raw_value(raw, mapping, logical_key)
        if value is None and logical_key in context:
            value = context.get(logical_key)
        if isinstance(value, str):
            value = value.strip()
        return value

    if profile_id in ("porralariak", "txirrindulariak"):
        izena = get("Izena")
        if not izena:
            return None
        return {"Izena": izena}

    if profile_id == "txapelketak":
        izena = get("Izena")
        urtea = _to_int(get("Urtea"))
        if not izena or urtea is None:
            return None
        return {"Izena": izena, "Urtea": urtea}

    if profile_id == "karrerak":
        txap_id = _to_int(get("Txapelketa_ID"))
        izena = get("Izena")
        urtea = _to_int(get("Urtea"))
        if txap_id is None or not izena or urtea is None:
            return None
        return {"Txapelketa_ID": txap_id, "Izena": izena, "Urtea": urtea}

    if profile_id == "txirrindulari_emaitzak":
        txap_id = _to_int(get("Txapelketa_ID"))
        posizioa = _to_int(get("Posizioa"))
        txirr_name = get("Txirrindularia")
        puntuak = _to_int(get("Puntuak"))
        if txap_id is None or posizioa is None or not txirr_name:
            return None
        if puntuak is None:
            puntuak = 0  # Puntuak falta bada 0 erabili errore baten ordez
        norm = {"Txapelketa_ID": txap_id, "Posizioa": posizioa, "Txirrindularia": txirr_name, "Puntuak": puntuak}
        dortsala = get("Dortsala")
        if dortsala not in (None, ""):
            norm["Dortsala"] = _to_int(dortsala)
        if con is not None:
            rider_id = _find_txirrindularia_id(con, txirr_name)
            if rider_id is not None:
                norm["Txirrindularia_ID"] = int(rider_id)
            elif create_missing:
                norm["Txirrindularia_ID"] = _ensure_txirrindularia_id(con, txirr_name)
        return norm

    if profile_id == "porralari_emaitzak":
        txap_id = _to_int(get("Txapelketa_ID"))
        posizioa = _to_int(get("Posizioa"))
        ezizena = get("Ezizena")
        puntuak = _to_int(get("Puntuak"))
        if txap_id is None or posizioa is None or not ezizena or puntuak is None:
            return None
        norm = {"Txapelketa_ID": txap_id, "Posizioa": posizioa, "Ezizena": ezizena, "Puntuak": puntuak}
        if con is not None:
            ezizen_id = _find_ezizen_id(con, txap_id, ezizena)
            if ezizen_id is not None:
                norm["Ezizen_ID"] = int(ezizen_id)
            elif create_missing:
                norm["Ezizen_ID"] = _ensure_ezizen_id(con, txap_id, ezizena)
        return norm

    if profile_id == "karrera_txirrindulari_emaitzak":
        karrera_id = _to_int(get("Karrera_ID"))
        txirr_name = get("Txirrindularia")
        puntuak = _to_int(get("Puntuak"))
        dortsala = _to_int(get("Dortsala"))
        if karrera_id is None or not txirr_name or puntuak is None or dortsala is None:
            return None
        norm = {"Karrera_ID": karrera_id, "Txirrindularia": txirr_name, "Puntuak": puntuak, "Dortsala": dortsala}
        if con is not None:
            rider_id = _find_txirrindularia_id(con, txirr_name)
            if rider_id is not None:
                norm["Txirrindularia_ID"] = int(rider_id)
            elif create_missing:
                norm["Txirrindularia_ID"] = _ensure_txirrindularia_id(con, txirr_name)
        return norm

    return None

def _row_exists(con, profile_id, norm):
    if profile_id == "porralariak":
        r = con.execute('SELECT Porralaria_ID FROM "Porralariak" WHERE Izena = ?', [norm["Izena"]]).fetchone()
        return (bool(r), f"ID={r[0]}" if r else "")
    if profile_id == "txirrindulariak":
        r = con.execute('SELECT Txirrindularia_ID FROM "Txirrindulariak" WHERE Izena = ?', [norm["Izena"]]).fetchone()
        return (bool(r), f"ID={r[0]}" if r else "")
    if profile_id == "txapelketak":
        r = con.execute('SELECT Txapelketa_ID FROM "Txapelketak" WHERE Izena = ? AND Urtea = ?', [norm["Izena"], norm["Urtea"]]).fetchone()
        return (bool(r), f"ID={r[0]}" if r else "")
    if profile_id == "karrerak":
        r = con.execute('SELECT Karrerak_ID FROM "Karrerak" WHERE Izena = ? AND Urtea = ? AND Txapelketa_ID = ?', [norm["Izena"], norm["Urtea"], norm["Txapelketa_ID"]]).fetchone()
        return (bool(r), f"ID={r[0]}" if r else "")
    if profile_id == "txirrindulari_emaitzak":
        rider_id = norm.get("Txirrindularia_ID") or _find_txirrindularia_id(con, norm["Txirrindularia"])
        if rider_id is None:
            return False, ""
        r = con.execute('SELECT 1 FROM "TxapelketaEmaitzaTxirrindulariak" WHERE Txapelketa_ID = ? AND Txirrindularia_ID = ?', [norm["Txapelketa_ID"], rider_id]).fetchone()
        return (bool(r), f"Txirrindularia_ID={rider_id}" if r else "")
    if profile_id == "porralari_emaitzak":
        ezizen_id = norm.get("Ezizen_ID") or _find_ezizen_id(con, norm["Txapelketa_ID"], norm["Ezizena"])
        if ezizen_id is None:
            return False, ""
        r = con.execute('SELECT 1 FROM "TxapelketaEmaitzaPorralariak" WHERE Txapelketa_ID = ? AND Ezizen_ID = ?', [norm["Txapelketa_ID"], ezizen_id]).fetchone()
        return (bool(r), f"Ezizen_ID={ezizen_id}" if r else "")
    if profile_id == "karrera_txirrindulari_emaitzak":
        rider_id = norm.get("Txirrindularia_ID") or _find_txirrindularia_id(con, norm["Txirrindularia"])
        if rider_id is None:
            return False, ""
        r = con.execute('SELECT 1 FROM "KarreraSailkapena" WHERE Karrera_ID = ? AND Txirrindularia_ID = ?', [norm["Karrera_ID"], rider_id]).fetchone()
        return (bool(r), f"Txirrindularia_ID={rider_id}" if r else "")
    return False, ""

def _insert_row(con, profile_id, norm):
    if profile_id == "porralariak":
        cur = con.execute('INSERT INTO "Porralariak" (Izena) VALUES (?)', [norm["Izena"]])
        return {"Porralaria_ID": int(cur.lastrowid)}
    if profile_id == "txirrindulariak":
        cur = con.execute('INSERT INTO "Txirrindulariak" (Izena) VALUES (?)', [norm["Izena"]])
        return {"Txirrindularia_ID": int(cur.lastrowid)}
    if profile_id == "txapelketak":
        cur = con.execute('INSERT INTO "Txapelketak" (Izena, Urtea) VALUES (?, ?)', [norm["Izena"], norm["Urtea"]])
        return {"Txapelketa_ID": int(cur.lastrowid)}
    if profile_id == "karrerak":
        cur = con.execute('INSERT INTO "Karrerak" (Txapelketa_ID, Izena, Urtea) VALUES (?, ?, ?)', [norm["Txapelketa_ID"], norm["Izena"], norm["Urtea"]])
        return {"Karrerak_ID": int(cur.lastrowid)}
    if profile_id == "txirrindulari_emaitzak":
        rider_id = norm.get("Txirrindularia_ID") or _ensure_txirrindularia_id(con, norm["Txirrindularia"])
        con.execute('INSERT INTO "TxapelketaEmaitzaTxirrindulariak" (Txapelketa_ID, Txirrindularia_ID, Posizioa, Puntuak) VALUES (?, ?, ?, ?)',
            [norm["Txapelketa_ID"], int(rider_id), norm["Posizioa"], norm["Puntuak"]])
        return {"Txapelketa_ID": norm["Txapelketa_ID"], "Txirrindularia_ID": int(rider_id)}
    if profile_id == "porralari_emaitzak":
        ezizen_id = norm.get("Ezizen_ID") or _ensure_ezizen_id(con, norm["Txapelketa_ID"], norm["Ezizena"])
        con.execute('INSERT INTO "TxapelketaEmaitzaPorralariak" (Txapelketa_ID, Ezizen_ID, Posizioa, Puntuak) VALUES (?, ?, ?, ?)',
            [norm["Txapelketa_ID"], int(ezizen_id), norm["Posizioa"], norm["Puntuak"]])
        return {"Txapelketa_ID": norm["Txapelketa_ID"], "Ezizen_ID": int(ezizen_id)}
    if profile_id == "karrera_txirrindulari_emaitzak":
        rider_id = norm.get("Txirrindularia_ID") or _ensure_txirrindularia_id(con, norm["Txirrindularia"])
        con.execute('INSERT INTO "KarreraSailkapena" (Karrera_ID, Txirrindularia_ID, Puntuak, Dortsala) VALUES (?, ?, ?, ?)',
            [norm["Karrera_ID"], int(rider_id), norm["Puntuak"], norm["Dortsala"]])
        return {"Karrera_ID": norm["Karrera_ID"], "Txirrindularia_ID": int(rider_id)}
    raise ValueError(f"Taula ezezaguna: {profile_id}")

def db_meta():
    with get_db() as con:
        tables = [row[0] for row in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()]
    return {"db_path": str(DB_PATH.resolve()), "db_exists": DB_PATH.exists(), "tables": tables}

def _quote_ident(name):
    return '"' + name.replace('"', '""') + '"'

def read_table(table_name):
    with get_db() as con:
        exists = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ? AND name NOT LIKE 'sqlite_%'", [table_name],
        ).fetchone()
        if not exists:
            raise ValueError(f"Taula ez da existitzen: {table_name}")
        quoted = _quote_ident(table_name)
        cols = [dict(r) for r in con.execute(f"PRAGMA table_info({quoted})").fetchall()]
        table_rows = [dict(r) for r in con.execute(f"SELECT * FROM {quoted}").fetchall()]
    return {"name": table_name, "columns": [{"name": c["name"], "type": c["type"], "pk": c["pk"]} for c in cols], "rows": table_rows, "count": len(table_rows)}

def update_table_row(table_name, payload):
    pk_values = payload.get("pk") or {}
    values = payload.get("values") or {}
    if not isinstance(pk_values, dict) or not isinstance(values, dict):
        raise ValueError("Datu baliogabeak")
    with get_db() as con:
        exists = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ? AND name NOT LIKE 'sqlite_%'", [table_name],
        ).fetchone()
        if not exists:
            raise ValueError(f"Taula ez da existitzen: {table_name}")
        quoted = _quote_ident(table_name)
        columns = [dict(r) for r in con.execute(f"PRAGMA table_info({quoted})").fetchall()]
        column_names = {c["name"] for c in columns}
        pk_columns = [c["name"] for c in sorted((c for c in columns if c["pk"]), key=lambda c: c["pk"])]
        if not pk_columns:
            raise ValueError("Taula honek ez dauka primary key-rik")
        if any(col not in pk_values for col in pk_columns):
            raise ValueError("Primary key balioak falta dira")
        editable = [col for col in column_names if col not in pk_columns]
        changes = {k: v for k, v in values.items() if k in editable}
        if not changes:
            raise ValueError("Ez dago aldatzeko zutaberik")
        set_sql = ", ".join(f"{_quote_ident(col)} = ?" for col in changes)
        where_sql = " AND ".join(f"{_quote_ident(col)} = ?" for col in pk_columns)
        params = list(changes.values()) + [pk_values[col] for col in pk_columns]
        cur = con.execute(f"UPDATE {quoted} SET {set_sql} WHERE {where_sql}", params)
        con.commit()
    return {"ok": True, "updated": cur.rowcount}

# ─── CSV Preview / Import ─────────────────────────────────────────────────────

def csv_preview(payload):
    profile = payload.get("profile") or payload.get("table", "")
    mapping = payload.get("mapping", {})
    raw     = payload.get("rows", [])
    context = payload.get("context", {})
    spec = _profile_spec(profile)
    if not spec:
        return {"will_insert": [], "already_exists": [], "errors": [{"row": {}, "reason": f"CSV profila ezezaguna: {profile}"}]}
    will_insert = []
    already_exists = []
    errors = []
    with get_db() as con:
        for raw_row in raw:
            norm = _normalize_row(profile, mapping, raw_row, context, con, create_missing=False)
            if norm is None:
                errors.append({"row": raw_row, "reason": "Eremu batzuk falta dira"})
                continue
            exists, reason = _row_exists(con, profile, norm)
            if exists:
                already_exists.append({**norm, "_exists_reason": reason})
            else:
                will_insert.append(norm)
    return {"will_insert": will_insert, "already_exists": already_exists, "errors": errors}

def csv_import(payload):
    profile   = payload.get("profile") or payload.get("table", "")
    mapping   = payload.get("mapping", {})
    raw       = payload.get("rows", [])
    context   = payload.get("context", {})
    label     = payload.get("label", f"CSV → {profile}")
    # merge_map: {csv_name: txirrindularia_id} - erabiltzaileak erabakitako fusio-map
    merge_map: dict = payload.get("merge_map", {})
    spec = _profile_spec(profile)
    if not spec:
        return {"inserted": 0, "skipped": 0, "errors": [{"row": {}, "reason": f"CSV profila ezezaguna: {profile}"}], "batch_id": len(_undo_stack)}
    inserted_identities = []
    inserted_rows = []
    skipped = 0
    errors = []
    with get_db() as con:
        for raw_row in raw:
            norm = _normalize_row(profile, mapping, raw_row, context, con, create_missing=True)
            if norm is None:
                errors.append({"row": raw_row, "reason": "Eremu batzuk falta dira"})
                continue
            # merge_map: CSV-ko izen bat DB-ko ID bati lotuta badago, ID hori erabili
            if merge_map and "Txirrindularia" in norm:
                csv_name = norm["Txirrindularia"]
                if csv_name in merge_map:
                    mapped_id = merge_map[csv_name]
                    if mapped_id is None:
                        # Erabiltzaileak "berri gisa sartu" aukeratu du
                        pass
                    else:
                        norm["Txirrindularia_ID"] = int(mapped_id)
            exists, _ = _row_exists(con, profile, norm)
            if exists:
                skipped += 1
                continue
            try:
                identity = _insert_row(con, profile, norm)
                inserted_identities.append(identity)
                inserted_rows.append(norm)
            except Exception as exc:
                errors.append({"row": norm, "reason": str(exc)})
        con.commit()
    if inserted_identities:
        batch = {"label": label, "profile": profile, "target": spec["target"], "rows": inserted_rows, "identities": inserted_identities, "identity_fields": spec["identity"]}
        _undo_stack.append(batch)
        if len(_undo_stack) > MAX_STACK:
            _undo_stack.pop(0)
        _redo_stack.clear()
    return {"inserted": len(inserted_identities), "skipped": skipped, "errors": errors, "batch_id": len(_undo_stack)}

# ─── Undo / Redo ─────────────────────────────────────────────────────────────

def do_undo():
    if not _undo_stack:
        return {"ok": False, "reason": "Undo stack hutsa"}
    batch = _undo_stack[-1]
    spec = _profile_spec(batch["profile"])
    tbl = spec["target"] if spec else None
    identities = batch.get("identities", [])
    identity_fields = batch.get("identity_fields", [])
    if not tbl or not identities:
        return {"ok": False, "reason": "Batch baliogabea"}
    batch = _undo_stack.pop()
    _redo_stack.append(batch)
    with get_db() as con:
        _delete_rows_by_identity(con, tbl, identity_fields, identities)
        con.commit()
    return {"ok": True, "deleted": len(identities), "label": batch["label"]}

def do_redo():
    if not _redo_stack:
        return {"ok": False, "reason": "Redo stack hutsa"}
    batch = _redo_stack[-1]
    spec = _profile_spec(batch["profile"])
    if not spec:
        return {"ok": False, "reason": "Redo batch baliogabea"}
    rows_list = batch.get("rows", [])
    inserted_identities = []
    skipped = 0
    errors = []
    with get_db() as con:
        for norm in rows_list:
            exists, _ = _row_exists(con, batch["profile"], norm)
            if exists:
                skipped += 1
                continue
            try:
                inserted_identities.append(_insert_row(con, batch["profile"], norm))
            except Exception as exc:
                errors.append({"row": norm, "reason": str(exc)})
        con.commit()
    batch = _redo_stack.pop()
    if inserted_identities:
        _undo_stack.append({**batch, "identities": inserted_identities})
        if len(_undo_stack) > MAX_STACK:
            _undo_stack.pop(0)
    return {"ok": True, "inserted": len(inserted_identities), "skipped": skipped, "errors": errors, "label": batch["label"]}

def undo_stack_state():
    return {
        "undo": [{"label": b["label"], "count": len(b.get("rows") or b.get("identities") or [])} for b in reversed(_undo_stack)],
        "redo": [{"label": b["label"], "count": len(b.get("rows") or b.get("identities") or [])} for b in reversed(_redo_stack)],
    }

# ─── Merge helpers ────────────────────────────────────────────────────────────

TXIRRINDULARIA_REFS = [
    ("TxapelketaEmaitzaTxirrindulariak",    "Txirrindularia_ID", ["Txapelketa_ID", "Txirrindularia_ID"]),
    ("TxapelketaSailkapenaTxirrindulariak", "Txirrindularia_ID", ["Txapelketa_ID", "Txirrindularia_ID", "Azken_Karrera_ID"]),
    ("KarreraSailkapena",                   "Txirrindularia_ID", ["Karrera_ID",    "Txirrindularia_ID"]),
    ("PorraApustuak",                       "Txirrindularia_ID", ["Txapelketa_ID", "Ezizen_ID", "Txirrindularia_ID"]),
]

PORRALARIA_REFS = [
    ("EzizenPorralariak", "Porralaria_ID", ["Ezizen_ID", "Porralaria_ID"]),
]

def _do_merge_refs(con, table, col, pks, keep_id, drop_id):
    exists = con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", [table]).fetchone()
    if not exists:
        return None
    ref_rows = con.execute(f'SELECT * FROM "{table}" WHERE "{col}" = ?', [drop_id]).fetchall()
    if not ref_rows:
        return None
    migrated = 0
    skipped = 0
    for ref_row in ref_rows:
        ref_dict  = dict(ref_row)
        new_vals  = {**ref_dict, col: keep_id}
        pk_vals   = [new_vals[pk] for pk in pks]
        pk_clause = " AND ".join(f'"{pk}" = ?' for pk in pks)
        conflict  = con.execute(f'SELECT 1 FROM "{table}" WHERE {pk_clause}', pk_vals).fetchone()
        old_pk_vals = [ref_dict[pk] for pk in pks]
        if conflict:
            con.execute(f'DELETE FROM "{table}" WHERE {pk_clause}', old_pk_vals)
            skipped += 1
        else:
            con.execute(f'UPDATE "{table}" SET "{col}" = ? WHERE {pk_clause}', [keep_id] + old_pk_vals)
            migrated += 1
    return {"table": table, "migrated": migrated, "skipped": skipped}

def merge_txirrindulariak(keep_id, drop_id):
    with get_db() as con:
        keep = con.execute('SELECT * FROM "Txirrindulariak" WHERE Txirrindularia_ID = ?', [keep_id]).fetchone()
        drop = con.execute('SELECT * FROM "Txirrindulariak" WHERE Txirrindularia_ID = ?', [drop_id]).fetchone()
        if not keep:
            return {"ok": False, "reason": f"Keep ID {keep_id} ez da existitzen"}
        if not drop:
            return {"ok": False, "reason": f"Drop ID {drop_id} ez da existitzen"}
        log = [r for table, col, pks in TXIRRINDULARIA_REFS if (r := _do_merge_refs(con, table, col, pks, keep_id, drop_id))]
        con.execute('DELETE FROM "Txirrindulariak" WHERE Txirrindularia_ID = ?', [drop_id])
        con.commit()
    return {"ok": True, "keep": {"id": keep_id, "izena": dict(keep)["Izena"]}, "dropped": {"id": drop_id, "izena": dict(drop)["Izena"]}, "log": log}

def merge_porralariak(keep_id, drop_id):
    with get_db() as con:
        keep = con.execute('SELECT * FROM "Porralariak" WHERE Porralaria_ID = ?', [keep_id]).fetchone()
        drop = con.execute('SELECT * FROM "Porralariak" WHERE Porralaria_ID = ?', [drop_id]).fetchone()
        if not keep:
            return {"ok": False, "reason": f"Keep ID {keep_id} ez da existitzen"}
        if not drop:
            return {"ok": False, "reason": f"Drop ID {drop_id} ez da existitzen"}
        log = [r for table, col, pks in PORRALARIA_REFS if (r := _do_merge_refs(con, table, col, pks, keep_id, drop_id))]
        keep_count = dict(keep).get("Zenbat Porra") or 1
        drop_count = dict(drop).get("Zenbat Porra") or 1
        con.execute('UPDATE "Porralariak" SET "Zenbat Porra" = ? WHERE Porralaria_ID = ?', [keep_count + drop_count, keep_id])
        con.execute('DELETE FROM "Porralariak" WHERE Porralaria_ID = ?', [drop_id])
        con.commit()
    return {"ok": True, "keep": {"id": keep_id, "izena": dict(keep)["Izena"]}, "dropped": {"id": drop_id, "izena": dict(drop)["Izena"]}, "log": log}

def merge_preview(kind, keep_id, drop_id):
    refs_map = TXIRRINDULARIA_REFS if kind == "txirrindulariak" else PORRALARIA_REFS
    id_col   = "Txirrindularia_ID"  if kind == "txirrindulariak" else "Porralaria_ID"
    table_n  = "Txirrindulariak"    if kind == "txirrindulariak" else "Porralariak"
    with get_db() as con:
        keep = con.execute(f'SELECT * FROM "{table_n}" WHERE {id_col} = ?', [keep_id]).fetchone()
        drop = con.execute(f'SELECT * FROM "{table_n}" WHERE {id_col} = ?', [drop_id]).fetchone()
        if not keep or not drop:
            return {"ok": False, "reason": "ID bat ez da existitzen"}
        refs = []
        for table, col, _ in refs_map:
            ex = con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", [table]).fetchone()
            if not ex:
                continue
            count = con.execute(f'SELECT COUNT(*) FROM "{table}" WHERE "{col}" = ?', [drop_id]).fetchone()[0]
            if count:
                refs.append({"table": table, "count": count})
        result = {"ok": True, "keep": {"id": keep_id, "izena": dict(keep)["Izena"]}, "dropped": {"id": drop_id, "izena": dict(drop)["Izena"]}, "refs": refs}
        if kind == "porralariak":
            result["zenbat_porra_merged"] = (dict(keep).get("Zenbat Porra") or 1) + (dict(drop).get("Zenbat Porra") or 1)
        return result


# ─── HTML ────────────────────────────────────────────────────────────────────

APP_HTML = r"""<!doctype html>
<html lang="eu">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>Aramaixo Porra</title>
  <link rel="preconnect" href="https://fonts.googleapis.com"/>
  <link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;700&family=Inter:wght@400;500&display=swap" rel="stylesheet"/>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    :root {
      --bg:#09090f; --surface:#13131f; --border:#1f2035;
      --accent:#e63946; --accent2:#f4c430;
      --text:#e8e8f0; --muted:#7070a0; --pill:#1e1e32;
      --radius:10px; --font-head:'Space Grotesk',sans-serif; --font-body:'Inter',sans-serif;
    }
    html,body{height:100%;background:var(--bg);color:var(--text);font-family:var(--font-body);font-size:14px;}
    .shell{display:flex;min-height:100vh;}
    .sidebar{width:220px;flex-shrink:0;background:var(--surface);border-right:1px solid var(--border);display:flex;flex-direction:column;padding:24px 0;position:sticky;top:0;height:100vh;overflow-y:auto;}
    .sidebar-logo{padding:0 20px 28px;font-family:var(--font-head);font-size:15px;font-weight:700;letter-spacing:-.3px;color:var(--text);border-bottom:1px solid var(--border);}
    .sidebar-logo span{color:var(--accent);}
    .sidebar-logo small{display:block;font-weight:400;font-size:11px;color:var(--muted);margin-top:2px;letter-spacing:.5px;text-transform:uppercase;}
    .nav-section{padding:20px 12px 8px;font-size:10px;font-weight:600;letter-spacing:1px;text-transform:uppercase;color:var(--muted);}
    .nav-item{display:flex;align-items:center;gap:10px;padding:9px 20px;cursor:pointer;color:var(--muted);font-size:13.5px;font-weight:500;border-left:2px solid transparent;transition:color .15s,background .15s,border-color .15s;}
    .nav-item:hover{color:var(--text);background:rgba(255,255,255,.04);}
    .nav-item.active{color:var(--text);border-left-color:var(--accent);background:rgba(230,57,70,.07);}
    .nav-item .icon{font-size:16px;width:18px;text-align:center;}
    .nav-sub-list{max-height:260px;overflow-y:auto;padding-bottom:6px;}
    .nav-sub-item{padding-left:28px;font-size:12.5px;}
    .nav-sub-empty{padding:8px 20px;color:var(--muted);font-size:12px;}
    .main{flex:1;overflow-y:auto;padding:36px 40px;}
    .page-header{display:flex;align-items:flex-end;justify-content:space-between;margin-bottom:28px;}
    .page-title{font-family:var(--font-head);font-size:26px;font-weight:700;letter-spacing:-.5px;}
    .page-title span{color:var(--accent);}
    .page-sub{color:var(--muted);font-size:13px;margin-top:3px;}
    .section{display:none;}
    .section.active{display:block;}
    .stats-row{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:28px;}
    .stat-card{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:18px 20px;}
    .stat-label{font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.8px;color:var(--muted);margin-bottom:6px;}
    .stat-val{font-family:var(--font-head);font-size:28px;font-weight:700;color:var(--text);}
    .stat-val.accent{color:var(--accent);}
    .stat-val.gold{color:var(--accent2);}
    .card{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);margin-bottom:20px;}
    .card-head{display:flex;align-items:center;justify-content:space-between;padding:16px 20px;border-bottom:1px solid var(--border);}
    .card-title{font-family:var(--font-head);font-size:15px;font-weight:600;}
    .card-body{padding:20px;}
    .tbl-wrap{overflow-x:auto;}
    table{width:100%;border-collapse:collapse;font-size:13px;}
    th{text-align:left;padding:9px 14px;font-size:11px;font-weight:600;letter-spacing:.6px;text-transform:uppercase;color:var(--muted);border-bottom:1px solid var(--border);}
    td{padding:10px 14px;border-bottom:1px solid var(--border);color:var(--text);}
    tr:last-child td{border-bottom:none;}
    tr:hover td{background:rgba(255,255,255,.025);}
    .pk-cell{color:var(--muted);font-family:var(--font-head);font-weight:600;}
    .cell-input{width:100%;min-width:110px;background:transparent;border:1px solid transparent;border-radius:6px;padding:6px 8px;color:var(--text);font:inherit;outline:none;}
    .cell-input:hover{border-color:var(--border);background:rgba(255,255,255,.025);}
    .cell-input:focus{border-color:var(--accent);background:var(--bg);}
    .row-actions{width:1%;white-space:nowrap;text-align:right;}
    .badge{display:inline-block;padding:2px 8px;border-radius:20px;font-size:11px;font-weight:600;background:var(--pill);}
    .toolbar{display:flex;gap:10px;align-items:center;padding:14px 20px;border-bottom:1px solid var(--border);}
    .search-input{flex:1;background:var(--bg);border:1px solid var(--border);border-radius:7px;padding:7px 12px;color:var(--text);font-size:13px;outline:none;transition:border-color .15s;}
    .search-input:focus{border-color:var(--accent);}
    .search-input::placeholder{color:var(--muted);}
    select.filter-sel{background:var(--bg);border:1px solid var(--border);border-radius:7px;padding:7px 28px 7px 10px;color:var(--text);font-size:13px;outline:none;appearance:none;cursor:pointer;}
    .form-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;}
    .form-grid.full{grid-template-columns:1fr;}
    .field label{display:block;font-size:11px;font-weight:600;letter-spacing:.6px;text-transform:uppercase;color:var(--muted);margin-bottom:5px;}
    .field input,.field select,.field textarea{width:100%;background:var(--bg);border:1px solid var(--border);border-radius:7px;padding:8px 12px;color:var(--text);font-size:13px;outline:none;transition:border-color .15s;}
    .field input:focus,.field select:focus{border-color:var(--accent);}
    .btn{display:inline-flex;align-items:center;gap:6px;padding:8px 16px;border-radius:7px;border:none;cursor:pointer;font-size:13px;font-weight:600;font-family:var(--font-body);transition:opacity .15s,transform .1s;}
    .btn:hover{opacity:.88;}
    .btn:active{transform:scale(.97);}
    .btn-primary{background:var(--accent);color:#fff;}
    .btn-ghost{background:var(--pill);color:var(--text);}
    .btn-sm{padding:5px 11px;font-size:12px;}
    .drop-zone{border:2px dashed var(--border);border-radius:var(--radius);padding:32px;text-align:center;cursor:pointer;transition:border-color .2s,background .2s;}
    .drop-zone:hover,.drop-zone.drag-over{border-color:var(--accent);background:rgba(230,57,70,.04);}
    .drop-zone .dz-icon{font-size:36px;margin-bottom:10px;}
    .drop-zone .dz-title{font-family:var(--font-head);font-size:15px;font-weight:600;margin-bottom:4px;}
    .drop-zone .dz-sub{color:var(--muted);font-size:12px;}
    #csv-file-input{display:none;}
    .preview-wrap{max-height:280px;overflow-y:auto;border:1px solid var(--border);border-radius:7px;margin-top:14px;}
    .csv-step-card{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:16px 18px;margin-top:16px;}
    .step-label{display:flex;align-items:center;gap:10px;font-size:13px;font-weight:600;margin-bottom:12px;}
    .step-num{display:inline-flex;align-items:center;justify-content:center;width:22px;height:22px;border-radius:50%;background:var(--pill);color:var(--text);font-size:12px;}
    .mapping-grid{display:grid;gap:10px;}
    .csv-column-summary{display:grid;gap:8px;padding:10px 12px;border:1px solid var(--border);border-radius:8px;background:var(--bg);color:var(--text);font-size:12px;margin-bottom:12px;}
    .csv-column-summary strong{color:var(--muted);font-weight:600;margin-right:6px;}
    .map-row{display:grid;grid-template-columns:1fr auto 1.2fr;gap:10px;align-items:center;padding:10px 12px;border:1px solid var(--border);border-radius:8px;background:var(--bg);}
    .map-field{color:var(--text);font-size:13px;font-weight:500;}
    .map-arrow{color:var(--muted);}
    .diff-summary{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin:14px 0;}
    .diff-stat{padding:10px 12px;border:1px solid var(--border);border-radius:8px;background:var(--bg);font-size:13px;}
    .diff-tabs{display:flex;gap:8px;flex-wrap:wrap;margin:12px 0;}
    .diff-tab-btn{padding:7px 12px;border-radius:7px;border:1px solid var(--border);background:var(--pill);color:var(--text);cursor:pointer;font-size:13px;}
    .diff-tab-btn.active{border-color:var(--accent);background:rgba(230,57,70,.12);}
    .diff-tab-content{display:none;}
    .diff-tab-content.active{display:block;}
    .undo-list{list-style:none;display:flex;flex-direction:column;gap:8px;}
    .undo-item{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:10px 12px;border:1px solid var(--border);border-radius:8px;background:var(--bg);}
    .undo-latest{border-color:rgba(230,57,70,.45);}
    .undo-label{font-size:13px;color:var(--text);}
    #toast{position:fixed;bottom:24px;right:24px;background:var(--surface);border:1px solid var(--border);border-radius:9px;padding:12px 18px;font-size:13px;font-weight:500;display:flex;align-items:center;gap:10px;transform:translateY(100px);opacity:0;transition:transform .3s,opacity .3s;z-index:999;}
    #toast.show{transform:translateY(0);opacity:1;}
    #toast.ok .toast-dot{color:#4ade80;}
    #toast.err .toast-dot{color:var(--accent);}
    .tabs{display:flex;gap:2px;background:var(--bg);border-radius:8px;padding:3px;margin-bottom:20px;width:fit-content;}
    .tab{padding:6px 14px;border-radius:6px;cursor:pointer;font-size:13px;font-weight:500;color:var(--muted);transition:color .15s,background .15s;}
    .tab.active{background:var(--surface);color:var(--text);}
    .merge-box{display:grid;grid-template-columns:1fr auto 1fr;gap:12px;align-items:center;padding:14px;background:var(--bg);border:1px solid var(--border);border-radius:8px;margin-bottom:14px;}
    .merge-side-label{font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.5px;color:var(--muted);margin-bottom:4px;}
    .merge-name{font-size:15px;font-weight:600;}
    .merge-name.keep{color:#4ade80;}
    .merge-name.drop{color:var(--accent);}
    @media(max-width:900px){.sidebar{display:none;}.main{padding:20px;}.stats-row{grid-template-columns:1fr 1fr;}.form-grid{grid-template-columns:1fr;}}
  </style>
</head>
<body>
<div class="shell">
  <nav class="sidebar">
    <div class="sidebar-logo">Aramaixo <span>Porra</span><small>Admin Panel</small></div>
    <div class="nav-section">Ikus</div>
    <div class="nav-item active" data-section="dashboard"><span class="icon">📊</span> Dashboard</div>
    <div class="nav-item" data-section="porralariak"><span class="icon">🏆</span> Porralariak</div>
    <div class="nav-item" data-section="txirrindulariak"><span class="icon">🚴</span> Txirrindulariak</div>
    <div class="nav-item" data-section="txapelketak"><span class="icon">🗓️</span> Txapelketak</div>
    <div class="nav-item" data-section="sailkapenak"><span class="icon">📋</span> Sailkapenak</div>
    <div class="nav-item" data-section="taulak"><span class="icon">▦</span> Taula guztiak</div>
    <div class="nav-sub-list" id="table-nav-list"></div>
    <div class="nav-section">Sartu</div>
    <div class="nav-item" data-section="add-manual"><span class="icon">✏️</span> Eskuz sartu</div>
    <div class="nav-item" data-section="add-csv"><span class="icon">📂</span> CSV inportatu</div>
    <div class="nav-item" data-section="merge"><span class="icon">🔀</span> Fusionatu</div>
    <div class="nav-item" data-section="ezizenak"><span class="icon">🏷️</span> Ezizenak lotu</div>
  </nav>
  <main class="main">

    <!-- DASHBOARD -->
    <section class="section active" id="sec-dashboard">
      <div class="page-header"><div><div class="page-title">Dashboard <span>·</span> Ikuspegi orokorra</div><div class="page-sub">Aramaixo Porra datu-basearen laburpena</div></div></div>
      <div class="stats-row">
        <div class="stat-card"><div class="stat-label">Txapelketak</div><div class="stat-val accent" id="st-txap">—</div></div>
        <div class="stat-card"><div class="stat-label">Porralariak</div><div class="stat-val" id="st-porra">—</div></div>
        <div class="stat-card"><div class="stat-label">Txirrindulariak</div><div class="stat-val" id="st-txirri">—</div></div>
        <div class="stat-card"><div class="stat-label">Karrerak</div><div class="stat-val gold" id="st-karrerak">—</div></div>
      </div>
      <div class="card">
        <div class="card-head"><div class="card-title">Azken sailkapen nagusiak</div></div>
        <div class="toolbar"><select class="filter-sel" id="dash-txap-sel" style="min-width:180px"><option value="">— Txapelketa aukeratu —</option></select></div>
        <div class="tbl-wrap"><table><thead><tr><th>#</th><th>Ezizena</th><th>Porralaria</th><th style="text-align:right">Puntuak</th></tr></thead><tbody id="dash-ranking-body"><tr><td colspan="4" style="color:var(--muted);padding:24px;text-align:center">Txapelketa bat aukeratu</td></tr></tbody></table></div>
      </div>
    </section>

    <!-- PORRALARIAK -->
    <section class="section" id="sec-porralariak">
      <div class="page-header"><div><div class="page-title">🏆 Porralariak</div><div class="page-sub">Parte-hartzaile guztiak</div></div></div>
      <div class="card">
        <div class="toolbar"><input class="search-input" id="porra-search" placeholder="Bilatu izena..."/><span style="color:var(--muted);font-size:12px" id="porra-count"></span></div>
        <div class="tbl-wrap"><table><thead><tr><th>ID</th><th>Izena</th><th>Porra kop.</th></tr></thead><tbody id="porra-tbody"></tbody></table></div>
      </div>
    </section>

    <!-- TXIRRINDULARIAK -->
    <section class="section" id="sec-txirrindulariak">
      <div class="page-header"><div><div class="page-title">🚴 Txirrindulariak</div><div class="page-sub">Erregistratutako txirrindulari guztiak</div></div></div>
      <div class="card">
        <div class="toolbar"><input class="search-input" id="txirri-search" placeholder="Bilatu txirrindularia..."/><span style="color:var(--muted);font-size:12px" id="txirri-count"></span></div>
        <div class="tbl-wrap"><table><thead><tr><th>ID</th><th>Izena</th></tr></thead><tbody id="txirri-tbody"></tbody></table></div>
      </div>
    </section>

    <!-- TXAPELKETAK -->
    <section class="section" id="sec-txapelketak">
      <div class="page-header"><div><div class="page-title">🗓️ Txapelketak</div><div class="page-sub">Txapelketa eta karrera guztiak</div></div></div>
      <div class="card"><div class="tbl-wrap"><table><thead><tr><th>ID</th><th>Izena</th><th>Urtea</th></tr></thead><tbody id="txap-tbody"></tbody></table></div></div>
      <div class="card"><div class="card-head"><div class="card-title">Karrerak</div></div><div class="tbl-wrap"><table><thead><tr><th>ID</th><th>Txapelketa</th><th>Izena</th><th>Urtea</th></tr></thead><tbody id="karrerak-tbody"></tbody></table></div></div>
    </section>

    <!-- SAILKAPENAK -->
    <section class="section" id="sec-sailkapenak">
      <div class="page-header"><div><div class="page-title">📋 Sailkapenak</div><div class="page-sub">Porralariak eta txirrindulariak txapelketaka</div></div></div>
      <div class="tabs"><div class="tab active" data-sltab="porralariak">Porralariak</div><div class="tab" data-sltab="txirrindulariak">Txirrindulariak</div></div>
      <div class="card">
        <div class="toolbar"><select class="filter-sel" id="sail-txap-sel" style="min-width:200px"><option value="">— Txapelketa guztiak —</option></select><input class="search-input" id="sail-search" placeholder="Bilatu..."/></div>
        <div class="tbl-wrap"><table><thead id="sail-thead"></thead><tbody id="sail-tbody"></tbody></table></div>
      </div>
    </section>

    <!-- TAULA GUZTIAK -->
    <section class="section" id="sec-taulak">
      <div class="page-header"><div><div class="page-title">▦ <span id="generic-table-title">Taula guztiak</span></div><div class="page-sub">Datu-baseko taula guztien ikuspegia</div></div></div>
      <div class="card">
        <div class="toolbar"><input class="search-input" id="generic-table-search" placeholder="Bilatu taulan..."/><span style="color:var(--muted);font-size:12px" id="generic-table-count"></span></div>
        <div class="tbl-wrap"><table><thead id="generic-table-thead"></thead><tbody id="generic-table-tbody"></tbody></table></div>
      </div>
    </section>

    <!-- ESKUZ SARTU -->
    <section class="section" id="sec-add-manual">
      <div class="page-header"><div><div class="page-title">✏️ Eskuz sartu</div><div class="page-sub">Erregistro berriak gehitu</div></div></div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px;">
        <div class="card"><div class="card-head"><div class="card-title">Txapelketa berria</div></div><div class="card-body"><div class="form-grid"><div class="field"><label>Izena</label><input id="m-txap-izena" placeholder="Tour de France"/></div><div class="field"><label>Urtea</label><input id="m-txap-urtea" type="number" placeholder="2025"/></div></div><div style="margin-top:14px"><button class="btn btn-primary" id="m-txap-btn">Gehitu txapelketa</button></div></div></div>
        <div class="card"><div class="card-head"><div class="card-title">Porralaria berria</div></div><div class="card-body"><div class="form-grid full"><div class="field"><label>Izena</label><input id="m-porra-izena" placeholder="Porralari izena"/></div></div><div style="margin-top:14px"><button class="btn btn-primary" id="m-porra-btn">Gehitu porralaria</button></div></div></div>
        <div class="card"><div class="card-head"><div class="card-title">Txirrindularia berria</div></div><div class="card-body"><div class="form-grid full"><div class="field"><label>Izena</label><input id="m-txirri-izena" placeholder="Pogacar Tadej"/></div></div><div style="margin-top:14px"><button class="btn btn-primary" id="m-txirri-btn">Gehitu txirrindularia</button></div></div></div>
        <div class="card"><div class="card-head"><div class="card-title">Karrera berria</div></div><div class="card-body"><div class="form-grid"><div class="field" style="grid-column:1/-1"><label>Txapelketa</label><select id="m-karrera-txap"><option value="">— Aukeratu —</option></select></div><div class="field"><label>Izena</label><input id="m-karrera-izena" placeholder="7. etapa"/></div><div class="field"><label>Urtea</label><input id="m-karrera-urtea" type="number" placeholder="2025"/></div></div><div style="margin-top:14px"><button class="btn btn-primary" id="m-karrera-btn">Gehitu karrera</button></div></div></div>
      </div>
    </section>

    <!-- CSV INPORTATU -->
    <section class="section" id="sec-add-csv">
      <div class="page-header"><div><div class="page-title">📂 CSV Inportatu</div><div class="page-sub">Datuak CSV fitxategitik kargatu</div></div></div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px;align-items:start">
        <div>
          <div class="card" style="margin-bottom:16px"><div class="card-body"><div class="field"><label>Datu mota</label><select id="csv-type" style="width:100%;background:var(--bg);border:1px solid var(--border);border-radius:7px;padding:8px 12px;color:var(--text);font-size:13px;outline:none"><option value="porralariak">Porralariak</option><option value="txirrindulariak">Txirrindulariak</option><option value="txapelketak">Txapelketak</option><option value="karrerak">Karrerak</option><option value="porralari_emaitzak">Porralari emaitzak (txapelketa)</option><option value="txirrindulari_emaitzak">Txirrindulari emaitzak (txapelketa)</option><option value="karrera_txirrindulari_emaitzak">Txirrindulari emaitzak (karrera)</option></select></div></div></div>
          <div class="card"><div class="card-body">
            <div class="drop-zone" id="drop-zone"><div class="dz-icon">📄</div><div class="dz-title">CSV fitxategia hemen utzi</div><div class="dz-sub">edo klik egin aukeratzeko</div><input type="file" id="csv-file-input" accept=".csv,.txt"/></div>
            <div id="csv-steps"></div>
            <div class="card" style="margin-top:16px"><div class="card-head"><div class="card-title">Atzera / Aurrera</div></div><div class="card-body" id="undo-wrap"><div style="display:flex;gap:8px;margin-bottom:12px"><button class="btn btn-ghost btn-sm" id="btn-undo">Atzera</button><button class="btn btn-ghost btn-sm" id="btn-redo">Aurrera</button></div><ul class="undo-list" id="undo-list"></ul></div></div>
          </div></div>
        </div>
        <div class="card"><div class="card-head"><div class="card-title">CSV formatua</div></div><div class="card-body" style="display:flex;flex-direction:column;gap:16px">
          <div><div style="font-size:12px;font-weight:600;color:var(--accent);margin-bottom:6px;text-transform:uppercase">Porralariak / Txirrindulariak</div><pre style="background:var(--bg);border:1px solid var(--border);border-radius:6px;padding:10px;font-size:12px;overflow-x:auto">Izena
Petit Breton
Vingegaard Jonas</pre></div>
          <div><div style="font-size:12px;font-weight:600;color:var(--accent2);margin-bottom:6px;text-transform:uppercase">Txapelketak / Karrerak</div><pre style="background:var(--bg);border:1px solid var(--border);border-radius:6px;padding:10px;font-size:12px;overflow-x:auto">Izena,Urtea
Tour De France,2026</pre></div>
          <div><div style="font-size:12px;font-weight:600;color:var(--muted);margin-bottom:6px;text-transform:uppercase">Txirrindulari sailkapena</div><pre style="background:var(--bg);border:1px solid var(--border);border-radius:6px;padding:10px;font-size:12px;overflow-x:auto">Posizioa,Txirrindularia,Puntuak
1,Pogacar Tadej,382
2,Vingegaard Jonas,242</pre></div>
        </div></div>
      </div>
    </section>

    <!-- EZIZENAK LOTU -->
    <section class="section" id="sec-ezizenak">
      <div class="page-header"><div><div class="page-title">🏷️ Ezizenak lotu</div><div class="page-sub">Ezizen bakoitza porralari bati esleitu</div></div></div>
      <div class="card">
        <div class="toolbar">
          <input class="search-input" id="ezizen-search" placeholder="Bilatu ezizena edo txapelketa..."/>
          <select class="filter-sel" id="ezizen-filter" style="min-width:160px">
            <option value="">Guztiak</option>
            <option value="lotu-gabe">Lotu gabekoak</option>
            <option value="lotuta">Lotutakoak</option>
          </select>
          <span style="color:var(--muted);font-size:12px" id="ezizen-count"></span>
        </div>
        <div class="tbl-wrap"><table>
          <thead><tr><th>Ezizena</th><th>Txapelketa</th><th>Porralaria</th><th style="width:200px">Esleitu</th></tr></thead>
          <tbody id="ezizen-tbody"></tbody>
        </table></div>
      </div>
    </section>

    <!-- FUSIONATU -->
    <section class="section" id="sec-merge">
      <div class="page-header"><div><div class="page-title">🔀 Fusionatu</div><div class="page-sub">Bikoiztutako txirrindulariak edo porralariak bat egin</div></div></div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px;align-items:start">
        <div class="card"><div class="card-head"><div class="card-title">Konfigurazioa</div></div><div class="card-body" style="display:flex;flex-direction:column;gap:14px">
          <div class="field"><label>Mota</label><select id="merge-kind" style="width:100%;background:var(--bg);border:1px solid var(--border);border-radius:7px;padding:8px 12px;color:var(--text);font-size:13px;outline:none"><option value="txirrindulariak">🚴 Txirrindulariak</option><option value="porralariak">🏆 Porralariak</option></select></div>
          <div class="field"><label>Bilatu</label><input class="search-input" id="merge-search" placeholder="Izena idatzi filtratzeko..." style="width:100%"/></div>
          <div class="field"><label>✅ KEEP — Bizirik geratuko dena</label><select id="merge-keep-sel" style="width:100%;background:var(--bg);border:1px solid var(--border);border-radius:7px;padding:8px 12px;color:var(--text);font-size:13px;outline:none"><option value="">— Hautatu —</option></select></div>
          <div class="field"><label>❌ DROP — Ezabatuko dena (erreferentziak KEEP-era pasatuko dira)</label><select id="merge-drop-sel" style="width:100%;background:var(--bg);border:1px solid var(--border);border-radius:7px;padding:8px 12px;color:var(--text);font-size:13px;outline:none"><option value="">— Hautatu —</option></select></div>
          <button class="btn btn-ghost" id="btn-merge-preview" style="width:fit-content">🔍 Aurreikusi fusio</button>
          <div id="merge-preview-wrap"></div>
        </div></div>
        <div class="card"><div class="card-head"><div class="card-title">Nola funtzionatzen du?</div></div><div class="card-body" style="display:flex;flex-direction:column;gap:14px;font-size:13px;line-height:1.7">
          <p>Bi erregistro <strong>KEEP</strong> (bizirik) eta <strong>DROP</strong> (ezabatu) moduan aukeratzen dituzu.</p>
          <ol style="padding-left:18px;display:flex;flex-direction:column;gap:8px">
            <li>DROP erregistroak dituen <strong>erreferentzia guztiak</strong> KEEP-era aldatzen dira.</li>
            <li>Erreferentzia bikoiztuak <strong>automatikoki ezabatzen dira</strong>.</li>
            <li>DROP erregistroa <strong>behin betiko ezabatzen da</strong>.</li>
            <li>Porralarien kasuan <strong>"Zenbat Porra"</strong> balioa batu egiten da.</li>
          </ol>
          <div style="padding:10px 12px;background:rgba(244,196,48,.08);border:1px solid rgba(244,196,48,.25);border-radius:7px">💡 <strong>Aholkua:</strong> KEEP moduan gorde nahi duzun formatua duen erregistroa hautatu.</div>
          <div style="padding:10px 12px;background:rgba(230,57,70,.08);border:1px solid rgba(230,57,70,.25);border-radius:7px">⚠️ Eragiketa hau <strong>ITZULEZINA da</strong>. Undo funtzioak ez du fusio bat desegin dezake.</div>
        </div></div>
      </div>
    </section>

  </main>
</div>
<div id="toast"><span class="toast-dot">●</span><span id="toast-msg"></span></div>
<script>
const state = {
  txirrindulariak: [], porralariak: [], txapelketak: [], karrerak: [],
  txirriEmaitzak: [], porraEmaitzak: [], karreraSailkapena: [],
  ezizenak: [],
  currentTable: null, currentTableData: null,
  sailTab: "porralariak",
};

const el = id => document.getElementById(id);
const esc = s => String(s ?? "").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");

function showToast(msg, type="ok") {
  const t = el("toast"); t.className = "show " + type;
  el("toast-msg").textContent = msg;
  clearTimeout(t._timer);
  t._timer = setTimeout(() => t.classList.remove("show"), 3500);
}

async function api(path, opts={}) {
  const r = await fetch(path, {headers:{"Content-Type":"application/json"}, ...opts});
  const data = await r.json();
  if (!r.ok) throw new Error(data.error || r.statusText);
  return data;
}

// ── Navigation ──────────────────────────────────────────────────────────────
function setSection(id) {
  document.querySelectorAll(".section").forEach(s => s.classList.remove("active"));
  document.querySelectorAll(".nav-item").forEach(n => n.classList.remove("active"));
  const sec = el("sec-" + id);
  if (sec) sec.classList.add("active");
  document.querySelector(`.nav-item[data-section="${id}"]`)?.classList.add("active");
  if (id === "merge") renderMergeSection();
  if (id === "ezizenak") loadEzizenak();
}

document.querySelectorAll(".nav-item[data-section]").forEach(item => {
  item.addEventListener("click", () => {
    const s = item.dataset.section;
    if (s === "taulak") return;
    setSection(s);
  });
});

// ── Data loading ─────────────────────────────────────────────────────────────
async function reloadData() {
  const [tx, po, txap, kar, txirriE, porraE, karE, undoSt] = await Promise.all([
    api("/api/txirrindulariak"), api("/api/porralariak"),
    api("/api/txapelketak"), api("/api/karrerak"),
    api("/api/txirrindulari-emaitzak"), api("/api/porralari-emaitzak"),
    api("/api/karrera-sailkapena"), api("/api/undo-state"),
  ]);
  state.txirrindulariak = tx; state.porralariak = po;
  state.txapelketak = txap; state.karrerak = kar;
  state.txirriEmaitzak = txirriE; state.porraEmaitzak = porraE;
  state.karreraSailkapena = karE;

  renderStats(); renderPorralariak(); renderTxirrindulariak();
  renderTxapelketak(); renderDashTxapSel(); renderManualSelects();
  renderSailTxapSel(); renderSailkapena(); renderUndoList(undoSt);
  if (state.currentTable) loadGenericTable(state.currentTable);
  if (el("sec-merge")?.classList.contains("active")) renderMergeSection();
  if (el("sec-ezizenak")?.classList.contains("active")) renderEzizenak();
}

// ── Stats ────────────────────────────────────────────────────────────────────
function renderStats() {
  el("st-txap").textContent   = state.txapelketak.length;
  el("st-porra").textContent  = state.porralariak.length;
  el("st-txirri").textContent = state.txirrindulariak.length;
  el("st-karrerak").textContent = state.karrerak.length;
}

// ── Porralariak ───────────────────────────────────────────────────────────────
function renderPorralariak() {
  const q = (el("porra-search")?.value || "").toLowerCase();
  const filtered = state.porralariak.filter(p => p.Izena?.toLowerCase().includes(q));
  el("porra-count").textContent = filtered.length + " erregistro";
  el("porra-tbody").innerHTML = filtered.map(p =>
    `<tr><td class="pk-cell">${esc(p.Porralaria_ID)}</td><td>${esc(p.Izena)}</td><td><span class="badge">${esc(p["Zenbat Porra"] ?? "—")}</span></td></tr>`
  ).join("") || `<tr><td colspan="3" style="color:var(--muted);padding:24px;text-align:center">Ez dago datürik</td></tr>`;
}

// ── Txirrindulariak ───────────────────────────────────────────────────────────
function renderTxirrindulariak() {
  const q = (el("txirri-search")?.value || "").toLowerCase();
  const filtered = state.txirrindulariak.filter(t => t.Izena?.toLowerCase().includes(q));
  el("txirri-count").textContent = filtered.length + " erregistro";
  el("txirri-tbody").innerHTML = filtered.map(t =>
    `<tr><td class="pk-cell">${esc(t.Txirrindularia_ID)}</td><td>${esc(t.Izena)}</td></tr>`
  ).join("") || `<tr><td colspan="2" style="color:var(--muted);padding:24px;text-align:center">Ez dago datürik</td></tr>`;
}

// ── Txapelketak ───────────────────────────────────────────────────────────────
function renderTxapelketak() {
  el("txap-tbody").innerHTML = state.txapelketak.map(t =>
    `<tr><td class="pk-cell">${esc(t.Txapelketa_ID)}</td><td>${esc(t.Izena)}</td><td>${esc(t.Urtea)}</td></tr>`
  ).join("");
  el("karrerak-tbody").innerHTML = state.karrerak.map(k => {
    const txap = state.txapelketak.find(t => t.Txapelketa_ID === k.Txapelketa_ID);
    return `<tr><td class="pk-cell">${esc(k.Karrerak_ID)}</td><td>${esc(txap?.Izena || k.Txapelketa_ID)}</td><td>${esc(k.Izena)}</td><td>${esc(k.Urtea)}</td></tr>`;
  }).join("");
}

// ── Dashboard ranking ─────────────────────────────────────────────────────────
function renderDashTxapSel() {
  el("dash-txap-sel").innerHTML = `<option value="">— Txapelketa aukeratu —</option>` +
    state.txapelketak.map(t => `<option value="${t.Txapelketa_ID}">${esc(t.Izena)} ${esc(t.Urtea)}</option>`).join("");
}
function renderDashRanking(txapId) {
  if (!txapId) { el("dash-ranking-body").innerHTML = `<tr><td colspan="4" style="color:var(--muted);padding:24px;text-align:center">Txapelketa bat aukeratu</td></tr>`; return; }
  const id = Number(txapId);
  const rows = state.porraEmaitzak.filter(r => r.Txapelketa_ID === id).sort((a,b) => a.Posizioa - b.Posizioa);
  if (!rows.length) { el("dash-ranking-body").innerHTML = `<tr><td colspan="4" style="color:var(--muted);padding:24px;text-align:center">Ez dago emaitzarik</td></tr>`; return; }
  el("dash-ranking-body").innerHTML = rows.map(r =>
    `<tr><td><span class="badge">${esc(r.Posizioa)}</span></td><td>${esc(r.Ezizena)}</td><td>${esc(r.Porralaria || "—")}</td><td style="text-align:right;font-weight:600">${esc(r.Puntuak)}</td></tr>`
  ).join("");
}

// ── Sailkapenak ───────────────────────────────────────────────────────────────
function renderSailTxapSel() {
  const opts = `<option value="">— Txapelketa guztiak —</option>` +
    state.txapelketak.map(t => `<option value="${t.Txapelketa_ID}">${esc(t.Izena)} ${esc(t.Urtea)}</option>`).join("");
  el("sail-txap-sel").innerHTML = opts;
}
function renderSailkapena() {
  const txapId = el("sail-txap-sel")?.value ? Number(el("sail-txap-sel").value) : null;
  const q = (el("sail-search")?.value || "").toLowerCase();
  const tab = state.sailTab;

  if (tab === "porralariak") {
    el("sail-thead").innerHTML = `<tr><th>#</th><th>Ezizena</th><th>Porralaria</th><th style="text-align:right">Puntuak</th></tr>`;
    let rows = state.porraEmaitzak;
    if (txapId) rows = rows.filter(r => r.Txapelketa_ID === txapId);
    if (q) rows = rows.filter(r => (r.Ezizena||"").toLowerCase().includes(q) || (r.Porralaria||"").toLowerCase().includes(q));
    rows = [...rows].sort((a,b) => a.Posizioa - b.Posizioa);
    el("sail-tbody").innerHTML = rows.map(r =>
      `<tr><td><span class="badge">${esc(r.Posizioa)}</span></td><td>${esc(r.Ezizena)}</td><td>${esc(r.Porralaria||"—")}</td><td style="text-align:right;font-weight:600">${esc(r.Puntuak)}</td></tr>`
    ).join("") || `<tr><td colspan="4" style="color:var(--muted);padding:24px;text-align:center">Ez dago datürik</td></tr>`;
  } else {
    el("sail-thead").innerHTML = `<tr><th>#</th><th>Txirrindularia</th><th style="text-align:right">Puntuak</th></tr>`;
    let rows = state.txirriEmaitzak;
    if (txapId) rows = rows.filter(r => r.Txapelketa_ID === txapId);
    if (q) rows = rows.filter(r => (r.Txirrindularia||"").toLowerCase().includes(q));
    rows = [...rows].sort((a,b) => a.Posizioa - b.Posizioa);
    el("sail-tbody").innerHTML = rows.map(r =>
      `<tr><td><span class="badge">${esc(r.Posizioa)}</span></td><td>${esc(r.Txirrindularia)}</td><td style="text-align:right;font-weight:600">${esc(r.Puntuak)}</td></tr>`
    ).join("") || `<tr><td colspan="3" style="color:var(--muted);padding:24px;text-align:center">Ez dago datürik</td></tr>`;
  }
}

// ── Generic table ─────────────────────────────────────────────────────────────
async function loadGenericTable(tableName) {
  state.currentTable = tableName;
  el("generic-table-title").textContent = tableName;
  try {
    const data = await api("/api/table/" + encodeURIComponent(tableName));
    state.currentTableData = data;
    renderGenericTable();
    setSection("taulak");
  } catch(e) { showToast(e.message, "err"); }
}
function renderGenericTable() {
  const data = state.currentTableData;
  if (!data) return;
  const q = (el("generic-table-search")?.value || "").toLowerCase();
  const pkCols = data.columns.filter(c => c.pk).map(c => c.name);
  const filtered = data.rows.filter(r =>
    Object.values(r).some(v => String(v ?? "").toLowerCase().includes(q))
  );
  el("generic-table-count").textContent = filtered.length + " / " + data.rows.length;
  el("generic-table-thead").innerHTML = `<tr>${data.columns.map(c => `<th>${esc(c.name)}</th>`).join("")}<th></th></tr>`;
  el("generic-table-tbody").innerHTML = filtered.map(row => {
    const cells = data.columns.map(col => {
      const isPk = pkCols.includes(col.name);
      if (isPk) return `<td class="pk-cell">${esc(row[col.name])}</td>`;
      return `<td><input class="cell-input" data-col="${esc(col.name)}" value="${esc(row[col.name] ?? "")}" data-orig="${esc(row[col.name] ?? "")}"/></td>`;
    }).join("");
    const pkJson = esc(JSON.stringify(Object.fromEntries(pkCols.map(k => [k, row[k]]))));
    return `<tr data-pk='${pkJson}'>${cells}<td class="row-actions"><button class="btn btn-sm btn-primary save-row-btn" style="display:none">Gorde</button></td></tr>`;
  }).join("");

  el("generic-table-tbody").querySelectorAll(".cell-input").forEach(inp => {
    inp.addEventListener("input", () => {
      const btn = inp.closest("tr")?.querySelector(".save-row-btn");
      if (btn) btn.style.display = "inline-flex";
    });
  });
  el("generic-table-tbody").querySelectorAll(".save-row-btn").forEach(btn => {
    btn.addEventListener("click", async () => {
      const tr = btn.closest("tr");
      const pkVal = JSON.parse(tr.dataset.pk);
      const values = {};
      tr.querySelectorAll(".cell-input").forEach(inp => {
        if (inp.value !== inp.dataset.orig) values[inp.dataset.col] = inp.value;
      });
      if (!Object.keys(values).length) return;
      try {
        await api("/api/table/" + encodeURIComponent(state.currentTable), {
          method: "PUT", body: JSON.stringify({pk: pkVal, values}),
        });
        showToast("Gordeta ✓");
        btn.style.display = "none";
        tr.querySelectorAll(".cell-input").forEach(inp => inp.dataset.orig = inp.value);
        await reloadData();
      } catch(e) { showToast(e.message, "err"); }
    });
  });
}

// ── Table nav ─────────────────────────────────────────────────────────────────
async function buildTableNav() {
  try {
    const meta = await api("/api/meta");
    const list = el("table-nav-list");
    list.innerHTML = meta.tables.map(t =>
      `<div class="nav-item nav-sub-item" data-table="${esc(t)}">${esc(t)}</div>`
    ).join("") || `<div class="nav-sub-empty">Taularik ez</div>`;
    list.querySelectorAll(".nav-item[data-table]").forEach(item => {
      item.addEventListener("click", () => {
        document.querySelectorAll(".nav-item").forEach(n => n.classList.remove("active"));
        item.classList.add("active");
        loadGenericTable(item.dataset.table);
      });
    });
  } catch(e) { console.error(e); }
}

// ── Manual selects ────────────────────────────────────────────────────────────
function renderManualSelects() {
  el("m-karrera-txap").innerHTML = `<option value="">— Aukeratu —</option>` +
    state.txapelketak.map(t => `<option value="${t.Txapelketa_ID}">${esc(t.Izena)} ${esc(t.Urtea)}</option>`).join("");
}

// ── Manual add ────────────────────────────────────────────────────────────────
async function manualAdd(payload) {
  try {
    await api("/api/insert", {method:"POST", body: JSON.stringify(payload)});
    showToast("Gordeta ✓"); await reloadData();
  } catch(e) { showToast(e.message, "err"); }
}

// ── CSV ───────────────────────────────────────────────────────────────────────
let csvRows = [], csvHeaders = [];

function parseCSV(text) {
  const lines = text.trim().split(/\r?\n/).filter(Boolean);
  if (!lines.length) return { headers: [], rows: [] };
  const parseRow = line => {
    const cols = []; let cur = "", inQ = false;
    for (const ch of line) {
      if (ch === '"') { inQ = !inQ; }
      else if (ch === ',' && !inQ) { cols.push(cur.trim()); cur = ""; }
      else cur += ch;
    }
    cols.push(cur.trim()); return cols;
  };
  const headers = parseRow(lines[0]);
  const rows = lines.slice(1).map(l => {
    const vals = parseRow(l);
    return Object.fromEntries(headers.map((h,i) => [h, vals[i] ?? ""]));
  });
  return { headers, rows };
}

function getContextFields() {
  const type = el("csv-type")?.value || "";
  const spec = {
    karrerak: ["Txapelketa_ID"],
    txirrindulari_emaitzak: ["Txapelketa_ID"],
    porralari_emaitzak: ["Txapelketa_ID"],
    karrera_txirrindulari_emaitzak: ["Karrera_ID"],
  };
  return spec[type] || [];
}

function renderCSVSteps() {
  const type  = el("csv-type")?.value || "";
  const steps = el("csv-steps");
  if (!csvRows.length) { steps.innerHTML = ""; return; }

  const contextFields = getContextFields();
  let contextHtml = "";
  if (contextFields.length) {
    contextHtml = `<div class="csv-step-card"><div class="step-label"><span class="step-num">1</span> Testuingurua</div><div class="mapping-grid">` +
      contextFields.map(f => {
        if (f === "Txapelketa_ID") {
          return `<div class="map-row"><div class="map-field">Txapelketa</div><div class="map-arrow">→</div>
            <select id="ctx-txap" style="background:var(--bg);border:1px solid var(--border);border-radius:7px;padding:7px 10px;color:var(--text);font-size:13px;outline:none">
              <option value="">— Aukeratu —</option>
              ${state.txapelketak.map(t => `<option value="${t.Txapelketa_ID}">${esc(t.Izena)} ${esc(t.Urtea)}</option>`).join("")}
            </select></div>`;
        }
        if (f === "Karrera_ID") {
          return `<div class="map-row"><div class="map-field">Karrera</div><div class="map-arrow">→</div>
            <select id="ctx-karrera" style="background:var(--bg);border:1px solid var(--border);border-radius:7px;padding:7px 10px;color:var(--text);font-size:13px;outline:none">
              <option value="">— Aukeratu —</option>
              ${state.karrerak.map(k => `<option value="${k.Karrerak_ID}">${esc(k.Izena)} ${esc(k.Urtea)}</option>`).join("")}
            </select></div>`;
        }
        return `<div class="map-row"><div class="map-field">${esc(f)}</div><div class="map-arrow">→</div><input id="ctx-${f}" style="background:var(--bg);border:1px solid var(--border);border-radius:7px;padding:7px 10px;color:var(--text);font-size:13px;outline:none" placeholder="ID"/></div>`;
      }).join("") + `</div></div>`;
  }

  const mapStep = `<div class="csv-step-card"><div class="step-label"><span class="step-num">${contextFields.length ? 2 : 1}</span> CSV zutabeen mapaketa</div>
    <div class="csv-column-summary"><span><strong>CSV zutabeak:</strong> ${csvHeaders.map(esc).join(", ")}</span></div>
    <div class="mapping-grid" id="mapping-grid"></div></div>`;

  const previewStep = `<div class="csv-step-card"><div class="step-label"><span class="step-num">${contextFields.length ? 3 : 2}</span> Aurreikuspen eta inportatu</div>
    <div style="display:flex;gap:8px;margin-bottom:12px">
      <button class="btn btn-ghost btn-sm" onclick="doCSVPreview()">🔍 Aurreikusi</button>
      <button class="btn btn-primary btn-sm" onclick="runFuzzyCheck()">⬆ Inportatu</button>
    </div>
    <div id="csv-preview-result"></div></div>`;

  // Gorde ctx-txap eta ctx-karrera balioak berridazketa aurretik
  const prevCtxTxap    = el("ctx-txap")?.value    || "";
  const prevCtxKarrera = el("ctx-karrera")?.value || "";

  steps.innerHTML = contextHtml + mapStep + previewStep;

  // Berrezarri hautatutako testuingurua
  if (prevCtxTxap    && el("ctx-txap"))    el("ctx-txap").value    = prevCtxTxap;
  if (prevCtxKarrera && el("ctx-karrera")) el("ctx-karrera").value = prevCtxKarrera;

  // Build mapping grid
  const FIELD_LABELS = {
    porralariak: ["Izena"], txirrindulariak: ["Izena"], txapelketak: ["Izena","Urtea"],
    karrerak: ["Izena","Urtea"], txirrindulari_emaitzak: ["Posizioa","Txirrindularia","Puntuak","Dortsala"],
    porralari_emaitzak: ["Posizioa","Ezizena","Puntuak"], karrera_txirrindulari_emaitzak: ["Txirrindularia","Puntuak","Dortsala"],
  };
  const logicals = FIELD_LABELS[type] || csvHeaders;
  const grid = el("mapping-grid");
  if (grid) grid.innerHTML = logicals.map(lf => {
    const autoMatch = csvHeaders.find(h => h.toLowerCase() === lf.toLowerCase()) || "";
    return `<div class="map-row"><div class="map-field">${esc(lf)}</div><div class="map-arrow">→</div>
      <select id="map-${esc(lf)}" style="background:var(--bg);border:1px solid var(--border);border-radius:7px;padding:7px 10px;color:var(--text);font-size:13px;outline:none">
        <option value="">— —</option>
        ${csvHeaders.map(h => `<option value="${esc(h)}" ${h===autoMatch?"selected":""}>${esc(h)}</option>`).join("")}
      </select></div>`;
  }).join("");
}

function getMapping() {
  const type = el("csv-type")?.value || "";
  const FIELD_LABELS = {
    porralariak: ["Izena"], txirrindulariak: ["Izena"], txapelketak: ["Izena","Urtea"],
    karrerak: ["Izena","Urtea"], txirrindulari_emaitzak: ["Posizioa","Txirrindularia","Puntuak","Dortsala"],
    porralari_emaitzak: ["Posizioa","Ezizena","Puntuak"], karrera_txirrindulari_emaitzak: ["Txirrindularia","Puntuak","Dortsala"],
  };
  const logicals = FIELD_LABELS[type] || [];
  const m = {};
  logicals.forEach(lf => { const sel = el("map-" + lf); if (sel?.value) m[lf] = sel.value; });
  return m;
}

function getContext() {
  const ctx = {};
  const txap = el("ctx-txap");
  if (txap?.value && txap.value !== "") ctx["Txapelketa_ID"] = Number(txap.value);
  const karrera = el("ctx-karrera");
  if (karrera?.value && karrera.value !== "") ctx["Karrera_ID"] = Number(karrera.value);
  return ctx;
}

async function doCSVPreview() {
  const type = el("csv-type")?.value || "";
  const ctx = getContext();
  // Testuingurua behar duten profilak egiaztatu
  const needsTxap = ["txirrindulari_emaitzak","porralari_emaitzak","karrerak"].includes(type);
  const needsKarrera = ["karrera_txirrindulari_emaitzak"].includes(type);
  if (needsTxap && !ctx["Txapelketa_ID"]) return showToast("Txapelketa bat hautatu ezinbestekoa da", "err");
  if (needsKarrera && !ctx["Karrera_ID"])  return showToast("Karrera bat hautatu ezinbestekoa da", "err");
  const payload = { profile: type, mapping: getMapping(), rows: csvRows, context: ctx };
  try {
    const r = await api("/api/csv/preview", { method: "POST", body: JSON.stringify(payload) });
    const res = el("csv-preview-result");
    const total = r.will_insert.length + r.already_exists.length + r.errors.length;
    const errHtml = r.errors.length
      ? `<div style="margin-top:10px;padding:10px;background:rgba(230,57,70,.08);border:1px solid rgba(230,57,70,.3);border-radius:7px;font-size:12px;color:var(--accent)">
          <strong>Lehen erroreak:</strong><br>
          ${r.errors.slice(0,5).map(e => `• ${esc(JSON.stringify(e.row).slice(0,60))} → ${esc(e.reason)}`).join("<br>")}
         </div>` : "";
    res.innerHTML = `<div class="diff-summary">
      <div class="diff-stat">📄 <strong>${total}</strong> lerro total</div>
      <div class="diff-stat" style="color:#4ade80">✅ <strong>${r.will_insert.length}</strong> sartuko dira</div>
      <div class="diff-stat" style="color:var(--accent2)">⚠️ <strong>${r.already_exists.length}</strong> jada daude</div>
      <div class="diff-stat" style="color:var(--accent)">❌ <strong>${r.errors.length}</strong> errore</div>
    </div>${errHtml}`;
  } catch(e) { showToast(e.message, "err"); }
}

async function doCSVImport() {
  const type = el("csv-type")?.value || "";
  const ctx = getContext();
  const needsTxap = ["txirrindulari_emaitzak","porralari_emaitzak","karrerak"].includes(type);
  const needsKarrera = ["karrera_txirrindulari_emaitzak"].includes(type);
  if (needsTxap && !ctx["Txapelketa_ID"]) return showToast("Txapelketa bat hautatu ezinbestekoa da", "err");
  if (needsKarrera && !ctx["Karrera_ID"])  return showToast("Karrera bat hautatu ezinbestekoa da", "err");
  const payload = { profile: type, mapping: getMapping(), rows: csvRows, context: ctx, label: `CSV → ${type}` };
  try {
    const r = await api("/api/csv/import", { method: "POST", body: JSON.stringify(payload) });
    console.log("Import emaitza:", r);
    if (r.errors.length > 0) {
      const sample = r.errors.slice(0,3).map(e => e.reason).join(" | ");
      showToast(`⚠️ ${r.inserted} sartu, ${r.skipped} saltatuta, ${r.errors.length} errore: ${sample}`, "err");
    } else {
      showToast(`✅ ${r.inserted} sartu, ${r.skipped} saltatuta`);
    }
    await reloadData();
    // Inportatu ondoren sailkapenera joan eta txapelketa hautatu
    if (r.inserted > 0 && ctx["Txapelketa_ID"]) {
      setSection("sailkapenak");
      state.sailTab = "txirrindulariak";
      document.querySelectorAll(".tab[data-sltab]").forEach(t => {
        t.classList.toggle("active", t.dataset.sltab === "txirrindulariak");
      });
      const sailSel = el("sail-txap-sel");
      if (sailSel) sailSel.value = ctx["Txapelketa_ID"];
      renderSailkapena();
    }
  } catch(e) { showToast(e.message, "err"); }
}

// ── CSV Fuzzy Check ──────────────────────────────────────────────────────────
// mergeMap: { csv_name -> txirrindularia_id | null }
// null = berri gisa sartu, id = DB-ko txirrindulari horrekin fusionatu
const mergeMap = {};

async function runFuzzyCheck() {
  const type = el("csv-type")?.value || "";
  if (!["txirrindulari_emaitzak", "karrera_txirrindulari_emaitzak"].includes(type)) {
    // Profil honentzat fuzzy check ez da beharrezkoa
    return doCSVImport();
  }
  const ctx = getContext();
  const needsTxap = ["txirrindulari_emaitzak"].includes(type);
  const needsKarrera = ["karrera_txirrindulari_emaitzak"].includes(type);
  if (needsTxap && !ctx["Txapelketa_ID"]) return showToast("Txapelketa bat hautatu ezinbestekoa da", "err");
  if (needsKarrera && !ctx["Karrera_ID"])  return showToast("Karrera bat hautatu ezinbestekoa da", "err");

  const payload = { profile: type, mapping: getMapping(), rows: csvRows, context: ctx };
  try {
    const r = await api("/api/csv/fuzzy-check", { method: "POST", body: JSON.stringify(payload) });
    if (!r.checks || r.checks.length === 0) {
      // Proposamenik ez → zuzenean inportatu
      return doCSVImport();
    }
    renderFuzzyCheckUI(r.checks, type, ctx);
  } catch(e) { showToast(e.message, "err"); }
}

function renderFuzzyCheckUI(checks, type, ctx) {
  // Garbitu mergeMap
  Object.keys(mergeMap).forEach(k => delete mergeMap[k]);

  const wrap = el("csv-preview-result");
  const rows = checks.map(c => {
    const sugs = c.suggestions;
    const nameEsc = esc(c.csv_name);
    const sugOpts = sugs.map(s =>
      `<option value="${s.Txirrindularia_ID}">${esc(s.Izena)} (${s.score}%)</option>`
    ).join("");
    const mergePart = sugs.length ? `
          <label style="display:flex;align-items:center;gap:8px;cursor:pointer;font-size:13px">
            <input type="radio" name="fz-${nameEsc}" value="merge"
              onchange="fuzzyChoice(this.closest('[data-csv]').dataset.csv, 'merge', null)">
            <span>🔀 Fusionatu honekin:</span>
          </label>
          <select id="fzsel-${nameEsc}"
            style="margin-left:22px;background:var(--surface);border:1px solid var(--border);border-radius:6px;padding:5px 8px;color:var(--text);font-size:12px;outline:none"
            onchange="fuzzyChoice(this.closest('[data-csv]').dataset.csv, 'merge', this.value)">
            ${sugOpts}
          </select>` : `<div style="font-size:12px;color:var(--muted);font-style:italic;margin-left:4px">Proposamenik ez — berri gisa sartuko da</div>`;
    return `
    <div data-csv="${nameEsc}" style="padding:12px;border:1px solid var(--border);border-radius:8px;margin-bottom:8px;background:var(--bg)">
      <div style="margin-bottom:8px">
        <span style="font-size:12px;color:var(--muted)">CSV-n:</span>
        <span style="font-size:14px;font-weight:700;color:var(--accent2);margin-left:6px">${nameEsc}</span>
      </div>
      <div style="display:flex;flex-direction:column;gap:6px">
        <label style="display:flex;align-items:center;gap:8px;cursor:pointer;font-size:13px">
          <input type="radio" name="fz-${nameEsc}" value="new" checked
            onchange="fuzzyChoice(this.closest('[data-csv]').dataset.csv, 'new', null)">
          <span>✨ Berri gisa sartu</span>
        </label>
        ${mergePart}
      </div>
    </div>`;
  }).join("");

  wrap.innerHTML = `
    <div class="csv-step-card" style="margin-top:12px">
      <div class="step-label"><span class="step-num">!</span> Txirrindulari antzekoak aurkitu dira</div>
      <p style="font-size:13px;color:var(--muted);margin-bottom:14px">
        Ondorengo txirrindulariak ez dira aurkitu DB-an baina antzeko izenak daude. Bakoitzarentzat erabaki:
      </p>
      <div id="fuzzy-rows">${rows}</div>
      <div style="display:flex;gap:10px;margin-top:14px">
        <button class="btn btn-primary" id="btn-fuzzy-confirm">⬆ Inportatu erabakiekin</button>
        <button class="btn btn-ghost" onclick="el('csv-preview-result').innerHTML=''">Utzi</button>
      </div>
    </div>`;

  // Hasierako egoera: denak "new"
  checks.forEach(c => { mergeMap[c.csv_name] = null; });

  el("btn-fuzzy-confirm")?.addEventListener("click", () => doCSVImportWithMergeMap(type, ctx));
}

function fuzzyChoice(csv_name, mode, sel_val) {
  if (mode === "new") {
    mergeMap[csv_name] = null;
    // Ziurtatu radio "new" markatuta dagoela
    const radio = document.querySelector(`input[name="fz-${esc(csv_name)}"][value="new"]`);
    if (radio) radio.checked = true;
  } else {
    // "merge" modua: select-eko balioa hartu
    const selEl = el("fzsel-" + esc(csv_name));
    const val = sel_val || selEl?.value;
    mergeMap[csv_name] = val ? Number(val) : null;
    // Radio "merge" markatu
    const radio = document.querySelector(`input[name="fz-${esc(csv_name)}"][value="merge"]`);
    if (radio) radio.checked = true;
  }
}

async function doCSVImportWithMergeMap(type, ctx) {
  const payload = {
    profile: type,
    mapping: getMapping(),
    rows: csvRows,
    context: ctx,
    label: `CSV → ${type}`,
    merge_map: mergeMap,
  };
  try {
    const r = await api("/api/csv/import", { method: "POST", body: JSON.stringify(payload) });
    console.log("Import emaitza (merge):", r);
    if (r.errors.length > 0) {
      const sample = r.errors.slice(0,3).map(e => e.reason).join(" | ");
      showToast(`⚠️ ${r.inserted} sartu, ${r.skipped} saltatuta, ${r.errors.length} errore: ${sample}`, "err");
    } else {
      showToast(`✅ ${r.inserted} sartu, ${r.skipped} saltatuta`);
    }
    el("csv-preview-result").innerHTML = "";
    await reloadData();
    if (r.inserted > 0 && ctx["Txapelketa_ID"]) {
      setSection("sailkapenak");
      state.sailTab = "txirrindulariak";
      document.querySelectorAll(".tab[data-sltab]").forEach(t => {
        t.classList.toggle("active", t.dataset.sltab === "txirrindulariak");
      });
      const sailSel = el("sail-txap-sel");
      if (sailSel) sailSel.value = ctx["Txapelketa_ID"];
      renderSailkapena();
    }
  } catch(e) { showToast(e.message, "err"); }
}

// ── Undo / Redo ───────────────────────────────────────────────────────────────
function renderUndoList(st) {
  const list = el("undo-list");
  if (!st || (!st.undo.length && !st.redo.length)) {
    list.innerHTML = `<li style="color:var(--muted);font-size:12px;padding:8px 0">Stack hutsa</li>`; return;
  }
  list.innerHTML = [...st.undo.map((b,i) =>
    `<li class="undo-item ${i===0?"undo-latest":""}">
      <span class="undo-label">↩ ${esc(b.label)} <span class="badge">${b.count}</span></span>
    </li>`
  ), ...st.redo.map(b =>
    `<li class="undo-item" style="opacity:.55">
      <span class="undo-label">↪ ${esc(b.label)} <span class="badge">${b.count}</span></span>
    </li>`
  )].join("");
}

// ── Ezizenak lotu ────────────────────────────────────────────────────────────
async function loadEzizenak() {
  try {
    const data = await api("/api/ezizenak");
    state.ezizenak = data;
    renderEzizenak();
  } catch(e) { showToast(e.message, "err"); }
}

function renderEzizenak() {
  const data = state.ezizenak || [];
  const q      = (el("ezizen-search")?.value || "").toLowerCase();
  const filter = el("ezizen-filter")?.value || "";

  let filtered = data.filter(r => {
    if (q && !(r.Ezizena||"").toLowerCase().includes(q) && !(r.Txapelketa||"").toLowerCase().includes(q)) return false;
    if (filter === "lotu-gabe" && r.Porralaria_ID) return false;
    if (filter === "lotuta"    && !r.Porralaria_ID) return false;
    return true;
  });

  el("ezizen-count").textContent = filtered.length + " ezizen";

  const porrOpts = (state.porralariak || [])
    .map(p => `<option value="${p.Porralaria_ID}">${esc(p.Izena)}</option>`)
    .join("");

  el("ezizen-tbody").innerHTML = filtered.map(r => {
    const lotuBadge = r.Porralaria_ID
      ? `<span style="color:#4ade80;font-weight:600">${esc(r.Porralaria)}</span>`
      : `<span style="color:var(--muted);font-size:12px">Lotu gabe</span>`;
    return `<tr>
      <td style="font-weight:600">${esc(r.Ezizena)}</td>
      <td style="color:var(--muted);font-size:12px">${esc(r.Txapelketa||"")}</td>
      <td>${lotuBadge}</td>
      <td>
        <div style="display:flex;gap:6px;align-items:center">
          <select id="porra-sel-${r.Ezizen_ID}" style="flex:1;background:var(--bg);border:1px solid var(--border);border-radius:6px;padding:5px 8px;color:var(--text);font-size:12px;outline:none">
            <option value="">— Hautatu —</option>
            ${porrOpts}
          </select>
          <button class="btn btn-sm btn-primary" onclick="lotuegin(${r.Ezizen_ID})">Lotu</button>
        </div>
      </td>
    </tr>`;
  }).join("") || `<tr><td colspan="4" style="color:var(--muted);padding:24px;text-align:center">Ez dago emaitzarik</td></tr>`;

  // Jarri aukeratuta jada lotutakoa
  filtered.forEach(r => {
    if (r.Porralaria_ID) {
      const sel = el("porra-sel-" + r.Ezizen_ID);
      if (sel) sel.value = r.Porralaria_ID;
    }
  });
}

async function lotuegin(ezizen_id) {
  const sel = el("porra-sel-" + ezizen_id);
  const porralaria_id = sel?.value;
  if (!porralaria_id) return showToast("Porralaria bat hautatu", "err");
  try {
    await api("/api/ezizen-lotu", {
      method: "POST",
      body: JSON.stringify({ ezizen_id: Number(ezizen_id), porralaria_id: Number(porralaria_id) }),
    });
    showToast("✅ Ezizena lotuta");
    await loadEzizenak();
  } catch(e) { showToast(e.message, "err"); }
}

// ── Merge ─────────────────────────────────────────────────────────────────────
function renderMergeSection() {
  const kind   = el("merge-kind")?.value || "txirrindulariak";
  const search = (el("merge-search")?.value || "").trim().toLowerCase();
  const list   = kind === "txirrindulariak" ? state.txirrindulariak : state.porralariak;
  const idKey  = kind === "txirrindulariak" ? "Txirrindularia_ID" : "Porralaria_ID";

  // Gorde aukeratutako balioak AURRETIK
  const keepSel = el("merge-keep-sel");
  const dropSel = el("merge-drop-sel");
  const prevKeep = keepSel?.value || "";
  const prevDrop = dropSel?.value || "";

  // Filtratu baina hautatutako elementuak beti sartu zerrendan
  const filtered = search ? list.filter(r => (r.Izena||"").toLowerCase().includes(search)) : list;

  // Hautatutakoak baina filtratuan ez daudenak gehitu
  const filteredIds = new Set(filtered.map(r => String(r[idKey])));
  const extras = [];
  if (prevKeep && !filteredIds.has(prevKeep)) {
    const found = list.find(r => String(r[idKey]) === prevKeep);
    if (found) extras.push(found);
  }
  if (prevDrop && !filteredIds.has(prevDrop)) {
    const found = list.find(r => String(r[idKey]) === prevDrop);
    if (found) extras.push(found);
  }

  const finalList = [...filtered, ...extras];

  const makeOpts = sel => `<option value="">— Hautatu —</option>` +
    finalList.map(r => `<option value="${r[idKey]}" ${sel===String(r[idKey])?"selected":""}>${esc(r.Izena)} (ID: ${r[idKey]})</option>`).join("");

  if (keepSel) keepSel.innerHTML = makeOpts(prevKeep);
  if (dropSel) dropSel.innerHTML = makeOpts(prevDrop);
}


async function runMergePreview() {
  const kind    = el("merge-kind")?.value || "txirrindulariak";
  const keep_id = el("merge-keep-sel")?.value;
  const drop_id = el("merge-drop-sel")?.value;
  if (!keep_id || !drop_id)   return showToast("Bi elementuak aukeratu", "err");
  if (keep_id === drop_id)    return showToast("Elementu desberdinak aukeratu", "err");

  const btn = el("btn-merge-preview");
  if (btn) { btn.disabled = true; btn.textContent = "Bilatzen..."; }
  try {
    const r = await api("/api/merge/preview", {
      method: "POST", body: JSON.stringify({ kind, keep_id: Number(keep_id), drop_id: Number(drop_id) }),
    });
    renderMergePreview(r, kind);
  } catch(e) { showToast(e.message, "err"); }
  finally { if (btn) { btn.disabled = false; btn.textContent = "🔍 Aurreikusi fusio"; } }
}

function renderMergePreview(r, kind) {
  const wrap = el("merge-preview-wrap");
  if (!wrap) return;
  if (!r.ok) { wrap.innerHTML = `<div style="color:var(--accent);padding:12px">${esc(r.reason)}</div>`; return; }

  const refsHtml = r.refs?.length
    ? r.refs.map(ref =>
        `<div class="undo-item" style="margin-bottom:6px">
          <span class="undo-label">📋 <strong>${esc(ref.table)}</strong></span>
          <span class="badge">${ref.count} erreferentzia</span>
        </div>`).join("")
    : `<p style="color:var(--muted);font-size:13px">Ez dago erreferentziarik migratzeko</p>`;

  const porraLine = r.zenbat_porra_merged !== undefined
    ? `<p style="margin-top:8px;font-size:13px;color:var(--muted)">🏅 <strong>"Zenbat Porra"</strong> balioa: <strong>${r.zenbat_porra_merged}</strong> izango da</p>`
    : "";

  wrap.innerHTML = `
    <div class="csv-step-card" style="margin-top:14px">
      <div class="step-label"><span class="step-num">✓</span> Fusioaren aurreikuspen</div>
      <div class="merge-box">
        <div>
          <div class="merge-side-label">✅ KEEP — Bizirik</div>
          <div class="merge-name keep">${esc(r.keep.izena)}</div>
          <div style="font-size:12px;color:var(--muted)">ID: ${r.keep.id}</div>
        </div>
        <div style="font-size:24px;color:var(--muted)">←</div>
        <div>
          <div class="merge-side-label">❌ DROP — Ezabatu</div>
          <div class="merge-name drop">${esc(r.dropped.izena)}</div>
          <div style="font-size:12px;color:var(--muted)">ID: ${r.dropped.id}</div>
        </div>
      </div>
      <div style="margin-bottom:12px">
        <div style="font-size:12px;font-weight:600;color:var(--muted);margin-bottom:8px;text-transform:uppercase">Taulen aldaketak</div>
        ${refsHtml}
      </div>
      ${porraLine}
      <div style="margin-top:12px;padding:10px 12px;background:rgba(230,57,70,.08);border:1px solid rgba(230,57,70,.3);border-radius:7px;font-size:12px;color:var(--accent)">
        ⚠️ Eragiketa <strong>itzulezina</strong> da. "${esc(r.dropped.izena)}" behin betiko ezabatuko da.
      </div>
      <div style="margin-top:12px;display:flex;gap:10px">
        <button class="btn btn-primary" id="btn-merge-execute" style="background:var(--accent)">🔀 Fusionatu orain</button>
        <button class="btn btn-ghost" id="btn-merge-cancel">Utzi</button>
      </div>
    </div>`;

  el("btn-merge-execute")?.addEventListener("click", () =>
    doMergeExecute(kind, r.keep.id, r.dropped.id, r.keep.izena, r.dropped.izena));
  el("btn-merge-cancel")?.addEventListener("click", () => { wrap.innerHTML = ""; });
}

async function doMergeExecute(kind, keep_id, drop_id, keep_name, drop_name) {
  const btn = el("btn-merge-execute");
  if (btn) { btn.disabled = true; btn.textContent = "Fusionatzen..."; }
  try {
    const r = await api("/api/merge/execute", {
      method: "POST", body: JSON.stringify({ kind, keep_id, drop_id }),
    });
    if (!r.ok) { showToast(r.reason || "Errore ezezaguna", "err"); return; }
    const migTotal  = (r.log||[]).reduce((s,x) => s + x.migrated, 0);
    const skipTotal = (r.log||[]).reduce((s,x) => s + x.skipped, 0);
    showToast(`✅ Fusio eginda: "${keep_name}" ← "${drop_name}" | ${migTotal} migratuta, ${skipTotal} saltatuta`);
    el("merge-preview-wrap").innerHTML = "";
    el("merge-keep-sel").value = "";
    el("merge-drop-sel").value = "";
    await reloadData();
  } catch(e) {
    showToast(e.message, "err");
    if (btn) { btn.disabled = false; btn.textContent = "🔀 Fusionatu orain"; }
  }
}

// ── Events ────────────────────────────────────────────────────────────────────
function bindDrop() {
  const dz = el("drop-zone");
  dz.addEventListener("click", () => el("csv-file-input").click());
  dz.addEventListener("dragover", e => { e.preventDefault(); dz.classList.add("drag-over"); });
  dz.addEventListener("dragleave", () => dz.classList.remove("drag-over"));
  dz.addEventListener("drop", e => { e.preventDefault(); dz.classList.remove("drag-over"); handleFile(e.dataTransfer.files[0]); });
  el("csv-file-input").addEventListener("change", e => handleFile(e.target.files[0]));
}

function handleFile(file) {
  if (!file) return;
  const reader = new FileReader();
  reader.onload = e => {
    const { headers, rows } = parseCSV(e.target.result);
    csvHeaders = headers; csvRows = rows;
    const dz = el("drop-zone");
    dz.querySelector(".dz-title").textContent = file.name;
    dz.querySelector(".dz-sub").textContent = rows.length + " lerro";
    renderCSVSteps();
  };
  reader.readAsText(file);
}

function bindMergeEvents() {
  el("merge-kind")?.addEventListener("change", () => {
    renderMergeSection();
    el("merge-preview-wrap").innerHTML = "";
  });
  el("merge-search")?.addEventListener("input", renderMergeSection);
  el("btn-merge-preview")?.addEventListener("click", runMergePreview);
}

async function init() {
  bindDrop();
  el("porra-search")?.addEventListener("input", renderPorralariak);
  el("txirri-search")?.addEventListener("input", renderTxirrindulariak);
  el("sail-txap-sel")?.addEventListener("change", renderSailkapena);
  el("sail-search")?.addEventListener("input", renderSailkapena);
  el("generic-table-search")?.addEventListener("input", renderGenericTable);
  el("dash-txap-sel")?.addEventListener("change", e => renderDashRanking(e.target.value));
  el("csv-type")?.addEventListener("change", renderCSVSteps);
  el("ezizen-search")?.addEventListener("input", renderEzizenak);
  el("ezizen-filter")?.addEventListener("change", renderEzizenak);

  document.querySelectorAll(".tab[data-sltab]").forEach(t => {
    t.addEventListener("click", () => {
      document.querySelectorAll(".tab[data-sltab]").forEach(x => x.classList.remove("active"));
      t.classList.add("active"); state.sailTab = t.dataset.sltab; renderSailkapena();
    });
  });

  el("m-txap-btn")?.addEventListener("click", () => manualAdd({
    table:"Txapelketak", data:{Izena: el("m-txap-izena").value, Urtea: Number(el("m-txap-urtea").value)}
  }));
  el("m-porra-btn")?.addEventListener("click", () => manualAdd({
    table:"Porralariak", data:{Izena: el("m-porra-izena").value}
  }));
  el("m-txirri-btn")?.addEventListener("click", () => manualAdd({
    table:"Txirrindulariak", data:{Izena: el("m-txirri-izena").value}
  }));
  el("m-karrera-btn")?.addEventListener("click", () => manualAdd({
    table:"Karrerak", data:{
      Txapelketa_ID: Number(el("m-karrera-txap").value),
      Izena: el("m-karrera-izena").value, Urtea: Number(el("m-karrera-urtea").value)
    }
  }));

  el("btn-undo")?.addEventListener("click", async () => {
    try { const r = await api("/api/undo",{method:"POST"}); showToast(r.ok ? `↩ Desegin: ${r.label}` : r.reason, r.ok?"ok":"err"); await reloadData(); } catch(e){showToast(e.message,"err");}
  });
  el("btn-redo")?.addEventListener("click", async () => {
    try { const r = await api("/api/redo",{method:"POST"}); showToast(r.ok ? `↪ Berregin: ${r.label}` : r.reason, r.ok?"ok":"err"); await reloadData(); } catch(e){showToast(e.message,"err");}
  });

  bindMergeEvents();
  await buildTableNav();
  await reloadData();
}

init();
</script>
</body>
</html>"""

# ─── HTTP Handler ──────────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def send_json(self, data, code=200):
        body = json.dumps(data, ensure_ascii=False, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_error_json(self, msg, code=400):
        self.send_json({"error": msg}, code)

    def do_GET(self):
        parsed = urlparse(self.path)
        path   = unquote(parsed.path).rstrip("/") or "/"

        if path in ("/", "/index.html"):
            body = APP_HTML.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        with get_db() as con:
            if path == "/api/porralariak":
                return self.send_json(rows(con,
                    'SELECT p.Porralaria_ID, p.Izena, COUNT(ep.Ezizen_ID) AS "Zenbat Porra" '
                    'FROM "Porralariak" p LEFT JOIN "EzizenPorralariak" ep ON p.Porralaria_ID = ep.Porralaria_ID '
                    'GROUP BY p.Porralaria_ID ORDER BY p.Izena'))
            if path == "/api/txirrindulariak":
                return self.send_json(rows(con, 'SELECT * FROM "Txirrindulariak" ORDER BY Izena'))
            if path == "/api/txapelketak":
                return self.send_json(rows(con, 'SELECT * FROM "Txapelketak" ORDER BY Urtea DESC, Izena'))
            if path == "/api/karrerak":
                return self.send_json(rows(con, 'SELECT * FROM "Karrerak" ORDER BY Urtea DESC, Izena'))
            if path == "/api/txirrindulari-emaitzak":
                return self.send_json(rows(con,
                    'SELECT e.*, t.Izena AS Txirrindularia FROM "TxapelketaEmaitzaTxirrindulariak" e '
                    'JOIN "Txirrindulariak" t ON e.Txirrindularia_ID = t.Txirrindularia_ID ORDER BY e.Txapelketa_ID, e.Posizioa'))
            if path == "/api/porralari-emaitzak":
                return self.send_json(rows(con,
                    'SELECT e.*, ez.Ezizena, p.Izena AS Porralaria FROM "TxapelketaEmaitzaPorralariak" e '
                    'JOIN "PorralariEzizenak" ez ON e.Ezizen_ID = ez.Ezizen_ID '
                    'LEFT JOIN "EzizenPorralariak" ep ON ez.Ezizen_ID = ep.Ezizen_ID '
                    'LEFT JOIN "Porralariak" p ON ep.Porralaria_ID = p.Porralaria_ID '
                    'ORDER BY e.Txapelketa_ID, e.Posizioa'))
            if path == "/api/karrera-sailkapena":
                return self.send_json(rows(con,
                    'SELECT ks.*, t.Izena AS Txirrindularia FROM "KarreraSailkapena" ks '
                    'JOIN "Txirrindulariak" t ON ks.Txirrindularia_ID = t.Txirrindularia_ID ORDER BY ks.Karrera_ID, ks.Puntuak DESC'))
            if path == "/api/ezizenak":
                return self.send_json(rows(con,
                    'SELECT ez.Ezizen_ID, ez.Ezizena, ez.Txapelketa_ID, '
                    't.Izena AS Txapelketa, ep.Porralaria_ID, p.Izena AS Porralaria '
                    'FROM "PorralariEzizenak" ez '
                    'LEFT JOIN "Txapelketak" t ON ez.Txapelketa_ID = t.Txapelketa_ID '
                    'LEFT JOIN "EzizenPorralariak" ep ON ez.Ezizen_ID = ep.Ezizen_ID '
                    'LEFT JOIN "Porralariak" p ON ep.Porralaria_ID = p.Porralaria_ID '
                    'ORDER BY t.Urtea DESC, ez.Ezizena'))
            if path == "/api/meta":
                return self.send_json(db_meta())
            if path == "/api/undo-state":
                return self.send_json(undo_stack_state())
            if path.startswith("/api/table/"):
                table_name = unquote(path[len("/api/table/"):])
                try:
                    return self.send_json(read_table(table_name))
                except ValueError as e:
                    return self.send_error_json(str(e), 404)

        self.send_error_json("Not found", 404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path   = unquote(parsed.path).rstrip("/")
        length = int(self.headers.get("Content-Length", 0))
        body   = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(body)
        except Exception:
            return self.send_error_json("JSON baliogabea", 400)

        if path == "/api/insert":
            table = data.get("table", "")
            vals  = data.get("data", {})
            if not table or not vals:
                return self.send_error_json("table eta data behar dira")
            try:
                with get_db() as con:
                    cols  = list(vals.keys())
                    marks = ["?"] * len(cols)
                    cur   = con.execute(
                        f'INSERT INTO "{table}" ({", ".join(f"{chr(34)}{c}{chr(34)}" for c in cols)}) VALUES ({", ".join(marks)})',
                        list(vals.values())
                    )
                    con.commit()
                return self.send_json({"ok": True, "id": cur.lastrowid})
            except Exception as e:
                return self.send_error_json(str(e))

        elif path == "/api/csv/fuzzy-check":
            return self.send_json(csv_fuzzy_check(data))

        elif path == "/api/csv/preview":
            return self.send_json(csv_preview(data))

        elif path == "/api/csv/import":
            return self.send_json(csv_import(data))

        elif path == "/api/undo":
            return self.send_json(do_undo())

        elif path == "/api/redo":
            return self.send_json(do_redo())

        elif path == "/api/ezizen-lotu":
            # Ezizen bat porralari bati lotu EzizenPorralariak taulan
            ezizen_id  = data.get("ezizen_id")
            porralaria_id = data.get("porralaria_id")
            if not ezizen_id or not porralaria_id:
                return self.send_error_json("ezizen_id eta porralaria_id behar dira")
            try:
                with get_db() as con:
                    # Begiratu jada ba ote dagoen
                    existing = con.execute(
                        'SELECT * FROM "EzizenPorralariak" WHERE Ezizen_ID = ?', [ezizen_id]
                    ).fetchone()
                    if existing:
                        con.execute(
                            'UPDATE "EzizenPorralariak" SET Porralaria_ID = ? WHERE Ezizen_ID = ?',
                            [porralaria_id, ezizen_id]
                        )
                    else:
                        con.execute(
                            'INSERT INTO "EzizenPorralariak" (Ezizen_ID, Porralaria_ID) VALUES (?, ?)',
                            [ezizen_id, porralaria_id]
                        )
                    con.commit()
                return self.send_json({"ok": True})
            except Exception as e:
                return self.send_error_json(str(e))

        elif path == "/api/merge/preview":
            kind    = data.get("kind", "")
            keep_id = data.get("keep_id")
            drop_id = data.get("drop_id")
            if not kind or keep_id is None or drop_id is None:
                return self.send_error_json("kind, keep_id eta drop_id behar dira")
            return self.send_json(merge_preview(kind, int(keep_id), int(drop_id)))

        elif path == "/api/merge/execute":
            kind    = data.get("kind", "")
            keep_id = data.get("keep_id")
            drop_id = data.get("drop_id")
            if not kind or keep_id is None or drop_id is None:
                return self.send_error_json("kind, keep_id eta drop_id behar dira")
            if kind == "txirrindulariak":
                return self.send_json(merge_txirrindulariak(int(keep_id), int(drop_id)))
            elif kind == "porralariak":
                return self.send_json(merge_porralariak(int(keep_id), int(drop_id)))
            else:
                return self.send_error_json(f"Mota ezezaguna: {kind}")

        else:
            self.send_error_json("Not found", 404)

    def do_PUT(self):
        parsed = urlparse(self.path)
        path   = unquote(parsed.path).rstrip("/")
        length = int(self.headers.get("Content-Length", 0))
        body   = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(body)
        except Exception:
            return self.send_error_json("JSON baliogabea", 400)

        if path.startswith("/api/table/"):
            table_name = unquote(path[len("/api/table/"):])
            try:
                return self.send_json(update_table_row(table_name, data))
            except ValueError as e:
                return self.send_error_json(str(e))

        self.send_error_json("Not found", 404)


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"http://localhost:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
