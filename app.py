#!/usr/bin/env python3
"""
Aramaixo Porra backend.
Zero dependentzia: Python stdlib soilik (sqlite3 + http.server)

Berrikuntza:
- /api/csv/preview  → diff aurreikuspena (zer gehituko den / zer dagoen jada)
- /api/csv/import   → inportatu batch bat, undo-stack-era gehitu
- /api/undo         → azken inportazio-batch-a desegin
- /api/undo/stack   → undo/redo pilen egoera
- /api/redo         → berregin
"""

import json
import os
import sqlite3
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse

BASE_DIR = Path(__file__).parent
SCHEMA   = BASE_DIR / "schema.sql"
PORT     = int(os.environ.get("PORT", 3000))

MIME = {
    ".html": "text/html; charset=utf-8",
    ".js":   "application/javascript; charset=utf-8",
    ".css":  "text/css; charset=utf-8",
    ".ico":  "image/x-icon",
}

# ─── Undo / Redo stack (memoria, ez iraunkorra) ───────────────────────────────
# Bakoitza: {"label": str, "profile": str, "rows": [...], "identities": [...], "identity_fields": [str, ...]}
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
        "fields": ["Txapelketa_ID", "Izena", "Urtea"],
        "required": ["Txapelketa_ID", "Izena", "Urtea"],
        "identity": ["Karrerak_ID"],
    },
    "txirrindulari_emaitzak": {
        "label": "Txirrindulari sailkapena",
        "target": "TxapelketaEmaitzaTxirrindulariak",
        "fields": ["Txapelketa_ID", "Posizioa", "Txirrindularia", "Puntuak", "Dortsala"],
        "required": ["Txapelketa_ID", "Posizioa", "Txirrindularia", "Puntuak"],
        "identity": ["Txapelketa_ID", "Txirrindularia_ID"],
    },
}

FIELD_ALIASES = {
    "Txapelketa_ID": ["Txapelketa_ID", "Txapelketa", "Competition", "Competition_ID"],
    "Karrerak_ID": ["Karrerak_ID", "Karrera_ID"],
    "Txirrindularia": ["Txirrindularia", "Izena", "Rider", "Cyclist"],
    "Porralaria": ["Porralaria", "Ezizena", "Porralari"],
    "Posizioa": ["Posizioa", "Sailkapena", "Postua", "Rank"],
    "Puntuak": ["Puntuak", "Puntu", "Points"],
    "Urtea": ["Urtea", "Year"],
    "Izena": ["Izena", "Name", "Title"],
    "Dortsala": ["Dortsala", "Dorsala", "Bib"],
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
    for wanted in names:
        for key, value in raw.items():
            if str(key).strip().lower() == wanted.strip().lower():
                return value
    return None


def _resolve_raw_value(raw: dict, mapping: dict, logical_key: str):
    csv_col = mapping.get(logical_key)
    if csv_col:
        for key, value in raw.items():
            if str(key).strip().lower() == str(csv_col).strip().lower():
                return value

    aliases = FIELD_ALIASES.get(logical_key, [logical_key])
    value = _first_match(raw, aliases)
    if value is not None:
        return value

    value = _first_match(raw, [logical_key])
    if value is not None:
        return value

    return None


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
    row = con.execute(
        'SELECT Txirrindularia_ID FROM "Txirrindulariak" WHERE Izena = ?',
        [name],
    ).fetchone()
    return row[0] if row else None


def _ensure_txirrindularia_id(con, name: str) -> int:
    txirrindularia_id = _find_txirrindularia_id(con, name)
    if txirrindularia_id is not None:
        return int(txirrindularia_id)
    cur = con.execute('INSERT INTO "Txirrindulariak" (Izena) VALUES (?)', [name])
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


def _normalize_row(profile_id: str, mapping: dict, raw: dict, context: dict | None = None, con=None, create_missing: bool = False) -> dict | None:
    spec = _profile_spec(profile_id)
    if not spec:
        return None

    context = context or {}

    def get(logical_key: str):
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
        if txap_id is None or posizioa is None or not txirr_name or puntuak is None:
            return None

        norm = {
            "Txapelketa_ID": txap_id,
            "Posizioa": posizioa,
            "Txirrindularia": txirr_name,
            "Puntuak": puntuak,
        }

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

    return None


def _row_exists(con, profile_id: str, norm: dict) -> tuple[bool, str]:
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
        rider_id = norm.get("Txirrindularia_ID")
        if rider_id is None:
            rider_id = _find_txirrindularia_id(con, norm["Txirrindularia"])
        if rider_id is None:
            return False, ""
        r = con.execute(
            'SELECT 1 FROM "TxapelketaEmaitzaTxirrindulariak" WHERE Txapelketa_ID = ? AND Txirrindularia_ID = ?',
            [norm["Txapelketa_ID"], rider_id],
        ).fetchone()
        return (bool(r), f"Txirrindularia_ID={rider_id}" if r else "")
    return False, ""


def _insert_row(con, profile_id: str, norm: dict) -> dict:
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
        rider_id = norm.get("Txirrindularia_ID")
        if rider_id is None:
            rider_id = _ensure_txirrindularia_id(con, norm["Txirrindularia"])
        cur = con.execute(
            'INSERT INTO "TxapelketaEmaitzaTxirrindulariak" (Txapelketa_ID, Txirrindularia_ID, Posizioa, Puntuak) VALUES (?, ?, ?, ?)',
            [norm["Txapelketa_ID"], int(rider_id), norm["Posizioa"], norm["Puntuak"]],
        )
        return {"Txapelketa_ID": norm["Txapelketa_ID"], "Txirrindularia_ID": int(rider_id)}
    raise ValueError(f"Taula ezezaguna: {profile_id}")


def db_meta():
    with get_db() as con:
        tables = [
            row[0]
            for row in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
        ]
    return {
        "db_path":  str(DB_PATH.resolve()),
        "db_exists": DB_PATH.exists(),
        "tables":   tables,
    }


# ─── CSV Preview (diff kalkulua) ──────────────────────────────────────────────

def csv_preview(payload: dict) -> dict:
    """
    payload:
      profile : inportazio profila (adib. txirrindulari_emaitzak)
      mapping : {eremu_logikoa: csv_zutabea}
      context : testuingurua (adib. {"Txapelketa_ID": 4})
      rows    : [{csv_zutabea: balioa, ...}, ...]

    Itzultzen du:
      {
        "will_insert": [{normalized_row}, ...],
        "already_exists": [{normalized_row}, ...],
        "errors": [{row, reason}, ...]
      }
    """
    profile = payload.get("profile") or payload.get("table", "")
    mapping = payload.get("mapping", {})
    raw     = payload.get("rows", [])
    context = payload.get("context", {})

    spec = _profile_spec(profile)
    if not spec:
        return {
            "will_insert": [],
            "already_exists": [],
            "errors": [{"row": {}, "reason": f"CSV profila ezezaguna: {profile}"}],
        }

    will_insert:    list[dict] = []
    already_exists: list[dict] = []
    errors:         list[dict] = []

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

    return {
        "will_insert":    will_insert,
        "already_exists": already_exists,
        "errors":         errors,
    }


def csv_import(payload: dict) -> dict:
    """
    payload:
      profile : inportazio profila
      mapping : mapa
      context : testuingurua
      rows    : lerro zerrendak
      label   : undo etiketa (aukerakoa)

    Itzultzen du:
      {"inserted": int, "skipped": int, "errors": [...], "batch_id": int}
    """
    profile = payload.get("profile") or payload.get("table", "")
    mapping = payload.get("mapping", {})
    raw     = payload.get("rows", [])
    context = payload.get("context", {})
    label   = payload.get("label", f"CSV → {profile}")

    spec = _profile_spec(profile)
    if not spec:
        return {"inserted": 0, "skipped": 0, "errors": [{"row": {}, "reason": f"CSV profila ezezaguna: {profile}"}], "batch_id": len(_undo_stack)}

    inserted_identities: list[dict] = []
    inserted_rows: list[dict] = []
    skipped = 0
    errors: list[dict] = []

    with get_db() as con:
        for raw_row in raw:
            norm = _normalize_row(profile, mapping, raw_row, context, con, create_missing=True)
            if norm is None:
                errors.append({"row": raw_row, "reason": "Eremu batzuk falta dira"})
                continue

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
        batch = {
            "label": label,
            "profile": profile,
            "target": spec["target"],
            "rows": inserted_rows,
            "identities": inserted_identities,
            "identity_fields": spec["identity"],
        }
        _undo_stack.append(batch)
        if len(_undo_stack) > MAX_STACK:
            _undo_stack.pop(0)
        _redo_stack.clear()

    return {
        "inserted": len(inserted_identities),
        "skipped":  skipped,
        "errors":   errors,
        "batch_id": len(_undo_stack),
    }


# ─── Undo / Redo ─────────────────────────────────────────────────────────────

def do_undo() -> dict:
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


def do_redo() -> dict:
    if not _redo_stack:
        return {"ok": False, "reason": "Redo stack hutsa"}

    batch = _redo_stack[-1]
    spec = _profile_spec(batch["profile"])
    if not spec:
        return {"ok": False, "reason": "Redo batch baliogabea"}

    rows = batch.get("rows", [])
    inserted_identities: list[dict] = []
    skipped = 0
    errors: list[dict] = []

    with get_db() as con:
        for norm in rows:
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


def undo_stack_state() -> dict:
    return {
        "undo": [{"label": b["label"], "count": len(b.get("rows") or b.get("identities") or [])} for b in reversed(_undo_stack)],
        "redo": [{"label": b["label"], "count": len(b.get("rows") or b.get("identities") or [])} for b in reversed(_redo_stack)],
    }


# ─── APP JS ──────────────────────────────────────────────────────────────────

APP_JS = r"""
(function () {
    const api = (path, options = {}) => fetch(path, {
        headers: { "Content-Type": "application/json" },
        ...options,
    }).then(async (response) => {
        const text = await response.text();
        let data = null;
        try { data = text ? JSON.parse(text) : null; }
        catch (e) { data = { error: text || response.statusText }; }
        if (!response.ok) {
            const message = data && data.error ? data.error : `HTTP ${response.status}`;
            throw new Error(message);
        }
        return data;
    });

    const state = {
        txapelketak: [], porralariak: [], txirrindulariak: [],
        karrerak: [], emPorra: [], emTxirri: [],
        sailTab: "porralariak",
        csv: null,           // {raw, headers, rows, type, mapping}
        preview: null,       // {will_insert, already_exists, errors}
        undoStack: [], redoStack: [],
    };

    const el = id => document.getElementById(id);
    const esc = v => String(v ?? "").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");

    // ── Toast ──────────────────────────────────────────────────────────────
    function showToast(msg, kind = "ok") {
        const t = el("toast"), tm = el("toast-msg");
        if (!t || !tm) return;
        t.classList.remove("ok","err","show");
        t.classList.add(kind === "err" ? "err" : "ok");
        tm.textContent = msg;
        requestAnimationFrame(() => t.classList.add("show"));
        clearTimeout(showToast._t);
        showToast._t = setTimeout(() => t.classList.remove("show"), 2600);
    }

    // ── Navigation ────────────────────────────────────────────────────────
    function setSection(name) {
        document.querySelectorAll(".nav-item[data-section]").forEach(n =>
            n.classList.toggle("active", n.dataset.section === name));
        document.querySelectorAll(".section[id^='sec-']").forEach(s =>
            s.classList.toggle("active", s.id === `sec-${name}`));
        if (name === "add-csv") refreshUndoUI();
    }
    function setTab(name) {
        document.querySelectorAll(".tab[data-sltab]").forEach(t =>
            t.classList.toggle("active", t.dataset.sltab === name));
        state.sailTab = name;
        renderSailkapenak();
    }

    // ── Generic table render ──────────────────────────────────────────────
    function renderTbody(bodyId, rows, cols, empty) {
        const body = el(bodyId);
        if (!body) return;
        if (!rows.length) {
            body.innerHTML = `<tr><td colspan="${cols.length}" style="color:var(--muted);padding:18px;text-align:center">${esc(empty)}</td></tr>`;
            return;
        }
        body.innerHTML = rows.map(row => {
            const cells = cols.map(col => {
                const v = typeof col.v === "function" ? col.v(row) : row[col.v];
                const align = col.align ? ` style="text-align:${col.align}"` : "";
                return `<td${align}>${esc(v ?? "—")}</td>`;
            }).join("");
            return `<tr>${cells}</tr>`;
        }).join("");
    }

    function populateSel(selId, items, placeholder, vk, lk, cur = "") {
        const s = el(selId); if (!s) return;
        s.innerHTML = [`<option value="">${esc(placeholder)}</option>`,
            ...items.map(i => `<option value="${esc(i[vk])}">${esc(i[lk])}</option>`)
        ].join("");
        if (cur) s.value = String(cur);
        else if (items.length) s.selectedIndex = 1;
    }

    // ── Render helpers ────────────────────────────────────────────────────
    function renderStats() {
        el("st-txap") && (el("st-txap").textContent = state.txapelketak.length);
        el("st-porra") && (el("st-porra").textContent = state.porralariak.length);
        el("st-txirri") && (el("st-txirri").textContent = state.txirrindulariak.length);
        el("st-karrerak") && (el("st-karrerak").textContent = state.karrerak.length);
    }
    function renderTxapelketak() {
        renderTbody("txap-tbody", state.txapelketak,
            [{v:"Txapelketa_ID"},{v:"Izena"},{v:"Urtea"}], "Ez dago txapelketarik");
    }
    function renderKarrerak() {
        renderTbody("karrerak-tbody", state.karrerak, [
            {v:"Karrerak_ID"},
            {v: r => { const t = state.txapelketak.find(x => String(x.Txapelketa_ID)===String(r.Txapelketa_ID)); return t ? t.Izena : r.Txapelketa_ID; }},
            {v:"Izena"},{v:"Urtea"}
        ], "Ez dago karrerarik");
    }
    function renderPorralariak() {
        const q = (el("porra-search")?.value||"").trim().toLowerCase();
        const rows = state.porralariak.filter(r => !q || r.Izena?.toLowerCase().includes(q));
        renderTbody("porra-tbody", rows,
            [{v:"Porralaria_ID"},{v:"Izena"},{v:r=>r["Zenbat Porra"]}], "Ez dago porralaririk");
        el("porra-count") && (el("porra-count").textContent = `${rows.length} erregistro`);
    }
    function renderTxirrindulariak() {
        const q = (el("txirri-search")?.value||"").trim().toLowerCase();
        const rows = state.txirrindulariak.filter(r => !q || r.Izena?.toLowerCase().includes(q));
        renderTbody("txirri-tbody", rows, [{v:"Txirrindularia_ID"},{v:"Izena"}], "Ez dago txirrindularirik");
        el("txirri-count") && (el("txirri-count").textContent = `${rows.length} erregistro`);
    }
    function renderDashRanking() {
        const sel = el("dash-txap-sel")?.value || "";
        const rows = state.emPorra.filter(r => !sel || String(r.Txapelketa_ID) === sel)
            .sort((a,b) => Number(a.Posizioa)-Number(b.Posizioa));
        renderTbody("dash-ranking-body", rows,
            [{v:"Posizioa"},{v:"Ezizena"},{v:"Porralaria_Izena"},{v:"Puntuak",align:"right"}],
            sel ? "Ez dago emaitzarik" : "Txapelketa bat aukeratu");
    }
    function renderSailkapenak() {
        const q = (el("sail-search")?.value||"").trim().toLowerCase();
        const sel = el("sail-txap-sel")?.value || "";
        const thead = el("sail-thead"), tbody = el("sail-tbody");
        if (!thead || !tbody) return;
        if (state.sailTab === "porralariak") {
            thead.innerHTML = "<tr><th>#</th><th>Ezizena</th><th>Porralaria</th><th style='text-align:right'>Puntuak</th></tr>";
            const rows = state.emPorra.filter(r => (!sel || String(r.Txapelketa_ID)===sel)
                && (!q || Object.values(r).some(v => String(v||"").toLowerCase().includes(q))))
                .sort((a,b) => Number(a.Posizioa)-Number(b.Posizioa));
            renderTbody("sail-tbody", rows,
                [{v:"Posizioa"},{v:"Ezizena"},{v:"Porralaria_Izena"},{v:"Puntuak",align:"right"}],
                "Ez dago emaitzarik");
        } else {
            thead.innerHTML = "<tr><th>#</th><th>Txirrindularia</th><th style='text-align:right'>Puntuak</th></tr>";
            const rows = state.emTxirri.filter(r => (!sel || String(r.Txapelketa_ID)===sel)
                && (!q || Object.values(r).some(v => String(v||"").toLowerCase().includes(q))))
                .sort((a,b) => Number(a.Posizioa)-Number(b.Posizioa));
            renderTbody("sail-tbody", rows,
                [{v:"Posizioa"},{v:"Izena"},{v:"Puntuak",align:"right"}], "Ez dago emaitzarik");
        }
    }

    // ── Reload ────────────────────────────────────────────────────────────
    async function reloadData() {
        const [txapelketak,porralariak,txirrindulariak,karrerak,emPorra,emTxirri] = await Promise.all([
            api("/api/txapelketak"), api("/api/porralariak"), api("/api/txirrindulariak"),
            api("/api/karrerak"), api("/api/emaitzak/porralariak"), api("/api/emaitzak/txirrindulariak"),
        ]);
        state.txapelketak    = Array.isArray(txapelketak)    ? txapelketak    : [];
        state.porralariak    = Array.isArray(porralariak)    ? porralariak    : [];
        state.txirrindulariak= Array.isArray(txirrindulariak)? txirrindulariak: [];
        state.karrerak       = Array.isArray(karrerak)       ? karrerak       : [];
        state.emPorra        = Array.isArray(emPorra)        ? emPorra        : [];
        state.emTxirri       = Array.isArray(emTxirri)       ? emTxirri       : [];

        const curDash = el("dash-txap-sel")?.value;
        const curSail = el("sail-txap-sel")?.value;
        const curKarr = el("m-karrera-txap")?.value;
        populateSel("dash-txap-sel", state.txapelketak, "— Txapelketa aukeratu —", "Txapelketa_ID", "Izena", curDash);
        populateSel("sail-txap-sel", state.txapelketak, "— Txapelketa guztiak —",  "Txapelketa_ID", "Izena", curSail);
        populateSel("m-karrera-txap", state.txapelketak, "— Aukeratu —",           "Txapelketa_ID", "Izena", curKarr);

        renderStats(); renderTxapelketak(); renderKarrerak();
        renderPorralariak(); renderTxirrindulariak();
        renderDashRanking(); renderSailkapenak();
        if (state.csv) renderStep1();
    }

    // ── Manual add ───────────────────────────────────────────────────────
    async function addTxapelketa() {
        const Izena = el("m-txap-izena")?.value?.trim(); const Urtea = Number(el("m-txap-urtea")?.value);
        if (!Izena || !Urtea) return showToast("Izena eta urtea behar dira", "err");
        await api("/api/txapelketak", {method:"POST", body:JSON.stringify({Izena,Urtea})});
        el("m-txap-izena").value = ""; el("m-txap-urtea").value = "";
        showToast("Txapelketa gehituta"); await reloadData();
    }
    async function addPorralaria() {
        const Izena = el("m-porra-izena")?.value?.trim();
        if (!Izena) return showToast("Izena behar da", "err");
        await api("/api/porralariak", {method:"POST", body:JSON.stringify({Izena})});
        el("m-porra-izena").value = ""; showToast("Porralaria gehituta"); await reloadData();
    }
    async function addTxirrindularia() {
        const Izena = el("m-txirri-izena")?.value?.trim();
        if (!Izena) return showToast("Izena behar da", "err");
        await api("/api/txirrindulariak", {method:"POST", body:JSON.stringify({Izena})});
        el("m-txirri-izena").value = ""; showToast("Txirrindularia gehituta"); await reloadData();
    }
    async function addKarrera() {
        const Txapelketa_ID = el("m-karrera-txap")?.value;
        const Izena = el("m-karrera-izena")?.value?.trim();
        const Urtea = Number(el("m-karrera-urtea")?.value);
        if (!Txapelketa_ID || !Izena || !Urtea) return showToast("Eremu guztiak behar dira", "err");
        await api("/api/karrerak", {method:"POST", body:JSON.stringify({Txapelketa_ID,Izena,Urtea})});
        el("m-karrera-izena").value = ""; el("m-karrera-urtea").value = "";
        showToast("Karrera gehituta"); await reloadData();
    }

    // ════════════════════════════════════════════════════════════════
    //  CSV IMPORT — 3 URRATS:
    //  1) Fitxategia kargatu → headers + lerro gordinak ikusi
    //  2) Zutabeak lotu (mapping) + preview diff
    //  3) Inportatu / Atzera
    // ════════════════════════════════════════════════════════════════

    // CSV profilak: iturburuko zutabeak ez dira DB-koen berdinak izan behar
    const CSV_PROFILES = {
        porralariak: {
            label: "Porralariak",
            target: "Porralariak",
            fields: ["Izena"],
        },
        txirrindulariak: {
            label: "Txirrindulariak",
            target: "Txirrindulariak",
            fields: ["Izena"],
        },
        txapelketak: {
            label: "Txapelketak",
            target: "Txapelketak",
            fields: ["Izena", "Urtea"],
        },
        karrerak: {
            label: "Karrerak",
            target: "Karrerak",
            fields: ["Txapelketa_ID", "Izena", "Urtea"],
        },
        txirrindulari_emaitzak: {
            label: "Txirrindulari sailkapena",
            target: "TxapelketaEmaitzaTxirrindulariak",
            fields: ["Txapelketa_ID", "Posizioa", "Txirrindularia", "Puntuak", "Dortsala"],
        },
    };
    const FIELD_ALIASES = {
        Txapelketa_ID: ["Txapelketa_ID", "Txapelketa", "Competition", "Competition_ID"],
        Txirrindularia: ["Txirrindularia", "Izena", "Rider", "Cyclist"],
        Posizioa: ["Posizioa", "Sailkapena", "Postua", "Rank"],
        Puntuak: ["Puntuak", "Puntu", "Points"],
        Urtea: ["Urtea", "Year"],
        Izena: ["Izena", "Name", "Title"],
        Dortsala: ["Dortsala", "Dorsala", "Bib"],
    };

    function parseCsv(text) {
        const lines = text.replace(/\r\n/g,"\n").replace(/\r/g,"\n").trim().split("\n").filter(Boolean);
        if (!lines.length) return {headers:[], rows:[]};
        const delim = lines[0].includes(";") ? ";" : ",";
        function parseLine(line) {
            const cells = []; let cur = "", q = false;
            for (let i=0;i<line.length;i++) {
                const c = line[i];
                if (c==='"') { if (q && line[i+1]==='"') { cur+='"'; i++; } else q=!q; }
                else if (!q && c===delim) { cells.push(cur.trim()); cur=""; }
                else cur+=c;
            }
            cells.push(cur.trim()); return cells;
        }
        const headers = parseLine(lines[0]);
        const rows = lines.slice(1).map(l => {
            const cells = parseLine(l);
            const obj = {};
            headers.forEach((h,i) => obj[h] = cells[i] ?? "");
            return obj;
        }).filter(r => Object.values(r).some(v=>v.trim()!==""));
        return {headers, rows};
    }

    // ── Urrats 1: Fitxategia kargatu ─────────────────────────────────────
    function defaultCsvContext(type) {
        const ctx = {};
        if (type === "txirrindulari_emaitzak") {
            ctx.Txapelketa_ID = el("dash-txap-sel")?.value || state.txapelketak[0]?.Txapelketa_ID || "";
        }
        return ctx;
    }

    function handleCsvFile(file) {
        const reader = new FileReader();
        reader.onload = () => {
            const {headers, rows} = parseCsv(String(reader.result||""));
            const type = el("csv-type")?.value || "porralariak";
            state.csv = {raw: String(reader.result), headers, rows, type,
                context: defaultCsvContext(type),
                mapping: buildAutoMapping(headers, (CSV_PROFILES[type] || CSV_PROFILES.porralariak).fields || [])};
            renderStep1();
        };
        reader.onerror = () => showToast("Ezin irakurri fitxategia", "err");
        reader.readAsText(file, "utf-8");
    }

    function buildAutoMapping(headers, fields) {
        // Saiatu automatikoki lotzen (case-insensitive) eta sinonimoekin
        function findHeader(names) {
            for (const wanted of names) {
                const match = headers.find(h => h.trim().toLowerCase() === wanted.trim().toLowerCase());
                if (match) return match;
            }
            return "";
        }
        const mapping = {};
        for (const f of fields) {
            mapping[f] = findHeader(FIELD_ALIASES[f] || [f]);
        }
        return mapping;
    }

    // ── Urrats 1 UI ──────────────────────────────────────────────────────
    function renderStep1() {
        const wrap = el("csv-steps"); if (!wrap) return;
        if (!state.csv) {
            wrap.innerHTML = ""; return;
        }
        const {headers, rows, type} = state.csv;
        const profile = CSV_PROFILES[type] || CSV_PROFILES.porralariak;
        const fields = profile.fields || [];

        // Mapping selects
        const mappingHtml = fields.map(f => `
            <div class="map-row">
                <span class="map-field">${esc(f)}</span>
                <span class="map-arrow">→</span>
                <select class="filter-sel map-sel" data-field="${esc(f)}">
                    <option value="">(saltatu)</option>
                    ${headers.map(h => `<option value="${esc(h)}" ${state.csv.mapping[f]===h?"selected":""}>${esc(h)}</option>`).join("")}
                </select>
            </div>`).join("");

        const contextHtml = type === "txirrindulari_emaitzak" ? `
        <div class="csv-step-card">
            <div class="step-label"><span class="step-num">3</span> Testuingurua</div>
            <div class="map-row">
                <span class="map-field">Txapelketa</span>
                <span class="map-arrow">→</span>
                <select class="filter-sel csv-context-sel" id="csv-txap-sel"></select>
            </div>
            <p style="margin-top:10px;color:var(--muted);font-size:12px">CSV-ko Txapelketa_ID zutabea ez baduzu mapatzen, hemen hautatutako txapelketa erabiliko da.</p>
        </div>` : "";

        // Raw preview (lehenengo 5 lerro)
        const previewRows = rows.slice(0,5);
        const previewHtml = `<div class="tbl-wrap preview-wrap"><table style="font-size:12px">
            <thead><tr>${headers.map(h=>`<th>${esc(h)}</th>`).join("")}</tr></thead>
            <tbody>${previewRows.map(r=>`<tr>${headers.map(h=>`<td>${esc(r[h]??'')}</td>`).join("")}</tr>`).join("")}</tbody>
        </table></div>`;

        wrap.innerHTML = `
        <div class="csv-step-card">
            <div class="step-label"><span class="step-num">1</span> CSV kargatu — <span style="color:var(--muted)">${esc(rows.length)} lerro, ${esc(headers.length)} zutabe</span></div>
            <p style="color:var(--muted);font-size:12px;margin-bottom:12px">Mapatu gabeko zutabeak ez dira gordetzen; profil bakoitzean beharrezko eremuak bakarrik erabiltzen dira.</p>
            ${previewHtml}
        </div>
        <div class="csv-step-card">
            <div class="step-label"><span class="step-num">2</span> Zutabeak lotu</div>
            <div class="mapping-grid">${mappingHtml}</div>
            <button class="btn btn-primary" style="margin-top:14px" id="btn-preview">
                🔍 Aldaketak aurreikusi
            </button>
        </div>
        ${contextHtml}
        <div id="step3-wrap"></div>`;

        // Binding
        wrap.querySelectorAll(".map-sel").forEach(s => {
            s.addEventListener("change", () => {
                state.csv.mapping[s.dataset.field] = s.value;
            });
        });
        const csvTxapSel = el("csv-txap-sel");
        if (csvTxapSel) {
            const cur = state.csv.context?.Txapelketa_ID || "";
            populateSel("csv-txap-sel", state.txapelketak, "— Txapelketa aukeratu —", "Txapelketa_ID", "Izena", cur);
            csvTxapSel.addEventListener("change", () => {
                state.csv.context = state.csv.context || {};
                state.csv.context.Txapelketa_ID = csvTxapSel.value;
            });
        }
        el("btn-preview")?.addEventListener("click", runPreview);
    }

    // ── Urrats 2: Preview diff ────────────────────────────────────────────
    async function runPreview() {
        const btn = el("btn-preview");
        if (btn) { btn.disabled = true; btn.textContent = "Bilatzen..."; }
        try {
            const result = await api("/api/csv/preview", {
                method: "POST",
                body: JSON.stringify({
                    profile: state.csv.type,
                    mapping: state.csv.mapping,
                    rows:    state.csv.rows,
                    context: state.csv.context || {},
                }),
            });
            state.preview = result;
            renderStep3(result);
        } catch(e) {
            showToast(e.message, "err");
        } finally {
            if (btn) { btn.disabled = false; btn.textContent = "🔍 Aldaketak aurreikusi"; }
        }
    }

    function renderStep3(preview) {
        const wrap = el("step3-wrap"); if (!wrap) return;
        const {will_insert=[], already_exists=[], errors=[]} = preview;
        const total = state.csv.rows.length;

        function colorBadge(n, col) {
            return n ? `<span class="badge" style="background:rgba(${col},.15);color:rgb(${col})">${n}</span>` : `<span class="badge">0</span>`;
        }

        const summaryHtml = `
        <div class="diff-summary">
            <div class="diff-stat ds-new">${colorBadge(will_insert.length,"74,222,128")} Gehituko dira</div>
            <div class="diff-stat ds-dup">${colorBadge(already_exists.length,"250,200,80")} Dagoeneko existitzen</div>
            <div class="diff-stat ds-err">${colorBadge(errors.length,"230,57,70")} Erroreak</div>
            <div class="diff-stat ds-tot"><span class="badge">${total}</span> Guztira</div>
        </div>`;

        // Gehituko diren taularen HTML
        function tableHtml(rows, kind) {
            if (!rows.length) return `<p style="color:var(--muted);font-size:12px;padding:8px 0">Ez dago</p>`;
            const keys = Object.keys(rows[0]).filter(k=>!k.startsWith("_"));
            return `<div class="tbl-wrap" style="max-height:200px;overflow-y:auto;border:1px solid var(--border);border-radius:7px">
            <table style="font-size:12px">
                <thead><tr>${keys.map(k=>`<th>${esc(k)}</th>`).join("")}</tr></thead>
                <tbody>${rows.slice(0,50).map(r=>`<tr class="${kind}">${keys.map(k=>`<td>${esc(r[k]??'')}</td>`).join("")}</tr>`).join("")}</tbody>
            </table></div>`;
        }

        const tabs = [
            {id:"diff-tab-new",  label:`✅ Berria (${will_insert.length})`,    rows: will_insert,     kind:"diff-new"},
            {id:"diff-tab-dup",  label:`⚠️ Bikoiztua (${already_exists.length})`, rows: already_exists, kind:"diff-dup"},
            {id:"diff-tab-err",  label:`❌ Errore (${errors.length})`,          rows: errors,          kind:"diff-err"},
        ];

        const tabBtns = tabs.map(t =>
            `<button class="diff-tab-btn ${t.id==='diff-tab-new'?'active':''}" data-dtab="${t.id}">${t.label}</button>`
        ).join("");

        const tabContent = tabs.map(t =>
            `<div class="diff-tab-content ${t.id==='diff-tab-new'?'active':''}" id="${t.id}">
                ${t.id==='diff-tab-err'
                    ? tableHtml(t.rows.map(r=>({...r.row??r, Arrazoia:r.reason??''})), t.kind)
                    : tableHtml(t.rows, t.kind)}
            </div>`
        ).join("");

        wrap.innerHTML = `
        <div class="csv-step-card">
            <div class="step-label"><span class="step-num">4</span> Aurreikuspen diff-a</div>
            ${summaryHtml}
            <div class="diff-tabs">${tabBtns}</div>
            ${tabContent}
            <div class="diff-actions" style="margin-top:16px;display:flex;gap:10px;align-items:center;flex-wrap:wrap">
                ${will_insert.length ? `<button class="btn btn-primary" id="btn-do-import">⬇️ Inportatu ${will_insert.length} erregistro</button>` : ""}
                <button class="btn btn-ghost" id="btn-csv-reset">🗑️ Berrabiarazi</button>
                <span id="import-result" style="font-size:12px;color:var(--muted)"></span>
            </div>
        </div>`;

        // Diff tab switching
        wrap.querySelectorAll(".diff-tab-btn").forEach(btn => {
            btn.addEventListener("click", () => {
                wrap.querySelectorAll(".diff-tab-btn").forEach(b => b.classList.remove("active"));
                wrap.querySelectorAll(".diff-tab-content").forEach(c => c.classList.remove("active"));
                btn.classList.add("active");
                el(btn.dataset.dtab)?.classList.add("active");
            });
        });

        el("btn-do-import")?.addEventListener("click", doImport);
        el("btn-csv-reset")?.addEventListener("click", resetCsv);
    }

    // ── Urrats 3: Inportatu ───────────────────────────────────────────────
    async function doImport() {
        const btn = el("btn-do-import");
        if (btn) { btn.disabled = true; btn.textContent = "Inportatzen..."; }
        try {
            const result = await api("/api/csv/import", {
                method: "POST",
                body: JSON.stringify({
                    profile: state.csv.type,
                    mapping: state.csv.mapping,
                    rows:    state.csv.rows,
                    context: state.csv.context || {},
                    label:   `CSV → ${(CSV_PROFILES[state.csv.type] || CSV_PROFILES.porralariak).label} (${state.csv.rows.length} lerro)`,
                }),
            });
            const msg = `✅ ${result.inserted} gehitu · ${result.skipped} saltatu · ${result.errors?.length||0} errore`;
            const res = el("import-result");
            if (res) res.textContent = msg;
            showToast(msg.replace("✅ ",""), result.errors?.length ? "err" : "ok");
            await reloadData();
            await refreshUndoUI();
        } catch(e) {
            showToast(e.message, "err");
            if (btn) { btn.disabled = false; btn.textContent = "⬇️ Inportatu"; }
        }
    }

    function resetCsv() {
        state.csv = null; state.preview = null;
        const wrap = el("csv-steps"); if (wrap) wrap.innerHTML = "";
        const fi = el("csv-file-input"); if (fi) fi.value = "";
    }

    // ── Undo / Redo UI ────────────────────────────────────────────────────
    async function refreshUndoUI() {
        try {
            const s = await api("/api/undo/stack");
            state.undoStack = s.undo || [];
            state.redoStack = s.redo || [];
            renderUndoUI();
        } catch(e) { /* silent */ }
    }

    function renderUndoUI() {
        const wrap = el("undo-wrap"); if (!wrap) return;
        const undoBtn = el("btn-undo");
        const redoBtn = el("btn-redo");
        const list    = el("undo-list");

        if (undoBtn) undoBtn.disabled = !state.undoStack.length;
        if (redoBtn) redoBtn.disabled = !state.redoStack.length;

        if (list) {
            if (!state.undoStack.length) {
                list.innerHTML = `<li style="color:var(--muted);font-style:italic">Ez dago atzera egiteko eragiketarik</li>`;
            } else {
                list.innerHTML = state.undoStack.map((b,i) =>
                    `<li class="undo-item ${i===0?'undo-latest':''}">
                        <span class="undo-label">${esc(b.label)}</span>
                        <span class="badge">${esc(b.count)} erregistro</span>
                    </li>`
                ).join("");
            }
        }
    }

    async function doUndo() {
        try {
            const r = await api("/api/undo", {method:"POST", body:"{}"});
            if (r.ok) {
                showToast(`Atzera egin: "${r.label}" (${r.deleted} ezabatu)`);
                await reloadData(); await refreshUndoUI();
            } else {
                showToast(r.reason || "Ezin atzera egin", "err");
            }
        } catch(e) { showToast(e.message, "err"); }
    }

    async function doRedo() {
        try {
            const r = await api("/api/redo", {method:"POST", body:"{}"});
            if (r.ok) {
                showToast(`Berreginda: "${r.label}" (${r.inserted} gehitu)`);
                await reloadData(); await refreshUndoUI();
            } else {
                showToast(r.reason || "Ezin berregin", "err");
            }
        } catch(e) { showToast(e.message, "err"); }
    }

    // ── Drop zone ────────────────────────────────────────────────────────
    function bindDrop() {
        const dz = el("drop-zone"), fi = el("csv-file-input");
        if (dz) {
            dz.addEventListener("click", () => fi?.click());
            dz.addEventListener("dragover", e => { e.preventDefault(); dz.classList.add("drag-over"); });
            dz.addEventListener("dragleave", () => dz.classList.remove("drag-over"));
            dz.addEventListener("drop", e => {
                e.preventDefault(); dz.classList.remove("drag-over");
                const file = e.dataTransfer?.files[0];
                if (file) { updateTableType(); handleCsvFile(file); }
            });
        }
        if (fi) fi.addEventListener("change", () => {
            const file = fi.files?.[0];
            if (file) { updateTableType(); handleCsvFile(file); }
        });
        el("csv-type")?.addEventListener("change", () => {
            if (state.csv) {
                state.csv.type = el("csv-type").value;
                state.csv.context = defaultCsvContext(state.csv.type);
                state.csv.mapping = buildAutoMapping(state.csv.headers, (CSV_PROFILES[state.csv.type] || CSV_PROFILES.porralariak).fields || []);
                renderStep1();
            }
        });
    }
    function updateTableType() {
        if (state.csv) state.csv.type = el("csv-type")?.value || "porralariak";
    }

    // ── Events ───────────────────────────────────────────────────────────
    function bindEvents() {
        document.querySelectorAll(".nav-item[data-section]").forEach(n =>
            n.addEventListener("click", () => setSection(n.dataset.section)));
        document.querySelectorAll(".tab[data-sltab]").forEach(t =>
            t.addEventListener("click", () => setTab(t.dataset.sltab)));

        el("dash-txap-sel")?.addEventListener("change", renderDashRanking);
        el("sail-txap-sel")?.addEventListener("change", renderSailkapenak);
        el("sail-search")?.addEventListener("input", renderSailkapenak);
        el("porra-search")?.addEventListener("input", renderPorralariak);
        el("txirri-search")?.addEventListener("input", renderTxirrindulariak);

        el("m-txap-btn")?.addEventListener("click", e => { e.preventDefault(); addTxapelketa().catch(e=>showToast(e.message,"err")); });
        el("m-porra-btn")?.addEventListener("click", e => { e.preventDefault(); addPorralaria().catch(e=>showToast(e.message,"err")); });
        el("m-txirri-btn")?.addEventListener("click", e => { e.preventDefault(); addTxirrindularia().catch(e=>showToast(e.message,"err")); });
        el("m-karrera-btn")?.addEventListener("click", e => { e.preventDefault(); addKarrera().catch(e=>showToast(e.message,"err")); });

        el("btn-undo")?.addEventListener("click", doUndo);
        el("btn-redo")?.addEventListener("click", doRedo);

        bindDrop();
    }

    function init() {
        bindEvents();
        setSection("dashboard");
        setTab("porralariak");
        reloadData().catch(e => showToast(e.message, "err"));
    }

    document.addEventListener("DOMContentLoaded", init);
})();
"""


# ─── HTTP Handler ─────────────────────────────────────────────────────────────

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

        elif path == "/api/undo/stack":
            self.send_json(undo_stack_state())

        elif path == "/api/meta":
            self.send_json(db_meta())

        elif path == "/app.js":
            body = APP_JS.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/javascript; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        else:
            file_path = BASE_DIR / (path.lstrip("/") or "index.html")
            if not file_path.exists() or not file_path.is_file():
                file_path = BASE_DIR / "index.html"
            try:
                content  = file_path.read_bytes()
                mime     = MIME.get(file_path.suffix, "application/octet-stream")
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

    def do_POST(self):
        path = urlparse(self.path).path
        data = self.read_json()

        try:
            # ── CSV Preview ──────────────────────────────────────────────
            if path == "/api/csv/preview":
                self.send_json(csv_preview(data))

            # ── CSV Import ───────────────────────────────────────────────
            elif path == "/api/csv/import":
                self.send_json(csv_import(data))

            # ── Undo ────────────────────────────────────────────────────
            elif path == "/api/undo":
                self.send_json(do_undo())

            # ── Redo ────────────────────────────────────────────────────
            elif path == "/api/redo":
                self.send_json(do_redo())

            # ── Existing manual-add endpoints ────────────────────────────
            elif path == "/api/txapelketak":
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


def main():
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"http://localhost:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nAgur!")


if __name__ == "__main__":
    main()
