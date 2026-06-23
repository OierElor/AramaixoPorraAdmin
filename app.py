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
from urllib.parse import unquote, urlparse, parse_qs

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
        "fields": ["Posizioa", "Txirrindularia", "Puntuak", "Puntuak_Sailkapen_Nag", "Puntuak_Mendian", "Zenbatek"],
        "context_fields": ["Txapelketa_ID"],
        "required": ["Txapelketa_ID", "Posizioa", "Txirrindularia"],
        "identity": ["Txapelketa_ID", "Txirrindularia_ID"],
    },
    "porralari_emaitzak": {
        "label": "Porralari emaitzak (txapelketa)",
        "target": "TxapelketaEmaitzaPorralariak",
        "fields": ["Posizioa", "Ezizena", "Puntuak", "Puntuak_Mendikoa", "Puntuak_Generala"],
        "context_fields": ["Txapelketa_ID"],
        "required": ["Txapelketa_ID", "Posizioa", "Ezizena", "Puntuak"],
        "identity": ["Txapelketa_ID", "Ezizen_ID"],
    },
    "karrera_txirrindulari_emaitzak": {
        "label": "Txirrindulari emaitzak (karrera)",
        "target": "KarreraSailkapena",
        "fields": ["Sailkapena", "Txirrindularia", "Puntuak"],
        "context_fields": ["Karrera_ID"],
        "required": ["Karrera_ID", "Txirrindularia", "Puntuak", "Sailkapena"],
        "identity": ["Karrera_ID", "Txirrindularia_ID"],
    },
}

FIELD_ALIASES = {
    "Txapelketa_ID": ["Txapelketa_ID", "Txapelketa", "Competition", "Competition_ID"],
    "Karrera_ID": ["Karrera_ID", "Karrerak_ID", "Karrera", "Lasterketa", "Race", "Race_ID"],
    "Karrerak_ID": ["Karrerak_ID", "Karrera_ID"],
    "Ezizena": ["Ezizena", "Porreroa", "Porrero", "Porralaria", "Porralari", "Nickname", "Taldea"],
    "Txirrindularia": ["Txirrindularia", "Txirrindulari", "Izena", "Rider", "Cyclist", "Name", "Nombre"],
    "Porralaria": ["Porralaria", "Porreroa", "Porrero", "Ezizena", "Porralari"],
    # .ods-etan karreren blokeak "Sailkapena", grand tourretan "Posizioa" edo "Aukeratze Sailkapena"
    "Sailkapena": ["Sailkapena", "Posizioa", "Sailkapen", "Postua", "Aukeratze Sailkapena", "Rank", "Pos", "Position", "#"],
    "Posizioa": ["Posizioa", "Sailkapena", "Sailkapen", "Postua", "Aukeratze Sailkapena", "Rank", "Pos", "Position", "#"],
    "Puntuak": ["Puntuak", "Guztira", "Puntu", "Points", "Pts", "Ptos"],
    "Urtea": ["Urtea", "Year", "Año"],
    "Izena": ["Izena", "Name", "Title", "Nombre", "Helmuga"],
    "Dortsala": ["Dortsala", "Dorsala", "Dorsalak", "Zbkia", "Zenbakia", "Bib", "Dorsal", "Dors"],
    "Puntuak_Sailkapen_Nag": ["Puntuak_Sailkapen_Nag", "Puntuak_SailkapenNag", "Sailkapen_Nagusia", "SailkapenNagusia", "Sailkapen Nagusia", "Nagusia", "Orokorra", "orokorra", "GC", "General"],
    "Puntuak_Mendian": ["Puntuak_Mendian", "Mendian", "Mendia", "Mendi", "Mountain", "KOM"],
    "Zenbatek": ["Zenbatek", "Zenbatek?", "Zenbatek Daukate?", "Zenbat", "Count", "Kopurua", "Aukeratu"],
    "Puntuak_Mendikoa": ["Puntuak_Mendikoa", "Mendikoa", "Mendian", "Mendia", "Mendi", "Mountain", "KOM"],
    "Puntuak_Generala": ["Puntuak_Generala", "Generala", "Orokorra", "orokorra", "General", "GC", "Sailkapen Nagusia", "Nagusia"],
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
    # DB-a jada badago (Txapelketak taula du), EZ exekutatu schema.sql:
    # schema.sql zaharkituta dago eta itzal-taula hutsak sor litzake.
    con = get_db()
    try:
        if con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='Txapelketak'"
        ).fetchone():
            return
    finally:
        con.close()
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
    # Bigarren pasada: partzial match — aliasa zutabe-izenaren AZPIKATE bada soilik.
    # (EZ alderantziz: bestela "Puntuak" zutabeak "Puntuak_Mendikoa" eremua faltsuki beteko luke.)
    for wanted in names:
        w = wanted.strip().lower()
        if len(w) < 3:
            continue
        for key, value in raw.items():
            k = str(key).strip().lower()
            if w in k:
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



import unicodedata as _ud
import re as _re

def _strip_country(name: str) -> str:
    n = _re.sub(r"[\(\[].*?[\)\]]", "", name).strip()
    return _re.sub(r"\s+", " ", n).strip()

def _normalize_name(name: str) -> str:
    n = _strip_country(name)
    n = _re.sub(r"[-\'.,]", " ", n)
    n = _ud.normalize("NFD", n.lower())
    n = "".join(c for c in n if _ud.category(c) != "Mn")
    return _re.sub(r"\s+", " ", n).strip()

def _name_tokens(name: str) -> frozenset:
    return frozenset(t for t in _normalize_name(name).split() if len(t) > 1)

def _fuzzy_name_score(a: str, b: str) -> int:
    na, nb = _normalize_name(a), _normalize_name(b)
    if not na or not nb:
        return 0
    if na == nb:
        return 100
    ta, tb = _name_tokens(a), _name_tokens(b)
    if ta and tb and ta == tb:
        return 98
    if ta and tb:
        inter = ta & tb
        if inter and (inter == ta or inter == tb):
            return max(88, int(len(inter) / max(len(ta), len(tb)) * 95))
        if inter:
            jaccard = len(inter) / len(ta | tb)
            if jaccard >= 0.5:
                return max(75, int(jaccard * 95))
    def bigrams(s):
        return set(s[i:i+2] for i in range(len(s) - 1))
    ba, bb = bigrams(na), bigrams(nb)
    denom = len(ba) + len(bb)
    if denom == 0:
        return 0
    return int(2 * len(ba & bb) / denom * 100)

def _find_fuzzy_matches(con, name: str, threshold: int = 50) -> list:
    clean = _strip_country(name)
    all_riders = con.execute(
        'SELECT Txirrindularia_ID, Izena FROM "Txirrindulariak" ORDER BY Izena'
    ).fetchall()
    matches = []
    for row in all_riders:
        score = _fuzzy_name_score(clean, row["Izena"])
        if score >= threshold:
            matches.append({"Txirrindularia_ID": row["Txirrindularia_ID"], "Izena": row["Izena"], "score": score})
    matches.sort(key=lambda x: -x["score"])
    return matches[:8]
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
    CSV-ko txirrindulari GUZTIAK itzuli, bai detektatuak bai ez:
      - matched_id:   DB-n aurkitu den ID (normalizazioarekin)
      - matched_name: DB-n aurkitutako izena
      - suggestions:  fuzzy antzekoak (detektatu ez bada)
    Horrela frontend-ean erabiltzaileak erabaki dezake bakoitzarentzat.
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
                # Aurkitu da — erakutsi detektatuta, baina aukera eman aldatzeko
                matched_row = con.execute(
                    'SELECT Izena FROM "Txirrindulariak" WHERE Txirrindularia_ID = ?', [exact_id]
                ).fetchone()
                matched_name = matched_row["Izena"] if matched_row else csv_name
                results.append({
                    "csv_name": csv_name,
                    "matched_id": int(exact_id),
                    "matched_name": matched_name,
                    "suggestions": _find_fuzzy_matches(con, _strip_country(csv_name), threshold=40),
                })
            else:
                # Ez da aurkitu — proposamenak eman
                clean_name = _strip_country(csv_name)
                suggestions = _find_fuzzy_matches(con, clean_name, threshold=40)
                results.append({
                    "csv_name": csv_name,
                    "matched_id": None,
                    "matched_name": None,
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
        'SELECT Ezizen_ID FROM "PorraEzizenak" WHERE Txapelketa_ID = ? AND Ezizena = ?',
        [txapelketa_id, ezizena],
    ).fetchone()
    return row[0] if row else None

def _ensure_ezizen_id(con, txapelketa_id: int, ezizena: str) -> int:
    eid = _find_ezizen_id(con, txapelketa_id, ezizena)
    if eid is not None:
        return int(eid)
    cur = con.execute(
        'INSERT INTO "PorraEzizenak" (Txapelketa_ID, Ezizena) VALUES (?, ?)',
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
            puntuak = 0
        norm = {"Txapelketa_ID": txap_id, "Posizioa": posizioa, "Txirrindularia": txirr_name, "Puntuak": puntuak}
        dortsala = get("Dortsala")
        if dortsala not in (None, ""):
            norm["Dortsala"] = _to_int(dortsala)
        pun_nag = _to_int(get("Puntuak_Sailkapen_Nag"))
        if pun_nag is not None:
            norm["Puntuak_Sailkapen_Nag"] = pun_nag
        pun_men = _to_int(get("Puntuak_Mendian"))
        if pun_men is not None:
            norm["Puntuak_Mendian"] = pun_men
        zenbatek = _to_int(get("Zenbatek"))
        if zenbatek is not None:
            norm["Zenbatek"] = zenbatek
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
        for opt_field in ("Puntuak_Mendikoa", "Puntuak_Generala"):
            val = _to_int(get(opt_field))
            if val is not None:
                norm[opt_field] = val
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
        sailkapena = _to_int(get("Sailkapena"))
        if karrera_id is None or not txirr_name or puntuak is None or sailkapena is None:
            return None
        norm = {"Karrera_ID": karrera_id, "Txirrindularia": txirr_name, "Puntuak": puntuak, "Sailkapena": sailkapena}
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
        cols   = ["Txapelketa_ID", "Txirrindularia_ID", "Posizioa", "Puntuak"]
        vals   = [norm["Txapelketa_ID"], int(rider_id), norm["Posizioa"], norm["Puntuak"]]
        DB_COL_MAP = {"Zenbatek": "Zenbatek?"}
        for opt in ("Puntuak_Sailkapen_Nag", "Puntuak_Mendian", "Zenbatek"):
            if opt in norm and norm[opt] is not None:
                cols.append(DB_COL_MAP.get(opt, opt))
                vals.append(norm[opt])
        placeholders = ", ".join("?" * len(cols))
        col_names    = ", ".join(f'"{c}"' for c in cols)
        con.execute(f'INSERT INTO "TxapelketaEmaitzaTxirrindulariak" ({col_names}) VALUES ({placeholders})', vals)
        return {"Txapelketa_ID": norm["Txapelketa_ID"], "Txirrindularia_ID": int(rider_id)}
    if profile_id == "porralari_emaitzak":
        ezizen_id = norm.get("Ezizen_ID") or _ensure_ezizen_id(con, norm["Txapelketa_ID"], norm["Ezizena"])
        cols = ["Txapelketa_ID", "Ezizen_ID", "Posizioa", "Puntuak"]
        vals = [norm["Txapelketa_ID"], int(ezizen_id), norm["Posizioa"], norm["Puntuak"]]
        for opt in ("Puntuak_Mendikoa", "Puntuak_Generala"):
            if opt in norm and norm[opt] is not None:
                cols.append(opt)
                vals.append(norm[opt])
        placeholders = ", ".join("?" * len(cols))
        col_names = ", ".join(f'"{c}"' for c in cols)
        con.execute(f'INSERT INTO "TxapelketaEmaitzaPorralariak" ({col_names}) VALUES ({placeholders})', vals)
        return {"Txapelketa_ID": norm["Txapelketa_ID"], "Ezizen_ID": int(ezizen_id)}
    if profile_id == "karrera_txirrindulari_emaitzak":
        rider_id = norm.get("Txirrindularia_ID") or _ensure_txirrindularia_id(con, norm["Txirrindularia"])
        con.execute('INSERT INTO "KarreraSailkapena" (Karrera_ID, Txirrindularia_ID, Puntuak, Sailkapena) VALUES (?, ?, ?, ?)',
            [norm["Karrera_ID"], int(rider_id), norm["Puntuak"], norm["Sailkapena"]])
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
    profile        = payload.get("profile") or payload.get("table", "")
    mapping        = payload.get("mapping", {})
    raw            = payload.get("rows", [])
    context        = payload.get("context", {})
    label          = payload.get("label", f"CSV → {profile}")
    # merge_map: {csv_name: txirrindularia_id} - erabiltzaileak erabakitako fusio-map
    merge_map: dict = payload.get("merge_map", {})
    # update_fields: zerrenda, jada dauden erregistroetan eguneratu beharreko zutabeak
    # Adib: ["Zenbatek"] -> erregistroa badago, "Zenbatek?" zutabea eguneratu
    update_fields: list = payload.get("update_fields", [])
    spec = _profile_spec(profile)
    if not spec:
        return {"inserted": 0, "skipped": 0, "errors": [{"row": {}, "reason": f"CSV profila ezezaguna: {profile}"}], "batch_id": len(_undo_stack)}
    inserted_identities = []
    inserted_rows = []
    skipped = 0
    errors = []
    with get_db() as con:
        for raw_row in raw:
            # create_missing=False: ez sortu txirrindularirik oraindik, merge_map aplikatu aurretik
            norm = _normalize_row(profile, mapping, raw_row, context, con, create_missing=False)
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
                if update_fields and profile == "txirrindulari_emaitzak":
                    # Eguneratu zehaztu diren zutabeak
                    rider_id = norm.get("Txirrindularia_ID")
                    if rider_id:
                        DB_COL_MAP = {"Zenbatek": "Zenbatek?"}
                        set_parts, set_vals = [], []
                        for f in update_fields:
                            db_col = DB_COL_MAP.get(f, f)
                            if f in norm and norm[f] is not None:
                                set_parts.append(f'"{db_col}" = ?')
                                set_vals.append(norm[f])
                        if set_parts:
                            set_sql = ", ".join(set_parts)
                            con.execute(
                                f'UPDATE "TxapelketaEmaitzaTxirrindulariak" SET {set_sql} '                                f'WHERE Txapelketa_ID = ? AND Txirrindularia_ID = ?',
                                set_vals + [norm["Txapelketa_ID"], int(rider_id)]
                            )
                            inserted_identities.append({"Txapelketa_ID": norm["Txapelketa_ID"], "Txirrindularia_ID": int(rider_id)})
                            inserted_rows.append(norm)
                            continue
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
    ("PorralariTaldeenEzizenak", "Porralaria_ID", ["Ezizen_ID", "Porralaria_ID"]),
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

def api_ezizenak(con):
    """Ezizen guztiak, bakoitzari lotutako porralarien zerrendarekin (anitz izan daiteke)."""
    ez_rows = rows(con,
        'SELECT ez.Ezizen_ID, ez.Ezizena, ez.Txapelketa_ID, t.Izena AS Txapelketa, t.Urtea AS Urtea '
        'FROM "PorraEzizenak" ez '
        'LEFT JOIN "Txapelketak" t ON ez.Txapelketa_ID = t.Txapelketa_ID '
        'ORDER BY t.Urtea DESC, ez.Ezizena')
    link_rows = rows(con,
        'SELECT ep.Ezizen_ID, p.Porralaria_ID, p.Izena '
        'FROM "PorralariTaldeenEzizenak" ep '
        'JOIN "Porralariak" p ON ep.Porralaria_ID = p.Porralaria_ID '
        'ORDER BY p.Izena')
    by_ezizen = {}
    for lr in link_rows:
        by_ezizen.setdefault(lr["Ezizen_ID"], []).append(
            {"Porralaria_ID": lr["Porralaria_ID"], "Izena": lr["Izena"]})
    for r in ez_rows:
        pl = by_ezizen.get(r["Ezizen_ID"], [])
        r["Porralariak"] = pl
        # Atzera-bateragarritasuna: lehen porralaria + izen bateratua
        r["Porralaria_ID"] = pl[0]["Porralaria_ID"] if pl else None
        r["Porralaria"] = ", ".join(x["Izena"] for x in pl) if pl else None
    return ez_rows

def _recompute_zenbat_porra(con, porralaria_ids):
    """Emandako porralarien 'Zenbat Porra' lotura-kopurutik eguneratu."""
    for pid in set(p for p in porralaria_ids if p):
        n = con.execute(
            'SELECT COUNT(*) FROM "PorralariTaldeenEzizenak" WHERE Porralaria_ID = ?', [pid]
        ).fetchone()[0]
        con.execute('UPDATE "Porralariak" SET "Zenbat Porra" = ? WHERE Porralaria_ID = ?',
                    [max(n, 1), pid])

def _porralaria_ezizenak(con, porralaria_id):
    """Porralari batek lotuta dituen ezizenak (txapelketarekin)."""
    return rows(con,
        'SELECT ez.Ezizen_ID, ez.Ezizena, ez.Txapelketa_ID, t.Izena AS Txapelketa '
        'FROM "PorralariTaldeenEzizenak" ep '
        'JOIN "PorraEzizenak" ez ON ep.Ezizen_ID = ez.Ezizen_ID '
        'LEFT JOIN "Txapelketak" t ON ez.Txapelketa_ID = t.Txapelketa_ID '
        'WHERE ep.Porralaria_ID = ? ORDER BY t.Urtea DESC, ez.Ezizena',
        [porralaria_id])

def _get_or_create_porralaria(con, izena):
    izena = (izena or "").strip()
    if not izena:
        return None
    row = con.execute('SELECT Porralaria_ID FROM "Porralariak" WHERE Izena = ?', [izena]).fetchone()
    if row:
        return row[0]
    cur = con.execute('INSERT INTO "Porralariak" (Izena, "Zenbat Porra") VALUES (?, 1)', [izena])
    return cur.lastrowid

def ezizen_lotu(data):
    """Ezizen bati porralari multzo bat esleitu (lehengoa ordezkatuz).
    data: { ezizen_id, porralaria_ids?:[...], porralaria_id?, new_porralariak?:[izenak] }"""
    ezizen_id = data.get("ezizen_id")
    if not ezizen_id:
        return {"ok": False, "reason": "ezizen_id behar da"}
    ids = list(data.get("porralaria_ids") or [])
    if data.get("porralaria_id"):
        ids.append(data["porralaria_id"])
    has_set = ("porralaria_ids" in data) or ("porralaria_id" in data) or bool(data.get("new_porralariak"))
    if not has_set:
        return {"ok": False, "reason": "porralaria_ids edo new_porralariak behar dira"}
    try:
        with get_db() as con:
            ez = con.execute('SELECT Ezizen_ID FROM "PorraEzizenak" WHERE Ezizen_ID = ?', [ezizen_id]).fetchone()
            if not ez:
                return {"ok": False, "reason": f"Ezizen_ID {ezizen_id} ez da existitzen"}
            # Izen berriak sortu
            for izena in (data.get("new_porralariak") or []):
                pid = _get_or_create_porralaria(con, izena)
                if pid:
                    ids.append(pid)
            target = []
            for x in ids:
                xi = int(x)
                if xi not in target:
                    target.append(xi)
            # Porralariak existitzen direla egiaztatu (mezu argia emateko)
            for pid in target:
                if not con.execute('SELECT 1 FROM "Porralariak" WHERE Porralaria_ID = ?', [pid]).fetchone():
                    return {"ok": False, "reason": f"Porralaria_ID {pid} ez da existitzen"}
            # Lehengo loturak (Zenbat Porra birkalkulatzeko)
            prev = [r[0] for r in con.execute(
                'SELECT Porralaria_ID FROM "PorralariTaldeenEzizenak" WHERE Ezizen_ID = ?', [ezizen_id]).fetchall()]
            con.execute('DELETE FROM "PorralariTaldeenEzizenak" WHERE Ezizen_ID = ?', [ezizen_id])
            for pid in target:
                con.execute('INSERT OR IGNORE INTO "PorralariTaldeenEzizenak" (Ezizen_ID, Porralaria_ID) VALUES (?, ?)',
                            [ezizen_id, pid])
            _recompute_zenbat_porra(con, set(prev) | set(target))
            con.commit()
            porralariak = rows(con,
                'SELECT p.Porralaria_ID, p.Izena FROM "PorralariTaldeenEzizenak" ep '
                'JOIN "Porralariak" p ON ep.Porralaria_ID = p.Porralaria_ID '
                'WHERE ep.Ezizen_ID = ? ORDER BY p.Izena', [ezizen_id])
        return {"ok": True, "ezizen_id": ezizen_id, "porralariak": porralariak}
    except Exception as e:
        return {"ok": False, "reason": str(e)}

def porralari_split(data):
    """Porralari bat banatu: aukeratutako ezizenak beste porralari bati esleitu.
    data: { source_id, ezizen_ids:[...], target_id? , new_izena? }
    target: lehendik dagoena (target_id) edo berria (new_izena)."""
    source_id = data.get("source_id")
    ezizen_ids = [int(x) for x in (data.get("ezizen_ids") or [])]
    target_id = data.get("target_id")
    new_izena = (data.get("new_izena") or "").strip()
    if not source_id:
        return {"ok": False, "reason": "source_id behar da"}
    if not ezizen_ids:
        return {"ok": False, "reason": "Gutxienez ezizen bat aukeratu behar da"}
    if not target_id and not new_izena:
        return {"ok": False, "reason": "Helburu porralaria (lehendik edo berria) behar da"}
    try:
        with get_db() as con:
            src = con.execute('SELECT Izena FROM "Porralariak" WHERE Porralaria_ID = ?', [source_id]).fetchone()
            if not src:
                return {"ok": False, "reason": f"Porralaria {source_id} ez da existitzen"}
            if target_id:
                target_id = int(target_id)
                tgt = con.execute('SELECT Izena FROM "Porralariak" WHERE Porralaria_ID = ?', [target_id]).fetchone()
                if not tgt:
                    return {"ok": False, "reason": f"Helburu porralaria {target_id} ez da existitzen"}
                if target_id == int(source_id):
                    return {"ok": False, "reason": "Iturria eta helburua ezin dira berdinak izan"}
            else:
                target_id = _get_or_create_porralaria(con, new_izena)
            moved = 0
            for eid in ezizen_ids:
                # Ezizena benetan iturriarena dela egiaztatu
                link = con.execute(
                    'SELECT 1 FROM "PorralariTaldeenEzizenak" WHERE Ezizen_ID = ? AND Porralaria_ID = ?',
                    [eid, source_id]).fetchone()
                if not link:
                    continue
                con.execute('DELETE FROM "PorralariTaldeenEzizenak" WHERE Ezizen_ID = ? AND Porralaria_ID = ?',
                            [eid, source_id])
                con.execute('INSERT OR IGNORE INTO "PorralariTaldeenEzizenak" (Ezizen_ID, Porralaria_ID) VALUES (?, ?)',
                            [eid, target_id])
                moved += 1
            _recompute_zenbat_porra(con, {int(source_id), int(target_id)})
            con.commit()
            tgt_izena = con.execute('SELECT Izena FROM "Porralariak" WHERE Porralaria_ID = ?', [target_id]).fetchone()[0]
        return {"ok": True, "source_id": int(source_id), "target_id": int(target_id),
                "target_izena": tgt_izena, "moved": moved}
    except Exception as e:
        return {"ok": False, "reason": str(e)}

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
            # Porralari bakoitzaren ezizenak erakutsi, zer fusionatzen den ikusteko
            result["keep"]["ezizenak"] = _porralaria_ezizenak(con, keep_id)
            result["dropped"]["ezizenak"] = _porralaria_ezizenak(con, drop_id)
        return result


# ─── HTML ────────────────────────────────────────────────────────────────────

# ─── Izen ordena tresna ──────────────────────────────────────────────────────

def _proposatu_ordena(izena: str) -> str:
    """
    Saiatu abizena-izena formatutik izena-abizena formatua proposatzen.
    Heuristika: lehen hitza guztiz maiuskulaz badago, abizena da.
    Adib: "ROGLIC Primož" -> "Primož Roglic"
          "Tadej Pogacar" -> aldaketarik ez (jada ondo)
          "POGACAR Tadej" -> "Tadej Pogacar"
    """
    import re
    parts = izena.strip().split()
    if len(parts) < 2:
        return izena
    # Lehen hitza guztiz maiuskulaz? (eta ez laburdura)
    if parts[0] == parts[0].upper() and len(parts[0]) > 2:
        # Abizena-Izena -> Izena Abizena
        return " ".join(parts[1:] + [parts[0].title()])
    return izena  # Jada ondo edo ezin jakin

def get_izen_ordenak() -> list:
    """Txirrindulari guztiak + proposamen ordena."""
    with get_db() as con:
        rows_list = con.execute(
            'SELECT Txirrindularia_ID, Izena FROM "Txirrindulariak" ORDER BY Izena'
        ).fetchall()
    result = []
    for row in rows_list:
        izena = row["Izena"]
        proposamena = _proposatu_ordena(izena)
        result.append({
            "Txirrindularia_ID": row["Txirrindularia_ID"],
            "Izena": izena,
            "Proposamena": proposamena,
            "Aldatu": proposamena != izena,
        })
    return result

def apply_izen_ordenak(aldaketak: list) -> dict:
    """
    aldaketak: [{"Txirrindularia_ID": 1, "Izena_Berria": "Primož Roglic"}, ...]
    """
    aldatuta = 0
    with get_db() as con:
        for item in aldaketak:
            tid  = item.get("Txirrindularia_ID")
            izena = item.get("Izena_Berria", "").strip()
            if not tid or not izena:
                continue
            con.execute(
                'UPDATE "Txirrindulariak" SET Izena = ? WHERE Txirrindularia_ID = ?',
                [izena, tid]
            )
            aldatuta += 1
        con.commit()
    return {"ok": True, "aldatuta": aldatuta}

# ─── Zenbat porra kalkulatu ───────────────────────────────────────────────────

def recalculate_zenbat_porra() -> dict:
    """
    Porralari bakoitzak zenbat txapelketatan parte hartu duen kalkulatu
    PorralariTaldeenEzizenak taulatik, eta Porralariak."Zenbat Porra" eguneratu.
    """
    with get_db() as con:
        # Porralari bakoitzarentzat zenbat ezizen (= txapelketa) dituen zenbatu
        counts = con.execute('''
            SELECT ep.Porralaria_ID, COUNT(DISTINCT pe.Txapelketa_ID) AS kopurua
            FROM "PorralariTaldeenEzizenak" ep
            JOIN "PorraEzizenak" pe ON ep.Ezizen_ID = pe.Ezizen_ID
            GROUP BY ep.Porralaria_ID
        ''').fetchall()

        aldatuta = 0
        for row in counts:
            pid     = row["Porralaria_ID"]
            kopurua = row["kopurua"]
            current = con.execute(
                'SELECT "Zenbat Porra" FROM "Porralariak" WHERE Porralaria_ID = ?', [pid]
            ).fetchone()
            if current and current["Zenbat Porra"] != kopurua:
                con.execute(
                    'UPDATE "Porralariak" SET "Zenbat Porra" = ? WHERE Porralaria_ID = ?',
                    [kopurua, pid]
                )
                aldatuta += 1

        # Porrarik ez duten porralariak 0-ra ezarri
        all_ids = {r["Porralaria_ID"] for r in con.execute('SELECT Porralaria_ID FROM "Porralariak"').fetchall()}
        counted_ids = {r["Porralaria_ID"] for r in counts}
        for pid in all_ids - counted_ids:
            current = con.execute(
                'SELECT "Zenbat Porra" FROM "Porralariak" WHERE Porralaria_ID = ?', [pid]
            ).fetchone()
            if current and current["Zenbat Porra"] != 0:
                con.execute(
                    'UPDATE "Porralariak" SET "Zenbat Porra" = 0 WHERE Porralaria_ID = ?', [pid]
                )
                aldatuta += 1

        con.commit()

    return {"ok": True, "aldatuta": aldatuta, "total": len(counts)}

# ─── Formato normalizatu ──────────────────────────────────────────────────────

def normalize_izenak() -> dict:
    """
    Txirrindulari eta Porralari izen guztiak Title Case-ra bihurtu.
    Adib: "POGACAR TADEJ" -> "Pogacar Tadej", "van der poel" -> "Van Der Poel"
    Itzultzen du: zenbat aldatu diren.
    """
    changed = {"txirrindulariak": 0, "porralariak": 0}

    with get_db() as con:
        # Txirrindulariak
        rows_t = con.execute('SELECT Txirrindularia_ID, Izena FROM "Txirrindulariak"').fetchall()
        for row in rows_t:
            new_name = row["Izena"].title()
            if new_name != row["Izena"]:
                con.execute(
                    'UPDATE "Txirrindulariak" SET Izena = ? WHERE Txirrindularia_ID = ?',
                    [new_name, row["Txirrindularia_ID"]]
                )
                changed["txirrindulariak"] += 1

        # Porralariak
        rows_p = con.execute('SELECT Porralaria_ID, Izena FROM "Porralariak"').fetchall()
        for row in rows_p:
            new_name = row["Izena"].title()
            if new_name != row["Izena"]:
                con.execute(
                    'UPDATE "Porralariak" SET Izena = ? WHERE Porralaria_ID = ?',
                    [new_name, row["Porralaria_ID"]]
                )
                changed["porralariak"] += 1

        con.commit()

    return {"ok": True, "changed": changed}

# ─── Izena/Abizena ordena tresna ─────────────────────────────────────────────

def _detect_order(name: str) -> str:
    """
    Saiatu detektatzen ea izena "ABIZENA Izena" edo "Izena ABIZENA" ordenan dagoen.
    "ABIZENA Izena": lehen hitza guztiz maiuskulaz (edo maiuskula gehiago ditu).
    Itzultzen du: "abizena_izena" | "izena_abizena" | "unknown"
    """
    parts = name.strip().split()
    if len(parts) < 2:
        return "unknown"
    # Lehen hitza guztiz maiuskulaz?
    first_upper = parts[0] == parts[0].upper() and any(c.isalpha() for c in parts[0])
    last_upper  = parts[-1] == parts[-1].upper() and any(c.isalpha() for c in parts[-1])
    if first_upper and not last_upper:
        return "abizena_izena"
    if last_upper and not first_upper:
        return "izena_abizena"
    return "unknown"

def _swap_name(name: str) -> str:
    """
    "POGACAR Tadej" -> "Tadej Pogacar" (Title Case)
    Hitz guztiak Title Case-ra pasatzen ditu eta ordena trukatzen du.
    """
    parts = name.strip().split()
    if len(parts) < 2:
        return name.title()
    # Bilatu non dagoen banaketa: maiuskula blokea vs minuskula blokea
    # Aurkitu lehen hitz-multzoa guztiz maiuskulaz (abizena)
    upper_end = 0
    for i, p in enumerate(parts):
        if p == p.upper() and any(c.isalpha() for c in p):
            upper_end = i + 1
        else:
            break
    if upper_end == 0 or upper_end == len(parts):
        return " ".join(p.title() for p in parts)
    abizenak = parts[:upper_end]
    izenak   = parts[upper_end:]
    return " ".join(p.title() for p in izenak + abizenak)

def get_txirrindulari_ordenak() -> list:
    """Txirrindulari guztiak itzuli detektatutako ordenarekin."""
    with get_db() as con:
        rows_all = con.execute(
            'SELECT Txirrindularia_ID, Izena FROM "Txirrindulariak" ORDER BY Izena'
        ).fetchall()
    result = []
    for row in rows_all:
        order = _detect_order(row["Izena"])
        result.append({
            "Txirrindularia_ID": row["Txirrindularia_ID"],
            "Izena": row["Izena"],
            "order": order,
            "suggested": _swap_name(row["Izena"]) if order == "abizena_izena" else None,
        })
    return result

def apply_txirrindulari_swap(ids: list) -> dict:
    """Emandako ID-entzat izena trukatu."""
    changed = 0
    skipped = 0
    errors  = []
    with get_db() as con:
        for tid in ids:
            row = con.execute(
                'SELECT Izena FROM "Txirrindulariak" WHERE Txirrindularia_ID = ?', [tid]
            ).fetchone()
            if not row:
                skipped += 1
                continue
            new_name = _swap_name(row["Izena"])
            if new_name == row["Izena"]:
                skipped += 1
                continue
            # Egiaztatu izen berria ez dela jada existitzen
            exists = con.execute(
                'SELECT 1 FROM "Txirrindulariak" WHERE Izena = ? AND Txirrindularia_ID != ?',
                [new_name, tid]
            ).fetchone()
            if exists:
                errors.append({"id": tid, "izena": row["Izena"], "reason": f"'{new_name}' jada existitzen da"})
                continue
            con.execute(
                'UPDATE "Txirrindulariak" SET Izena = ? WHERE Txirrindularia_ID = ?',
                [new_name, tid]
            )
            changed += 1
        con.commit()
    return {"ok": True, "changed": changed, "skipped": skipped, "errors": errors}

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
            body = (BASE_DIR / "index.html").read_text("utf-8").encode()
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
                    'FROM "Porralariak" p LEFT JOIN "PorralariTaldeenEzizenak" ep ON p.Porralaria_ID = ep.Porralaria_ID '
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
                # Ezizen batek porralari anitz izan ditzake (talde-porra): izenak batu, errenkadak ez bikoizteko.
                return self.send_json(rows(con,
                    'SELECT e.*, ez.Ezizena, '
                    'GROUP_CONCAT(p.Izena, ", ") AS Porralaria '
                    'FROM "TxapelketaEmaitzaPorralariak" e '
                    'JOIN "PorraEzizenak" ez ON e.Ezizen_ID = ez.Ezizen_ID '
                    'LEFT JOIN "PorralariTaldeenEzizenak" ep ON ez.Ezizen_ID = ep.Ezizen_ID '
                    'LEFT JOIN "Porralariak" p ON ep.Porralaria_ID = p.Porralaria_ID '
                    'GROUP BY e.Txapelketa_ID, e.Ezizen_ID '
                    'ORDER BY e.Txapelketa_ID, e.Posizioa'))
            if path == "/api/karrera-sailkapena":
                return self.send_json(rows(con,
                    'SELECT ks.*, t.Izena AS Txirrindularia FROM "KarreraSailkapena" ks '
                    'JOIN "Txirrindulariak" t ON ks.Txirrindularia_ID = t.Txirrindularia_ID ORDER BY ks.Karrera_ID, ks.Puntuak DESC'))
            if path == "/api/karrera-emaitza":
                params = parse_qs(parsed.query)
                karrera_id = params.get("karrera_id", [None])[0]
                if not karrera_id:
                    return self.send_error_json("karrera_id parametroa behar da", 400)
                karrera = con.execute(
                    'SELECT k.*, tx.Izena AS Txapelketa FROM "Karrerak" k '
                    'JOIN "Txapelketak" tx ON k.Txapelketa_ID = tx.Txapelketa_ID '
                    'WHERE k.Karrerak_ID = ?', [int(karrera_id)]
                ).fetchone()
                if not karrera:
                    return self.send_error_json("Karrera ez da aurkitu", 404)
                sailkapena = rows(con,
                    'SELECT ks.Sailkapena, t.Izena AS Txirrindularia, ks.Puntuak '
                    'FROM "KarreraSailkapena" ks '
                    'JOIN "Txirrindulariak" t ON ks.Txirrindularia_ID = t.Txirrindularia_ID '
                    'WHERE ks.Karrera_ID = ? ORDER BY ks.Sailkapena',
                    [int(karrera_id)]
                )
                return self.send_json({"karrera": dict(karrera), "sailkapena": sailkapena})
            if path == "/api/ezizenak":
                return self.send_json(api_ezizenak(con))
            if path == "/api/porralaria-ezizenak":
                params = parse_qs(parsed.query)
                pid = params.get("porralaria_id", [None])[0]
                if not pid:
                    return self.send_error_json("porralaria_id parametroa behar da", 400)
                return self.send_json(_porralaria_ezizenak(con, int(pid)))
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
            # Ezizen bati porralari bat EDO anitz esleitu (talde-porra).
            # Multzo osoa ordezkatzen du: porralaria_ids = behin betiko zerrenda.
            return self.send_json(ezizen_lotu(data))

        elif path == "/api/porralari-split":
            return self.send_json(porralari_split(data))

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

        elif path == "/api/recalculate-zenbat-porra":
            return self.send_json(recalculate_zenbat_porra())

        elif path == "/api/normalize-izenak":
            return self.send_json(normalize_izenak())

        elif path == "/api/izen-ordenak/get":
            return self.send_json(get_izen_ordenak())

        elif path == "/api/izen-ordenak/apply":
            aldaketak = data.get("aldaketak", [])
            return self.send_json(apply_izen_ordenak(aldaketak))

        elif path == "/api/txirrindulari-ordenak":
            return self.send_json(get_txirrindulari_ordenak())

        elif path == "/api/txirrindulari-swap":
            ids = data.get("ids", [])
            if not ids:
                return self.send_error_json("ids behar dira")
            return self.send_json(apply_txirrindulari_swap([int(i) for i in ids]))

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
