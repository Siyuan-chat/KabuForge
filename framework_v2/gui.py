"""Small local review frontend; execution runs in an isolated Python process."""
from __future__ import annotations
import json
from pathlib import Path
import subprocess
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

def main():
    window=tk.Tk(); window.title("Private Engine v2 · Local Review"); window.geometry("1000x760")
    path=tk.StringVar(); status=tk.StringVar(value="Open a factor, strategy or run JSON to review.")
    process=None
    bar=ttk.Frame(window); bar.pack(fill="x",padx=10,pady=8)
    ttk.Entry(bar,textvariable=path).pack(side="left",fill="x",expand=True)
    text=tk.Text(window,wrap="none",undo=True); text.pack(fill="both",expand=True,padx=10)
    output=tk.Text(window,height=12,wrap="word",state="disabled"); output.pack(fill="x",padx=10,pady=8)
    ttk.Label(window,textvariable=status).pack(anchor="w",padx=10)

    def display(value):
        output.configure(state="normal"); output.delete("1.0","end"); output.insert("1.0",value); output.configure(state="disabled")

    def open_json():
        selected=filedialog.askopenfilename(filetypes=[("JSON configuration","*.json")])
        if not selected: return
        try:
            value=json.loads(Path(selected).read_text(encoding="utf-8"))
            text.delete("1.0","end"); text.insert("1.0",json.dumps(value,ensure_ascii=False,indent=2))
            path.set(selected); status.set("Loaded locally. Save a copy before validating edits.")
        except Exception as exc: messagebox.showerror("Open failed",str(exc))

    def save_copy():
        try: value=json.loads(text.get("1.0","end"))
        except Exception as exc: messagebox.showerror("Invalid JSON",str(exc)); return
        selected=filedialog.asksaveasfilename(defaultextension=".json",filetypes=[("JSON configuration","*.json")])
        if not selected: return
        # Explicit user Save dialog authorizes replacing the chosen file.
        Path(selected).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding="utf-8")
        path.set(selected); status.set("Saved. Relative references resolve beside this file.")

    def validate():
        nonlocal process
        if process is not None: return
        if not path.get(): messagebox.showerror("No file","Open or save a run JSON first."); return
        # This CLI is the same ApplicationService used by offline planning.
        command=[sys.executable,"-B","-m","framework_v2.cli","validate",str(Path(path.get()).resolve())]
        process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,
            creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0),cwd=str(Path(__file__).resolve().parents[1]))
        status.set(f"Validating saved run in process {process.pid}. No orders are submitted.")
        window.after(100,poll)

    def poll():
        nonlocal process
        if process is None: return
        if process.poll() is None: window.after(100,poll); return
        out,err=process.communicate(); status.set(f"Validation exit code: {process.returncode}")
        display(out+err); process=None

    def close():
        if process is not None:
            # Only the validation child created by this frontend is terminated.
            process.terminate(); process.communicate(timeout=10)
        window.destroy()

    ttk.Button(bar,text="Open JSON",command=open_json).pack(side="left",padx=5)
    ttk.Button(bar,text="Save copy",command=save_copy).pack(side="left",padx=5)
    ttk.Button(bar,text="Validate saved run",command=validate).pack(side="left",padx=5)
    window.protocol("WM_DELETE_WINDOW",close); window.mainloop()

if __name__=="__main__": main()
