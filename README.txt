Tala Brain Tools v2 (Drop-in)

FILES
- brain_common.py  (shared helpers: DB detect + memory store)
- brain_search.py  (CLI search)
- brain_chat.py    (offline chat + memory writeback)
- brain_gui.py     (Tkinter GUI search)
- brain_agent.py   (simple agent plan checkpoint)

REQUIREMENTS
- Python 3.x
- No external pip installs needed (stdlib only)
- brain_index.sqlite must exist (built by assemble_brain_v2.py)

QUICK START (in C:\Users\delwi\TalaRipper)
1) Probe DB
   python brain_search.py --probe

2) Search
   python brain_search.py plants
   python brain_search.py "due process" --limit 8

3) Chat + remember
   python brain_chat.py
   /remember My kids names are ...
   /pin   Critical: always rebuild DB after ingest
   /mem kids
   /plan Build a better search ranking

4) GUI
   python brain_gui.py
