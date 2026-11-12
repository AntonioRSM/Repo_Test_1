#!/usr/bin/env python3
"""Genera il PDF 'AML_società personalizzato Workspace Srl'.

Uso:
  python build_report.py --dati dati.json --out AML_societa_Workspace_Srl.pdf

Il layout si ispira al report Cribis Advisor Antiriciclaggio, con sezioni proprie:
sintesi decisionale, indicatori di bilancio pluriennali, solidità patrimoniale,
anomalie finanziarie, titolari effettivi, screening, rischio riciclaggio con
scoring trasparente e piano di verifica rafforzata.
"""
import argparse
import json
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

NAVY = colors.HexColor("#1F1F5C")
ORANGE = colors.HexColor("#E8752A")
GREY = colors.HexColor("#5B5B66")
LIGHT = colors.HexColor("#F1F2F5")
RISK_COLORS = {
    "BASSO": colors.HexColor("#2E9E4F"),
    "INTERMEDIO": colors.HexColor("#E0A800"),
    "ALTO": colors.HexColor("#C0392B"),
}
RISK_LABEL = {
    "BASSO": "Verde - verifica ordinaria",
    "INTERMEDIO": "Giallo - verifica rafforzata",
    "ALTO": "Rosso - verifica rafforzata con valutazione di segnalazione",
}

ss = getSampleStyleSheet()
H1 = ParagraphStyle("H1", parent=ss["Heading1"], fontName="Helvetica-Bold", fontSize=18, textColor=GREY, spaceAfter=6)
H2 = ParagraphStyle("H2", parent=ss["Heading2"], fontName="Helvetica-Bold", fontSize=12.5, textColor=NAVY, spaceBefore=8, spaceAfter=4)
BODY = ParagraphStyle("BODY", parent=ss["BodyText"], fontName="Helvetica", fontSize=8.8, leading=11.5, alignment=TA_LEFT)
SMALL = ParagraphStyle("SMALL", parent=BODY, fontSize=7.4, leading=9.4, textColor=GREY)
CELL = ParagraphStyle("CELL", parent=BODY, fontSize=8, leading=9.6)
CELLB = ParagraphStyle("CELLB", parent=CELL, fontName="Helvetica-Bold")


def eur(v):
    return f"€ {v:,.0f}".replace(",", ".")


def pct(v):
    return f"{v:.1f}%".replace(".", ",")


def tbl(rows, widths, header=True):
    data = [[Paragraph(str(c), CELLB if (header and i == 0) else CELL) for c in r] for i, r in enumerate(rows)]
    t = Table(data, colWidths=widths, repeatRows=1 if header else 0)
    style = [
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#D5D7DE")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    if header:
        style.append(("BACKGROUND", (0, 0), (-1, 0), LIGHT))
    t.setStyle(TableStyle(style))
    return t


# ---------- indicatori ----------

def indicatori(bil):
    out = []
    for i, b in enumerate(bil):
        prev = bil[i - 1] if i else None
        crescita = ((b["ricavi"] / prev["ricavi"]) - 1) * 100 if prev else None
        out.append({
            "anno": b["anno"],
            "ricavi": b["ricavi"],
            "crescita": crescita,
            "ebitda_margin": b["ebitda"] / b["ricavi"] * 100 if b["ricavi"] else 0,
            "roe": b["utile_netto"] / b["patrimonio_netto"] * 100 if b["patrimonio_netto"] > 0 else None,
            "indice_liquidita": b["liquidita_immediate"] / b["debiti_breve"] if b["debiti_breve"] else None,
            "indebitamento": (b["attivo_totale"] - b["patrimonio_netto"]) / b["patrimonio_netto"] if b["patrimonio_netto"] > 0 else None,
            "patrimonio_su_attivo": b["patrimonio_netto"] / b["attivo_totale"] * 100 if b["attivo_totale"] else 0,
            "oneri_su_ebitda": b["oneri_finanziari"] / b["ebitda"] * 100 if b["ebitda"] else None,
        })
    return out


def cagr(bil):
    if len(bil) < 2 or bil[0]["ricavi"] <= 0:
        return None
    n = bil[-1]["anno"] - bil[0]["anno"]
    return ((bil[-1]["ricavi"] / bil[0]["ricavi"]) ** (1 / n) - 1) * 100 if n else None


# ---------- anomalie e scoring ----------

def anomalie(d, ind):
    """Regole trasparenti. Ritorna lista di (gravita, descrizione, peso)."""
    res = []
    bil = d["bilanci"]
    last = ind[-1]
    if d["eventi"]["protesti"] or d["eventi"]["procedure_concorsuali"] or d["eventi"]["misure_protettive"]:
        res.append(("CRITICA", "Protesti, procedure o misure protettive rilevate", 40))
    if d["screening"]["sanzioni_uif_eu_onu"] != "nessun riscontro":
        res.append(("CRITICA", "Riscontro in liste sanzionatorie o UIF", 50))
    if any(s.get("pep") for s in d["soci"]) or d["screening"]["pep_soci_amministratori"] != "nessun riscontro":
        res.append(("ALTA", "Esponente politicamente esposto (PEP) o riscontro in screening", 25))
    for x in ind:
        if x["crescita"] is not None and x["crescita"] > 40:
            res.append(("MEDIA", f"Crescita ricavi {pct(x['crescita'])} nel {x['anno']} da verificare", 8))
    for x in ind:
        if x["roe"] is None:
            res.append(("ALTA", f"Patrimonio netto non positivo nel {x['anno']}", 20))
    if last["indice_liquidita"] is not None and last["indice_liquidita"] < 0.5:
        res.append(("ALTA", f"Indice di liquidità immediata basso ({last['indice_liquidita']:.2f})", 15))
    if last["oneri_su_ebitda"] is not None and last["oneri_su_ebitda"] > 15:
        res.append(("MEDIA", f"Oneri finanziari pari al {pct(last['oneri_su_ebitda'])} dell'EBITDA", 8))
    for b in bil:
        if not b.get("depositato", True):
            res.append(("ALTA", f"Bilancio {b['anno']} non depositato", 15))
    addetti_ultimo = d["azienda"]["addetti"][-1]["medio"]
    if last["ricavi"] / max(addetti_ultimo, 1) > 150000:
        res.append(("MEDIA", "Ricavi per addetto anomali rispetto al settore", 6))
    if d["eventi"]["cessazioni_cariche_collegate_ultimi_5a"] >= 2:
        res.append(("ALTA", "Cessazioni ripetute di cariche collegate ai soci", 15))
    if d["eventi"]["pratiche_registro_ultimi_12m"] >= 6:
        res.append(("MEDIA", "Numero elevato di pratiche al Registro Imprese negli ultimi 12 mesi", 8))
    for am in d["screening"].get("adverse_media", []):
        if am.get("valutazione") not in ("neutra", "positiva"):
            res.append(("ALTA", f"Notizia negativa: {am.get('sintesi', '')}", 20))
    return res


def scoring(anom):
    score = min(100, sum(p for _, _, p in anom))
    critica = any(g == "CRITICA" for g, _, _ in anom)
    if critica or score > 60:
        livello = "ALTO"
    elif score >= 25:
        livello = "INTERMEDIO"
    else:
        livello = "BASSO"
    return score, livello


# ---------- PDF ----------

def build(d, out_path):
    bil = d["bilanci"]
    ind = indicatori(bil)
    anom = anomalie(d, ind)
    score, livello = scoring(anom)
    profilo = d.get("profilo", "medium")
    fonte = d.get("fonte", "")
    az = d["azienda"]

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(GREY)
        canvas.drawString(15 * mm, 9 * mm, f"AML società - {az['denominazione']} - {fonte} - profilo {profilo}")
        canvas.drawRightString(A4[0] - 15 * mm, 9 * mm, f"Pag. {doc.page}")
        canvas.restoreState()

    doc = SimpleDocTemplate(out_path, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm,
                            topMargin=15 * mm, bottomMargin=16 * mm,
                            title=f"AML società - {az['denominazione']}", author="Verifica AML")
    s = []

    # Intestazione
    banner = Table([[Paragraph(
        f"<font color='white'><b>AML SOCIETÀ</b> &nbsp;|&nbsp; Valutazione rischio riciclaggio<br/>"
        f"<font size='8'>Profilo di ricerca: {profilo.upper()} &nbsp;|&nbsp; Fonte: {fonte}</font></font>",
        ParagraphStyle("b", parent=BODY, fontSize=12, leading=15))]], colWidths=[180 * mm])
    banner.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), NAVY), ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8), ("LEFTPADDING", (0, 0), (-1, -1), 10)]))
    s += [banner, Spacer(1, 4 * mm)]
    s.append(Paragraph(f"<b>{az['denominazione']}</b><br/>C.F. {az['codice_fiscale']} &nbsp; P.IVA {az['partita_iva']} &nbsp; REA {az['rea']}<br/>{az['sede_legale']}", BODY))
    s.append(Spacer(1, 4 * mm))

    # 1. Sintesi decisionale
    s.append(Paragraph("1. Sintesi decisionale", H2))
    box = Table([[Paragraph(f"<font color='white'><b>{RISK_LABEL[livello]}</b></font>", ParagraphStyle("r", parent=BODY, fontSize=13, leading=16, alignment=1))],
                 [Paragraph(f"Scoring rischio riciclaggio: <b>{score}/100</b> &nbsp;|&nbsp; Anomalie rilevate: <b>{len(anom)}</b> &nbsp;|&nbsp; Critiche: <b>{sum(1 for g,_,_ in anom if g=='CRITICA')}</b>", ParagraphStyle("r2", parent=BODY, alignment=1))]],
                colWidths=[180 * mm])
    box.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), RISK_COLORS[livello]), ("BACKGROUND", (0, 1), (-1, 1), LIGHT), ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
    s += [box, Spacer(1, 3 * mm)]
    ultimo = ind[-1]
    s.append(Paragraph(
        f"Ultimo esercizio disponibile ({ultimo['anno']}): ricavi {eur(ultimo['ricavi'])}, EBITDA margin {pct(ultimo['ebitda_margin'])}, "
        f"patrimonio netto/attivo {pct(ultimo['patrimonio_su_attivo'])}, liquidità immediata/debiti a breve {ultimo['indice_liquidita']:.2f}. "
        f"CAGR ricavi nel periodo: {pct(cagr(bil)) if cagr(bil) is not None else 'n.d.'}. "
        "Il livello indicato è un supporto alla valutazione: le conclusioni definitive spettano al soggetto obbligato, che deve verificare e documentare gli elementi.", BODY))

    # 2. Scheda identificativa
    s.append(Paragraph("2. Scheda identificativa e struttura", H2))
    s.append(tbl([
        ["Campo", "Valore", "Campo", "Valore"],
        ["Forma giuridica", az["forma_giuridica"], "Stato", az["stato_attivita"]],
        ["Costituzione", az["data_costituzione"], "Capitale sociale", eur(az["capitale_sociale_eur"])],
        ["ATECO 2025", az["ateco_2025"], "Addetti (ultimo anno)", str(az["addetti"][-1]["medio"])],
        ["PEC", az["pec"], "Sede legale", az["sede_legale"]],
    ], [32 * mm, 58 * mm, 32 * mm, 58 * mm]))
    s.append(Spacer(1, 2 * mm))
    s.append(tbl([["Socio / amministratore", "C.F.", "Quota", "Carica", "PEP"]] +
                 [[x["nome"], x["codice_fiscale"], pct(x["quota_pct"]), x["carica"], "No" if not x.get("pep") else "Sì"] for x in d["soci"]],
                 [52 * mm, 42 * mm, 18 * mm, 48 * mm, 20 * mm]))

    # 3. Titolari effettivi
    s.append(Paragraph("3. Titolari effettivi", H2))
    s.append(tbl([["Titolare effettivo", "Criterio", "Quota"]] +
                 [[t["nome"], t["criterio"], pct(t["quota_pct"])] for t in d["titolari_effettivi"]],
                 [70 * mm, 80 * mm, 30 * mm]))
    s.append(Paragraph("Identificazione automatica: da verificare con documenti e dichiarazione del cliente.", SMALL))

    # 4. Indicatori pluriennali
    s.append(Paragraph("4. Indicatori di bilancio pluriennali", H2))
    rows = [["Anno", "Ricavi", "Crescita", "EBITDA %", "ROE", "Liquidità/Deb. BT", "Debito/PN", "Oneri/EBITDA"]]
    for x in ind:
        rows.append([
            str(x["anno"]), eur(x["ricavi"]),
            pct(x["crescita"]) if x["crescita"] is not None else "-",
            pct(x["ebitda_margin"]),
            pct(x["roe"]) if x["roe"] is not None else "n.s.",
            f"{x['indice_liquidita']:.2f}" if x["indice_liquidita"] is not None else "-",
            f"{x['indebitamento']:.2f}" if x["indebitamento"] is not None else "n.s.",
            pct(x["oneri_su_ebitda"]) if x["oneri_su_ebitda"] is not None else "-",
        ])
    s.append(tbl(rows, [14 * mm, 26 * mm, 20 * mm, 20 * mm, 20 * mm, 30 * mm, 26 * mm, 24 * mm]))
    s.append(Paragraph("Indici calcolati dai dati di bilancio depositati. n.s. = non significativo (patrimonio netto non positivo).", SMALL))

    # 5. Solidità patrimoniale
    s.append(Paragraph("5. Solidità patrimoniale e tendenza", H2))
    s.append(tbl([["Anno", "Patrimonio netto", "Attivo totale", "Debiti a breve", "Liquidità immediate"]] +
                 [[str(b["anno"]), eur(b["patrimonio_netto"]), eur(b["attivo_totale"]), eur(b["debiti_breve"]), eur(b["liquidita_immediate"])] for b in bil],
                 [18 * mm, 42 * mm, 42 * mm, 40 * mm, 38 * mm]))

    # 6. Anomalie
    s.append(Paragraph("6. Anomalie finanziarie e segnali di rischio", H2))
    if anom:
        rows = [["Gravità", "Anomalia", "Peso"]] + [[g, desc, str(p)] for g, desc, p in sorted(anom, key=lambda x: -x[2])]
        s.append(tbl(rows, [26 * mm, 136 * mm, 18 * mm]))
    else:
        s.append(Paragraph("Nessuna anomalia rilevata dalle regole automatiche.", BODY))

    # 7. Eventi, catasto, screening
    s.append(Paragraph("7. Eventi, patrimonio immobiliare e screening", H2))
    e = d["eventi"]
    s.append(tbl([
        ["Verifica", "Esito"],
        ["Protesti / procedure concorsuali / misure protettive", f"{e['protesti']} / {e['procedure_concorsuali']} / {e['misure_protettive']}"],
        ["Pratiche al Registro Imprese (12 mesi)", str(e["pratiche_registro_ultimi_12m"])],
        ["Sanzioni UIF, UE, ONU", d["screening"]["sanzioni_uif_eu_onu"]],
        ["PEP tra soci e amministratori", d["screening"]["pep_soci_amministratori"]],
        ["Immobili catastali (comm./resid./terreni)", f"{d['catasto']['immobili_commerciali']} / {d['catasto']['immobili_residenziali']} / {d['catasto']['terreni']}"],
    ], [100 * mm, 80 * mm]))
    for am in d["screening"].get("adverse_media", []):
        s.append(Paragraph(f"Adverse media {am['data']} - {am['fonte']}: {am['sintesi']} (valutazione: {am['valutazione']})", SMALL))

    # 8. Deep search
    dw = d.get("web_deep_search", {})
    s.append(Paragraph("8. Ricerca web approfondita (deep search)", H2))
    if dw.get("eseguita"):
        s.append(Paragraph(f"Query eseguite: {dw.get('query_eseguite', 0)}. Siti visionati con browser e analisi visiva: {', '.join(dw.get('siti_visionati', []))}. {dw.get('note', '')}", BODY))
    else:
        s.append(Paragraph("Ricerca web non eseguita nel profilo selezionato.", BODY))

    # 9. Piano di verifica rafforzata
    s.append(Paragraph("9. Piano di verifica e azioni", H2))
    azioni = {
        "BASSO": ["Verifica ordinaria dell'identità e dello scopo del rapporto", "Aggiornamento della valutazione secondo la periodicità della classe di rischio"],
        "INTERMEDIO": ["Acquisizione della fonte del patrimonio e dei fondi", "Verifica documentale dei bilanci non ancora confrontati", "Approvazione del responsabile AML prima dell'avvio"],
        "ALTO": ["Approfondimento rafforzato su titolari effettivi, fonti dei fondi e scopo", "Valutazione di una eventuale segnalazione di operazione sospetta", "Decisione motivata del responsabile AML e conservazione della documentazione"],
    }[livello]
    for a in azioni:
        s.append(Paragraph(f"• {a}", BODY))

    # 10. Fonti e metodo
    s.append(Paragraph("10. Fonti, metodo e limiti", H2))
    for f in d.get("fonti", []):
        s.append(Paragraph(f"• {f}", SMALL))
    if d.get("errori_fetch"):
        s.append(Paragraph("Endpoint non disponibili: " + "; ".join(f"{x['endpoint']} ({x['errore']})" for x in d["errori_fetch"]), SMALL))
    s.append(Spacer(1, 2 * mm))
    s.append(Paragraph(
        f"Generato il {d.get('generato_il', '')}. Lo scoring è trasparente: somma dei pesi delle anomalie, con livello ALTO se presente una anomalia critica o punteggio oltre 60, "
        "INTERMEDIO da 25 a 60, BASSO sotto 25. Le informazioni provengono da banche dati e fonti pubbliche e non sostituiscono la verifica del soggetto obbligato.", SMALL))

    doc.build(s, onFirstPage=footer, onLaterPages=footer)
    return {"livello": livello, "score": score, "anomalie": len(anom)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dati", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    d = json.loads(Path(a.dati).read_text(encoding="utf-8"))
    esito = build(d, a.out)
    print(f"PDF creato: {a.out} | livello {esito['livello']} | score {esito['score']} | anomalie {esito['anomalie']}")


if __name__ == "__main__":
    main()
