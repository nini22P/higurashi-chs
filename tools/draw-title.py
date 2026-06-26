import csv, os, re, unicodedata
from PIL import Image, ImageFont, ImageDraw

SLOTS = 32
HOU_CSV = "higurashi-hou.csv"
HOU_OUT = "assets/txa-hou"
SUI_OUT = "assets/txa-sui"

SECTIONS = [
    ("tips_a",   224, 523,  ["　？？？"], [],  r'^[０１２３４５６７８９]{3}「|」$'),
    ("tips_b",   710, 911,  [],         ["鬼狩柳樱"],  r'^\d{3} '),
    ("kakera_a", 555, 686,  [],         ["｢祭囃篇｣结束","｢澪尽篇･表｣结束","｢碎片世界･尾声｣结束"],  r'^「|」$|／[^．]+'),
    ("kakera_b", 928, 1003, [],         [],  r'^\d{2}「|」$'),
]

PLAN = [
    (["tips_a"],                ["tipsget", "tipsmode"],  ["hou", "sui"],  0),
    (["tips_b"],                ["tipsget", "tipsmode"],  ["hou"],         6),
    (["kakera_a", "kakera_b"],  ["tipsget"],              ["hou"],         0),
    (["kakera_a"],              ["tipsget"],              ["sui"],         0),
]

PROFILES = {
    "tipsget_hou":  {"font_path": "assets/font/NotoSansCJKsc-Medium.otf", "width": 528, "height": 2048, "bg": (71, 112, 76, 0),   "font_size": 52, "text_color": (255, 255, 255, 255), "stroke_width": 4, "stroke_color": (0, 0, 0, 255), "scale_x": 0.85, "offset_y": -1},
    "tipsmode_hou": {"font_path": "assets/font/NotoSansCJKsc-Regular.otf", "width": 640, "height": 2048, "bg": (71, 112, 76, 0),   "font_size": 52, "text_color": (255, 255, 255, 255), "stroke_width": 5, "stroke_color": (0, 0, 0, 255), "scale_x": 0.85, "offset_y": -1},
    "tipsget_sui":  {"font_path": "assets/font/NotoSansCJKsc-Medium.otf", "width": 264, "height": 1016, "bg": (0, 0, 0, 0),        "font_size": 24, "text_color": (255, 255, 255, 255), "stroke_width": 2, "stroke_color": (0, 0, 0, 255), "scale_x": 0.8, "offset_y": 0},
    "tipsmode_sui": {"font_path": "assets/font/NotoSansCJKsc-Regular.otf", "width": 320, "height": 1064, "bg": (0, 0, 0, 0),        "font_size": 24, "text_color": (255, 255, 255, 255), "stroke_width": 2, "stroke_color": (0, 0, 0, 255), "scale_x": 0.8, "offset_y": 0},
}


def slot_bands(h):
    return [(h * i // SLOTS, h * (i + 1) // SLOTS - 1) for i in range(SLOTS)]


def draw_line(img, text, font_path, font_size, text_color, stroke_width, stroke_color, y1, y2, width):
    font = ImageFont.truetype(font_path, font_size)
    cx, cy = width // 2, (y1 + y2) // 2
    d = ImageDraw.Draw(img)
    if stroke_width:
        d.text((cx, cy), text, font=font, fill=text_color, stroke_width=stroke_width, stroke_fill=stroke_color, anchor="mm")
    else:
        d.text((cx, cy), text, font=font, fill=text_color, anchor="mm")


def draw(img, lines, prof):
    bands = slot_bands(prof["height"])
    for (y1, y2), line in zip(bands, lines):
        if not line:
            continue
        draw_line(img, line, prof["font_path"], prof["font_size"], prof["text_color"], prof["stroke_width"], prof["stroke_color"], y1, y2, prof["width"])


def main():
    def safe_int(v):
        try:
            return int(v)
        except:
            return -1

    rows = []
    with open(HOU_CSV, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if row.get("type") != "select_choice":
                continue
            txt = row.get("text", "")
            if not txt or txt in ("戻る", "次へ"):
                continue
            idx = safe_int(row.get("index_hou", ""))
            if idx < 0:
                continue
            tr = row.get("translation", "")
            rows.append((idx, txt, tr))

    BASE = {"hou": HOU_OUT, "sui": SUI_OUT}
    FNAME = {"tipsget": lambda g: f"title_{g:03d}.png", "tipsmode": lambda g: f"title{g}.png"}
    counts = {}

    section_entries = {}
    for sid, lo, hi, front, back, strip_pat in SECTIONS:
        def clean(s, p=strip_pat):
            return re.sub(p, '', s)
        picked = [(idx, txt, tr) for idx, txt, tr in rows if lo <= idx <= hi]
        picked.sort(key=lambda x: x[0])
        def norm(s):
            s = s.replace('．', ' ')
            s = unicodedata.normalize('NFKC', s)
            s = s.replace('「', '｢').replace('」', '｣').replace('・', '･')
            return s
        section_entries[sid] = front + [norm(clean(tr) or clean(txt)) for idx, txt, tr in picked] + back

    for data_ids, modes, platforms, start_gid in PLAN:
        merged = []
        for sid in data_ids:
            merged.extend(section_entries[sid])
        groups = {}
        for i, entry in enumerate(merged):
            gid = start_gid + i // SLOTS
            groups.setdefault(gid, []).append(entry)

        prefix = data_ids[0].split('_')[0]
        for gid in sorted(groups):
            lines = groups[gid]
            for mode in modes:
                folder = prefix + mode[4:]
                for p in platforms:
                    pk = f"{mode}_{p}"
                    out_dir = f"{BASE[p]}/{folder}"
                    os.makedirs(out_dir, exist_ok=True)
                    prof = PROFILES[pk]
                    w, h = prof["width"], prof["height"]
                    if prof["scale_x"] != 1:
                        draw_w = int(w / prof["scale_x"])
                        draw_img = Image.new("RGBA", (draw_w, h), prof["bg"])
                        draw_prof = {**prof, "width": draw_w}
                        draw(draw_img, lines, draw_prof)
                        scaled = draw_img.resize((w, h), Image.Resampling.LANCZOS)
                        img = Image.new("RGBA", (w, h), prof["bg"])
                        img.paste(scaled, (0, prof["offset_y"]))
                    else:
                        img = Image.new("RGBA", (w, h), prof["bg"])
                        draw(img, lines, prof)
                    img.save(os.path.join(out_dir, FNAME[mode](gid)))
                    counts[out_dir] = counts.get(out_dir, 0) + 1

    print("done: " + "  ".join(f"{d}={c}" for d, c in counts.items()))


if __name__ == "__main__":
    main()
