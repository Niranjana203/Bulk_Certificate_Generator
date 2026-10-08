"""PDF rendering of the single predefined certificate template."""
import os
from datetime import date

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfgen import canvas


def render_certificate(path: str, *, recipient_name: str, title: str, issuer: str,
                       issue_date: date, certificate_id: str) -> None:
    """Draw the certificate and write it to `path` (parent dirs are created)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    width, height = landscape(A4)
    c = canvas.Canvas(path, pagesize=landscape(A4))
    c.setTitle(f"Certificate - {recipient_name}")

    # Double border
    c.setStrokeColor(colors.HexColor("#1F3A5F"))
    c.setLineWidth(6)
    c.rect(25, 25, width - 50, height - 50)
    c.setLineWidth(1.5)
    c.rect(38, 38, width - 76, height - 76)

    cx = width / 2
    c.setFillColor(colors.HexColor("#1F3A5F"))
    c.setFont("Helvetica-Bold", 38)
    c.drawCentredString(cx, height - 130, "CERTIFICATE OF COMPLETION")

    c.setFillColor(colors.black)
    c.setFont("Helvetica", 16)
    c.drawCentredString(cx, height - 185, "This is to certify that")

    c.setFont("Helvetica-Bold", 34)
    c.drawCentredString(cx, height - 245, recipient_name)
    name_w = c.stringWidth(recipient_name, "Helvetica-Bold", 34)
    c.setLineWidth(1)
    c.line(cx - name_w / 2 - 20, height - 255, cx + name_w / 2 + 20, height - 255)

    c.setFont("Helvetica", 16)
    c.drawCentredString(cx, height - 300, "has successfully completed")
    c.setFont("Helvetica-Bold", 24)
    c.drawCentredString(cx, height - 340, title)

    c.setFont("Helvetica", 14)
    c.drawString(80, 90, f"Date: {issue_date.strftime('%d %B %Y')}")
    c.drawRightString(width - 80, 90, f"Issued by: {issuer}")
    c.setFont("Helvetica", 9)
    c.setFillColor(colors.grey)
    c.drawCentredString(cx, 55, f"Certificate ID: {certificate_id}")

    c.showPage()
    c.save()
