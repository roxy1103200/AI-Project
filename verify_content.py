# -*- coding: utf-8 -*-
"""Character-level diff between the rebuilt .docx and the source PDF text."""
import re
import sys

import pymupdf
from docx import Document
from docx.oxml.ns import qn

HERE = r"E:\development\AI-Project"
PDF = HERE + r"\直聘简历-未命名.pdf"
DOCX = HERE + r"\直聘简历-未命名.docx"


def norm(s):
    """Drop all whitespace; unify the quote/dash variants Word may swap."""
    s = s.replace("\u00a0", " ")
    s = re.sub(r"\s+", "", s)
    for a, b in (("\u201c", '"'), ("\u201d", '"'), ("\u2018", "'"), ("\u2019", "'")):
        s = s.replace(a, b)
    return s


def pdf_text():
    doc = pymupdf.open(PDF)
    return norm(doc[0].get_text())


def docx_text():
    doc = Document(DOCX)
    parts = []

    def walk(el):
        for child in el.iter():
            if child.tag == qn("w:t") and child.text:
                parts.append(child.text)

    for p in doc.paragraphs:
        walk(p._p)
    for t in doc.tables:
        for row in t.rows:
            for cell in row.cells:
                for p in cell.paragraphs:
                    walk(p._p)
    return norm("".join(parts))


a, b = pdf_text(), docx_text()
print(f"pdf  chars: {len(a)}")
print(f"docx chars: {len(b)}")

# Reading order differs (PyMuPDF emits the header block last), so compare as
# multisets first: that isolates real content drift from pure ordering noise.
from collections import Counter

ca, cb = Counter(a), Counter(b)
missing = ca - cb          # in the PDF, absent from the docx
extra = cb - ca            # in the docx, absent from the PDF

if not missing and not extra:
    print("\nNO CONTENT DRIFT — every character in the PDF is present in the docx.")
else:
    if missing:
        print(f"\nMISSING from docx: {''.join(sorted(missing.elements()))!r}")
    if extra:
        print(f"\nEXTRA in docx:     {''.join(sorted(extra.elements()))!r}")

if a != b:
    import difflib

    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    print(f"\nordered similarity: {sm.ratio():.6f} (differences below may be ordering only)")
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        if tag in ("delete", "replace"):
            print(f"  -PDF  [{tag}] {a[i1:i2]!r}")
        if tag in ("insert", "replace"):
            print(f"  +DOCX [{tag}] {b[j1:j2]!r}")
