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
from urllib.parse import urlparse

BASE_DIR = Path(__file__).parent
SCHEMA = BASE_DIR / "schema.sql"
PORT = int(os.environ.get("PORT", 3000))

MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".ico": "image/x-icon",
}

APP_JS = r"""
(function () {
    const api = (path, options = {}) => fetch(path, {
        headers: { "Content-Type": "application/json" },
        ...options,
    }).then(async (response) => {
        const text = await response.text();
        let data = null;
        try {
            data = text ? JSON.parse(text) : null;
        } catch (error) {
            data = { error: text || response.statusText };
        }
        if (!response.ok) {
            const message = data && data.error ? data.error : `HTTP ${response.status}`;
            throw new Error(message);
        }
        return data;
    });

    const state = {
        txapelketak: [],
        porralariak: [],
        txirrindulariak: [],
        karrerak: [],
        emPorra: [],
        emTxirri: [],
        sailTab: "porralariak",
        csv: null,
    };

    const el = (id) => document.getElementById(id);

    const nodes = {
        toast: el("toast"),
        toastMsg: el("toast-msg"),
        navItems: Array.from(document.querySelectorAll(".nav-item[data-section]")),
        sections: Array.from(document.querySelectorAll(".section[id^='sec-']")),
        tabs: Array.from(document.querySelectorAll(".tab[data-sltab]")),
        dashTxapSel: el("dash-txap-sel"),
        sailTxapSel: el("sail-txap-sel"),
        sailSearch: el("sail-search"),
        sailHead: el("sail-thead"),
        sailBody: el("sail-tbody"),
        porraSearch: el("porra-search"),
        txirriSearch: el("txirri-search"),
        porraBody: el("porra-tbody"),
        txirriBody: el("txirri-tbody"),
        txapBody: el("txap-tbody"),
        karrerakBody: el("karrerak-tbody"),
        dashRankingBody: el("dash-ranking-body"),
        stTxap: el("st-txap"),
        stPorra: el("st-porra"),
        stTxirri: el("st-txirri"),
        stKarrerak: el("st-karrerak"),
        mTxapIzena: el("m-txap-izena"),
        mTxapUrtea: el("m-txap-urtea"),
        mTxapBtn: el("m-txap-btn"),
        mPorraIzena: el("m-porra-izena"),
        mPorraBtn: el("m-porra-btn"),
        mTxirriIzena: el("m-txirri-izena"),
        mTxirriBtn: el("m-txirri-btn"),
        mKarreraTxap: el("m-karrera-txap"),
        mKarreraIzena: el("m-karrera-izena"),
        mKarreraUrtea: el("m-karrera-urtea"),
        mKarreraBtn: el("m-karrera-btn"),
        dropZone: el("drop-zone"),
        csvFileInput: el("csv-file-input"),
        csvType: el("csv-type"),
        csvPreviewSection: el("csv-preview-section"),
        csvPreviewInfo: el("csv-preview-info"),
        csvPreviewHead: el("csv-preview-thead"),
        csvPreviewBody: el("csv-preview-tbody"),
        csvClearBtn: el("csv-clear-btn"),
        csvImportBtn: el("csv-import-btn"),
        csvResult: el("csv-result"),
    };

    function escapeHtml(value) {
        return String(value ?? "")
            .replaceAll("&", "&amp;")
            .replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;")
            .replaceAll('"', "&quot;")
            .replaceAll("'", "&#39;");
    }

    function showToast(message, kind = "ok") {
        if (!nodes.toast || !nodes.toastMsg) return;
        nodes.toast.classList.remove("ok", "err", "show");
        nodes.toast.classList.add(kind === "err" ? "err" : "ok");
        nodes.toastMsg.textContent = message;
        requestAnimationFrame(() => nodes.toast.classList.add("show"));
        window.clearTimeout(showToast._timer);
        showToast._timer = window.setTimeout(() => nodes.toast.classList.remove("show"), 2400);
    }

    function setActiveSection(sectionName) {
        nodes.navItems.forEach((item) => item.classList.toggle("active", item.dataset.section === sectionName));
        nodes.sections.forEach((section) => section.classList.toggle("active", section.id === `sec-${sectionName}`));
    }

    function setActiveTab(tabName) {
        nodes.tabs.forEach((tab) => tab.classList.toggle("active", tab.dataset.sltab === tabName));
        state.sailTab = tabName;
        renderSailkapenak();
    }

    function asText(value) {
        return value === null || value === undefined || value === "" ? "—" : String(value);
    }

    function renderTableBody(body, rows, columns, emptyText) {
        if (!body) return;
        if (!rows.length) {
            body.innerHTML = `<tr><td colspan="${columns.length}" style="color:var(--muted);padding:18px;text-align:center">${escapeHtml(emptyText)}</td></tr>`;
            return;
        }
        body.innerHTML = rows.map((row) => {
            const cells = columns.map((column) => {
                const value = typeof column.value === "function" ? column.value(row) : row[column.value];
                const align = column.align ? ` style="text-align:${column.align}"` : "";
                return `<td${align}>${escapeHtml(asText(value))}</td>`;
            }).join("");
            return `<tr>${cells}</tr>`;
        }).join("");
    }

    function populateSelect(select, items, placeholder, valueKey, labelKey, selectedValue = "") {
        if (!select) return;
        const options = [`<option value="">${escapeHtml(placeholder)}</option>`].concat(
            items.map((item) => `<option value="${escapeHtml(item[valueKey])}">${escapeHtml(item[labelKey])}</option>`)
        );
        select.innerHTML = options.join("");
        if (selectedValue) select.value = String(selectedValue);
        else if (items.length) select.selectedIndex = 1;
    }

    function currentTxapId(select) {
        return select && select.value ? String(select.value) : "";
    }

    function renderStats() {
        if (nodes.stTxap) nodes.stTxap.textContent = state.txapelketak.length;
        if (nodes.stPorra) nodes.stPorra.textContent = state.porralariak.length;
        if (nodes.stTxirri) nodes.stTxirri.textContent = state.txirrindulariak.length;
        if (nodes.stKarrerak) nodes.stKarrerak.textContent = state.karrerak.length;
    }

    function renderTxapelketak() {
        renderTableBody(nodes.txapBody, state.txapelketak, [
            { value: "Txapelketa_ID" },
            { value: "Izena" },
            { value: "Urtea" },
        ], "Ez dago txapelketarik");
    }

    function renderKarrerak() {
        renderTableBody(nodes.karrerakBody, state.karrerak, [
            { value: "Karrerak_ID" },
            { value: (row) => {
                const txap = state.txapelketak.find((item) => String(item.Txapelketa_ID) === String(row.Txapelketa_ID));
                return txap ? txap.Izena : row.Txapelketa_ID;
            } },
            { value: "Izena" },
            { value: "Urtea" },
        ], "Ez dago karrerarik");
    }

    function renderPorralariak() {
        const query = (nodes.porraSearch && nodes.porraSearch.value || "").trim().toLowerCase();
        const rows = state.porralariak.filter((row) => !query || String(row.Izena || "").toLowerCase().includes(query));
        renderTableBody(nodes.porraBody, rows, [
            { value: "Porralaria_ID" },
            { value: "Izena" },
            { value: (row) => row["Zenbat Porra"] },
        ], "Ez dago porralaririk");
        if (el("porra-count")) el("porra-count").textContent = `${rows.length} erregistro`;
    }

    function renderTxirrindulariak() {
        const query = (nodes.txirriSearch && nodes.txirriSearch.value || "").trim().toLowerCase();
        const rows = state.txirrindulariak.filter((row) => !query || String(row.Izena || "").toLowerCase().includes(query));
        renderTableBody(nodes.txirriBody, rows, [
            { value: "Txirrindularia_ID" },
            { value: "Izena" },
        ], "Ez dago txirrindularirik");
        if (el("txirri-count")) el("txirri-count").textContent = `${rows.length} erregistro`;
    }

    function filterRankingRows(rows, query) {
        const q = query.trim().toLowerCase();
        if (!q) return rows;
        return rows.filter((row) => Object.values(row).some((value) => String(value ?? "").toLowerCase().includes(q)));
    }

    function renderDashboardRanking() {
        const selected = currentTxapId(nodes.dashTxapSel);
        const rows = state.emPorra.filter((row) => !selected || String(row.Txapelketa_ID) === selected);
        const sorted = rows.slice().sort((a, b) => Number(a.Posizioa) - Number(b.Posizioa));
        renderTableBody(nodes.dashRankingBody, sorted, [
            { value: "Posizioa" },
            { value: "Ezizena" },
            { value: "Porralaria_Izena" },
            { value: "Puntuak", align: "right" },
        ], selected ? "Ez dago emaitzarik txapelketa honetan" : "Txapelketa bat aukeratu ezkerreko menuan");
    }

    function renderSailkapenak() {
        const query = (nodes.sailSearch && nodes.sailSearch.value || "").trim();
        const selected = currentTxapId(nodes.sailTxapSel);
        if (state.sailTab === "porralariak") {
            const rows = filterRankingRows(
                state.emPorra.filter((row) => !selected || String(row.Txapelketa_ID) === selected),
                query
            ).sort((a, b) => Number(a.Posizioa) - Number(b.Posizioa));
            nodes.sailHead.innerHTML = "<tr><th>#</th><th>Ezizena</th><th>Porralaria</th><th style=\"text-align:right\">Puntuak</th></tr>";
            renderTableBody(nodes.sailBody, rows, [
                { value: "Posizioa" },
                { value: "Ezizena" },
                { value: "Porralaria_Izena" },
                { value: "Puntuak", align: "right" },
            ], selected ? "Ez dago emaitzarik" : "Txapelketa bat aukeratu");
            return;
        }
        const rows = filterRankingRows(
            state.emTxirri.filter((row) => !selected || String(row.Txapelketa_ID) === selected),
            query
        ).sort((a, b) => Number(a.Posizioa) - Number(b.Posizioa));
        nodes.sailHead.innerHTML = "<tr><th>#</th><th>Txirrindularia</th><th style=\"text-align:right\">Puntuak</th></tr>";
        renderTableBody(nodes.sailBody, rows, [
            { value: "Posizioa" },
            { value: "Izena" },
            { value: "Puntuak", align: "right" },
        ], selected ? "Ez dago emaitzarik" : "Txapelketa bat aukeratu");
    }

    function csvDelimiterFor(type) {
        return type === "txapelketak" || type === "karrerak" ? "," : null;
    }

    function parseCsvLine(line, delimiter) {
        const cells = [];
        let current = "";
        let quoted = false;
        for (let index = 0; index < line.length; index += 1) {
            const char = line[index];
            if (char === '"') {
                if (quoted && line[index + 1] === '"') {
                    current += '"';
                    index += 1;
                } else {
                    quoted = !quoted;
                }
            } else if (!quoted && char === delimiter) {
                cells.push(current.trim());
                current = "";
            } else {
                current += char;
            }
        }
        cells.push(current.trim());
        return cells;
    }

    function parseCsv(text, type) {
        const normalized = text.replace(/\r\n/g, "\n").replace(/\r/g, "\n").trim();
        const lines = normalized.split("\n").filter(Boolean);
        if (!lines.length) return [];
        const delimiter = csvDelimiterFor(type) || (lines[0].includes(";") ? ";" : ",");
        const header = parseCsvLine(lines[0], delimiter).map((value) => value.toLowerCase());
        const dataLines = header.some((value) => ["izena", "urtea", "txapelketa_id"].includes(value)) ? lines.slice(1) : lines;
        return dataLines.map((line) => {
            const cells = parseCsvLine(line, delimiter);
            const row = {};
            header.forEach((name, index) => {
                row[name] = cells[index] ?? "";
            });
            if (!header.length) {
                row.izena = cells[0] ?? "";
                if (type === "txapelketak" || type === "karrerak") {
                    row.urtea = cells[1] ?? "";
                }
                if (type === "karrerak") {
                    row.txapelketa_id = cells[0] ?? "";
                    row.izena = cells[1] ?? "";
                    row.urtea = cells[2] ?? "";
                }
            }
            return row;
        }).filter((row) => Object.values(row).some((value) => String(value).trim() !== ""));
    }

    function renderCsvPreview() {
        if (!state.csv) {
            if (nodes.csvPreviewSection) nodes.csvPreviewSection.style.display = "none";
            return;
        }
        const rows = state.csv.rows.slice(0, 10);
        if (nodes.csvPreviewSection) nodes.csvPreviewSection.style.display = "block";
        if (nodes.csvPreviewInfo) nodes.csvPreviewInfo.textContent = `${state.csv.rows.length} lerro prest`;

        const columns = state.csv.columns;
        if (nodes.csvPreviewHead) {
            nodes.csvPreviewHead.innerHTML = `<tr>${columns.map((column) => `<th>${escapeHtml(column)}</th>`).join("")}</tr>`;
        }
        if (nodes.csvPreviewBody) {
            nodes.csvPreviewBody.innerHTML = rows.map((row) => `<tr>${columns.map((column) => `<td>${escapeHtml(row[column] ?? "")}</td>`).join("")}</tr>`).join("");
        }
    }

    function setCsvState(type, rows) {
        if (!rows.length) {
            state.csv = null;
            renderCsvPreview();
            return;
        }
        const columns = type === "porralariak" || type === "txirrindulariak"
            ? ["izena"]
            : type === "txapelketak"
                ? ["izena", "urtea"]
                : ["txapelketa_id", "izena", "urtea"];
        state.csv = { type, rows, columns };
        renderCsvPreview();
    }

    async function submitRow(type, row) {
        if (type === "porralariak") {
            return api("/api/porralariak", {
                method: "POST",
                body: JSON.stringify({ Izena: row.izena }),
            });
        }
        if (type === "txirrindulariak") {
            return api("/api/txirrindulariak", {
                method: "POST",
                body: JSON.stringify({ Izena: row.izena }),
            });
        }
        if (type === "txapelketak") {
            return api("/api/txapelketak", {
                method: "POST",
                body: JSON.stringify({ Izena: row.izena, Urtea: row.urtea }),
            });
        }
        if (type === "karrerak") {
            return api("/api/karrerak", {
                method: "POST",
                body: JSON.stringify({ Txapelketa_ID: row.txapelketa_id, Izena: row.izena, Urtea: row.urtea }),
            });
        }
        throw new Error("CSV mota ezezaguna");
    }

    async function importCsv() {
        if (!state.csv) {
            showToast("Lehenengo CSV fitxategi bat aukeratu", "err");
            return;
        }
        const { type, rows } = state.csv;
        if (!rows.length) {
            showToast("CSV hutsik dago", "err");
            return;
        }
        const results = [];
        for (const row of rows) {
            try {
                await submitRow(type, row);
                results.push({ ok: true });
            } catch (error) {
                results.push({ ok: false, error: error.message });
            }
        }
        const okCount = results.filter((result) => result.ok).length;
        const errCount = results.length - okCount;
        if (nodes.csvResult) {
            nodes.csvResult.style.display = "block";
            nodes.csvResult.style.borderColor = errCount ? "var(--accent)" : "#4ade80";
            nodes.csvResult.innerHTML = errCount
                ? `${okCount} inportatuta, ${errCount} errore`
                : `${okCount} erregistro ondo inportatu dira`;
        }
        showToast(errCount ? "CSV inportazioa amaitu da, erroreekin" : "CSV ondo inportatu da", errCount ? "err" : "ok");
        await reloadData();
    }

    async function reloadData() {
        const [txapelketak, porralariak, txirrindulariak, karrerak, emPorra, emTxirri, meta] = await Promise.all([
            api("/api/txapelketak"),
            api("/api/porralariak"),
            api("/api/txirrindulariak"),
            api("/api/karrerak"),
            api("/api/emaitzak/porralariak"),
            api("/api/emaitzak/txirrindulariak"),
            api("/api/meta").catch(() => null),
        ]);

        state.txapelketak = Array.isArray(txapelketak) ? txapelketak : [];
        state.porralariak = Array.isArray(porralariak) ? porralariak : [];
        state.txirrindulariak = Array.isArray(txirrindulariak) ? txirrindulariak : [];
        state.karrerak = Array.isArray(karrerak) ? karrerak : [];
        state.emPorra = Array.isArray(emPorra) ? emPorra : [];
        state.emTxirri = Array.isArray(emTxirri) ? emTxirri : [];

        populateSelect(nodes.dashTxapSel, state.txapelketak, "— Txapelketa aukeratu —", "Txapelketa_ID", "Izena", nodes.dashTxapSel && nodes.dashTxapSel.value);
        populateSelect(nodes.sailTxapSel, state.txapelketak, "— Txapelketa guztiak —", "Txapelketa_ID", "Izena", nodes.sailTxapSel && nodes.sailTxapSel.value);
        populateSelect(nodes.mKarreraTxap, state.txapelketak, "— Aukeratu —", "Txapelketa_ID", "Izena", nodes.mKarreraTxap && nodes.mKarreraTxap.value);

        renderStats();
        renderTxapelketak();
        renderKarrerak();
        renderPorralariak();
        renderTxirrindulariak();
        renderDashboardRanking();
        renderSailkapenak();

        if (meta && meta.db_path) {
            console.info("DB active:", meta.db_path, meta.tables || []);
        }
    }

    async function addTxapelketa() {
        const Izena = (nodes.mTxapIzena.value || "").trim();
        const Urtea = Number(nodes.mTxapUrtea.value);
        if (!Izena || !Urtea) return showToast("Izena eta urtea behar dira", "err");
        await api("/api/txapelketak", { method: "POST", body: JSON.stringify({ Izena, Urtea }) });
        nodes.mTxapIzena.value = "";
        nodes.mTxapUrtea.value = "";
        showToast("Txapelketa gehituta");
        await reloadData();
    }

    async function addPorralaria() {
        const Izena = (nodes.mPorraIzena.value || "").trim();
        if (!Izena) return showToast("Izena behar da", "err");
        await api("/api/porralariak", { method: "POST", body: JSON.stringify({ Izena, Zenbat_Porra: 1 }) });
        nodes.mPorraIzena.value = "";
        showToast("Porralaria gehituta");
        await reloadData();
    }

    async function addTxirrindularia() {
        const Izena = (nodes.mTxirriIzena.value || "").trim();
        if (!Izena) return showToast("Izena behar da", "err");
        await api("/api/txirrindulariak", { method: "POST", body: JSON.stringify({ Izena }) });
        nodes.mTxirriIzena.value = "";
        showToast("Txirrindularia gehituta");
        await reloadData();
    }

    async function addKarrera() {
        const Txapelketa_ID = nodes.mKarreraTxap.value;
        const Izena = (nodes.mKarreraIzena.value || "").trim();
        const Urtea = Number(nodes.mKarreraUrtea.value);
        if (!Txapelketa_ID || !Izena || !Urtea) return showToast("Txapelketa, izena eta urtea behar dira", "err");
        await api("/api/karrerak", { method: "POST", body: JSON.stringify({ Txapelketa_ID, Izena, Urtea }) });
        nodes.mKarreraIzena.value = "";
        nodes.mKarreraUrtea.value = "";
        showToast("Karrera gehituta");
        await reloadData();
    }

    function bindEvents() {
        nodes.navItems.forEach((item) => item.addEventListener("click", () => setActiveSection(item.dataset.section)));
        nodes.tabs.forEach((tab) => tab.addEventListener("click", () => setActiveTab(tab.dataset.sltab)));

        if (nodes.dashTxapSel) nodes.dashTxapSel.addEventListener("change", renderDashboardRanking);
        if (nodes.sailTxapSel) nodes.sailTxapSel.addEventListener("change", renderSailkapenak);
        if (nodes.sailSearch) nodes.sailSearch.addEventListener("input", renderSailkapenak);
        if (nodes.porraSearch) nodes.porraSearch.addEventListener("input", renderPorralariak);
        if (nodes.txirriSearch) nodes.txirriSearch.addEventListener("input", renderTxirrindulariak);

        if (nodes.mTxapBtn) nodes.mTxapBtn.addEventListener("click", (event) => { event.preventDefault(); addTxapelketa().catch((error) => showToast(error.message, "err")); });
        if (nodes.mPorraBtn) nodes.mPorraBtn.addEventListener("click", (event) => { event.preventDefault(); addPorralaria().catch((error) => showToast(error.message, "err")); });
        if (nodes.mTxirriBtn) nodes.mTxirriBtn.addEventListener("click", (event) => { event.preventDefault(); addTxirrindularia().catch((error) => showToast(error.message, "err")); });
        if (nodes.mKarreraBtn) nodes.mKarreraBtn.addEventListener("click", (event) => { event.preventDefault(); addKarrera().catch((error) => showToast(error.message, "err")); });

        if (nodes.dropZone) {
            nodes.dropZone.addEventListener("click", () => nodes.csvFileInput && nodes.csvFileInput.click());
            nodes.dropZone.addEventListener("dragover", (event) => { event.preventDefault(); nodes.dropZone.classList.add("drag-over"); });
            nodes.dropZone.addEventListener("dragleave", () => nodes.dropZone.classList.remove("drag-over"));
            nodes.dropZone.addEventListener("drop", (event) => {
                event.preventDefault();
                nodes.dropZone.classList.remove("drag-over");
                const file = event.dataTransfer.files[0];
                if (file) handleCsvFile(file);
            });
        }

        if (nodes.csvFileInput) {
            nodes.csvFileInput.addEventListener("change", () => {
                const file = nodes.csvFileInput.files && nodes.csvFileInput.files[0];
                if (file) handleCsvFile(file);
            });
        }

        if (nodes.csvClearBtn) nodes.csvClearBtn.addEventListener("click", (event) => { event.preventDefault(); state.csv = null; renderCsvPreview(); if (nodes.csvResult) nodes.csvResult.style.display = "none"; if (nodes.csvFileInput) nodes.csvFileInput.value = ""; });
        if (nodes.csvImportBtn) nodes.csvImportBtn.addEventListener("click", (event) => { event.preventDefault(); importCsv().catch((error) => showToast(error.message, "err")); });
        if (nodes.csvType) nodes.csvType.addEventListener("change", () => { if (state.csv) state.csv.type = nodes.csvType.value; renderCsvPreview(); });
    }

    function handleCsvFile(file) {
        const reader = new FileReader();
        reader.onload = () => {
            const type = nodes.csvType ? nodes.csvType.value : "porralariak";
            const rows = parseCsv(String(reader.result || ""), type).map((row) => {
                if (type === "porralariak" || type === "txirrindulariak") {
                    return { izena: row.izena || row.Izena || row.name || "" };
                }
                if (type === "txapelketak") {
                    return { izena: row.izena || row.Izena || "", urtea: row.urtea || row.Urtea || "" };
                }
                return {
                    txapelketa_id: row.txapelketa_id || row.Txapelketa_ID || "",
                    izena: row.izena || row.Izena || "",
                    urtea: row.urtea || row.Urtea || "",
                };
            }).filter((row) => Object.values(row).some((value) => String(value).trim() !== ""));
            setCsvState(type, rows);
        };
        reader.onerror = () => showToast("Ezin izan da fitxategia irakurri", "err");
        reader.readAsText(file, "utf-8");
    }

    function init() {
        bindEvents();
        setActiveSection("dashboard");
        setActiveTab("porralariak");
        reloadData().catch((error) => showToast(error.message, "err"));
    }

    document.addEventListener("DOMContentLoaded", init);
})();
"""


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


def db_meta():
    with get_db() as con:
        tables = [
            row[0]
            for row in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
        ]
    return {
        "db_path": str(DB_PATH.resolve()),
        "db_exists": DB_PATH.exists(),
        "tables": tables,
    }


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

        elif path == "/api/sariak":
            with get_db() as c:
                self.send_json(rows(c, 'SELECT * FROM "Sariak" ORDER BY Txapelketa_ID DESC, Posizioa ASC'))

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
                izena = (data.get("Izena") or "").strip()
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
                izena = (data.get("Izena") or "").strip()
                urtea = data.get("Urtea")
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
