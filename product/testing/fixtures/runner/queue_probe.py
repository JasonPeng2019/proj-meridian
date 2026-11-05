"""Synthetic Python owner for the remote cross-process queue check."""
import json
import os
from pathlib import Path
import sys
import time

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "development"))
from backend.ai.runner import SerialQueue

queue_path, output = map(Path, sys.argv[1:])
with SerialQueue(queue_path, timeout=5).acquire():
    for state in ("start", "end"):
        with output.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"pid": os.getpid(), "event": state, "at": time.time()}) + "\n")
            handle.flush()
        if state == "start":
            time.sleep(0.1)
