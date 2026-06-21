#!/usr/bin/env python3
"""
Klasikak 2024, 2025 eta 2026 emaitzak datubasean sartu.
"""

import sqlite3
import csv
import os

DB_PATH = "/home/oier/AramaixoPorraAdmin/AramaixoPorra.db"
BASE = "/home/oier/AramaixoPorraAdmin/CSV klasikak"

# ── Puntuazio taulak ──────────────────────────────────────────────────────────
SCORING = {
    '5':          [400, 320, 260, 220, 180, 140, 120, 100,  80,  68,  56,  48,  40,  32,  28],
    '4':          [500, 400, 325, 275, 225, 175, 150, 125, 100,  85,  70,  60,  50,  40,  35],
    'Monumentua': [800, 640, 520, 440, 360, 280, 240, 200, 160, 135, 110,  95,  85,  65,  55],
    'Proseries':  [250, 170, 140, 120, 100,  80,  70,  60,  50,  40,  30,  20,  10,  10,  10],
    'Berezia':    [900, 715, 600, 490, 410, 340, 265, 225, 190, 150, 130, 105,  90,  75,  60],
}

# ── Karrera izena -> kategoria ─────────────────────────────────────────────────
NAME_TO_KATEGORIA = {
    'Omloop Nieuwsblad':                          '5',
    'Strade Bianche':                             '4',
    'Milano-Sanremo':                             'Monumentua',
    'Milano - Torino':                            'Proseries',
    'Classic Brugge-De Panne':                    '5',
    'E3 Saxo Classic':                            '5',
    'Gent-Wevelgem in Flanders Fields':           '4',
    'Dwars door Vlaanderen - A travers la Flandre': '5',
    'A travers la Flandre':                       '5',
    'Ronde van Vlaanderen - Tour des Flandres':   'Monumentua',
    'Tour des Flandres':                          'Monumentua',
    'Paris-Roubaix':                              'Monumentua',
    'Amstel Gold Race':                           '4',
    'La Flèche Wallonne':                         '4',
    'Liège-Bastogne-Liège':                       'Monumentua',
    'Eschborn-Frankfurt':                         '5',
    'De Brabantse Pijl - La Flèche Brabançonne':  'Proseries',
    'Brussels Cycling Classic':                   'Proseries',
    'Copenhagen Sprint':                          '5',
    'Donostia San Sebastian Klasikoa':            '5',
    'Bretagne Classic - Ouest-France':            '5',
    'BEMER Cyclassics':                           '5',
    'ADAC Cyclassics':                            '5',
    'Grand Prix Cycliste de Québec':              '4',
    'Grand Prix Cycliste de Montréal':            '4',
    'World championship':                         'Berezia',
    "Giro dell'Emilia":                           'Proseries',
    'Il Lombardia':                               'Monumentua',
    'Paris – Tours':                              'Proseries',
    'Paris - Tours':                              'Proseries',
}

# K26 Mota kode -> kategoria
MOTA_TO_KATEGORIA = {
    'S5':  '5',
    'S4':  '4',
    'S3':  'Monumentua',
    'Pro': 'Proseries',
    'Ber': 'Berezia',
}

# ── Laguntzaileak ─────────────────────────────────────────────────────────────

def get_or_create_txirrindularia(cur, izena):
    izena = izena.strip()
    cur.execute("SELECT Txirrindularia_ID FROM Txirrindulariak WHERE Izena = ?", (izena,))
    row = cur.fetchone()
    if row:
        return row[0]
    cur.execute("INSERT INTO Txirrindulariak (Izena) VALUES (?)", (izena,))
    return cur.lastrowid


def get_or_create_karrera(cur, txapelketa_id, izena, urtea, kategoria):
    cur.execute(
        "SELECT Karrerak_ID FROM Karrerak WHERE Izena = ? AND Urtea = ?",
        (izena, urtea)
    )
    row = cur.fetchone()
    if row:
        return row[0]
    cur.execute(
        "INSERT INTO Karrerak (Txapelketa_ID, Izena, Urtea, Kategoria) VALUES (?,?,?,?)",
        (txapelketa_id, izena, urtea, kategoria)
    )
    return cur.lastrowid


def insert_race_results_from_csv_row(cur, karrera_id, rider_names, kategoria):
    """2024/2025 CSV errenkada batetik KarreraSailkapena sartu."""
    puntuak_list = SCORING[kategoria]
    pos = 1
    for i, name in enumerate(rider_names):
        name = name.strip()
        if not name or name == 'Zerrendaz kanpo':
            pos += 1
            continue
        if pos > 15:
            break
        puntuak = puntuak_list[pos - 1]
        txirrindularia_id = get_or_create_txirrindularia(cur, name)
        cur.execute(
            "INSERT OR IGNORE INTO KarreraSailkapena (Karrera_ID, Txirrindularia_ID, Puntuak, Sailkapena)"
            " VALUES (?,?,?,?)",
            (karrera_id, txirrindularia_id, puntuak, pos)
        )
        pos += 1


# ── 2024 eta 2025 CSVak ───────────────────────────────────────────────────────

def process_emaitza_csv(cur, filepath, txapelketa_id, urtea):
    print(f"\n=== Prozesatzen: {filepath} (txapelketa={txapelketa_id}, urtea={urtea}) ===")
    with open(filepath, encoding='utf-8') as f:
        reader = csv.reader(f)
        header = next(reader)  # skip header
        for row in reader:
            if len(row) < 5:
                continue
            # Zutabeak: (idx), Izena, Data, UCI_kategoria, pos1..pos15
            race_name = row[1].strip()
            rider_cols = row[4:19]  # 15 postu

            kategoria = NAME_TO_KATEGORIA.get(race_name)
            if kategoria is None:
                print(f"  [OHARRA] Kategoria ez da aurkitu: '{race_name}'")
                continue

            karrera_id = get_or_create_karrera(cur, txapelketa_id, race_name, urtea, kategoria)
            insert_race_results_from_csv_row(cur, karrera_id, rider_cols, kategoria)
            print(f"  + {race_name} ({kategoria}) -> Karrera_ID={karrera_id}")


# ── Klasikak 2026 ─────────────────────────────────────────────────────────────

def get_k26_ezizen_map(cur):
    """Folder 1eko Sailkapen nagusia irakurri eta PorralariEzizenak sortu K26rako."""
    k26_dir = os.path.join(BASE, "klasikak26", "1")
    sailkapen_file = os.path.join(k26_dir, "Sailkapen nagusia K26.csv")

    # Ea dagoeneko sartuta dauden
    cur.execute("SELECT COUNT(*) FROM PorralariEzizenak WHERE Txapelketa_ID = 15")
    if cur.fetchone()[0] > 0:
        print("  PorralariEzizenak K26rako dagoeneko daude, mapa kargatzen...")
        zbkia_to_ezizen = {}
        with open(sailkapen_file, encoding='utf-8') as f:
            reader = csv.reader(f)
            next(reader)
            for row in reader:
                if len(row) < 3:
                    continue
                zbkia = int(row[1].strip())
                ezizena = row[2].strip()
                cur.execute(
                    "SELECT Ezizen_ID FROM PorralariEzizenak WHERE Txapelketa_ID=15 AND Ezizena=?",
                    (ezizena,)
                )
                r = cur.fetchone()
                if r:
                    zbkia_to_ezizen[zbkia] = r[0]
        return zbkia_to_ezizen

    print("  PorralariEzizenak K26 sortzen...")
    zbkia_to_ezizen = {}
    with open(sailkapen_file, encoding='utf-8') as f:
        reader = csv.reader(f)
        next(reader)
        for row in reader:
            if len(row) < 3:
                continue
            zbkia = int(row[1].strip())
            ezizena = row[2].strip()
            cur.execute(
                "INSERT OR IGNORE INTO PorralariEzizenak (Txapelketa_ID, Ezizena) VALUES (15, ?)",
                (ezizena,)
            )
            cur.execute(
                "SELECT Ezizen_ID FROM PorralariEzizenak WHERE Txapelketa_ID=15 AND Ezizena=?",
                (ezizena,)
            )
            ezizen_id = cur.fetchone()[0]
            zbkia_to_ezizen[zbkia] = ezizen_id
    print(f"  {len(zbkia_to_ezizen)} ezizen sortu/kargatu dira K26rako")
    return zbkia_to_ezizen


def process_k26_folder(cur, folder_num, zbkia_to_ezizen):
    folder_path = os.path.join(BASE, "klasikak26", str(folder_num))
    files = os.listdir(folder_path)

    # Karrera-espezifikoa aurkitu
    race_file = None
    for f in files:
        lower = f.lower()
        if 'sailkapen nagusia' not in lower and 'tx sailkapena' not in lower:
            race_file = os.path.join(folder_path, f)
            break
    if race_file is None:
        print(f"  [ERROREA] Ez da karrera fitxategia aurkitu {folder_num} karpetan")
        return None

    # Karrera sailkapena CSV irakurri
    with open(race_file, encoding='utf-8') as f:
        reader = csv.reader(f)
        header_row = next(reader)
        # Lasterketa:,<num>,<name>,Mota:,<mota>
        race_name = header_row[2].strip()
        mota_code = header_row[4].strip()
        kategoria = MOTA_TO_KATEGORIA.get(mota_code, '5')

        karrera_id = get_or_create_karrera(cur, 15, race_name, 2026, kategoria)
        print(f"  + {race_name} ({kategoria}) -> Karrera_ID={karrera_id}")

        next(reader)  # salbuespena: "Sailkapena,Dortsala,Izena,Puntuak,Zenbatek"
        race_results = []
        for row in reader:
            if len(row) < 4:
                continue
            sailkapena = int(row[0].strip())
            izena = row[2].strip()
            puntuak = int(row[3].strip())
            zenbatek = int(row[4].strip()) if len(row) > 4 and row[4].strip() else 0
            race_results.append((sailkapena, izena, puntuak, zenbatek))

        for sailkapena, izena, puntuak, zenbatek in race_results:
            txirr_id = get_or_create_txirrindularia(cur, izena)
            cur.execute(
                "INSERT OR IGNORE INTO KarreraSailkapena (Karrera_ID, Txirrindularia_ID, Puntuak, Sailkapena)"
                " VALUES (?,?,?,?)",
                (karrera_id, txirr_id, puntuak, sailkapena)
            )

    # Tx sailkapena CSV irakurri -> TxapelketaSailkapenaTxirrindulariak
    tx_file = os.path.join(folder_path, "Tx sailkapena K26.csv")
    with open(tx_file, encoding='utf-8') as f:
        reader = csv.reader(f)
        next(reader)  # "Txirrindulari Sailkapena,,,,"
        next(reader)  # "Posizioa,Zbkia,Txirrindularia,Zenbatek,Puntuak"
        for row in reader:
            if len(row) < 5:
                continue
            izena = row[2].strip()
            puntuak_total = int(row[4].strip())
            if not izena:
                continue
            txirr_id = get_or_create_txirrindularia(cur, izena)

            # Puntuak_Azken_Karrera: karrera honetan lortutako puntuak
            # (race_results-etik bilatzen dugu)
            puntuak_karrera = 0
            for _, r_izena, r_puntuak, _ in race_results:
                if r_izena == izena:
                    puntuak_karrera = r_puntuak
                    break

            cur.execute(
                "INSERT OR IGNORE INTO TxapelketaSailkapenaTxirrindulariak"
                " (Txapelketa_ID, Txirrindularia_ID, Azken_Karrera_ID, Puntuak_Totalean, Puntuak_Azken_Karrera)"
                " VALUES (?,?,?,?,?)",
                (15, txirr_id, karrera_id, puntuak_total, puntuak_karrera)
            )

    # Sailkapen nagusia CSV irakurri -> TxapelketaSailkapenaPorralariak
    sn_file = os.path.join(folder_path, "Sailkapen nagusia K26.csv")
    for enc in ('utf-8', 'latin-1'):
        try:
            with open(sn_file, encoding=enc) as f:
                f.read()
            break
        except UnicodeDecodeError:
            continue
    with open(sn_file, encoding=enc) as f:
        reader = csv.reader(f)
        for row in reader:
            # Gidoi bikoitzeko fitxategietan (6-9 karpeta) hutsik dauden errenkadak saltatu
            if len(row) < 5:
                continue
            zbkia_str = row[1].strip()
            if not zbkia_str or not zbkia_str.isdigit():
                continue
            zbkia = int(zbkia_str)
            gaur_str = row[3].strip()
            guztira_str = row[4].strip()
            if not gaur_str.lstrip('-').isdigit() or not guztira_str.lstrip('-').isdigit():
                continue
            gaur = int(gaur_str)
            guztira = int(guztira_str)
            ezizen_id = zbkia_to_ezizen.get(zbkia)
            if ezizen_id is None:
                print(f"    [OHARRA] Zbkia {zbkia} ez da ezizen mapan aurkitu")
                continue
            cur.execute(
                "INSERT OR IGNORE INTO TxapelketaSailkapenaPorralariak"
                " (Txapelketa_ID, Ezizen_ID, Azken_Karrera_ID, Puntuak_Totalean, Puntuak_Azken_Karrera)"
                " VALUES (?,?,?,?,?)",
                (15, ezizen_id, karrera_id, guztira, gaur)
            )

    return karrera_id


# ── Nagusia ───────────────────────────────────────────────────────────────────

def main():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("PRAGMA foreign_keys = ON")

    # 2024 CSV
    process_emaitza_csv(
        cur,
        os.path.join(BASE, "Klasika bakoitzaren emaitza 2024.csv"),
        txapelketa_id=13,
        urtea=2024
    )

    # 2025 CSV
    process_emaitza_csv(
        cur,
        os.path.join(BASE, "Klasika bakoitzaren emaitza 2025.csv"),
        txapelketa_id=14,
        urtea=2025
    )

    # K26: lehenik PorralariEzizenak sortu
    print("\n=== Klasikak 2026 (K26) ===")
    zbkia_map = get_k26_ezizen_map(cur)

    for i in range(1, 10):
        print(f"\n  -- Karpeta {i} --")
        process_k26_folder(cur, i, zbkia_map)

    con.commit()
    con.close()
    print("\n✓ Datu guztiak behar bezala sartu dira.")


if __name__ == "__main__":
    main()
