# Aramaixo Porra — Txirrindularitza Porraren Kudeatzailea

Proiektu honen helburua txirrindularitza txapelketen (Tourra, Giroa, Vuelta, urte osoko klasikak...) inguruko apustu edo "porra" bat kudeatzea da. Bi zati ditu:

* **Datu-basea** (`AramaixoPorra.db`, SQLite): txirrindularien emaitzak, porralarien apustuak eta sailkapenen bilakaera gordetzen ditu.
* **Web administrazio-tresna** (`app.py` + `index.html`): datuak ikusi, editatu eta inportatzeko interfaze grafikoa.

---

## 🚀 Web orria abiaraztea

Dependentziarik gabe doa (Python-en `stdlib` soilik: `sqlite3` + `http.server`). Terminalean:

```bash
python3 app.py
```

Gero, nabigatzailean ireki: **http://localhost:3000**

Aukerak (ingurune-aldagaiak):

```bash
PORT=8080 python3 app.py                 # beste portu bat erabili
DB_FILE=/bide/beste.db python3 app.py     # beste datu-base bat erabili (probetarako, adib.)
```

> 💡 Datu-basea aldatu aurretik **babeskopia** bat egitea gomendatzen da: `cp AramaixoPorra.db AramaixoPorra.db.bak`.

---

## 🧭 Web orriaren atalak

Ezkerreko menutik nabigatzen da. Atal bakoitza:

### 📊 Dashboard
Estatistika orokorrak (zenbat txapelketa, porralari, txirrindulari, karrera) eta txapelketa baten sailkapena azkar ikusteko. Goian txapelketa bat aukeratuta, bere porralarien sailkapena erakusten du.

### 🏆 Porralariak
Porran jokatzen duten pertsona errealen zerrenda. Bilatzailea du, eta "Zenbat Porra" zutabeak pertsona bakoitzak zenbat porratan parte hartzen duen erakusten du. Porralari berriak gehitzeko, **Eskuz sartu** atala erabili.

### 🚴 Txirrindulariak
Txirrindularien zerrenda. Izen-ordena okerra badago (adib. `POGAČAR Tadej` vs `Tadej Pogačar`), errenkadako **⇄** botoiak izena-abizena tokiz aldatzeko proposamena egiten du.

### 🗓️ Txapelketak
Txapelketak (itzuliak/klasikak) eta haien karrerak/etapak zerrendatzen ditu.

### 📋 Sailkapenak
Txapelketa baten **azken sailkapenak** ikusteko, bai porralarienak bai txirrindularienak (bi fitxa). Txapelketaren eta izenaren arabera iragaz daiteke.

### 🏁 Karrera emaitzak
Karrera/etapa zehatz baten sailkapena ikusteko (top txirrindulariak eta puntuak).

### ▦ Taula guztiak
Datu-baseko **edozein taula zuzenean editatzeko**. Taula bat aukeratu, zelda batean klik egin, balioa aldatu eta **Gorde** sakatu. Lehen mailako gakoak (ID) ezin dira editatu.

### ✏️ Eskuz sartu
Erregistro bakanak eskuz gehitzeko (porralari berri bat, txapelketa bat, etab.).

### 📂 CSV inportatu
Datuak CSV bidez kargatzeko. Ikus beheko **".ods-etik inportatzea"** atala.

### 🔀 Fusionatu
Bikoiztutako **txirrindulariak** edo **porralariak** bat egiteko. KEEP (geratuko dena) eta DROP (ezabatuko dena) aukeratu, **Aurreikusi** sakatu — porralarien kasuan, alde bakoitzak zein **ezizen** dituen erakusten du, zer batzen ari zaren ikusteko — eta gero **Fusionatu**. ⚠️ Eragiketa hau **itzulezina** da.

### 🏷️ Ezizenak lotu
Ezizen bakoitza (porra-izena edo talde-izena) porralari errealari lotzeko.

* **Porralari bat** lotu: aukeratu zerrendatik eta **+ Gehitu**.
* **Porralari berria** sortu eta lotu: **+ Berria**.
* **Talde-porra**: ezizen berari **porralari anitz** gehi dakizkioke; orduan 👥 marka agertzen da. Honela talde batek egindako porra adieraz daiteke.
* Lotutako porralaria kentzeko, txipeko **✕** sakatu.
* Iragazkiak: lotu gabekoak, lotutakoak edo talde-porrak (2+) bakarrik erakusteko.

### ✂️ Banatu porralaria
Porralari baten porrak **bi pertsonaren artean banatzeko**. Porralaria aukeratu, bere porrak (ezizenak) checkbox-ekin agertzen dira; aukeratutakoak **porralari berri bati** (izena idatzita) edo **lehendik dagoen bati** esleitzen zaizkio.

### ↩️ Atzera / Aurrera (Undo / Redo)
CSV bidezko inportazioak desegin edo berregin daitezke (CSV atalaren behealdean).

---

## 📥 .ods-etik inportatzea (CSV bidez)

Zure LibreOffice `.ods` fitxategietatik datuak inportatzeko:

1. LibreOffice-n nahi duzun **blokea hautatu eta kopiatu** (edo orria **CSV gisa gorde**).
2. Web orrian **CSV Inportatu** atalera joan, **datu-mota** aukeratu, eta fitxategia/edukia utzi.
3. **Aurreikusi** eta gero **Inportatu**.

Xehetasunak:

* Mugatzailea automatikoki antzematen da: `,`, `;` (LibreOffice) edo tabuladorea.
* Hasierako lerro/zutabe hutsak baztertzen dira (blokeak kopiatzean ohikoa).
* Zutabe-izenak **sinonimoekin** lotzen dira; ez dute zehatzak izan behar (adib. `Porreroa`→ezizena, `Zbkia`→dortsala, `Sailkapena`→posizioa, `Izena`→txirrindularia, `Guztira`→puntuak, `Mendia`→mendikoa, `Orokorra`→generala).

Datu-mota bakoitzeko zer esportatu:

| Datu-mota | Iturria (.ods) | Behar diren zutabeak |
|---|---|---|
| Porralariak / Txirrindulariak | Izen-zerrenda | `Izena` |
| Txapelketak / Karrerak | Etapak / izenak | `Izena`, `Urtea` |
| Txirrindulari emaitzak (karrera) | Klasikak → *Sailkapenak erakutsi* lasterketa-blokea | `Sailkapena`, `Izena`, `Puntuak` (karrera aukeratu) |
| Txirrindulari emaitzak (txapelketa) | Txirrindulari sailkapena blokea | `Posizioa`, `Txirrindularia`, `Puntuak` |
| Porralari emaitzak (txapelketa) | Sailkapen nagusia blokea | `Posizioa`, `Porreroa`, `Puntuak` |

Txirrindularien izenak inportatzean, tresnak DB-ko izenekin **antzekotasunez** parekatzen ditu (azentu eta ordena ezikusita), eta bat ez datozenetarako aukera ematen du fusionatzeko edo berri gisa sartzeko.

---

## 🗄️ Datu-basearen eskema

Taulak lau bloketan banatzen dira:

### 1. Oinarrizko datuak
* **`Txapelketak`**: jokatzen diren itzuliak/klasikak (Izena, Urtea).
* **`Karrerak`**: txapelketa bateko etapa edo lasterketa bakoitza (Izena, Urtea, Kategoria).
* **`Txirrindulariak`**: parte hartzen duten txirrindulariak.
* **`Porralariak`**: porran jokatzen duten pertsona errealak.

### 2. Porralarien kudeaketa eta apustuak
* **`PorraEzizenak`**: porralari batek txapelketa zehatz batean erabiltzen duen izena edo "talde izena".
* **`PorralariTaldeenEzizenak`**: ezizen baten eta porralari erreal baten/batzuen arteko lotura (talde batek porra bat batera bota dezake ezizen bat erabiliz).
* **`PorraApustuak`**: porralari bakoitzak txapelketa batean zein txirrindulari aukeratu dituen.

### 3. Sailkapenak (karreraz karrera)
* **`KarreraSailkapena`**: karrera zehatz batean txirrindulariek lortutako puntuak eta sailkapena (postua).
* **`TxapelketaSailkapenaTxirrindulariak`**: karrera bakoitzaren ostean txirrindulariaren egoera orokorra (puntuak totalean, eboluzioa...).
* **`TxapelketaSailkapenaPorralariak`**: karrera bakoitzaren ostean porralarien sailkapena.

### 4. Azken emaitzak eta sariak
* **`TxapelketaEmaitzaTxirrindulariak`**: txirrindularien behin betiko posizioa eta puntuak.
* **`TxapelketaEmaitzaPorralariak`**: porralarien azken sailkapena.
* **`Sariak`**: txapelketako posizio bakoitzari dagokion saria.

> ℹ️ Datu-basea jada sortuta dago (`AramaixoPorra.db`). `app.py`-k ez du eskema berriz sortzen datu-basea badagoenean.
