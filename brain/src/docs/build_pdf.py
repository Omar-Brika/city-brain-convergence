#!/usr/bin/env python3
"""
Renders City_Brain_Math_Core_Reasoning.md into
City_Brain_Math_Core_Reasoning.pdf using reportlab (Platypus).

This is a small, purpose-built Markdown-subset renderer -- not a general
Markdown engine -- covering exactly what the source document uses: #/##/###
headers, paragraphs with **bold**/*italic*/`code` inline spans, bullet
lists, numbered lists, horizontal rules, and blockquote-less plain text.
Regenerate with:

    python docs/build_pdf.py
"""
import re
from pathlib import Path

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, ListFlowable, ListItem,
    HRFlowable, PageBreak,
)

HERE = Path(__file__).resolve().parent
SRC = HERE / "City_Brain_Math_Core_Reasoning.md"
OUT = HERE / "City_Brain_Math_Core_Reasoning.pdf"

styles = getSampleStyleSheet()

styles.add(ParagraphStyle(
    name="DocTitle", fontName="Helvetica-Bold", fontSize=22, leading=27,
    spaceAfter=6, textColor=colors.HexColor("#1a1a2e"), alignment=TA_CENTER,
))
styles.add(ParagraphStyle(
    name="DocSubtitle", fontName="Helvetica-Oblique", fontSize=12, leading=16,
    spaceAfter=4, textColor=colors.HexColor("#555566"), alignment=TA_CENTER,
))
styles.add(ParagraphStyle(
    name="H1", fontName="Helvetica-Bold", fontSize=16, leading=20,
    spaceBefore=18, spaceAfter=8, textColor=colors.HexColor("#1a1a2e"),
))
styles.add(ParagraphStyle(
    name="H2", fontName="Helvetica-Bold", fontSize=13, leading=17,
    spaceBefore=14, spaceAfter=6, textColor=colors.HexColor("#2a2a4e"),
))
styles.add(ParagraphStyle(
    name="Body", fontName="Helvetica", fontSize=10.3, leading=14.8,
    spaceAfter=8, alignment=TA_JUSTIFY,
))
styles.add(ParagraphStyle(
    name="BulletBody", fontName="Helvetica", fontSize=10.3, leading=14.8,
    alignment=TA_JUSTIFY,
))
styles.add(ParagraphStyle(
    name="Mono", fontName="Courier", fontSize=9, leading=12.5,
    spaceBefore=4, spaceAfter=8, leftIndent=18,
    backColor=colors.HexColor("#f4f4f8"), borderPadding=6,
))


def inline(text: str) -> str:
    """Convert a Markdown-subset inline span to reportlab's XML-ish markup."""
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    # restore intentional entities we just escaped inside code spans later
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<!\*)\*([^*]+?)\*(?!\*)", r"<i>\1</i>", text)
    text = re.sub(r"`([^`]+?)`", r'<font face="Courier" size="9.5">\1</font>', text)
    text = text.replace("--", "&#8212;")
    return text


def build_story(markdown_text: str):
    lines = markdown_text.split("\n")
    story = []
    i = 0
    n = len(lines)
    title_done = False
    pending_bullets = []

    def flush_bullets():
        nonlocal pending_bullets
        if pending_bullets:
            items = [
                ListItem(Paragraph(inline(b), styles["BulletBody"]), leftIndent=14)
                for b in pending_bullets
            ]
            story.append(ListFlowable(items, bulletType="bullet", start="circle",
                                       leftIndent=18, spaceAfter=8, spaceBefore=2))
            pending_bullets = []

    while i < n:
        line = lines[i].rstrip()

        if not line.strip():
            flush_bullets()
            i += 1
            continue

        if line.strip() == "---":
            flush_bullets()
            story.append(Spacer(1, 4))
            story.append(HRFlowable(width="100%", thickness=0.6,
                                     color=colors.HexColor("#cccccc")))
            story.append(Spacer(1, 8))
            i += 1
            continue

        if line.startswith("# "):
            flush_bullets()
            text = line[2:].strip()
            if not title_done:
                story.append(Paragraph(inline(text), styles["DocTitle"]))
                title_done = True
            else:
                story.append(Paragraph(inline(text), styles["H1"]))
            i += 1
            continue

        if line.startswith("*") and line.endswith("*") and not line.startswith("**"):
            # italic standalone line used as the subtitle/byline
            flush_bullets()
            story.append(Paragraph(inline(line.strip("*")), styles["DocSubtitle"]))
            i += 1
            continue

        if line.startswith("## "):
            flush_bullets()
            story.append(Paragraph(inline(line[3:].strip()), styles["H1"]))
            i += 1
            continue

        if line.startswith("### "):
            flush_bullets()
            story.append(Paragraph(inline(line[4:].strip()), styles["H2"]))
            i += 1
            continue

        if line.strip().startswith("```"):
            flush_bullets()
            i += 1
            code_lines = []
            while i < n and not lines[i].strip().startswith("```"):
                code_lines.append(lines[i])
                i += 1
            i += 1  # skip closing fence
            code_text = "\n".join(code_lines)
            code_text = code_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            code_text = code_text.replace("\n", "<br/>").replace(" ", "&nbsp;")
            story.append(Paragraph(code_text, styles["Mono"]))
            continue

        if line.lstrip().startswith("- ") or line.lstrip().startswith("* "):
            item = line.lstrip()[2:].strip()
            # a bullet item may continue on the next non-blank, non-bullet line
            j = i + 1
            while j < n and lines[j].strip() and not lines[j].lstrip().startswith(("- ", "* ")) \
                    and not lines[j].startswith("#") and lines[j].strip() != "---":
                item += " " + lines[j].strip()
                j += 1
            pending_bullets.append(item)
            i = j
            continue

        if re.match(r"^\d+\.\s", line.strip()):
            flush_bullets()
            # collect the whole numbered block
            num_items = []
            while i < n and re.match(r"^\d+\.\s", lines[i].strip()):
                content = re.sub(r"^\d+\.\s", "", lines[i].strip())
                j = i + 1
                while j < n and lines[j].strip() and not re.match(r"^\d+\.\s", lines[j].strip()) \
                        and not lines[j].startswith("#") and lines[j].strip() != "---":
                    content += " " + lines[j].strip()
                    j += 1
                num_items.append(content)
                i = j
            items = [Paragraph(inline(x), styles["BulletBody"]) for x in num_items]
            story.append(ListFlowable(
                [ListItem(p, leftIndent=14) for p in items],
                bulletType="1", start=1, leftIndent=18, spaceAfter=8,
            ))
            continue

        if line.startswith("|"):
            flush_bullets()
            table_lines = []
            while i < n and lines[i].startswith("|"):
                table_lines.append(lines[i])
                i += 1
            # simple pipe-table -> paragraph fallback (kept rare/short in this doc)
            rows = []
            for tl in table_lines:
                cells = [c.strip() for c in tl.strip("|").split("|")]
                if set("".join(cells)) <= set("-: "):
                    continue
                rows.append(cells)
            if rows:
                from reportlab.platypus import Table, TableStyle
                data = [[Paragraph(inline(c), styles["BulletBody"]) for c in r] for r in rows]
                t = Table(data, hAlign="LEFT")
                t.setStyle(TableStyle([
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eeeef5")),
                    ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 5),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ]))
                story.append(t)
                story.append(Spacer(1, 10))
            continue

        # plain paragraph: gather continuation lines
        para = line
        j = i + 1
        while j < n and lines[j].strip() and not lines[j].startswith("#") \
                and lines[j].strip() != "---" and not lines[j].lstrip().startswith(("- ", "* ")) \
                and not lines[j].startswith("```") and not lines[j].startswith("|"):
            para += " " + lines[j].strip()
            j += 1
        flush_bullets()
        story.append(Paragraph(inline(para), styles["Body"]))
        i = j

    flush_bullets()
    return story


def main():
    md = SRC.read_text()
    doc = SimpleDocTemplate(
        str(OUT), pagesize=LETTER,
        leftMargin=0.9 * inch, rightMargin=0.9 * inch,
        topMargin=0.8 * inch, bottomMargin=0.8 * inch,
        title="City Brain Math Core — Reasoning Document",
        author="City Brain team",
    )
    story = build_story(md)
    doc.build(story)
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
