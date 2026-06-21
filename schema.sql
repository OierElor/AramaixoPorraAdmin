-- Zuk sortutako eskema (EZ ALDATU automatikoki).
-- Inportatzaileak taula/zutabe berriak ez ditu gehitzen.
-- Zutabe berriak gehi nahi badituzu, zuk egin datu-basean.

PRAGMA foreign_keys = ON;

-- Erreferentzia: jatorrizko taulak eta zutabeak

CREATE TABLE IF NOT EXISTS "Txapelketak" (
    "Txapelketa_ID" INTEGER NOT NULL UNIQUE,
    "Izena" TEXT NOT NULL,
    "Urtea" INTEGER NOT NULL,
    UNIQUE("Izena", "Urtea"),
    PRIMARY KEY("Txapelketa_ID" AUTOINCREMENT)
);

CREATE TABLE "Karrerak" (
	"Karrerak_ID"	INTEGER NOT NULL UNIQUE,
	"Txapelketa_ID"	INTEGER NOT NULL,
	"Izena"	TEXT NOT NULL,
	"Urtea"	INTEGER NOT NULL,
	"Kategoria"	TEXT,
	UNIQUE("Izena","Urtea"),
	PRIMARY KEY("Karrerak_ID" AUTOINCREMENT),
	FOREIGN KEY("Txapelketa_ID") REFERENCES "Txapelketak"("Txapelketa_ID")
)

CREATE TABLE IF NOT EXISTS "Porralariak" (
	"Porralaria_ID"	INTEGER NOT NULL UNIQUE,
	"Izena"	TEXT NOT NULL UNIQUE,
	"Zenbat Porra"	INTEGER DEFAULT 1,
	PRIMARY KEY("Porralaria_ID" AUTOINCREMENT)
);

CREATE TABLE IF NOT EXISTS "Txirrindulariak" (
    "Txirrindularia_ID" INTEGER NOT NULL UNIQUE,
    "Izena" TEXT NOT NULL UNIQUE,
    PRIMARY KEY("Txirrindularia_ID" AUTOINCREMENT)
);

CREATE TABLE "KarreraSailkapena" (
	"Karrera_ID"	INTEGER NOT NULL,
	"Txirrindularia_ID"	INTEGER NOT NULL,
	"Puntuak"	INTEGER NOT NULL,
	"Sailkapena"	INTEGER NOT NULL,
	PRIMARY KEY("Karrera_ID","Txirrindularia_ID"),
	FOREIGN KEY("Karrera_ID") REFERENCES "Karrerak"("Karrerak_ID"),
	FOREIGN KEY("Txirrindularia_ID") REFERENCES "Txirrindulariak"("Txirrindularia_ID")
)

CREATE TABLE "TxapelketaSailkapenaPorralariak" (
	"Txapelketa_ID"	INTEGER NOT NULL,
	"Ezizen_ID"	INTEGER NOT NULL,
	"Azken_Karrera_ID"	INTEGER NOT NULL,
	"Puntuak_Totalean"	INTEGER NOT NULL,
	"Puntuak_Azken_Karrera"	INTEGER NOT NULL,
	"Puntuazio_Finala"	INTEGER NOT NULL DEFAULT 0,
	"Puntuazioa_Fin_Mendikoa"	INTEGER,
	"Puntuazioa_Fin_Generala"	INTEGER,
	PRIMARY KEY("Txapelketa_ID","Ezizen_ID","Azken_Karrera_ID"),
	FOREIGN KEY("Azken_Karrera_ID") REFERENCES "Karrerak"("Karrerak_ID"),
	FOREIGN KEY("Ezizen_ID") REFERENCES "PorralariEzizenak"("Ezizen_ID"),
	FOREIGN KEY("Txapelketa_ID") REFERENCES "Txapelketak"("Txapelketa_ID")
)

CREATE TABLE "TxirrindulariakTxapleketanParteHartzea" (
	"TxapelketaID"	INTEGER NOT NULL,
	"TxirrindulariaID"	INTEGER NOT NULL,
	"Dortsala"	INTEGER NOT NULL,
	PRIMARY KEY("TxapelketaID","TxirrindulariaID"),
	FOREIGN KEY("TxapelketaID") REFERENCES "Txapelketak"("Txapelketa_ID"),
	FOREIGN KEY("TxirrindulariaID") REFERENCES "Txirrindulariak"("Txirrindularia_ID")
)

CREATE TABLE IF NOT EXISTS "TxapelketaSailkapenaTxirrindulariak" (
    "Txapelketa_ID" INTEGER NOT NULL,
    "Txirrindularia_ID" INTEGER NOT NULL,
    "Azken_Karrera_ID" INTEGER NOT NULL,
    "Puntuak_Totalean" INTEGER NOT NULL,
    "Puntuak_Azken_Karrera" INTEGER NOT NULL,
    "Puntuak_Sailkapen nagusia" INTEGER,
    "Puntuak_Mendian" INTEGER,
    "Eboluzioa" INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY("Txapelketa_ID", "Txirrindularia_ID", "Azken_Karrera_ID"),
    FOREIGN KEY("Azken_Karrera_ID") REFERENCES "Karrerak"("Karrerak_ID"),
    FOREIGN KEY("Txapelketa_ID") REFERENCES "Txapelketak"("Txapelketa_ID"),
    FOREIGN KEY("Txirrindularia_ID") REFERENCES "Txirrindulariak"("Txirrindularia_ID")
);

CREATE TABLE "TxapelketaEmaitzaPorralariak" (
	"Txapelketa_ID"	INTEGER NOT NULL,
	"Ezizen_ID"	INTEGER NOT NULL,
	"Posizioa"	INTEGER NOT NULL,
	"Puntuak"	INTEGER NOT NULL,
	"Puntuak_Mendikoa"	INTEGER,
	"Puntuak_Generala"	INTEGER,
	PRIMARY KEY("Txapelketa_ID","Ezizen_ID"),
	FOREIGN KEY("Ezizen_ID") REFERENCES "PorralariEzizenak"("Ezizen_ID"),
	FOREIGN KEY("Txapelketa_ID") REFERENCES "Txapelketak"("Txapelketa_ID")
)

CREATE TABLE "TxapelketaEmaitzaTxirrindulariak" (
	"Txapelketa_ID"	INTEGER NOT NULL,
	"Txirrindularia_ID"	INTEGER NOT NULL,
	"Posizioa"	INTEGER NOT NULL,
	"Puntuak"	INTEGER NOT NULL,
	"Puntuak_Sailkapen_Nag"	INTEGER,
	"Puntuak_Mendian"	INTEGER,
	"Zenbatek?"	INTEGER,
	PRIMARY KEY("Txapelketa_ID","Txirrindularia_ID"),
	FOREIGN KEY("Txapelketa_ID") REFERENCES "Txapelketak"("Txapelketa_ID"),
	FOREIGN KEY("Txirrindularia_ID") REFERENCES "Txirrindulariak"("Txirrindularia_ID")
)

CREATE TABLE IF NOT EXISTS "PorraApustuak" (
    "Txapelketa_ID"     INTEGER NOT NULL,
    "Ezizen_ID"     INTEGER NOT NULL,
    "Txirrindularia_ID" INTEGER NOT NULL,
    PRIMARY KEY("Txapelketa_ID", "Ezizen_ID", "Txirrindularia_ID"),
    FOREIGN KEY("Txapelketa_ID")     REFERENCES "Txapelketak"("Txapelketa_ID"),
    FOREIGN KEY("Ezizen_ID")     REFERENCES "PorralariEzizenak"("Ezizen_ID"),
    FOREIGN KEY("Txirrindularia_ID") REFERENCES "Txirrindulariak"("Txirrindularia_ID")
);

CREATE TABLE IF NOT EXISTS "Sariak" (
    "Txapelketa_ID"  INTEGER NOT NULL,
    "Posizioa"       INTEGER NOT NULL,
    "Saria"          TEXT NOT NULL,
    PRIMARY KEY("Txapelketa_ID", "Posizioa"),
    FOREIGN KEY("Txapelketa_ID") REFERENCES "Txapelketak"("Txapelketa_ID")
);

CREATE TABLE "EzizenPorralariak" (
    "Ezizen_ID"     INTEGER NOT NULL,
    "Porralaria_ID" INTEGER NOT NULL,
    PRIMARY KEY("Ezizen_ID", "Porralaria_ID"),
    FOREIGN KEY("Ezizen_ID")    REFERENCES "PorralariEzizenak"("Ezizen_ID"),
    FOREIGN KEY("Porralaria_ID") REFERENCES "Porralariak"("Porralaria_ID")
);

CREATE TABLE IF NOT EXISTS "PorralariEzizenak" (
    "Ezizen_ID"      INTEGER NOT NULL,
    "Txapelketa_ID"  INTEGER NOT NULL,
    "Ezizena"        TEXT NOT NULL,
    PRIMARY KEY("Ezizen_ID" AUTOINCREMENT),
    UNIQUE("Txapelketa_ID", "Ezizena"),
    FOREIGN KEY("Txapelketa_ID") REFERENCES "Txapelketak"("Txapelketa_ID")
);

CREATE INDEX IF NOT EXISTS "KarreraSailkapenIndizea" ON "KarreraSailkapena" (
    "Karrera_ID",
    "Txirrindularia_ID"
);

CREATE INDEX IF NOT EXISTS "TxapelketaSailkapenTxirrindulariIndizea"
ON "TxapelketaSailkapenaTxirrindulariak" (
    "Txapelketa_ID",
    "Azken_Karrera_ID",
    "Txirrindularia_ID"
);
