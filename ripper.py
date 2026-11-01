# Tala Ripper GUI (Windows)
# Adds: progress bar, file counter, "Open folder" buttons, logs, failure bin, stop/start.
import os, sys, json, subprocess, shutil, tempfile, uuid, time, re, threading, queue, datetime
from pathlib import Path
from tkinter import Tk, StringVar, BooleanVar, IntVar, ttk, filedialog, Text, END, DISABLED, NORMAL

def which(cmd):
    try:
        return subprocess.run(["where", cmd], capture_output=True, text=True).returncode == 0
    except Exception:
        return False

HAVE_PDFTOTEXT = which("pdftotext")
HAVE_PDFTOPPM  = which("pdftoppm")
HAVE_TESS      = which("tesseract")

try:
    from ebooklib import epub
    from bs4 import BeautifulSoup
except Exception:
    raise SystemExit("Missing deps. Run: pip install ebooklib beautifulsoup4 lxml")

def clean_text(s: str) -> str:
    s = s.replace("\r\n","\n").replace("\r","\n")
    s = re.sub(r"[ \t]+\n", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s

def pdf_to_text(path: Path, ocr_only: bool, lang: str, TMP_DIR: Path):
    if HAVE_PDFTOTEXT and not ocr_only:
        tmp_txt = TMP_DIR / (path.stem + ".pdftotext.txt")
        r = subprocess.run(["pdftotext","-layout","-enc","UTF-8", str(path), str(tmp_txt)],
                           capture_output=True, text=True)
        if r.returncode == 0 and tmp_txt.exists():
            data = tmp_txt.read_text(encoding="utf-8", errors="ignore").strip()
            if len(data) > 30:
                return data
    if not (HAVE_PDFTOPPM and HAVE_TESS):
        raise RuntimeError("Need pdftoppm + tesseract for OCR.")
    ocr_dir = TMP_DIR / f"{path.stem}_ocr"
    if ocr_dir.exists(): shutil.rmtree(ocr_dir)
    ocr_dir.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(["pdftoppm","-png", str(path), str(ocr_dir / "page")],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"pdftoppm failed: {r.stderr}")
    texts = []
    for img in sorted(ocr_dir.glob("page-*.png")):
        out_txt = img.with_suffix("")
        _ = subprocess.run(["tesseract", str(img), str(out_txt), "-l", lang],
                           capture_output=True, text=True)
        f = Path(str(out_txt) + ".txt")
        if f.exists():
            texts.append(f.read_text(encoding="utf-8", errors="ignore"))
    if not texts: raise RuntimeError("OCR produced no text.")
    return "\n".join(texts)

def epub_to_text(path: Path) -> str:
    book = epub.read_epub(str(path))
    parts = []
    for item in book.get_items():
        if item.get_type() == 9:
            try:
                soup = BeautifulSoup(item.get_content(), "lxml")
                for t in soup(["script","style"]): t.decompose()
                parts.append(soup.get_text(separator="\n", strip=True))
            except Exception:
                pass
    return "\n\n".join(p for p in parts if p)

def mobi_to_text(path: Path, TMP_DIR: Path) -> str:
    from kindleunpack.kindleunpack import unpackBook
    work = Path(tempfile.mkdtemp(dir=TMP_DIR)); outdir = work / "ku_out"; outdir.mkdir(exist_ok=True)
    _ = unpackBook(str(path), str(outdir))
    htmls = list(outdir.rglob("*.htm")) + list(outdir.rglob("*.html")) + list(outdir.rglob("*.xhtml"))
    parts = []
    for h in sorted(htmls):
        try:
            soup = BeautifulSoup(h.read_text(encoding="utf-8", errors="ignore"), "lxml")
            for t in soup(["script","style"]): t.decompose()
            parts.append(soup.get_text(separator="\n", strip=True))
        except Exception:
            pass
    shutil.rmtree(work, ignore_errors=True)
    return "\n\n".join(p for p in parts if p)

def split_into_cells(master: dict, OUT_CELLS: Path, cell_size: int, min_chars: int):
    text = master["text"]
    paras = [p.strip() for p in text.split("\n") if p.strip() != ""]
    cells = []
    start = 0; idx = 0
    while start < len(paras):
        end = min(start + cell_size, len(paras))
        chunk = "\n\n".join(paras[start:end])
        if end == len(paras) and len(chunk) < min_chars and cells:
            cells[-1]["text"] += "\n\n" + chunk
            cells[-1]["paras_end"] = end
            cells[-1]["words"] = len(cells[-1]["text"].split())
            break
        cells.append({
            "cell_id": f"{master['id']}::{idx}",
            "source_id": master["id"],
            "source_name": master["source_name"],
            "source_path": master["source_path"],
            "index": idx,
            "paras_start": start,
            "paras_end": end,
            "created_utc": int(time.time()),
            "text": chunk,
            "words": len(chunk.split())
        })
        start = end; idx += 1

    base_stem = Path(master["source_name"]).stem
    outdir = OUT_CELLS / base_stem
    outdir.mkdir(parents=True, exist_ok=True)
    for c in cells:
        (outdir / f"{base_stem}__cell_{c['index']:05d}.json").write_text(
            json.dumps(c, ensure_ascii=False, indent=2), encoding="utf-8")
    (outdir / "progress_sync.json").write_text(json.dumps({
        "source_id": master["id"],
        "source_name": master["source_name"],
        "total_cells": len(cells),
        "cell_folder": str(outdir),
        "created_utc": int(time.time()),
        "cell_size_paras": cell_size
    }, indent=2), encoding="utf-8")
    return len(cells), outdir

class RipperWorker(threading.Thread):
    """Worker sends tuples to the GUI queue:
       ('log', text)
       ('progress', done, total)
       ('done', None, None)
    """
    def __init__(self, opts, q, stop_event):
        super().__init__(daemon=True)
        self.o = opts; self.q = q; self.stop = stop_event

    def log(self, s):
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {s}"
        self.q.put(('log', line, None))
        if self.o["log_file"]:
            with open(self.o["log_file"], "a", encoding="utf-8") as f:
                f.write(line + "\n")

    def run(self):
        IN_DIR   = Path(self.o["input"])
        OUT_TXT  = Path(self.o["outbase"]) / "output_text"
        OUT_JSON = Path(self.o["outbase"]) / "output_json"
        OUT_CELLS= OUT_JSON / "cells"
        TMP_DIR  = Path(self.o["outbase"]) / "temp"
        for p in (OUT_TXT, OUT_JSON, OUT_CELLS, TMP_DIR):
            p.mkdir(parents=True, exist_ok=True)
        failed_dir = IN_DIR / "_failed"; failed_dir.mkdir(exist_ok=True)

        patterns = ("*.pdf","*.epub","*.mobi","*.azw","*.azw3","*.prc")
        files = []
        for pat in patterns:
            files += list(IN_DIR.rglob(pat) if self.o["recursive"] else IN_DIR.glob(pat))
        files = sorted(files)
        total = len(files); done = 0
        self.log(f"Found {total} file(s). Writing to {self.o['outbase']}")
        self.q.put(('progress', done, total))

        for f in files:
            if self.stop.is_set():
                self.log("Stopped by user.")
                break
            try:
                stem = f.stem
                txt_path  = OUT_TXT / f"{stem}.txt"
                json_path = OUT_JSON / f"{stem}.json"

                if txt_path.exists() and json_path.exists() and not self.o["overwrite"]:
                    self.log(f"→ {f.name} (skip, exists)")
                else:
                    self.log(f"→ {f.name}")
                    ext = f.suffix.lower()
                    if ext == ".pdf":
                        text = pdf_to_text(f, self.o["ocr_only"], self.o["lang"], TMP_DIR)
                    elif ext == ".epub":
                        text = epub_to_text(f)
                    elif ext in (".mobi",".azw",".azw3",".prc"):
                        text = mobi_to_text(f, TMP_DIR)
                    else:
                        self.log(f"  ! skip type {ext}")
                        raise RuntimeError("Unsupported type")

                    if not text or len(text.strip()) < 10:
                        raise RuntimeError("No usable text extracted.")

                    text = clean_text(text)
                    if not self.o["dry_run"]:
                        txt_path.write_text(text, encoding="utf-8", errors="ignore")

                    if not (self.o["dry_run"] or self.o["txt_only"]):
                        master = {
                            "id": str(uuid.uuid4()),
                            "source_path": str(f),
                            "source_name": f.name,
                            "ext": ext,
                            "created_utc": int(time.time()),
                            "chars": len(text),
                            "words": len(text.split()),
                            "text": text
                        }
                        json_path.write_text(json.dumps(master, ensure_ascii=False, indent=2), encoding="utf-8")
                        count, cell_dir = split_into_cells(master, OUT_CELLS,
                                                           self.o["cell_size"], self.o["min_cell_chars"])
                        self.log(f"  ✔ wrote master + {count} cells → {cell_dir}")
                    else:
                        self.log("  ✔ wrote .txt only")

            except Exception as e:
                self.log(f"  ✖ ERROR: {e}")
                try:
                    shutil.copy2(f, failed_dir / f.name)
                    self.log(f"  → moved to {failed_dir}")
                except Exception as ee:
                    self.log(f"  ! failed to move to _failed: {ee}")

            finally:
                done += 1
                self.q.put(('progress', done, total))

        self.q.put(('done', None, None))

def open_folder(path: Path):
    try:
        os.startfile(str(path))
    except Exception:
        pass

def main():
    base = Path.home() / "TalaRipper"
    for p in ("input_books","output_text","output_json","output_json/cells","temp","logs"):
        (base / p).mkdir(parents=True, exist_ok=True)

    root = Tk(); root.title("Tala Ripper"); root.geometry("900x600")

    input_var = StringVar(value=str(base / "input_books"))
    out_var   = StringVar(value=str(base))
    lang_var  = StringVar(value="eng")
    ocr_var   = BooleanVar(value=False)
    rec_var   = BooleanVar(value=False)
    over_var  = BooleanVar(value=False)
    txtonly_var = BooleanVar(value=False)
    dry_var   = BooleanVar(value=False)
    cell_var  = IntVar(value=200)
    minchars_var = IntVar(value=800)

    frm = ttk.Frame(root, padding=10); frm.pack(fill="both", expand=True)
    ttk.Label(frm, text="Input folder:").grid(row=0, column=0, sticky="w")
    in_entry = ttk.Entry(frm, textvariable=input_var, width=80); in_entry.grid(row=0, column=1, sticky="we")
    ttk.Button(frm, text="Browse", command=lambda: input_var.set(filedialog.askdirectory(initialdir=input_var.get() or str(base)) or input_var.get())).grid(row=0, column=2)
    ttk.Button(frm, text="Open", command=lambda: open_folder(Path(input_var.get()))).grid(row=0, column=3)

    ttk.Label(frm, text="Output base:").grid(row=1, column=0, sticky="w")
    out_entry= ttk.Entry(frm, textvariable=out_var, width=80); out_entry.grid(row=1, column=1, sticky="we")
    ttk.Button(frm, text="Browse", command=lambda: out_var.set(filedialog.askdirectory(initialdir=out_var.get() or str(base)) or out_var.get())).grid(row=1, column=2)
    ttk.Button(frm, text="Open", command=lambda: open_folder(Path(out_var.get()))).grid(row=1, column=3)

    row=2
    ttk.Checkbutton(frm, text="OCR only (PDF)", variable=ocr_var).grid(row=row, column=0, sticky="w")
    ttk.Checkbutton(frm, text="Recursive", variable=rec_var).grid(row=row, column=1, sticky="w")
    ttk.Checkbutton(frm, text="Overwrite", variable=over_var).grid(row=row, column=2, sticky="w"); row+=1
    ttk.Checkbutton(frm, text="TXT only", variable=txtonly_var).grid(row=row, column=0, sticky="w")
    ttk.Checkbutton(frm, text="Dry run", variable=dry_var).grid(row=row, column=1, sticky="w")
    ttk.Label(frm, text="Lang:").grid(row=row, column=2, sticky="e")
    ttk.Combobox(frm, values=["eng","spa","deu","fra","ita","por","nld","pol","rus","chi_sim","jpn"], textvariable=lang_var, width=10).grid(row=row, column=3, sticky="w"); row+=1
    ttk.Label(frm, text="Cell size:").grid(row=row, column=0, sticky="e"); ttk.Spinbox(frm, from_=50, to=500, textvariable=cell_var, width=6).grid(row=row, column=1, sticky="w")
    ttk.Label(frm, text="Min last cell chars:").grid(row=row, column=2, sticky="e"); ttk.Spinbox(frm, from_=0, to=5000, textvariable=minchars_var, width=6).grid(row=row, column=3, sticky="w"); row+=1

    # Folder quick-open row
    quick = ttk.Frame(frm); quick.grid(row=row, column=0, columnspan=4, pady=4, sticky="we"); row+=1
    ttk.Button(quick, text="Open Output Text", command=lambda: open_folder(Path(out_var.get()) / "output_text")).pack(side="left", padx=4)
    ttk.Button(quick, text="Open Output JSON", command=lambda: open_folder(Path(out_var.get()) / "output_json")).pack(side="left", padx=4)
    ttk.Button(quick, text="Open Cells", command=lambda: open_folder(Path(out_var.get()) / "output_json" / "cells")).pack(side="left", padx=4)
    ttk.Button(quick, text="Open Logs", command=lambda: open_folder(Path(out_var.get()) / "logs")).pack(side="left", padx=4)

    # Start/Stop + progress
    ctrl = ttk.Frame(frm); ctrl.grid(row=row, column=0, columnspan=4, pady=6, sticky="we"); row+=1
    start_btn = ttk.Button(ctrl, text="Start"); stop_btn = ttk.Button(ctrl, text="Stop", state=DISABLED)
    start_btn.pack(side="left", padx=4); stop_btn.pack(side="left", padx=4)
    prog = ttk.Progressbar(ctrl, orient="horizontal", mode="determinate", length=400); prog.pack(side="left", padx=10)
    count_lbl = ttk.Label(ctrl, text="0 / 0"); count_lbl.pack(side="left")

    log = Text(frm, height=18, wrap="word"); log.grid(row=row, column=0, columnspan=4, sticky="nsew", pady=6)
    frm.rowconfigure(row, weight=1); frm.columnconfigure(1, weight=1)

    q = queue.Queue(); stop_event = threading.Event(); holder = {"t": None}

    def pump():
        try:
            while True:
                kind, a, b = q.get_nowait()
                if kind == 'log':
                    log.insert(END, a + "\n"); log.see(END)
                elif kind == 'progress':
                    done, total = a, b
                    prog["maximum"] = max(1, total)
                    prog["value"] = done
                    count_lbl.config(text=f"{done} / {total}")
                elif kind == 'done':
                    start_btn.config(state=NORMAL); stop_btn.config(state=DISABLED)
        except queue.Empty:
            pass
        root.after(150, pump)

    def on_start():
        ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        log_file = Path(out_var.get()) / "logs" / f"ripper-{ts}.log"
        (Path(out_var.get()) / "logs").mkdir(parents=True, exist_ok=True)
        opts = {
            "input": input_var.get(),
            "outbase": out_var.get(),
            "ocr_only": bool(ocr_var.get()),
            "recursive": bool(rec_var.get()),
            "overwrite": bool(over_var.get()),
            "txt_only": bool(txtonly_var.get()),
            "dry_run": bool(dry_var.get()),
            "lang": lang_var.get(),
            "cell_size": int(cell_var.get()),
            "min_cell_chars": int(minchars_var.get()),
            "log_file": str(log_file)
        }
        stop_event.clear()
        t = RipperWorker(opts, q, stop_event); holder["t"] = t
        start_btn.config(state=DISABLED); stop_btn.config(state=NORMAL)
        log.insert(END, f"=== Start: logging to {log_file} ===\n"); log.see(END)
        prog["value"] = 0; count_lbl.config(text="0 / 0")
        t.start()

    def on_stop():
        stop_event.set()
        log.insert(END, "=== Stop requested ===\n"); log.see(END)

    start_btn.config(command=on_start); stop_btn.config(command=on_stop)
    pump()
    root.mainloop()

if __name__ == "__main__":
    main()
