"""
Entry point for running headless (via pythonw.exe / Task Scheduler - no
console window). Redirects stdout/stderr to server.log BEFORE importing
anything that might print, since pythonw.exe gives sys.stdout = None and
any bare print() would crash the process.

Manual run (console visible): python run_server.py
Headless run (used by the scheduled task): pythonw run_server.py
"""
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

if sys.stdout is None or not hasattr(sys.stdout, "write"):
    log_path = os.path.join(BASE_DIR, "server.log")
    log_file = open(log_path, "a", buffering=1, encoding="utf-8")
    sys.stdout = log_file
    sys.stderr = log_file

import uvicorn

if __name__ == "__main__":
    print("=" * 60)
    print("Tally Live Entity Dashboard starting - http://127.0.0.1:8731/")
    print("=" * 60)
    uvicorn.run("main:app", host="127.0.0.1", port=8731)
