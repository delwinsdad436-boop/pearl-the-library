import os
import json
import shutil

SRC = r"output_json\cells"
DST = r"output_json\flat_cells"

os.makedirs(DST, exist_ok=True)

for root, _, files in os.walk(SRC):
    for f in files:
        if f.endswith(".json"):
            src_path = os.path.join(root, f)
            dst_path = os.path.join(DST, f)
            shutil.copyfile(src_path, dst_path)

print("FLATTEN COMPLETE")