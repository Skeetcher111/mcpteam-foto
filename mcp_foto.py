"""MCPteam Фото — бесплатная уникализация фото без ИИ. Пакетно: папка или файлы → N копий каждого
с изменёнными светом, контрастом, резкостью, кадром, наклоном, шумом, сеткой, зеркалом, EXIF и именем.
Каждая копия сверяется по отпечатку (dHash) с оригиналом и прошлыми копиями. Запуск: python mcp_foto.py
Без окна: python mcp_foto.py --cli <папка_или_файлы...> --out <папка> --copies 3"""
import io
import random
import secrets
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageOps

EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".heic"}
try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except ImportError:
    EXT.discard(".heic")

# Что менять и на сколько (доля шкалы). Галочки в окне включают/выключают пункты.
OPTS = {
    "light": ("Яркость", True), "contrast": ("Контраст", True), "color": ("Насыщенность и оттенок", True),
    "sharp": ("Резкость", True), "crop": ("Кадр (приближение)", True), "tilt": ("Наклон 0,5–1,5°", False),
    "mirror": ("Зеркало", False), "grid": ("Невидимая сетка", False), "noise": ("Шум", False),
    "exif": ("Новый EXIF (камера, дата)", False), "rename": ("Имена как с телефона", True),
}
CAMS = [("Apple", "iPhone 13"), ("Apple", "iPhone 14 Pro"), ("Apple", "iPhone 15"), ("samsung", "SM-S918B"),
        ("Xiaomi", "23049PCD8G"), ("HUAWEI", "ELS-NX9")]


def variant(im, rnd, o, power=1.0):
    """Одна копия. o — {ключ: вкл}, power 0.5–2 — сила. Возвращает (jpeg-байты, отчёт)."""
    rep, out, w, h = {}, im, *im.size
    if o.get("crop"):
        k = 1 - rnd.uniform(0.07, 0.10) * power
        cw, ch = round(w * k), round(h * k)
        x, y = rnd.randint(0, w - cw), rnd.randint(0, h - ch)
        out = im.crop((x, y, x + cw, y + ch))
        rep["Кадр"] = f"{(1 - k) * 100:.1f}%"
    if o.get("tilt"):
        a = rnd.choice((-1, 1)) * rnd.uniform(0.5, 1.5) * power
        cw, ch = out.size
        out = out.rotate(a, Image.BICUBIC, expand=False)
        m = 0.02 * power + 0.005  # срезаем углы после поворота
        out = out.crop((round(cw * m), round(ch * m), round(cw * (1 - m)), round(ch * (1 - m))))
        rep["Наклон"] = f"{a:+.1f}°"
    if o.get("mirror"):
        out = ImageOps.mirror(out)
        rep["Зеркало"] = "да"
    z = rnd.uniform(0.97, 0.995)
    out = out.resize((round(w * z), round(h * z)), Image.LANCZOS)
    off = rnd.choice((-1, 1)) * rnd.uniform(0.04, 0.10) * power if o.get("light") else 0
    co = 1 + rnd.choice((-1, 1)) * rnd.uniform(0.04, 0.10) * power if o.get("contrast") else 1
    tint = rnd.uniform(-0.015, 0.015) * power if o.get("color") else 0
    if off or co != 1 or tint:
        luts = []
        for t in (tint, 0, -tint):
            luts += [max(0, min(255, round(((v / 255 - 0.5) * co + 0.5 + off + t) * 255))) for v in range(256)]
        out = out.point(luts)
        rep.update({"Яркость": f"{off * 100:+.1f}%", "Контраст": f"{(co - 1) * 100:+.1f}%"})
    if o.get("color"):
        sa = 1 + rnd.uniform(-0.04, 0.04) * power
        out = ImageEnhance.Color(out).enhance(sa)
        rep["Насыщенность"] = f"{(sa - 1) * 100:+.1f}%"
    if o.get("sharp"):
        sh = 1 + rnd.choice((-1, 1)) * rnd.uniform(0.15, 0.4) * power
        out = ImageEnhance.Sharpness(out).enhance(sh)
        rep["Резкость"] = f"{(sh - 1) * 100:+.0f}%"
    if o.get("grid"):
        g = Image.new("RGBA", out.size, (0, 0, 0, 0))
        d, step, c = ImageDraw.Draw(g), rnd.randint(24, 60), rnd.choice(((255, 255, 255), (0, 0, 0)))
        for x in range(rnd.randint(0, step), out.size[0], step):
            d.line((x, 0, x, out.size[1]), (*c, round(6 * power)))
        for y in range(rnd.randint(0, step), out.size[1], step):
            d.line((0, y, out.size[0], y), (*c, round(6 * power)))
        out = Image.alpha_composite(out.convert("RGBA"), g).convert("RGB")
        rep["Сетка"] = f"шаг {step}"
    if o.get("noise"):
        n = Image.effect_noise(out.size, 40).convert("RGB")
        out = Image.blend(out, n, 0.025 * power)
        rep["Шум"] = f"{2.5 * power:.1f}%"
    q, sub = rnd.randint(86, 95), rnd.choice((0, 2))
    kw = {}
    if o.get("exif"):
        ex, (mk, md) = Image.Exif(), rnd.choice(CAMS)
        ex[0x010F], ex[0x0110] = mk, md
        ex[0x0132] = f"{rnd.randint(2023, 2026)}:{rnd.randint(1, 12):02d}:{rnd.randint(1, 28):02d} {rnd.randint(8, 21):02d}:{rnd.randint(0, 59):02d}:{rnd.randint(0, 59):02d}"
        kw["exif"] = ex.tobytes()
        rep["EXIF"] = f"{mk} {md}"
    buf = io.BytesIO()
    out.save(buf, "JPEG", quality=q, subsampling=sub, optimize=True, **kw)  # без exif= метаданных нет вовсе
    rep.update({"Размер": f"{out.size[0]}x{out.size[1]}", "Качество": q})
    return buf.getvalue(), rep


def dhash(data):
    g = (data if isinstance(data, Image.Image) else Image.open(io.BytesIO(data))).convert("L").resize((9, 8), Image.LANCZOS)
    px = list(g.getdata())
    return sum(1 << i for i, (a, b) in enumerate((px[r * 9 + c], px[r * 9 + c + 1]) for r in range(8) for c in range(8)) if a > b)


def dist(a, b):
    return bin(a ^ b).count("1")


MIN_DIFF, TRIES = 10, 12  # dHash ближе 10 из 64 обычно считают «той же картинкой»


def stamp(rnd):
    return f"IMG_{rnd.randint(2023, 2026)}{rnd.randint(1, 12):02d}{rnd.randint(1, 28):02d}_{rnd.randint(8, 21):02d}{rnd.randint(0, 59):02d}{rnd.randint(0, 59):02d}"


def process(files, out_dir, copies=3, o=None, power=1.0, log=print):
    """Делает copies копий каждого файла в out_dir. Возвращает список (файл, отличие)."""
    o = o or {k: v[1] for k, v in OPTS.items()}
    rnd, out_dir, res = random.Random(secrets.randbits(64)), Path(out_dir), []
    out_dir.mkdir(parents=True, exist_ok=True)
    for f in files:
        f = Path(f)
        try:
            with Image.open(f) as src:
                im = ImageOps.exif_transpose(src).convert("RGB")
        except Exception as e:
            log(f"Пропуск {f.name}: {e}")
            continue
        seen = [dhash(im)]
        for n in range(1, copies + 1):
            best = None
            for _ in range(TRIES):
                data, rep = variant(im, rnd, o, power)
                h = dhash(data)
                d = min(dist(h, s) for s in seen)
                if best is None or d > best[0]:
                    best = (d, data, h, rep)
                if d >= MIN_DIFF:
                    break
            d, data, h, rep = best
            seen.append(h)
            name = (stamp(rnd) if o.get("rename") else f"{f.stem}_{n:02d}") + ".jpg"
            while (out_dir / name).exists():
                name = Path(name).stem + "_1.jpg"
            (out_dir / name).write_bytes(data)
            res.append((name, d))
            log(f"{f.name} -> {name}: отличие {d}/64; " + ", ".join(f"{k} {v}" for k, v in rep.items()))
    return res


def collect(paths):
    out = []
    for p in map(Path, paths):
        out += sorted(x for x in p.iterdir() if x.suffix.lower() in EXT) if p.is_dir() else [p]
    return out


def gui():
    import threading
    import tkinter as tk
    from tkinter import filedialog, ttk

    win = tk.Tk()
    win.title("MCPteam Фото — уникализация фото без ИИ")
    win.geometry("720x620")
    st = {"files": []}
    top = ttk.Frame(win, padding=10)
    top.pack(fill="x")
    lbl = ttk.Label(top, text="Фото не выбраны")
    pick = lambda fs: (st.__setitem__("files", collect(fs)), lbl.config(text=f"Выбрано фото: {len(st['files'])}"))
    ttk.Button(top, text="Выбрать фото…", command=lambda: pick(filedialog.askopenfilenames(filetypes=[("Фото", " ".join("*" + e for e in EXT))]))).pack(side="left")
    ttk.Button(top, text="Выбрать папку…", command=lambda: (d := filedialog.askdirectory()) and pick([d])).pack(side="left", padx=6)
    lbl.pack(side="left", padx=8)
    box = ttk.LabelFrame(win, text="Что менять", padding=10)
    box.pack(fill="x", padx=10)
    vars_ = {}
    for i, (k, (t, on)) in enumerate(OPTS.items()):
        vars_[k] = tk.BooleanVar(value=on)
        ttk.Checkbutton(box, text=t, variable=vars_[k]).grid(row=i // 3, column=i % 3, sticky="w", padx=6, pady=2)
    row = ttk.Frame(win, padding=10)
    row.pack(fill="x")
    ttk.Label(row, text="Копий на фото:").pack(side="left")
    cp = tk.IntVar(value=3)
    ttk.Spinbox(row, from_=1, to=50, textvariable=cp, width=5).pack(side="left", padx=6)
    ttk.Label(row, text="Сила:").pack(side="left", padx=(16, 0))
    pw = tk.DoubleVar(value=1.0)
    ttk.Scale(row, from_=0.5, to=2.0, variable=pw, length=180).pack(side="left", padx=6)
    txt = tk.Text(win, height=16, wrap="word")
    log = lambda s: win.after(0, lambda: (txt.insert("end", s + "\n"), txt.see("end")))

    def run():
        if not st["files"]:
            return log("Сначала выберите фото или папку.")
        out = filedialog.askdirectory(title="Куда сохранить копии")
        if not out:
            return
        go.config(state="disabled")

        def job():
            r = process(st["files"], out, cp.get(), {k: v.get() for k, v in vars_.items()}, pw.get(), log)
            log(f"Готово: {len(r)} копий в {out}")
            win.after(0, lambda: go.config(state="normal"))
        threading.Thread(target=job, daemon=True).start()
    go = ttk.Button(row, text="Сделать копии", command=run)
    go.pack(side="right")
    txt.pack(fill="both", expand=True, padx=10, pady=(0, 10))
    log("Бесплатно, без интернета и без ИИ. Оригиналы не меняются. mcpteam.ru/foto/")
    win.mainloop()


if __name__ == "__main__":
    a = sys.argv[1:]
    if a and a[0] == "--cli":
        a = a[1:]
        out = a[a.index("--out") + 1] if "--out" in a else "unique"
        n = int(a[a.index("--copies") + 1]) if "--copies" in a else 3
        srcs = [x for i, x in enumerate(a) if not x.startswith("--") and (i == 0 or a[i - 1] not in ("--out", "--copies"))]
        r = process(collect(srcs), out, n)
        assert r and all(d >= 0 for _, d in r)
    else:
        gui()
