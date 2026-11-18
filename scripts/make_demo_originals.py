"""Regenerate the invented demo originals in src/db/demo_originals/."""
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "src" / "db" / "demo_originals"

REVIEW_LINES = [
    "Brightwater Appliance Co. - Annual Performance Review 2024",
    "Employee: Odalys Brannigan-Voss    Title: Operations Coordinator",
    "Reviewer: Priya Halvorsen, Distribution Manager    Period: Jan-Dec 2024",
    "Overall rating: Exceeds expectations",
    "Odalys rebuilt the daily dispatch board; order-to-ship time fell from 5.2 to 3.4 days.",
    "She trained nine new warehouse hires on the receiving checklist.",
    "Their 30-day error rate was 40 percent below the previous cohort.",
    "Goal for 2025: own the carrier rate review and the parts-shortage playbook.",
]

JOB_DESCRIPTION = """Coordinator, Distribution Operations - Brightwater Appliance Co. (invented posting)

Summary
Run the daily dispatch board and keep orders moving from dock to customer.

Responsibilities
- Sequence open orders by customer deadline and carrier cut-off.
- Keep the shared inventory tracker accurate and reconcile it weekly.
- Train new warehouse hires on the receiving checklist.
- Work with carriers and vendors to resolve delays.

Requirements
- 3+ years in dispatch, warehousing or production scheduling.
- Strong spreadsheet skills; comfortable with warehouse management software.
- Clear written and spoken communication.
"""


def text_pdf(lines):
    esc = lambda s: s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    body = "BT /F1 11 Tf 14 TL 56 740 Td\n" + "\n".join(f"({esc(line)}) Tj T*" for line in lines) + "\nET"
    stream = body.encode("latin-1")
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R"
            b" /Resources << /Font << /F1 5 0 R >> >> >>"
        ),
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out, offsets = b"%PDF-1.4\n", []
    for i, obj in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + obj + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return out


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "performance_review_2024.pdf").write_bytes(text_pdf(REVIEW_LINES))
    (OUT / "job_description_coordinator.txt").write_text(JOB_DESCRIPTION, encoding="utf-8")
    print("wrote", OUT)
