import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shin-tools"))

from pic_tool import build_layout_map

TARGETS = [
    "a/livec_1",
    "a/livec_2",
    "a/livec_3",
    "q",
    "t",
]

HOU_PNG_DIR = Path("assets/pic-hou")
SUI_PIC_DIR = Path("raw/sui/data/picture")
SUI_OUT_DIR = Path("assets/pic-sui")
CORNER_TOL = 8


def _normalize(entry):
    entry = entry.strip().replace("\\", "/").rstrip("/")
    if entry.lower().endswith(".png") or entry.lower().endswith(".pic"):
        entry = entry[:-4]
    return entry


def expand_targets():
    scope = set()
    for entry in TARGETS:
        rel = _normalize(entry)
        if not rel:
            continue
        target = SUI_PIC_DIR / rel
        if target.is_dir():
            for pic in sorted(target.glob("*.pic")):
                scope.add(f"{rel}/{pic.stem}.png".removeprefix("./"))
        elif target.with_suffix(".pic").is_file():
            scope.add(f"{rel}.png")
        else:
            print(f"[warn] not found in {SUI_PIC_DIR}: {entry}")
    return scope


def corner_bg_color(img):
    w, h = img.size
    corners = (
        img.getpixel((0, 0)),
        img.getpixel((w - 1, 0)),
        img.getpixel((0, h - 1)),
        img.getpixel((w - 1, h - 1)),
    )
    base = corners[0]
    if base[3] == 0:
        return None
    for c in corners[1:]:
        if c[3] == 0:
            return None
        if any(abs(base[i] - c[i]) > CORNER_TOL for i in range(4)):
            return None
    return base


def process(rel, layout):
    target_w, target_h = layout.width, layout.height
    if target_w <= 0 or target_h <= 0:
        return "layout-invalid", None
    with Image.open(HOU_PNG_DIR / rel) as im:
        img = im.convert("RGBA")
    bg = corner_bg_color(img)
    w, h = img.size
    scale = min(target_w / w, target_h / h)
    sw = max(1, round(w * scale))
    sh = max(1, round(h * scale))
    scaled = img.resize((sw, sh), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (target_w, target_h), bg or (0, 0, 0, 0))
    canvas.alpha_composite(scaled, dest=((target_w - sw) // 2, (target_h - sh) // 2))
    out = SUI_OUT_DIR / rel
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out)
    return "ok", bg is not None


def main():
    scope = expand_targets()
    rels = []
    if HOU_PNG_DIR.is_dir():
        for png in sorted(HOU_PNG_DIR.rglob("*.png")):
            rel = png.relative_to(HOU_PNG_DIR).as_posix()
            if rel in scope:
                rels.append(rel)
    layout_map = build_layout_map([str(SUI_PIC_DIR)])
    stats = {"candidates": len(rels), "ok": 0, "bg": 0, "no-sui": 0}
    for rel in rels:
        layout = layout_map.get(rel[:-4] + ".pic")
        if layout is None:
            stats["no-sui"] += 1
            print(f"[skip] no sui layout: {rel}")
            continue
        status, used_bg = process(rel, layout)
        if status == "ok":
            stats["ok"] += 1
            if used_bg:
                stats["bg"] += 1
        else:
            stats["no-sui"] += 1
            print(f"[skip] {status}: {rel}")
    print("done:", stats)


if __name__ == "__main__":
    main()
