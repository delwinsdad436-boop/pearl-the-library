# Tala Ripper GUI (fixed)
import os, json, uuid, time, re, subprocess, shutil, tempfile, threading, queue, datetime
from pathlib import Path
from tkinter import Tk, StringVar, BooleanVar, IntVar, ttk, filedialog, Text, END, DISABLED, NORMAL
from ebooklib import epub
from bs4 import BeautifulSoup

def which(cmd):
    try: return subprocess.run(["where", cmd], capture_output=True, text=True).returncode == 0
    except: return False

HAVE_PDFTOPPM = which("pdftoppm")
HAVE_TESS     = which("tesseract")

def clean_text(s):
    s = s.replace("\r\n","\n").replace("\r","\n")
    s = re.sub(r"[ \t]+\n", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s

def pdf_to_text(path: Path, ocr_only: bool, lang: str, tmp: Path):
    if which("pdftotext") and not ocr_only:
        out = tmp / (path.stem + ".pdftotext.txt")
        r = subprocess.run(["pdftotext","-layout","-enc","UTF-8",str(path),str(out)], capture_output=True, text=True)
        if r.returncode == 0 and out.exists():
            t = out.read_text(encoding="utf-8", errors="ignore").strip()
            if len(t) > 30: return t
    if not (HAVE_PDFTOPPM and HAVE_TESS):
        raise RuntimeError("Need pdftoppm + tesseract for OCR.")
    ocr = tmp / f"{path.stem}_ocr"
    if ocr.exists(): shutil.rmtree(ocr)
    ocr.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(["pdftoppm","-png",str(path),str(ocr/"page")], capture_output=True, text=True)
    if r.returncode != 0: raise RuntimeError(f"pdftoppm failed: {r.stderr}")
    pages = []
    for img in sorted(ocr.glob("page-*.png")):
        base = img.with_suffix("")
        subprocess.run(["tesseract",str(img),str(base),"-l",lang], capture_output=True, text=True)
        txt = Path(str(base)+".txt")
        if txt.exists(): pages.append(txt.read_text(encoding="utf-8", errors="ignore"))
    if not pages: raise RuntimeError("OCR produced no text.")
    return "\n".join(pages)

def epub_to_text(path: Path):
    book = epub.read_epub(str(path))
    parts = []
    for it in book.get_items():
        if it.get_type() == 9:
            try:
                soup = BeautifulSoup(it.get_content(),"lxml")
                for t in soup(["script","style"]): t.decompose()
                parts.append(soup.get_text(separator="\n", strip=True))
            except: pass
    return "\n\n".join(p for p in parts if p)

def mobi_to_text(path: Path, tmp: Path):
    try:
        from kindleunpack.kindleunpack import unpackBook
    except Exception:
        import kindleunpack as _ku; unpackBook = _ku.unpackBook
    work = Path(tempfile.mkdtemp(dir=tmp)); out = work/"ku_out"; out.mkdir(exist_ok=True)
    _ = unpackBook(str(path), str(out))
    parts = []
    for h in sorted(list(out.rglob("*.htm"))+list(out.rglob("*.html"))+list(out.rglob("*.xhtml"))):
        try:
            soup = BeautifulSoup(h.read_text(encoding="utf-8", errors="ignore"),"lxml")
            for t in soup(["script","style"]): t.decompose()
            parts.append(soup.get_text(separator="\n", strip=True))
        except: pass
    shutil.rmtree(work, ignore_errors=True)
    return "\n\n".join(p for p in parts if p)

def split_cells(master: dict, out_cells: Path, cell_size: int, min_chars: int):
    text = master["text"]; paras = [p.strip() for p in text.split("\n") if p.strip()]
    cells=[]; i=0; s=0
    while s < len(paras):
        e = min(s + cell_size, len(paras))
        chunk = "\n\n".join(paras[s:e])
        if e == len(paras) and len(chunk) < min_chars and cells:
            cells[-1]["text"] += "\n\n" + chunk
            break
        cells.append({
            "cell_id": f"{master['id']}::{i}", "source_id": master["id"],
            "source_name": master["source_name"], "source_path": master["source_path"],
            "index": i, "text": chunk, "created_utc": int(time.time())
        })
        s = e; i += 1
    base = Path(master["source_name"]).stem
    folder = out_cells / base; folder.mkdir(parents=True, exist_ok=True)
    for c in cells:
        (folder / f"{base}__cell_{c['index']:05d}.json").write_text(json.dumps(c,ensure_ascii=False,indent=2),encoding="utf-8")
    (folder / "progress_sync.json").write_text(json.dumps({"total_cells":len(cells),"created_utc":int(time.time())},indent=2),encoding="utf-8")
    return len(cells), folder

def build_brain(out_json: Path):
    cells_dir = out_json / "cells"; brain = out_json / "brain.jsonl"
    if brain.exists(): brain.unlink()
    count = 0; srcs = set()
    with brain.open("w", encoding="utf-8", newline="\n") as f:
        for cf in cells_dir.rglob("*.json"):
            if cf.name == "progress_sync.json": continue
            try:
                obj = json.loads(cf.read_text(encoding="utf-8", errors="ignore"))
                srcs.add(obj.get("source_name") or obj.get("source_path") or "unknown")
                f.write(json.dumps(obj, ensure_ascii=False) + "\n")
                count += 1
            except: pass
    return count, len(srcs), brain

class Worker(threading.Thread):
    def __init__(self, opts, q, stop):
        super().__init__(daemon=True); self.o=opts; self.q=q; self.stop=stop
    def log(self, m):
        ts=datetime.datetime.now().strftime("%H:%M:%S"); line=f"[{ts}] {m}"
        self.q.put(('log', line))
        if self.o["log_file"]:
            with open(self.o["log_file"],"a",encoding="utf-8") as fp: fp.write(line+"\n")
    def run(self):
        IN=Path(self.o["input"]); OUTB=Path(self.o["outbase"])
        OUT_TXT=OUTB/"output_text"; OUT_JSON=OUTB/"output_json"; OUT_CELLS=OUT_JSON/"cells"; TMP=OUTB/"temp"
        for p in (OUT_TXT,OUT_JSON,OUT_CELLS,TMP): p.mkdir(parents=True, exist_ok=True)
        failed=IN/"_failed"; failed.mkdir(exist_ok=True)
        exts=("*.pdf","*.epub","*.mobi","*.azw","*.azw3","*.prc")
        files=[]; [files.extend(IN.rglob(x) if self.o["recursive"] else IN.glob(x)) for x in exts]
        files=sorted(files); total=len(files); done=0
        self.log(f"Found {total} file(s)."); self.q.put(('progress', (done,total)))
        for f in files:
            if self.stop.is_set(): self.log("Stopped by user."); break
            try:
                stem=f.stem; txt=OUT_TXT/f"{stem}.txt"; js=OUT_JSON/f"{stem}.json"
                if txt.exists() and js.exists() and not self.o["overwrite"]:
                    self.log(f"→ {f.name} (skip, exists)")
                else:
                    self.log(f"→ {f.name}")
                    if f.suffix.lower()==".pdf": t=pdf_to_text(f,self.o["ocr_only"],self.o["lang"],TMP)
                    elif f.suffix.lower()==".epub": t=epub_to_text(f)
                    else: t=mobi_to_text(f,TMP)
                    if not t or len(t.strip())<10: raise RuntimeError("No usable text.")
                    t=clean_text(t)
                    if not self.o["dry_run"]: txt.write_text(t,encoding="utf-8")
                    if not (self.o["dry_run"] or self.o["txt_only"]):
                        master={"id":str(uuid.uuid4()),"source_path":str(f),"source_name":f.name,"text":t}
                        js.write_text(json.dumps(master,ensure_ascii=False,indent=2),encoding="utf-8")
                        c,_=split_cells(master,OUT_CELLS,self.o["cell_size"],self.o["min_cell_chars"])
                        self.log(f"  ✔ cells: {c}")
                    else:
                        self.log("  ✔ wrote .txt only")
            except Exception as e:
                self.log(f"  ✖ ERROR: {e}")
                try: shutil.copy2(f, failed/f.name); self.log(f"  → moved to {failed}")
                except Exception as ee: self.log(f"  ! move failed: {ee}")
            finally:
                done+=1; self.q.put(('progress',(done,total)))
        try:
            cells,sources,brain=build_brain(OUT_JSON)
            self.log(f"  ✔ built brain: {brain}  ({cells} cells / {sources} sources)")
        except Exception as e:
            self.log(f"  ! brain build failed: {e}")
        self.q.put(('done', None))

def open_folder(p: Path):
    try: os.startfile(str(p))
    except: pass

def main():
    base = Path.home()/"TalaRipper"
    root=Tk(); root.title("Tala Ripper"); root.geometry("900x600")
    input_var=StringVar(value=str(base/"input_books")); out_var=StringVar(value=str(base))
    lang_var=StringVar(value="eng"); ocr_var=BooleanVar(value=False)
    rec_var=BooleanVar(value=False); over_var=BooleanVar(value=False)
    txtonly_var=BooleanVar(value=False); dry_var=BooleanVar(value=False)
    cell_var=IntVar(value=200); minchars_var=IntVar(value=800)

    frm=ttk.Frame(root,padding=10); frm.pack(fill="both",expand=True)
    ttk.Label(frm,text="Input folder:").grid(row=0,column=0,sticky="w")
    ttk.Entry(frm,textvariable=input_var,width=80).grid(row=0,column=1,sticky="we")
    ttk.Button(frm,text="Browse",command=lambda: input_var.set(filedialog.askdirectory(initialdir=input_var.get()) or input_var.get())).grid(row=0,column=2)
    ttk.Button(frm,text="Open",command=lambda: open_folder(Path(input_var.get()))).grid(row=0,column=3)
    ttk.Label(frm,text="Output base:").grid(row=1,column=0,sticky="w")
    ttk.Entry(frm,textvariable=out_var,width=80).grid(row=1,column=1,sticky="we")
    ttk.Button(frm,text="Browse",command=lambda: out_var.set(filedialog.askdirectory(initialdir=out_var.get()) or out_var.get())).grid(row=1,column=2)
    ttk.Button(frm,text="Open",command=lambda: open_folder(Path(out_var.get()))).grid(row=1,column=3)

    row=2
    ttk.Checkbutton(frm,text="OCR only (PDF)",variable=ocr_var).grid(row=row,column=0,sticky="w")
    ttk.Checkbutton(frm,text="Recursive",variable=rec_var).grid(row=row,column=1,sticky="w")
    ttk.Checkbutton(frm,text="Overwrite",variable=over_var).grid(row=row,column=2,sticky="w"); row+=1
    ttk.Checkbutton(frm,text="TXT only",variable=txtonly_var).grid(row=row,column=0,sticky="w")
    ttk.Checkbutton(frm,text="Dry run",variable=dry_var).grid(row=row,column=1,sticky="w")
    ttk.Label(frm,text="Lang:").grid(row=row,column=2,sticky="e")
    ttk.Combobox(frm,values=["eng","spa","deu","fra","ita","por","nld","pol","rus","chi_sim","jpn"],textvariable=lang_var,width=10).grid(row=row,column=3,sticky="w"); row+=1
    ttk.Label(frm,text="Cell size:").grid(row=row,column=0,sticky="e"); ttk.Spinbox(frm,from_=50,to=500,textvariable=cell_var,width=6).grid(row=row,column=1,sticky="w")
    ttk.Label(frm,text="Min last cell chars:").grid(row=row,column=2,sticky="e"); ttk.Spinbox(frm,from_=0,to=5000,textvariable=minchars_var,width=6).grid(row=row,column=3,sticky="w"); row+=1

    ctrl=ttk.Frame(frm); ctrl.grid(row=row,column=0,columnspan=4,sticky="we",pady=6); row+=1
    start_btn=ttk.Button(ctrl,text="Start"); stop_btn=ttk.Button(ctrl,text="Stop",state=DISABLED)
    start_btn.pack(side="left"); stop_btn.pack(side="left",padx=6)
    prog=ttk.Progressbar(ctrl,orient="horizontal",mode="determinate",length=400); prog.pack(side="left",padx=10)
    count=ttk.Label(ctrl,text="0 / 0"); count.pack(side="left")

    log=Text(frm,height=18,wrap="word"); log.grid(row=row,column=0,columnspan=4,sticky="nsew"); frm.rowconfigure(row,weight=1); frm.columnconfigure(1,weight=1)

    q=queue.Queue(); stop=threading.Event()

    def pump():
        try:
            while True:
                kind,val=q.get_nowait()
                if kind=='log': log.insert(END,val+"\n"); log.see(END)
                elif kind=='progress':
                    d,t = val; prog["maximum"]=max(1,t); prog["value"]=d; count.config(text=f"{d} / {t}")
                elif kind=='done': start_btn.config(state=NORMAL); stop_btn.config(state=DISABLED)
        except queue.Empty: pass
        root.after(150,pump)

    def on_start():
        ts=datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        log_file=Path(out_var.get())/"logs"/f"ripper-{ts}.log"; (log_file.parent).mkdir(parents=True, exist_ok=True)
        opts={"input":input_var.get(),"outbase":out_var.get(),"ocr_only":bool(ocr_var.get()),
              "recursive":bool(rec_var.get()),"overwrite":bool(over_var.get()),
              "txt_only":bool(txtonly_var.get()),"dry_run":bool(dry_var.get()),
              "lang":"eng","cell_size":int(cell_var.get()),"min_cell_chars":int(minchars_var.get()),
              "log_file":str(log_file)}
        stop.clear(); w=Worker(opts,q,stop)
        start_btn.config(state=DISABLED); stop_btn.config(state=NORMAL)
        log.insert(END,f"=== Start: logging to {log_file} ===\n"); log.see(END)
        prog["value"]=0; count.config(text="0 / 0"); w.start()

    def on_stop():
        stop.set(); log.insert(END,"=== Stop requested ===\n"); log.see(END)

    start_btn.config(command=on_start); stop_btn.config(command=on_stop)
    pump(); root.mainloop()

if __name__=="__main__": main()
 