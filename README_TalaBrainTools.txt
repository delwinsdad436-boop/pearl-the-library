TalaBrainTools (offline)

You already built:
  brain_index.sqlite  (from assemble_brain_v2.py)

These tools let you SEARCH that DB.

0) Put these .py files in the SAME folder as brain_index.sqlite
   Example: C:\Users\<you>\TalaRipper\

1) Quick sanity check:
   python brain_probe.py

   You should see TABLE: brain and rows: 2087 (or whatever your count is).

2) Search (command line):
   python brain_search.py plants
   python brain_search.py "black seed oil" --limit 25
   python brain_search.py --probe

3) Interactive search (mini chat):
   python brain_chat.py
   - type your query and press Enter
   - /probe to show tables
   - /exit to quit
   - If it hangs, press Ctrl+C (that's the KeyboardInterrupt you saw — it's normal).

4) GUI search (optional):
   python brain_gui.py

NOTES
- Your DB table is named: brain (NOT cells). That was the earlier mismatch.
- If you see “No matches found”, try a simpler word that you KNOW exists in the text.

