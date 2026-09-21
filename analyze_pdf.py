"""Dump the resume PDF's exact layout: page geometry, rendered preview, text spans."""
import sys
import pymupdf

PDF = r"E:\development\AI-Project\直聘简历-未命名.pdf"
OUT_PNG = r"E:\development\AI-Project\_page1.png"
OUT_TXT = r"E:\development\AI-Project\_layout.txt"

def _fmt(bbox):
    return ",".join(f"{v:.1f}" for v in bbox)


doc = pymupdf.open(PDF)

lines = []
lines.append(f"pages={doc.page_count}  metadata={doc.metadata}")
lines.append(f"has_links={len(doc[0].get_links())}")

for pno, page in enumerate(doc):
    r = page.rect
    lines.append("")
    lines.append(f"=== PAGE {pno}  size={r.width:.1f} x {r.height:.1f} pt "
                 f"({r.width/72*25.4:.0f} x {r.height/72*25.4:.0f} mm) ===")

    # embedded images (a resume often carries a headshot)
    for i, img in enumerate(page.get_images(full=True)):
        xref = img[0]
        info = doc.extract_image(xref)
        lines.append(f"  IMAGE #{i} xref={xref} {info['width']}x{info['height']} "
                     f"ext={info['ext']} bytes={len(info['image'])}")

    d = page.get_text("dict")
    for bi, block in enumerate(d["blocks"]):
        if block["type"] != 0:
            lines.append(f"  [block {bi}] type={block['type']} bbox={_fmt(block['bbox'])}")
            continue
        for li, line in enumerate(block["lines"]):
            for si, span in enumerate(line["spans"]):
                if not span["text"].strip():
                    continue
                col = span["color"]
                lines.append(
                    f"  b{bi}.l{li}.s{si} "
                    f"bbox=({span['bbox'][0]:7.1f},{span['bbox'][1]:7.1f},"
                    f"{span['bbox'][2]:7.1f},{span['bbox'][3]:7.1f}) "
                    f"size={span['size']:5.2f} font={span['font']:<28} "
                    f"flags={span['flags']:<3} color=#{col:06x} "
                    f"| {span['text']}"
                )

    pix = page.get_pixmap(matrix=pymupdf.Matrix(2, 2))
    pix.save(OUT_PNG if pno == 0 else OUT_PNG.replace(".png", f"_{pno}.png"))
    lines.append(f"  rendered -> {pix.width}x{pix.height} px")

with open(OUT_TXT, "w", encoding="utf-8") as fh:
    fh.write("\n".join(lines))

print(f"wrote {OUT_TXT} ({len(lines)} lines)")
