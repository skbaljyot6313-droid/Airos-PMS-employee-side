"""Salary slip PDF — rendered from the frozen payroll line snapshot.

The slip never recomputes salary: it shows exactly what was calculated and
approved, plus any approved adjustments listed separately.
"""

from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

from app.models.payroll import PayrollAdjustment


def _rows(items: list[dict]) -> list[list[str]]:
    return [[i["label"], f"{float(i['amount']):,.2f}"] for i in items]


def render_slip(*, company_name: str, employee_name: str, employee_uid: str,
                department: str | None, designation: str | None, period: str,
                line_snapshot: dict, line_status: str, payment_date: str | None,
                adjustments: list[PayrollAdjustment], net: str) -> bytes:
    styles = getSampleStyleSheet()
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=16 * mm, bottomMargin=16 * mm,
                            title=f"Salary slip {period} — {employee_name}")
    m = line_snapshot.get("metrics", {})
    story = [
        Paragraph(f"<b>{company_name}</b>", styles["Title"]),
        Paragraph(f"Salary slip for {period}", styles["Heading3"]),
        Spacer(1, 4 * mm),
    ]
    info = Table([
        ["Employee", employee_name, "Employee ID", employee_uid],
        ["Department", department or "—", "Designation", designation or "—"],
        ["Payment status", line_status.title(), "Payment date", payment_date or "—"],
    ], colWidths=[32 * mm, 58 * mm, 32 * mm, 58 * mm])
    info.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, -1), 9),
                              ("TEXTCOLOR", (0, 0), (0, -1), colors.grey),
                              ("TEXTCOLOR", (2, 0), (2, -1), colors.grey)]))
    story += [info, Spacer(1, 4 * mm)]

    attendance = Table([
        ["Present days", m.get("present_days", 0), "Absent days", m.get("absent_days", 0)],
        ["Half days", m.get("half_days", 0), "Late entries", m.get("late_entries", 0)],
        ["Paid leave", m.get("paid_leave_days", 0), "Unpaid leave", m.get("unpaid_leave_days", 0)],
        ["Working hours", m.get("worked_hours", "0"), "Overtime hours", m.get("overtime_hours", "0")],
    ], colWidths=[40 * mm, 45 * mm, 40 * mm, 45 * mm])
    attendance.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, -1), 9),
                                    ("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey)]))
    story += [Paragraph("<b>Attendance</b>", styles["Heading4"]), attendance, Spacer(1, 4 * mm)]

    def _block(title: str, items: list[dict], total_label: str, total: str):
        data = [[title, "Amount (₹)"]] + _rows(items) + [[total_label, f"{float(total):,.2f}"]]
        t = Table(data, colWidths=[120 * mm, 50 * mm])
        t.setStyle(TableStyle([
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EEF3EE")),
            ("ALIGN", (1, 0), (1, -1), "RIGHT"),
            ("LINEABOVE", (0, -1), (-1, -1), 0.5, colors.black),
            ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ]))
        return t

    story.append(_block("Earnings", line_snapshot.get("earnings", []), "Gross earnings",
                        line_snapshot.get("gross", "0")))
    story.append(Spacer(1, 3 * mm))
    story.append(_block("Deductions", line_snapshot.get("deductions", []), "Total deductions",
                        line_snapshot.get("total_deductions", "0")))
    story.append(Spacer(1, 3 * mm))
    if adjustments:
        adj_rows = [[f"Approved adjustment — {a.reason}", f"{float(a.amount):,.2f}"] for a in adjustments]
        story.append(Table([["Adjustments (approved, listed separately)", "Amount (₹)"]] + adj_rows,
                           colWidths=[120 * mm, 50 * mm], style=TableStyle([
                               ("FONTSIZE", (0, 0), (-1, -1), 9),
                               ("ALIGN", (1, 0), (1, -1), "RIGHT")])))
        story.append(Spacer(1, 3 * mm))
    story.append(Paragraph(f"<b>Net salary payable: ₹ {float(net):,.2f}</b>", styles["Heading3"]))
    notes = line_snapshot.get("notes") or []
    if notes:
        story.append(Spacer(1, 3 * mm))
        for n in notes:
            story.append(Paragraph(f"• {n}", styles["Normal"]))
    story.append(Spacer(1, 6 * mm))
    story.append(Paragraph("This is a computer-generated salary slip.", styles["Italic"]))
    doc.build(story)
    return buf.getvalue()
