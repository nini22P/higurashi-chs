import csv, os, sys, argparse
from PIL import Image, ImageFont, ImageDraw

BG = (71, 112, 76, 0)
FG = (255, 255, 255, 240)
W, H = 960, 480
GAP = 4
LINE_GAP = 8
FONT_SCALE = 0.9


def text_bands(img):
    pix = img.load()
    rows = [y for y in range(img.height) if any(pix[x, y][3] > 0 for x in range(img.width))]
    if not rows:
        return []
    bands, y0 = [], rows[0]
    for i in range(1, len(rows)):
        if rows[i] - rows[i - 1] > GAP:
            bands.append((y0, rows[i - 1]))
            y0 = rows[i]
    bands.append((y0, rows[-1]))
    return bands


def fit_width(text, max_w, max_sz, font_path, min_sz=12):
    lines = text.split("\n") if isinstance(text, str) else text
    lo, hi = min_sz, max_sz
    best = min_sz
    while lo <= hi:
        mid = (lo + hi) // 2
        f = ImageFont.truetype(font_path, mid)
        tw = max(f.getbbox(l.strip())[2] for l in lines)
        if tw <= max_w:
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def draw_text(img, text, y, max_sz, max_w, font_path, outline=0):
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    if not lines:
        return
    w = img.width
    sz = fit_width(lines, max_w, max_sz, font_path)
    font = ImageFont.truetype(font_path, sz)
    lh = font.getbbox("测A")[3] - font.getbbox("测A")[1]
    d = ImageDraw.Draw(img)
    for i, line in enumerate(lines):
        tw = font.getbbox(line)[2]
        x = (w - tw) // 2
        ly = y + i * (lh + LINE_GAP)
        if outline:
            solid = outline * 2 // 3
            d.text((x, ly), line, font=font, fill=FG, stroke_width=outline, stroke_fill=(0, 0, 0, 128), anchor="lt")
            if solid:
                d.text((x, ly), line, font=font, fill=FG, stroke_width=solid, stroke_fill=(0, 0, 0, 255), anchor="lt")
        d.text((x, ly), line, font=font, fill=FG, anchor="lt")


def draw(img, translation, orig_text, font_path):
    bands = text_bands(img)
    qy1, qy2 = bands[0]
    band_h = qy2 - qy1 + 1

    qq = [b for b in bands if b[0] < 99]
    orig_q_h = (qq[-1][1] - qq[0][0] + 1) if len(qq) > 1 else band_h

    base_sz = max(12, int(band_h * FONT_SCALE))

    def erase_and_draw(text, y, max_sz, max_w, ref_h):
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        if not lines:
            return
        sz = fit_width(lines, max_w, max_sz, font_path)
        font = ImageFont.truetype(font_path, sz)
        lh = font.getbbox("测A")[3] - font.getbbox("测A")[1]
        text_h = len(lines) * lh + (len(lines) - 1) * LINE_GAP
        eh = max(text_h, ref_h)
        ey = min(qy1 + eh - 1, H - 1)
        ImageDraw.Draw(img).rectangle([(0, y), (W, ey)], fill=BG)
        draw_text(img, text, y, max_sz, max_w, font_path)

    if "\n\n" in orig_text:
        parts = translation.split("\n\n")
        erase_and_draw(parts[0].strip(), qy1, base_sz, W, orig_q_h)

        if len(parts) > 1:
            large = [b for b in bands if b[0] >= 220]
            if not large:
                large = [b for b in bands[1:] if b[1] - b[0] + 1 > 160]
            if large:
                ly1, ly2 = large[0]
                large_h = ly2 - ly1 + 1
                ImageDraw.Draw(img).rectangle([(0, ly1), (W, ly2)], fill=BG)
                draw_text(img, parts[1].strip(), ly1, max(12, int(large_h * FONT_SCALE)), W, font_path, outline=6)
    else:
        erase_and_draw(translation, qy1, base_sz, W, orig_q_h)

    return img


def main():
    p = argparse.ArgumentParser(description="Draw translation onto quiz images.")
    p.add_argument("--font", required=True)
    p.add_argument("--csv", required=True)
    p.add_argument("--hou-in", required=True)
    p.add_argument("--hou-out", required=True)
    p.add_argument("--sui-out", default=None, help="Enable sui output (qlv0-4 only)")
    args = p.parse_args()

    for path in [args.font, args.csv, args.hou_in]:
        if not os.path.exists(path):
            print(f"not found: {path}")
            sys.exit(1)

    os.makedirs(args.hou_out, exist_ok=True)
    if args.sui_out:
        os.makedirs(args.sui_out, exist_ok=True)

    with open(args.csv, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    ok_hou = ok_sui = 0
    for row in rows:
        translation = row["translation"].strip()
        if not translation:
            continue
        qid = row["file"]

        src = os.path.join(args.hou_in, qid, qid + ".png")
        if not os.path.isfile(src):
            continue

        img = Image.open(src).convert("RGBA")
        draw(img, translation, row["text"], args.font)

        d = os.path.join(args.hou_out, qid)
        os.makedirs(d, exist_ok=True)
        img.save(os.path.join(d, qid + ".png"))
        ok_hou += 1

        if args.sui_out and qid[:4] in ("qlv0", "qlv1", "qlv2", "qlv3", "qlv4"):
            sui_img = img.resize((480, 240), Image.Resampling.LANCZOS)
            canvas = Image.new("RGBA", (480, 242), BG)
            canvas.paste(sui_img, (0, 0))
            d = os.path.join(args.sui_out, qid)
            os.makedirs(d, exist_ok=True)
            canvas.save(os.path.join(d, qid + ".png"))
            ok_sui += 1

    print(f"done: hou={ok_hou}  sui={ok_sui}")


if __name__ == "__main__":
    main()
