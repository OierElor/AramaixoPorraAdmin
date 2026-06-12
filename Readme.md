# Txirrindularitza Porra - Datu-Basearen Eskema

Proiektu honen helburua txirrindularitza txapelketen (adibidez, Frantziako Tourra, Italiako Giroa, Espainiako Vuelta) inguruko apustu edo "porra" bat kudeatzeko datu-base erlazionala eskaintzea da. Eskema SQLite formatuan diseinatuta dago.

Datu-base honek txirrindularien eguneroko emaitzak, porralarien apustuak eta etapa bakoitzaren osteko sailkapen eboluzioa era zehatzean gordetzeko gaitasuna dauka.

---

## 📂 Egitura Orokorra

Datu-basearen taulak lau bloke nagusitan banatzen dira euren funtzioaren arabera:

### 1. Oinarrizko Datuak (Entitate Nagusiak)
Jokoaren oinarria osatzen duten elementuak dira:
* **`Txapelketak`**: Jokatzen diren itzuliak (Izena eta Urtea) (Ahal da izan urte guztiko klasikak).
* **`Karrerak`**: Txapelketa bateko etapa edo lasterketa bakoitza.
* **`Txirrindulariak`**: Karreretan parte hartzen duten txirrindulariak.
* **`Porralariak`**: Porran jokatzen duten erabiltzaile edo pertsona errealak.

### 2. Porralarien Kudeaketa eta Apustuak
Jokalariek txapelketa bakoitzean duten parte-hartzea definitzen dute:
* **`PorralariEzizenak`**: Porralari batek txapelketa zehatz batean erabiltzen duen izena edo "talde izena".
* **`EzizenPorralariak`**: Porralari errealaren (`Porralariak`) eta bere ezizenaren arteko lotura (Porralari talde batek ahal du porra bat batera bota eta ezizen bat erabili talde errepresentatzeko).
* **`PorraApustuak`**: Porralari bakoitzak txapelketa batean zein txirrindulari aukeratu dituen gordetzen du.

### 3. Etapetako Sailkapenak (Karreraz Karrera)
Lasterketa bakoitza amaitzean gertatzen den bilakaera gordetzeko (historikoa izateko):
* **`KarreraSailkapena`**: Etapa/Karrera zehatz batean txirrindulariek lortutako puntuak eta erabilitako dortsala.
* **`TxapelketaSailkapenaTxirrindulariak`**: Etapa bakoitzaren ostean txirrindulariak txapelketan duen egoera orokorra (puntuak totalean, mendian, eboluzioa...).
* **`TxapelketaSailkapenaPorralariak`**: Etapa bakoitzaren ostean porralarien sailkapena nola dagoen.

### 4. Azken Emaitzak eta Sariak
Txapelketa guztiz amaitzean kalkulatzen eta gordetzen diren datu estatikoak:
* **`TxapelketaEmaitzaTxirrindulariak`**: Txirrindularien behin betiko posizioa eta puntuak itzuliaren amaieran.
* **`TxapelketaEmaitzaPorralariak`**: Porralarien azken sailkapena.
* **`Sariak`**: Txapelketako posizio bakoitzari dagokion sariaren definizioa.

---

## 🚀 Nola Erabili (Instalazioa)

Eskema hau SQLite datu-base batean inplementatzeko prest dago. Fitxategia exekutatu eta datu-base hutsa sortzeko, erabili hurrengo komandoa zure terminalean:

```bash
sqlite3 AramaixoPorra.db < schema.sql
