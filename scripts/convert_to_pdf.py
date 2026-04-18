import re
from pathlib import Path
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import inch
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.enums import TA_LEFT

RAW_DOCS_DIR = Path(__file__).parent.parent / "data" / "raw_docs"

STYLE = ParagraphStyle(
    name="body",
    fontName="Courier",
    fontSize=10,
    leading=14,
    alignment=TA_LEFT,
    wordWrap="LTR",
)


def clean_text(text: str) -> str:
    lines = text.splitlines()
    cleaned = []
    for line in lines:
        line = re.sub(r"\*\*", "", line)
        line = re.sub(r"^#{1,3}\s*", "", line)
        line = re.sub(r"^-{3,}\s*$", "", line)
        line = re.sub(r"^[-*]\s+", "", line)
        line = line.rstrip()
        cleaned.append(line)
    return "\n".join(cleaned)


def txt_to_pdf(txt_path: Path) -> None:
    pdf_path = txt_path.with_suffix(".pdf")
    raw_text = txt_path.read_text(encoding="utf-8")
    text = clean_text(raw_text)

    doc = SimpleDocTemplate(
        str(pdf_path),
        pagesize=A4,
        leftMargin=inch,
        rightMargin=inch,
        topMargin=inch,
        bottomMargin=inch,
    )

    story = []
    for line in text.splitlines():
        if line.strip() == "":
            story.append(Spacer(1, 10))
        else:
            safe_line = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            story.append(Paragraph(safe_line, STYLE))

    doc.build(story)
    print(f"[OK] {pdf_path.name}")


def main():
    txt_files = sorted(RAW_DOCS_DIR.glob("*.txt"))
    if not txt_files:
        print(f"No .txt files found in {RAW_DOCS_DIR}")
        return
    print(f"Converting {len(txt_files)} files in {RAW_DOCS_DIR}\n")
    for txt_path in txt_files:
        try:
            txt_to_pdf(txt_path)
        except Exception as e:
            print(f"[ERROR] {txt_path.name}: {e}")
    print("\nDone.")


if __name__ == "__main__":
    main()
