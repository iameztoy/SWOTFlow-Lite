"""Small desktop interface over the verified processing and Cloud engines."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
from queue import Queue, Empty
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import webbrowser

from swotflow.paths import APP_ROOT
from swotflow.project.model import save_project
from swotflow.processing.download import normalize_utm_tiles, authenticate
from swotflow_lite import __version__
from swotflow_lite import project as model, planner, runner, statistics
from swotflow_lite.tile_selection import ContinentPicker, TileMapDialog, combine_continents


class LiteApp:
    """Keep GUI mutation on the main thread and one project operation at a time."""
    def __init__(self, root: tk.Tk) -> None:
        self.root=root; self.project=None; self.busy=False
        self.events=Queue(); self.stop=threading.Event(); self.buttons=[]
        root.title(f"SWOTFlow Lite v{__version__}"); root.geometry("1120x820")
        self.title=tk.StringVar(value="Create or open a separate Lite project")
        ttk.Label(root,textvariable=self.title,font=("Segoe UI",12,"bold")).pack(anchor="w",padx=14,pady=10)
        self.notebook=ttk.Notebook(root); self.notebook.pack(fill="both",expand=True,padx=12)
        self.tabs={}
        for name in ("Project", "Process", "Cloud", "Statistics"):
            outer=ttk.Frame(self.notebook); self.notebook.add(outer,text=name)
            canvas=tk.Canvas(outer,highlightthickness=0); bar=ttk.Scrollbar(outer,orient="vertical",command=canvas.yview)
            canvas.configure(yscrollcommand=bar.set); bar.pack(side="right",fill="y"); canvas.pack(fill="both",expand=True)
            frame=ttk.Frame(canvas,padding=14); window=canvas.create_window((0,0),window=frame,anchor="nw")
            frame.bind("<Configure>",lambda e,c=canvas:c.configure(scrollregion=c.bbox("all")))
            canvas.bind("<Configure>",lambda e,c=canvas,w=window:c.itemconfigure(w,width=e.width))
            canvas.bind("<MouseWheel>",lambda e,c=canvas:c.yview_scroll(int(-e.delta/120),"units"))
            frame.columnconfigure(1,weight=1); self.tabs[name]=frame
        self.vars={}
        self._project_tab(); self._process_tab(); self._cloud_tab(); self._statistics_tab()
        self.status=tk.StringVar(value="Ready. No project data is stored in the application folder.")
        ttk.Label(root,textvariable=self.status,wraplength=1080).pack(fill="x",padx=12,pady=5)
        self.log=tk.Text(root,height=9,wrap="word",state="disabled"); self.log.pack(fill="both",padx=12,pady=(0,8))
        root.protocol("WM_DELETE_WINDOW",self.close); root.after(150,self.drain)

    def entry(self, tab: str, row: int, key: str, label: str, value: str="") -> None:
        """Add an editable setting with a shared variable."""
        frame=self.tabs[tab]; self.vars[key]=tk.StringVar(value=value)
        ttk.Label(frame,text=label).grid(row=row,column=0,sticky="w",pady=5,padx=(0,16))
        ttk.Entry(frame,textvariable=self.vars[key]).grid(row=row,column=1,sticky="ew",pady=5)

    def button(self, parent: object, text: str, command: object) -> None:
        """Register operation buttons so overlapping runs are disabled."""
        b=ttk.Button(parent,text=text,command=command); b.pack(side="left",padx=(0,8));self.buttons.append(b)

    def _project_tab(self) -> None:
        """Display scope and Cloud destination without browser automation controls."""
        f=self.tabs["Project"]; actions=ttk.Frame(f); actions.grid(row=0,column=0,columnspan=2,sticky="w",pady=8)
        self.button(actions,"New project",self.new); self.button(actions,"Open project",self.open)
        self.button(actions,"Save settings",self.save)
        self.entry("Project",1,"tiles","UTM tiles (comma separated)","UTM35L")
        tools=ttk.Frame(f); tools.grid(row=2,column=0,columnspan=2,sticky="w",pady=6)
        self.button(tools,"Select on map…",self.select_map)
        self.button(tools,"Clear tiles",lambda:self.set_tiles([]))
        self.tile_count=tk.StringVar(value="1 tile selected")
        ttk.Label(tools,textvariable=self.tile_count).pack(side="left")
        self.vars["tiles"].trace_add("write",lambda *args:self.update_tile_count())
        self.continents=ContinentPicker(f,self.select_continents,self.buttons)
        self.continents.grid(row=3,column=0,columnspan=2,sticky="ew",pady=6)
        ttk.Label(f,text="Add combines checked continents with your tiles. Use only replaces the list. You can then adjust tiles on the map or above. "
                  "After changing scope, run Catalogue / plan before Start / Resume; existing history is retained.",
                  wraplength=950).grid(row=4,column=0,columnspan=2,sticky="w",pady=(4,10))
        self.entry("Project",5,"start","First acquisition date (YYYY-MM-DD)")
        self.entry("Project",6,"end","Last acquisition date (YYYY-MM-DD)")
        self.entry("Project",7,"gdal","GDAL Python executable")
        ttk.Button(f,text="Browse GDAL Python",command=self.choose_gdal).grid(row=8,column=1,sticky="w")
        ttk.Label(f,text="Native 100 m, exact UTM tiles. Lowest quality code selects the paired elevation/quality; deterministic ties. "
                  "Preferred NASA versions and full filename history are retained. Map boundaries are for selection only; the processing grid stays unchanged.",
                  wraplength=950).grid(row=9,column=0,columnspan=2,sticky="w",pady=18)
        self.entry("Project",10,"destination","EE ImageCollection ID")
        self.entry("Project",11,"cloud_project","Google Cloud project ID")
        self.entry("Project",12,"bucket","Bucket name (without gs://)")
        ttk.Label(f,text="Use a new empty EE collection for a new Lite project. To add tiles or dates to an existing collection, "
                  "reopen its original project and history. Keep automatic and manual upload routes in that same project. "
                  "Assets without recorded source history prevent safe local cleanup.",
                  wraplength=950).grid(row=13,column=0,columnspan=2,sticky="w",pady=12)

    def update_tile_count(self) -> None:
        try:self.tile_count.set(f"{len(normalize_utm_tiles(self.vars['tiles'].get()))} tiles selected")
        except ValueError:self.tile_count.set("Check tile names (example: UTM35L)")

    def set_tiles(self, tiles) -> None:
        if self.busy:return
        self.vars["tiles"].set(", ".join(normalize_utm_tiles(tiles)))
        self.status.set("Tile selection changed. Save settings, then refresh Catalogue / plan before processing the new scope.")

    def select_continents(self, names, replace=False) -> None:
        if self.busy:return
        try:self.set_tiles(combine_continents(self.vars["tiles"].get(),names,replace=replace))
        except ValueError as exc:messagebox.showerror("Continent selection",str(exc),parent=self.root)

    def select_map(self) -> None:
        if self.busy:return
        try:TileMapDialog(self.root,normalize_utm_tiles(self.vars["tiles"].get()),self.set_tiles)
        except (ValueError,OSError) as exc:messagebox.showerror("Tile map",str(exc),parent=self.root)

    def _process_tab(self) -> None:
        """Expose bounded processing and existing worker controls."""
        f=self.tabs["Process"]; self.mode=tk.StringVar(value="prepare")
        ttk.Radiobutton(f,text="Prepare locally for manual bucket upload",variable=self.mode,value="prepare").grid(row=0,column=0,columnspan=2,sticky="w")
        ttk.Radiobutton(f,text="Fully automatic: process → bucket → EE → verified cleanup",variable=self.mode,value="automatic").grid(row=1,column=0,columnspan=2,sticky="w")
        for row,key,label,value in ((2,"batch_mosaics","Target maximum mosaics per batch","50"),(3,"batch_source_gib","Maximum source data per batch (GiB)","2"),
            (4,"max_prepared_gib","Pause new processing at retained mosaics (GiB)","20"),(5,"min_free_gib","Minimum free disk reserve (GiB)","10"),
            (6,"download_threads","Parallel downloads","10"),(7,"download_batch","NASA network batch size","50"),
            (8,"extract_workers","Extraction workers","4"),(9,"mosaic_workers","Mosaic workers","4")):
            self.entry("Process",row,key,label,value)
        self.intermediate=tk.BooleanVar(value=True); self.mosaic_cleanup=tk.BooleanVar(value=True)
        ttk.Checkbutton(f,text="Clean downloaded/extracted files after verified downstream processing",variable=self.intermediate).grid(row=10,column=0,columnspan=2,sticky="w",pady=5)
        ttk.Checkbutton(f,text="Clean local mosaics only after confirmed EE ingestion + matching provenance",variable=self.mosaic_cleanup).grid(row=11,column=0,columnspan=2,sticky="w",pady=5)
        actions=ttk.Frame(f); actions.grid(row=12,column=0,columnspan=2,sticky="w",pady=10)
        self.button(actions,"Authenticate NASA",lambda:self.launch("NASA sign-in",lambda p:authenticate(strategy="interactive",persist=False),save=False,needs_project=False))
        self.button(actions,"Catalogue / plan",lambda:self.launch("NASA catalogue planning",lambda p:planner.build_plan(p,self.emit)))
        self.button(actions,"Start / Resume",lambda:self.launch("Processing",lambda p:runner.run(p,self.stop,self.emit)))
        ttk.Button(actions,text="Stop after current stage",command=self.stop.set).pack(side="left")
        ttk.Label(f,text="NASA sign-in uses the launch console and stays in memory. Batches never split an acquisition day. "
                  "Source limits and disk reserve are checked before new processing; raster expansion estimates are not a hard disk quota. "
                  "Manual mode pauses as prepared files accumulate. EE tasks already submitted continue if the app closes.",
                  wraplength=950).grid(row=13,column=0,columnspan=2,sticky="w",pady=10)

    def _cloud_tab(self) -> None:
        """Offer automatic transfer and explicit registration of manual uploads."""
        f=self.tabs["Cloud"]
        for row,key,label,value in ((0,"transfers","Concurrent Cloud transfers (1–8)","2"),(1,"ingestions","Maximum active EE ingestions","2"),
            (2,"staging_gib","Automatic staging cap (GiB)","3"),(3,"prefix","App-owned staging prefix","swotflow-lite")):
            self.entry("Cloud",row,key,label,value)
        self.cloud_cleanup=tk.BooleanVar(value=True)
        ttk.Checkbutton(f,text="Remove verified Cloud staging copies",variable=self.cloud_cleanup).grid(row=4,column=0,columnspan=2,sticky="w",pady=8)
        self.entry("Cloud",5,"manual_plan","Manual batch plan JSON")
        actions=ttk.Frame(f); actions.grid(row=6,column=0,columnspan=2,sticky="w",pady=10)
        self.button(actions,"Prepare manual batch",self.prepare_manual)
        self.button(actions,"Choose batch plan",self.choose_plan)
        self.button(actions,"Import / Resume bucket batch",self.import_manual)
        actions2=ttk.Frame(f); actions2.grid(row=7,column=0,columnspan=2,sticky="w",pady=8)
        self.button(actions2,"Upload ready local mosaics",self.upload_ready)
        self.button(actions2,"Sync EE / clean verified copies",lambda:self.launch("EE sync and cleanup",lambda p:self.sync_locked(p)))
        self.button(actions2,"Setup guide",lambda:webbrowser.open((APP_ROOT/"docs/lite-setup.html").as_uri()))
        ttk.Label(f,text="Manual: prepare a batch plan, upload its listed TIFFs into its exact bucket folder using Cloud Console, then import. "
                  "Keep the project records on the controlling computer. Import sends no local raster bytes. It makes a generation-checked server-side "
                  "copy into an app-owned path, submits EE ingestion and removes both copies after verification. This briefly uses extra bucket storage. "
                  "Unlisted files are never adopted or deleted. The automatic staging cap cannot limit your browser uploads. "
                  "Switch upload routes within the same project; a separate project lacks the collection's earlier source history.",
                  wraplength=950).grid(row=8,column=0,columnspan=2,sticky="w",pady=12)

    def _statistics_tab(self) -> None:
        """Show full plan coverage and reusable engine accounting."""
        f=self.tabs["Statistics"]; bar=ttk.Frame(f);bar.grid(row=0,column=0,columnspan=2,sticky="w",pady=6)
        self.button(bar,"Refresh Statistics",lambda:self.launch("Statistics",lambda p:None,save=False))
        self.metrics=ttk.Treeview(f,columns=("metric","value"),show="headings",height=12)
        self.metrics.heading("metric",text="Metric");self.metrics.heading("value",text="Value")
        self.metrics.column("metric",width=500); self.metrics.column("value",width=400)
        self.metrics.grid(row=1,column=0,columnspan=2,sticky="ew")
        self.coverage=ttk.Treeview(f,columns=("tile","period","expected","verified","state"),show="headings",height=12)
        for key,label in (("tile","Tile"),("period","Acquisition dates"),("expected","NASA inputs"),("verified","Verified in EE"),("state","Batch state")):
            self.coverage.heading(key,text=label);self.coverage.column(key,width=165)
        self.coverage.grid(row=2,column=0,columnspan=2,sticky="ew",pady=12)
        ttk.Label(f,text="Counts cover every batch in the current requested scope, not just the latest year. Local-ready and bucket-uploaded are not EE complete. "
                  "EE counts reflect the last verified observation; Sync EE refreshes it. Full source-to-pixel correctness is a separate audit.",
                  wraplength=950).grid(row=3,column=0,columnspan=2,sticky="w")

    def new(self) -> None:
        """Create new data outside either app checkout."""
        root=filedialog.askdirectory(title="Choose a new, separate project folder")
        if root:
            try:self.apply(model.create(Path(root),Path(root).name))
            except Exception as exc:messagebox.showerror("New project",str(exc))

    def open(self) -> None:
        """Load an existing Lite project without migration."""
        path=filedialog.askopenfilename(title="Open Lite project",filetypes=[("Lite project","project.yaml")])
        if path:
            try:self.apply(model.open_project(Path(path).parent))
            except Exception as exc:messagebox.showerror("Open project",str(exc))

    def apply(self, project: object) -> None:
        """Populate controls without changing persistent project data."""
        self.project=project;c=project.config;l=c["lite"];cloud=c.get("cloud_upload",{})
        values={"tiles":", ".join(c["download"].get("utm_tiles",[])),"start":c["download"].get("start_date",""),"end":c["download"].get("end_date",""),
            "gdal":c["gdal"]["python"],"destination":c.get("destination_parent",""),"cloud_project":cloud.get("project",""),"bucket":cloud.get("bucket",""),
            "transfers":cloud.get("concurrent_uploads",2),"ingestions":c["upload"].get("max_active_ingestions",2),"staging_gib":cloud.get("staging_limit_gib",3),"prefix":cloud.get("prefix","swotflow-lite"),
            "download_threads":c["download"]["threads"],"download_batch":c["download"]["batch_size"],"extract_workers":c["extract"]["workers"],"mosaic_workers":c["mosaic"]["workers"]}
        values.update({k:l[k] for k in ("batch_mosaics","batch_source_gib","max_prepared_gib","min_free_gib")})
        for k,v in values.items():self.vars[k].set(str(v))
        self.continents.reset()
        self.vars["manual_plan"].set(""); self.mode.set(l["mode"])
        self.intermediate.set(l["cleanup_intermediates"]);self.mosaic_cleanup.set(l["cleanup_mosaics"])
        self.cloud_cleanup.set(cloud.get("delete_after_verification",True))
        self.title.set(f"SWOTFlow Lite v{__version__} — {project.root}")

    def save(self) -> bool:
        """Save editable controls; none affect an already running worker."""
        if not self.project:return False
        try:
            c=deepcopy(self.project.config);v={k:x.get().strip() for k,x in self.vars.items()}
            c["download"].update(utm_tiles=normalize_utm_tiles(v["tiles"]),start_date=v["start"],end_date=v["end"],threads=int(v["download_threads"]),batch_size=int(v["download_batch"]))
            c["extract"]["workers"]=int(v["extract_workers"]);c["mosaic"]["workers"]=int(v["mosaic_workers"])
            c["gdal"]["python"]=v["gdal"];c["destination_parent"]=v["destination"]
            c["cloud_upload"].update(project=v["cloud_project"],bucket=v["bucket"],prefix=v["prefix"],concurrent_uploads=int(v["transfers"]),staging_limit_gib=float(v["staging_gib"]),delete_after_verification=self.cloud_cleanup.get())
            c["upload"].update(backend="gcs",max_active_ingestions=int(v["ingestions"]),completion_mode="wait_for_ee")
            c["lite"].update(mode=self.mode.get(),batch_mosaics=int(v["batch_mosaics"]),cleanup_intermediates=self.intermediate.get(),cleanup_mosaics=self.mosaic_cleanup.get())
            for k in ("batch_source_gib","max_prepared_gib","min_free_gib"):c["lite"][k]=float(v[k])
            c["cleanup"].update(mosaics_enabled=self.mosaic_cleanup.get(),mosaic_policy="confirmed_ingestion")
            self.project.config=c;save_project(self.project);self.status.set("Settings saved. Resume keeps recorded scientific work.");return True
        except (ValueError,OSError) as exc:messagebox.showerror("Settings",str(exc));return False

    def choose_gdal(self) -> None:
        path=filedialog.askopenfilename(title="GDAL environment Python executable")
        if path:self.vars["gdal"].set(path)

    def choose_plan(self) -> None:
        path=filedialog.askopenfilename(title="Choose manual batch plan",filetypes=[("JSON batch plan","*.json")])
        if path:self.vars["manual_plan"].set(path)

    def prepare_manual(self) -> None:
        """Export one expected manual batch with its exact upload folder."""
        def task(p: object) -> None:
            from swotflow_lite.manual_import import prepare_manual_batch
            batch=datetime.now().strftime("%Y%m%dT%H%M%S")
            path=p.root/"00_logs/manual_batches"/(batch+".json")
            with model.lite_lock(p.root):
                worker=runner.make_cloud_worker(p)
                prefix="manual-upload/"+worker.owner+"/"+batch
                try:result=prepare_manual_batch(worker,path,prefix,limit=p.config["lite"]["batch_mosaics"])
                finally:worker.report.write()
            self.events.put(("plan",str(path)))
            self.emit("Manual batch prepared: "+str(path)+"; upload folder: gs://"+p.config["cloud_upload"]["bucket"]+"/"+prefix+"/")
            self.emit(json.dumps(result,default=str)[:800])
        self.launch("Prepare manual upload batch",task)

    def import_manual(self) -> None:
        path=Path(self.vars["manual_plan"].get())
        def task(p: object) -> None:
            from swotflow_lite.manual_import import import_manual_batch
            with model.lite_lock(p.root):
                worker=runner.make_cloud_worker(p)
                try:result=import_manual_batch(worker,path,wait_for_ee=True,stop_event=self.stop)
                finally:worker.report.write()
            self.emit(json.dumps(result,default=str))
            self.sync_locked(p)
        self.launch("Import manual bucket batch",task)

    def sync_locked(self, project: object) -> None:
        with model.lite_lock(project.root):runner.sync_and_cleanup(project,self.emit)

    def upload_ready(self) -> None:
        def task(p: object) -> None:
            from swotflow.earthengine.uploader import main
            with model.lite_lock(p.root):
                result=main(["--config",str(runner.cloud_config_path(p)),"--yes"])
                self.emit(f"Cloud upload returned {result}; pending/failed files are retained.")
                runner.sync_and_cleanup(p,self.emit)
        self.launch("Upload prepared local mosaics",task)

    def show_stats(self, p: object) -> None:
        result=statistics.snapshot(p);model.write_json(p.root/"00_logs/lite_statistics.json",result);self.events.put(("stats",result))

    def launch(self, label: str, task: object, *, save: bool=True, needs_project: bool=True) -> None:
        """Run an operation on frozen settings and report progress to the GUI."""
        if self.busy:return
        if needs_project and not self.project:
            messagebox.showinfo("Project required","Create or open a Lite project first.");return
        if save and not self.save():return
        project=deepcopy(self.project);self.busy=True;self.stop.clear()
        for button in self.buttons:button.configure(state="disabled")
        self.status.set(label+" running…")
        def background() -> None:
            try:
                task(project)
                if project:self.show_stats(project)
                self.events.put(("done",label+" finished. Review pending/attention counts."))
            except Exception as exc:
                self.events.put(("error",str(exc)))
        threading.Thread(target=background,daemon=False).start()

    def emit(self, text: str) -> None:
        self.events.put(("log",str(text)))

    def drain(self) -> None:
        """Marshal progress and results onto the Tk thread."""
        try:
            for _ in range(150):
                kind,value=self.events.get_nowait()
                if kind=="stats":
                    self.metrics.delete(*self.metrics.get_children());self.coverage.delete(*self.coverage.get_children())
                    for key,val in value["metrics"].items():self.metrics.insert("","end",values=(key,val))
                    for row in value["batches"]:self.coverage.insert("","end",values=(row["tile"],row["start"]+" / "+row["end"],row["expected"],row["verified"],row["state"]))
                elif kind=="plan":self.vars["manual_plan"].set(value)
                else:
                    self.log.configure(state="normal");self.log.insert("end",value+"\n");self.log.see("end");self.log.configure(state="disabled")
                    if kind in {"done","error"}:
                        self.busy=False;self.status.set(value)
                        for button in self.buttons:button.configure(state="normal")
                        if kind=="error":messagebox.showerror("Operation needs attention",value)
        except Empty:pass
        self.root.after(150,self.drain)

    def close(self) -> None:
        if self.busy:
            self.stop.set();messagebox.showinfo("Operation active","Stop requested. Let the current stage/Cloud verification finish before closing. Checkpoints survive an unexpected shutdown.")
        else:self.root.destroy()


def main() -> None:
    """Launch the separate Lite application."""
    root=tk.Tk();LiteApp(root);root.mainloop()
