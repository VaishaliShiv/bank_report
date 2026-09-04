"""Build the formatted reconciliation workbook.

One responsibility: turn deduplicated vendor-day rows into a styled .xlsx.
Used by both the download endpoint and the daily archive job, so the file a
user downloads is byte-for-byte the process that archives it.
"""
from datetime import date
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo

GREEN = "007560"
RED = "A8261E"
AMBER = "8A5300"
GREY = "6F817E"

HEAD = ["Source", "Vendor", "Date", "Status", "Records (Partner)", "Records (SAP)",
        "Matched", "Anomalies", "Match rate %", "Amount Partner", "Amount SAP",
        "Balance difference", "Missing in SAP", "Missing in Partner",
        "SAP amt high", "Partner amt high", "Duplicates", "Date differences",
        "Runs", "Pipeline summary"]
WIDTHS = [34, 10, 12, 15, 17, 15, 10, 11, 12, 16, 16, 17, 13, 16, 13, 15, 11, 15, 7, 90]
MONEY = "#,##0.00"
COUNT = "#,##0"


def _kpi_sheet(wb, day, rows, k):
    ws = wb.create_sheet("Summary", 0)
    headline = (f"All {k['sources']} sources reconciled" if not k["sourcesNotReconciled"]
                else f"{k['sourcesNotReconciled']} of {k['sources']} sources did not reconcile")
    ws["A1"] = "Payment Reconciliation"
    ws["A1"].font = Font(bold=True, size=16, color=GREEN)
    ws["A2"] = day.strftime("%d %B %Y")
    ws["A2"].font = Font(size=11, color=GREY)
    ws["A4"] = headline
    ws["A4"].font = Font(bold=True, size=13,
                         color=RED if k["sourcesNotReconciled"] else GREEN)

    figures = [
        ("Sources reconciled", f"{k['sourcesReconciled']} of {k['sources']}"),
        ("Records processed", k["records"]),
        ("Records matched", k["matched"]),
        ("Anomalies", k["anomalies"]),
        ("Anomaly rate %", k["anomalyRatePct"]),
        ("Value processed (AED)", k["valuePartner"]),
        ("Value in SAP (AED)", k["valueSap"]),
        ("Balance difference (AED)", k["balanceDifference"]),
    ]
    for i, (label, value) in enumerate(figures, start=6):
        ws.cell(row=i, column=1, value=label).font = Font(bold=True, color=GREY)
        c = ws.cell(row=i, column=2, value=value)
        c.font = Font(bold=True, size=11)
        if isinstance(value, (int, float)):
            c.number_format = MONEY if "AED" in label or "%" in label else COUNT

    note = ws.cell(row=16, column=1)
    if k["figuresVaried"]:
        note.value = ("WARNING: re-runs produced different figures for "
                      + ", ".join(k["figuresVaried"])
                      + ". Latest run shown - verify which is authoritative.")
        note.font = Font(bold=True, color=RED, size=10)
    elif k["rerunsCollapsed"]:
        note.value = (f"{k['rerunsCollapsed']} duplicate run(s) collapsed; latest run "
                      "per source shown. Figures were identical across runs.")
        note.font = Font(italic=True, color=AMBER, size=10)
    else:
        note.value = "No re-runs on this date. Each source reported once."
        note.font = Font(italic=True, color=GREY, size=10)

    ws.column_dimensions["A"].width = 26
    ws.column_dimensions["B"].width = 30
    return ws


def build(day: date, rows: list[dict], kpis: dict) -> BytesIO:
    """Return an in-memory .xlsx for one business date."""
    wb = Workbook()
    wb.remove(wb.active)
    _kpi_sheet(wb, day, rows, kpis)

    ws = wb.create_sheet("Detail")
    ws.append(HEAD)
    for r in rows:
        ws.append([
            r["source"], r["vendorId"], day, r["status"],
            r["recordsPartner"], r["recordsSap"], r["matched"], r["anomalies"],
            r["matchRatePct"], r["amountPartner"], r["amountSap"],
            r["balanceDifference"], r["missingInSap"], r["missingInPartner"],
            r["sapAmountHigh"], r["partnerAmountHigh"], r["duplicates"],
            r["dateDifferences"], r["runCount"], r["summary"],
        ])

    fill = PatternFill("solid", fgColor=GREEN)
    for c in range(1, len(HEAD) + 1):
        cell = ws.cell(row=1, column=c)
        cell.font = Font(bold=True, color="FFFFFF", size=11)
        cell.fill = fill
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.row_dimensions[1].height = 32

    thin = Side(style="thin", color="D5E0DE")
    for row_i in range(2, ws.max_row + 1):
        ws.cell(row=row_i, column=3).number_format = "dd-mmm-yyyy"
        for col in (5, 6, 7, 8, 13, 14, 15, 16, 17, 18, 19):
            ws.cell(row=row_i, column=col).number_format = COUNT
        for col in (9, 10, 11, 12):
            ws.cell(row=row_i, column=col).number_format = MONEY

        status = ws.cell(row=row_i, column=4)
        ok = status.value == "Reconciled"
        status.font = Font(bold=True, color=GREEN if ok else RED)
        status.alignment = Alignment(horizontal="center")

        diff = ws.cell(row=row_i, column=12)
        if diff.value:
            diff.font = Font(bold=True, color=RED)
        anom = ws.cell(row=row_i, column=8)
        if anom.value:
            anom.font = Font(bold=True, color=RED)
        runs = ws.cell(row=row_i, column=19)
        if (runs.value or 0) > 1:
            runs.font = Font(bold=True, color=AMBER)
        ws.cell(row=row_i, column=20).alignment = Alignment(wrap_text=True, vertical="top")
        ws.cell(row=row_i, column=2).alignment = Alignment(horizontal="left")
        for c in range(1, len(HEAD) + 1):
            ws.cell(row=row_i, column=c).border = Border(bottom=thin)

    ref = f"A1:{get_column_letter(len(HEAD))}{ws.max_row}"
    tbl = Table(displayName="ReconciliationDetail", ref=ref)
    tbl.tableStyleInfo = TableStyleInfo(name="TableStyleLight1", showRowStripes=True)
    ws.add_table(tbl)
    for i, w in enumerate(WIDTHS, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A2"

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def filename(day: date) -> str:
    return f"reconciliation_{day.isoformat()}.xlsx"
