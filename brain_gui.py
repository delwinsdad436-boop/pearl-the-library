import sqlite3
from pathlib import Path
import tkinter as tk
from tkinter import ttk

DB_DEFAULT = "brain_index.sqlite"

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Brain GUI")
        self.geometry("900x600")

        self.db = None
        self.table = None
        self.textcol = None

        top = ttk.Frame(self)
        top.pack(fill="x", padx=10, pady=10)

        self.q = tk.StringVar()
        ttk.Entry(top, textvariable=self.q, width=40).pack(side="left")
        ttk.Button(top, text="Search", command=self.search).pack(side="left", padx=5)

        self.listbox = tk.Listbox(self)
        self.listbox.pack(fill="both", expand=True, padx=10, pady=10)

        self.connect()

    def connect(self):
        db = Path(DB_DEFAULT)
        if not db.exists():
            return
        self.db = sqlite3.connect(str(db))
        self.db.row_factory = sqlite3.Row
        tables = self.db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()
        if not tables:
            return
        self.table = tables[0][0]
        cols = [c[1] for c in self.db.execute(f"PRAGMA table_info({self.table})").fetchall()]
        self.textcol = cols[0]

    def search(self):
        self.listbox.delete(0, tk.END)
        if not self.db:
            return
        q = self.q.get()
        rows = self.db.execute(f"SELECT * FROM {self.table} WHERE {self.textcol} LIKE ? LIMIT 50", (f"%{q}%",)).fetchall()
        for r in rows:
            self.listbox.insert(tk.END, str(r[self.textcol])[:200])

if __name__ == "__main__":
    app = App()
    app.mainloop()
