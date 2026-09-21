"""Pull the section-header band geometry/colors and the embedded images out of the PDF."""
import os
import pymupdf

PDF = r"E:\development\AI-Project\直聘简历-未命名.pdf"
OUTDIR = r"E:\development\AI-Project\_assets"
os.makedirs(OUTDIR, exist_ok=True)

doc = pymupdf.open(PDF)
page = doc[0]

lines = []

lines.append("=== DRAWINGS / FILLS ===")
for d in page.get_drawings():
    fill = d.get("fill")
    rect = d["rect"]
    lines.append(
        f"  rect=({rect.x0:7.2f},{rect.y0:7.2f},{rect.x1:7.2f},{rect.y1:7.2f}) "
        f"w={rect.width:7.2f} h={rect.height:6.2f} "
        f"fill={fill} stroke={d.get('color')} type={d.get('type')} "
        f"items={[it[0] for it in d['items']]}"
    )

lines.append("")
lines.append("=== FONTS on page ===")
for f in page.get_fonts(full=True):
    lines.append(f"  xref={f[0]} ext={f[1]} type={f[2]} basefont={f[3]} name={f[4]} enc={f[5]}")

lines.append("")
lines.append("=== IMAGES extracted ===")
for i, img in enumerate(page.get_images(full=True)):
    xref = img[0]
    info = doc.extract_image(xref)
    path = os.path.join(OUTDIR, f"img{i}_xref{xref}.{info['ext']}")
    with open(path, "wb") as fh:
        fh.write(info["image"])
    # where is it placed on the page?
    rects = page.get_image_rects(xref)
    lines.append(f"  img{i} xref={xref} {info['width']}x{info['height']} {info['ext']} "
                 f"{len(info['image'])}B -> {os.path.basename(path)}  placed_at={rects}")

with open(r"E:\development\AI-Project\_assets\report.txt", "w", encoding="utf-8") as fh:
    fh.write("\n".join(lines))

print("\n".join(lines))
