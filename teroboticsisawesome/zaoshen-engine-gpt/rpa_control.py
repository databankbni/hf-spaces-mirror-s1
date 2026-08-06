#!/usr/bin/env python3
"""造神引擎 RPA Windows 控制器：配對、啟動、停止與本機狀態。"""
import json, os, platform, subprocess, sys, threading, urllib.request
from pathlib import Path
import tkinter as tk
from tkinter import messagebox

ROOT = Path(__file__).resolve().parent
CONFIG = Path(os.environ.get("LOCALAPPDATA", ROOT)) / "ZaoshenRPA" / "device.json"
VERSION = "1.2.3"
PRODUCTION_SERVER = "https://teroboticsisawesome-zaoshen-engine-gpt.hf.space"


def post(server, path, payload, token=""):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(server.rstrip("/") + path, json.dumps(payload).encode(), headers, method="POST")
    with urllib.request.urlopen(req, timeout=20) as response:
        return json.load(response)


class Control:
    def __init__(self, root):
        self.root, self.process = root, None
        root.title(f"造神引擎 RPA {VERSION}"); root.geometry("560x500"); root.configure(bg="#090c13")
        self.server = tk.StringVar(value=PRODUCTION_SERVER)
        self.code = tk.StringVar(); self.device = tk.StringVar(value=platform.node() or "Windows 電腦")
        self.status = tk.StringVar(value="尚未配對")
        tk.Label(root,text="🔥 造神引擎 RPA",font=("Microsoft JhengHei",20,"bold"),fg="#ffffff",bg="#090c13").pack(pady=(24,3))
        tk.Label(root,text="Facebook 登入資料只保留在這台電腦",fg="#31e8d3",bg="#090c13").pack(pady=(0,18))
        box=tk.Frame(root,bg="#111722",padx=22,pady=18);box.pack(fill="x",padx=24)
        self.field(box,"網站網址",self.server);self.field(box,"裝置名稱",self.device);self.field(box,"一次性配對碼",self.code)
        row=tk.Frame(box,bg="#111722");row.pack(fill="x",pady=(16,5))
        self.pair_btn=self.button(row,"1. 配對裝置",self.pair,"#9c5cff");self.pair_btn.pack(side="left",expand=True,fill="x",padx=(0,5))
        self.start_btn=self.button(row,"2. 啟動 RPA",self.start,"#ff3f81");self.start_btn.pack(side="left",expand=True,fill="x",padx=5)
        self.stop_btn=self.button(row,"停止",self.stop,"#3a4252");self.stop_btn.pack(side="left",expand=True,fill="x",padx=(5,0))
        stat=tk.Frame(root,bg="#111722",padx=18,pady=16);stat.pack(fill="x",padx=24,pady=14)
        tk.Label(stat,text="●",fg="#31e8d3",bg="#111722",font=("Arial",15)).pack(side="left")
        tk.Label(stat,textvariable=self.status,fg="#ffffff",bg="#111722",font=("Microsoft JhengHei",12,"bold")).pack(side="left",padx=8)
        tk.Label(root,text="操作順序：網站產生配對碼 → 在此配對 → 按啟動。\n啟動後網站會在約 20 秒內顯示在線。關閉或停止後，約 65 秒顯示離線。",justify="left",fg="#929db0",bg="#090c13").pack(anchor="w",padx=28)
        self.load()
        root.protocol("WM_DELETE_WINDOW", self.close)

    def field(self,parent,label,var):
        tk.Label(parent,text=label,anchor="w",fg="#b7c0cf",bg="#111722").pack(fill="x",pady=(7,2))
        tk.Entry(parent,textvariable=var,font=("Arial",11),bg="#080c13",fg="#ffffff",insertbackground="#fff",relief="flat").pack(fill="x",ipady=8)

    def button(self,parent,text,cmd,color):
        return tk.Button(parent,text=text,command=cmd,bg=color,fg="#fff",activebackground=color,activeforeground="#fff",relief="flat",font=("Microsoft JhengHei",10,"bold"),pady=9,cursor="hand2")

    def load(self):
        if CONFIG.is_file():
            try:
                d=json.loads(CONFIG.read_text(encoding="utf-8"));self.server.set(d.get("server",self.server.get()));self.device.set(d.get("device_name",self.device.get()))
                if d.get("device_token"): self.status.set(f"已配對：{d.get('display_name','夥伴')}／{d.get('device_name','裝置')}（尚未啟動）")
            except Exception: pass

    def pair(self):
        if not self.code.get().strip(): return messagebox.showwarning("需要配對碼","請先到網站的『夥伴與 RPA 裝置』產生配對碼。")
        self.status.set("配對中…")
        def work():
            try:
                d=post(self.server.get(),"/api/rpa/pair",{"code":self.code.get().strip().upper(),"device_name":self.device.get().strip(),"rpa_version":VERSION,"os_version":platform.platform()})
                CONFIG.parent.mkdir(parents=True,exist_ok=True);CONFIG.write_text(json.dumps({"server":self.server.get().rstrip('/'),"device_token":d["device_token"],"device_id":d["device_id"],"display_name":d["display_name"],"device_name":self.device.get().strip()},ensure_ascii=False,indent=2),encoding="utf-8")
                self.root.after(0,lambda:self.status.set(f"配對成功：{d['display_name']}／{self.device.get()}"))
            except Exception as e:self.root.after(0,lambda:messagebox.showerror("配對失敗",str(e)))
        threading.Thread(target=work,daemon=True).start()

    def start(self):
        if not CONFIG.is_file(): return messagebox.showwarning("尚未配對","請先完成配對。")
        if self.process and self.process.poll() is None:return
        if getattr(sys, "frozen", False):
            command=[sys.executable,"--worker"]
        else:
            command=[sys.executable,str(ROOT/"local_worker.py")]
        self.process=subprocess.Popen(command,cwd=str(ROOT))
        self.status.set("RPA 啟動中；請在專用 Edge 完成 Facebook 登入")
        self.root.after(1500,self.watch)

    def watch(self):
        if self.process and self.process.poll() is None:
            self.status.set("專用 Edge 已開啟；登入 Facebook 後自動待命");self.root.after(1500,self.watch)
        elif self.process:
            self.status.set("RPA 已停止")

    def stop(self):
        if self.process and self.process.poll() is None:self.process.terminate()
        self.status.set("RPA 已停止；網站將自動顯示離線")

    def close(self): self.stop();self.root.destroy()


if __name__ == "__main__":
    if "--worker" in sys.argv:
        import local_worker
        local_worker.main()
    else:
        root=tk.Tk();Control(root);root.mainloop()
