"""Build the plain course report (Assignment 3 structure) from report.md.

    .venv/bin/python paper/regular/make_report.py

Writes paper/regular/Report.docx and, if LibreOffice is installed, paper/regular/Report.pdf.
The look is set here: Times New Roman throughout, black headings, A4 with 2.2 cm margins and
page numbers. Numbers, the equation and highlights are plain Word features, so the file also
imports cleanly into Google Docs.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIGURES = HERE.parent / "figures"
SOFFICE = Path("/Applications/LibreOffice.app/Contents/MacOS/soffice")
FONT = "Times New Roman"

FOOTER = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
          '<w:ftr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
          '<w:p><w:pPr><w:jc w:val="center"/></w:pPr>'
          '<w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:instrText xml:space="preserve"> PAGE </w:instrText></w:r>'
          '<w:r><w:fldChar w:fldCharType="separate"/></w:r><w:r><w:t>1</w:t></w:r><w:r><w:fldChar w:fldCharType="end"/></w:r>'
          '</w:p></w:ftr>')

# Paragraph and run settings per style: (size in half points, bold, space before, space after, extra).
STYLES = {
    "Normal": (21, None, None, None, ""),
    "BodyText": (21, None, 0, 80, '<w:jc w:val="both"/>'),
    "FirstParagraph": (21, None, 0, 80, '<w:jc w:val="both"/>'),
    "Compact": (19, None, 0, 20, '<w:jc w:val="left"/>'),
    "Title": (36, True, 0, 60, '<w:jc w:val="center"/>'),
    "Subtitle": (26, False, 0, 120, '<w:jc w:val="center"/>'),
    "Author": (22, None, 0, 0, '<w:jc w:val="center"/>'),
    "Date": (22, None, 0, 160, '<w:jc w:val="center"/>'),
    "Heading1": (26, True, 220, 80, ""),
    "Heading2": (22, True, 140, 40, ""),
    "Heading3": (22, True, 120, 40, ""),
    "ImageCaption": (19, None, 20, 120, '<w:jc w:val="center"/>'),
    "TableCaption": (19, None, 120, 40, '<w:jc w:val="center"/>'),
    "Caption": (20, None, 40, 120, '<w:jc w:val="center"/>'),
    "Bibliography": (19, None, 0, 40, ""),
}


def reference_docx(out: Path) -> None:
    """pandoc's default reference.docx, restyled."""
    work = Path(tempfile.mkdtemp())
    default = work / "default.docx"
    default.write_bytes(subprocess.run(["pandoc", "--print-default-data-file", "reference.docx"],
                                       capture_output=True, check=True).stdout)
    unpacked = work / "u"
    with zipfile.ZipFile(default) as z:
        z.extractall(unpacked)

    theme = unpacked / "word/theme/theme1.xml"
    theme.write_text(re.sub(r'<a:latin typeface="[^"]*"', f'<a:latin typeface="{FONT}"', theme.read_text()))

    styles_path = unpacked / "word/styles.xml"
    s = styles_path.read_text()
    s = re.sub(r'<w:rFonts w:asciiTheme="(major|minor)HAnsi"[^>]*/>',
               f'<w:rFonts w:ascii="{FONT}" w:hAnsi="{FONT}" w:eastAsia="{FONT}" w:cs="{FONT}" />', s)
    for sid, (size, bold, before, after, extra) in STYLES.items():
        m = re.search(r'(<w:style [^>]*w:styleId="%s".*?</w:style>)' % sid, s, re.S)
        if not m:
            continue
        st = re.sub(r"<w:(pPr|rPr)\s*/>", "", m.group(1))       # empty placeholders in pandoc's file
        st = re.sub(r'<w:color [^>]*/>', '<w:color w:val="000000" />', st)
        st = re.sub(r'<w:sz w:val="\d+"\s*/>', f'<w:sz w:val="{size}" />', st)
        st = re.sub(r'<w:szCs w:val="\d+"\s*/>', f'<w:szCs w:val="{size}" />', st)
        if "<w:sz " not in st:
            st = st.replace("</w:rPr>", f'<w:sz w:val="{size}" /><w:szCs w:val="{size}" /></w:rPr>', 1) if "<w:rPr>" in st \
                else st.replace("</w:style>", f'<w:rPr><w:sz w:val="{size}" /><w:szCs w:val="{size}" /></w:rPr></w:style>')
        if bold is False:
            st = re.sub(r'<w:b\s*/>|<w:bCs\s*/>', "", st)
        if bold and "<w:b />" not in st and "<w:b/>" not in st:
            st = st.replace("<w:rPr>", "<w:rPr><w:b /><w:bCs />", 1)
        if before is not None:
            # Rebuild the paragraph properties in the order Word requires.
            old = re.search(r"<w:pPr>(.*?)</w:pPr>", st, re.S)
            body = old.group(1) if old else ""
            keep = "".join(t for t in ("<w:keepNext />", "<w:keepLines />") if t.replace(" ", "") in body.replace(" ", ""))
            outline = re.search(r"<w:outlineLvl [^>]*/>", body)
            ppr = (f'<w:pPr>{keep}<w:spacing w:before="{before}" w:after="{after}" />{extra}'
                   f'{outline.group(0) if outline else ""}</w:pPr>')
            st = st.replace(old.group(0), ppr) if old else st.replace("<w:rPr>", ppr + "<w:rPr>", 1)
        s = s.replace(m.group(1), st)
    # Captions in italics are fine; headings must not be coloured anywhere.
    styles_path.write_text(s)

    doc_path = unpacked / "word/document.xml"
    d = doc_path.read_text()
    sect = ('<w:sectPr><w:footerReference w:type="default" r:id="rIdFooter1" />'
            '<w:pgSz w:w="11906" w:h="16838" /><w:pgMar w:top="1247" w:right="1247" w:bottom="1247" w:left="1247" '
            'w:header="708" w:footer="708" w:gutter="0" /></w:sectPr>')
    d = re.sub(r'<w:sectPr.*?</w:sectPr>', sect, d, flags=re.S) if "<w:sectPr" in d else d.replace("</w:body>", sect + "</w:body>")
    doc_path.write_text(d)
    (unpacked / "word/footer1.xml").write_text(FOOTER)
    rels = unpacked / "word/_rels/document.xml.rels"
    rels.write_text(rels.read_text().replace(
        "</Relationships>",
        '<Relationship Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" '
        'Id="rIdFooter1" Target="footer1.xml" /></Relationships>'))
    ct = unpacked / "[Content_Types].xml"
    if "footer1.xml" not in ct.read_text():
        ct.write_text(ct.read_text().replace(
            "</Types>",
            '<Override PartName="/word/footer1.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/></Types>'))

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(unpacked.rglob("*")):
            if f.is_file():
                z.write(f, f.relative_to(unpacked).as_posix())
    shutil.rmtree(work)


MATH_ORDER = ["lit", "nor", "scr", "sty", "brk", "aln"]


def tidy(path: Path) -> None:
    """Fix two things in pandoc's output that strict Word checkers reject: images must be declared by
    type, and the settings inside an equation run must come in schema order."""
    tmp = path.with_suffix(".tmp")
    with zipfile.ZipFile(path) as zin, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "[Content_Types].xml":
                text = data.decode("utf-8")
                if 'Extension="png"' not in text:
                    text = text.replace("<Types ", "<Types ", 1).replace(
                        "</Types>", '<Default Extension="png" ContentType="image/png"/></Types>')
                data = text.encode("utf-8")
            elif item.filename == "word/document.xml":
                text = data.decode("utf-8")

                def order(m: re.Match) -> str:
                    kids = re.findall(r"<m:(\w+)\b[^>]*/>", m.group(1))
                    parts = re.findall(r"<m:\w+\b[^>]*/>", m.group(1))
                    pairs = list(zip(kids, parts))
                    if "nor" in kids:                         # normal text and a style cannot both be set
                        pairs = [kp for kp in pairs if kp[0] not in ("scr", "sty")]
                    ranked = sorted(pairs, key=lambda kp: MATH_ORDER.index(kp[0]) if kp[0] in MATH_ORDER else 99)
                    return "<m:rPr>" + "".join(part for _, part in ranked) + "</m:rPr>"

                text = re.sub(r"<m:rPr>(.*?)</m:rPr>", order, text, flags=re.S)
                data = text.encode("utf-8")
            zout.writestr(item, data)
    tmp.replace(path)


def main() -> None:
    ref = Path(tempfile.mkdtemp()) / "reference.docx"
    reference_docx(ref)
    out = HERE / "Report.docx"
    subprocess.run(["pandoc", str(HERE / "report.md"), "-o", str(out), "--reference-doc", str(ref),
                    "--resource-path", f"{HERE}:{FIGURES}", "--number-sections"], check=True)
    tidy(out)
    print(f"saved {out}")
    if SOFFICE.exists():
        subprocess.run([str(SOFFICE), "--headless", "--convert-to", "pdf", "--outdir", str(HERE), str(out)],
                       check=True, capture_output=True)
        print(f"saved {HERE / 'Report.pdf'}")


if __name__ == "__main__":
    main()
