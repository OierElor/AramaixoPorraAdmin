#!/usr/bin/env python3
"""Klasikak 2026 (Txapelketa 15): 10-17 karrerak datubasean sartu ODS-tik.

Iturria: 'Klasikoen porra 2026.ods'
 - Frogak              -> karrera bakoitzeko top-15 dortsalak + kodea
 - TX zerrenda         -> dortsal -> izena (maiuskula)
 - Puntuak             -> puntuazio taula kategoriaka
 - Sailkapena kalkulatu-> porralarien puntu metatuak karreraka

Logika 1-9 karrera existenteekin balidatuta dago sartu aurretik.
"""
import sqlite3, re, unicodedata, sys
import pandas as pd

DB = "/home/oier/AramaixoPorraAdmin/AramaixoPorra.db"
ODS = "/home/oier/AramaixoPorraAdmin/Porren datuak sartzeko excelak/Klasikak/Klasikoen porra 2026.ods"
TXAP = 15
URTEA = 2026
KODE2KAT = {'Pro': 'Proseries', 'S3': 'Monumentua', 'S4': '4', 'S5': '5', 'T1': 'Berezia'}

# Subset-token faltsu negatiboak (TX zerrenda izen laburragoa DB izen luzeagoan)
DORTSAL_OVERRIDE = {
    '1701': 'Nielsen Magnus Cort',     # CORT Magnus
    '1712': 'Dversnes Lavik Fredrik',  # DVERSNES Fredrik
}

def fold(s):
    s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode()
    return frozenset(t for t in re.split(r'[\s\-]+', s.lower()) if t)

# ── Datuak kargatu ────────────────────────────────────────────────────────────
def load_scoring():
    df = pd.read_excel(ODS, engine='odf', sheet_name='Puntuak', header=None)
    return {str(df.iat[r, 1]).strip(): [int(df.iat[r, 3 + p]) for p in range(15)] for r in range(2, 7)}

def load_dortsal_map():
    tz = pd.read_excel(ODS, engine='odf', sheet_name='TX zerrenda', header=None)
    m = {}
    for r in range(tz.shape[0]):
        for c in (0, 3, 6):
            d, n = tz.iat[r, c], tz.iat[r, c + 1]
            if isinstance(d, str) and re.fullmatch(r'\d{4}', d.strip()) and isinstance(n, str) and n.strip():
                m[d.strip()] = n.strip()
    return m

def load_races():
    fr = pd.read_excel(ODS, engine='odf', sheet_name='Frogak', header=None)
    races = []
    for r in range(3, fr.shape[0]):
        name = fr.iat[r, 1]
        if not isinstance(name, str) or not name.strip():
            break
        kode = str(fr.iat[r, 5]).strip()
        dorts = [str(fr.iat[r, 6 + i]).strip() if pd.notna(fr.iat[r, 6 + i]) else None for i in range(15)]
        if all(d is None for d in dorts):
            break
        races.append({'name': name.strip(), 'kode': kode, 'dorts': dorts})
    return races

def load_bettors():
    sk = pd.read_excel(ODS, engine='odf', sheet_name='Sailkapena kalkulatu', header=None)
    bett = []
    for r in range(3, sk.shape[0]):
        ez, zb = sk.iat[r, 0], sk.iat[r, 1]
        if not (isinstance(ez, str) and ez.strip()) or pd.isna(zb) or str(ez).strip() == 'Izena':
            break
        cum = [int(sk.iat[r, 6 + 3 * i]) if pd.notna(sk.iat[r, 6 + 3 * i]) else 0 for i in range(17)]
        bett.append({'ezizena': ez.strip(), 'zbk': int(zb), 'cum': cum})
    return bett

# ── Mapaketak eraiki ────────────────────────────────────────────────────────────
def build_rider_map(cur, races, dmap, existing_kids):
    """dortsal -> ('id', Txirrindularia_ID) edo ('new', maiuskula_izena)."""
    # Ground truth 1-9 karreretatik: dortsal -> Txirrindularia_ID
    gt = {}
    for i in range(len(existing_kids)):
        kid = existing_kids[i]
        cur.execute("SELECT Sailkapena, Txirrindularia_ID FROM KarreraSailkapena WHERE Karrera_ID=?", (kid,))
        pos2id = dict(cur.fetchall())
        for pos in range(1, 16):
            d = races[i]['dorts'][pos - 1]
            if d and pos in pos2id:
                gt[d] = pos2id[pos]
    # Txirrindulariak fold mapa
    cur.execute("SELECT Txirrindularia_ID, Izena FROM Txirrindulariak")
    foldmap = {}
    name2id = {}
    for tid, izena in cur.fetchall():
        foldmap.setdefault(fold(izena), []).append((tid, izena))
        name2id[izena] = tid

    resolved = {}   # dortsal -> ('id', tid) | ('new', caps)
    for rc in races:
        for d in rc['dorts']:
            if not d or d in resolved:
                continue
            if d in gt:
                resolved[d] = ('id', gt[d])
                continue
            if d in DORTSAL_OVERRIDE:
                resolved[d] = ('id', name2id[DORTSAL_OVERRIDE[d]])
                continue
            caps = dmap.get(d)
            if caps is None:
                raise SystemExit(f"ERROREA: dortsal {d} ez dago TX zerrendan")
            hit = foldmap.get(fold(caps))
            if hit and len(hit) == 1:
                resolved[d] = ('id', hit[0][0])
            elif hit:
                raise SystemExit(f"ERROREA: dortsal {d} ({caps}) anbiguoa: {hit}")
            else:
                resolved[d] = ('new', caps)
    return resolved

def build_bettor_map(cur, bettors, last_kid):
    """ODS Zenbakia -> Ezizen_ID, race-9 puntu metatuen bidez."""
    cur.execute("SELECT Ezizen_ID, Puntuak_Totalean FROM TxapelketaSailkapenaPorralariak "
                "WHERE Txapelketa_ID=? AND Azken_Karrera_ID=?", (TXAP, last_kid))
    by_pts = {}
    for eid, tot in cur.fetchall():
        by_pts.setdefault(tot, []).append(eid)
    cur.execute("SELECT Ezizen_ID, Ezizena FROM PorraEzizenak WHERE Txapelketa_ID=?", (TXAP,))
    name2eid = {ez: eid for eid, ez in cur.fetchall()}
    NAME_FALLBACK = {'Jak': 'Jak', 'Lasa': 'Lasa'}
    mapping = {}
    used = set()
    for b in bettors:
        cum9 = b['cum'][8]
        cand = by_pts.get(cum9, [])
        cand = [c for c in cand if c not in used]
        if len(cand) == 1:
            eid = cand[0]
        elif b['ezizena'] in NAME_FALLBACK:
            eid = name2eid[NAME_FALLBACK[b['ezizena']]]
        else:
            raise SystemExit(f"ERROREA: porralaria parekatu ezin '{b['ezizena']}' (zbk {b['zbk']}, pts {cum9}) -> {cand}")
        mapping[b['zbk']] = eid
        used.add(eid)
    return mapping

# ── Balidazioa 1-9 karreretan ──────────────────────────────────────────────────
def validate(cur, races, scoring, rider_map, bettor_map, bettors, existing_kids):
    errs = 0
    cum_rider = {}  # tid -> metatua
    for i in range(len(existing_kids)):
        kid = existing_kids[i]
        rc = races[i]
        pts = scoring[rc['kode']]
        per = {}
        for pos in range(1, 16):
            d = rc['dorts'][pos - 1]
            if not d:
                continue
            kind, val = rider_map[d]
            tid = val  # 1-9 karreretan beti 'id'
            p = pts[pos - 1]
            per[tid] = per.get(tid, 0) + p
            cum_rider[tid] = cum_rider.get(tid, 0) + p
        # cyclist cumulative
        cur.execute("SELECT Txirrindularia_ID, Puntuak_Totalean, Puntuak_Azken_Karrera "
                    "FROM TxapelketaSailkapenaTxirrindulariak WHERE Txapelketa_ID=? AND Azken_Karrera_ID=?", (TXAP, kid))
        db_tx = {tid: (tot, last) for tid, tot, last in cur.fetchall()}
        if set(db_tx) != set(cum_rider):
            print(f"  [TX KOP] race{i+1}: ODS={len(cum_rider)} DB={len(db_tx)}"); errs += 1
        for tid, tot in cum_rider.items():
            dt = db_tx.get(tid)
            if not dt or dt[0] != tot or dt[1] != per.get(tid, 0):
                print(f"  [TX] race{i+1} tid{tid}: ODS=(tot{tot},last{per.get(tid,0)}) DB={dt}"); errs += 1
        # bettor cumulative
        cur.execute("SELECT Ezizen_ID, Puntuak_Totalean, Puntuak_Azken_Karrera "
                    "FROM TxapelketaSailkapenaPorralariak WHERE Txapelketa_ID=? AND Azken_Karrera_ID=?", (TXAP, kid))
        db_po = {eid: (tot, last) for eid, tot, last in cur.fetchall()}
        for b in bettors:
            eid = bettor_map[b['zbk']]
            tot = b['cum'][i]; last = b['cum'][i] - (b['cum'][i - 1] if i > 0 else 0)
            dp = db_po.get(eid)
            if not dp or dp[0] != tot or dp[1] != last:
                print(f"  [PO] race{i+1} '{b['ezizena']}' eid{eid}: ODS=(tot{tot},last{last}) DB={dp}"); errs += 1
    return errs, cum_rider

# ── Sartu 10-17 karrerak ─────────────────────────────────────────────────────────
def main():
    scoring = load_scoring()
    dmap = load_dortsal_map()
    races = load_races()
    bettors = load_bettors()
    print(f"Karrerak ODS: {len(races)} | Porralariak: {len(bettors)}")

    con = sqlite3.connect(DB)
    con.execute("PRAGMA foreign_keys = ON")
    cur = con.cursor()
    cur.execute("SELECT Karrerak_ID, Izena FROM Karrerak WHERE Txapelketa_ID=? ORDER BY Karrerak_ID", (TXAP,))
    existing = cur.fetchall()
    existing_kids = [k for k, _ in existing]
    n_done = len(existing_kids)
    print(f"DB-n dauden karrerak: {n_done}")
    if n_done >= len(races):
        print("Ez dago sartzeko karrera berririk."); return

    rider_map = build_rider_map(cur, races, dmap, existing_kids)
    bettor_map = build_bettor_map(cur, bettors, existing_kids[-1])

    print("\n── Balidazioa 1-9 karreretan ──")
    errs, cum_rider = validate(cur, races, scoring, rider_map, bettor_map, bettors, existing_kids)
    if errs:
        print(f"\n✗ BALIDAZIOAK HUTS EGIN DU ({errs} errore). Ez da ezer sartu.")
        con.close(); sys.exit(1)
    print("✓ Balidazioa zuzena: 1-9 karrerak bat datoz ODS-rekin.")

    # Sortu behar diren txirrindulari berriak
    new_dorts = sorted(d for d, (k, v) in rider_map.items() if k == 'new')
    print(f"\nTxirrindulari berriak sortuko dira: {len(new_dorts)}")
    for d in new_dorts:
        print(f"   {d}  {rider_map[d][1]}")

    # ── INSERT ──
    def rider_id(d):
        kind, val = rider_map[d]
        if kind == 'id':
            return val
        # 'new' -> sortu (behin)
        cur.execute("SELECT Txirrindularia_ID FROM Txirrindulariak WHERE Izena=?", (val,))
        row = cur.fetchone()
        if row:
            tid = row[0]
        else:
            cur.execute("INSERT INTO Txirrindulariak (Izena) VALUES (?)", (val,))
            tid = cur.lastrowid
        rider_map[d] = ('id', tid)
        return tid

    print("\n── Karrerak sartzen (10-17) ──")
    for i in range(n_done, len(races)):
        rc = races[i]
        pts = scoring[rc['kode']]
        kat = KODE2KAT[rc['kode']]
        cur.execute("INSERT INTO Karrerak (Txapelketa_ID, Izena, Urtea, Kategoria) VALUES (?,?,?,?)",
                    (TXAP, rc['name'], URTEA, kat))
        kid = cur.lastrowid
        # KarreraSailkapena + per-race rider points
        per = {}
        for pos in range(1, 16):
            d = rc['dorts'][pos - 1]
            if not d:
                continue
            tid = rider_id(d)
            p = pts[pos - 1]
            cur.execute("INSERT OR IGNORE INTO KarreraSailkapena (Karrera_ID, Txirrindularia_ID, Puntuak, Sailkapena) VALUES (?,?,?,?)",
                        (kid, tid, p, pos))
            per[tid] = per.get(tid, 0) + p
            cum_rider[tid] = cum_rider.get(tid, 0) + p
        # TxapelketaSailkapenaTxirrindulariak (metatua)
        for tid, tot in cum_rider.items():
            cur.execute("INSERT OR IGNORE INTO TxapelketaSailkapenaTxirrindulariak "
                        "(Txapelketa_ID, Txirrindularia_ID, Azken_Karrera_ID, Puntuak_Totalean, Puntuak_Azken_Karrera, Eboluzioa) "
                        "VALUES (?,?,?,?,?,0)", (TXAP, tid, kid, tot, per.get(tid, 0)))
        # TxapelketaSailkapenaPorralariak
        for b in bettors:
            eid = bettor_map[b['zbk']]
            tot = b['cum'][i]; last = b['cum'][i] - b['cum'][i - 1]
            cur.execute("INSERT OR IGNORE INTO TxapelketaSailkapenaPorralariak "
                        "(Txapelketa_ID, Ezizen_ID, Azken_Karrera_ID, Puntuak_Totalean, Puntuak_Azken_Karrera, Puntuazio_Finala) "
                        "VALUES (?,?,?,?,?,0)", (TXAP, eid, kid, tot, last))
        print(f"  + {rc['name']} ({kat}) -> Karrera_ID={kid}  [{len([d for d in rc['dorts'] if d])} txirr., {len(cum_rider)} metatuan]")

    con.commit()
    con.close()
    print("\n✓ Datu guztiak behar bezala sartu dira.")

if __name__ == "__main__":
    main()
