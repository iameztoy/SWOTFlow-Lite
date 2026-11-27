"""Paged full-history Statistics, with a full-period coverage map and plots."""
from __future__ import annotations

from collections import Counter
import csv
import json
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from typing import Callable

from swotflow.ui.utm_map import CanvasTransform, hit_test_tile, ring_to_canvas_points
from swotflow_lite.tile_selection import selection_geometry, country_reference, line_segments, visible, WORLD

GROUPS = {
    "Overview": {"metrics":"All totals", "stage_status_counts":"Stage outcomes"},
    "Tiles and dates": {"tiles":"Finished and pending tiles", "years":"Entire period by tile/year", "batches":"Processing batches", "zones":"Zone / hemisphere coverage",
                        "upload_qa_tile_rows":"Pipeline records by tile", "tile_counts":"Download/extraction records by tile", "date_counts":"Records by acquisition date"},
    "Files and lineage": {"preferred_inputs":"Preferred NASA inputs in plan", "download_manifest":"Every recorded download", "extract_manifest":"Every recorded extraction", "mosaic_lineage_rows":"Source-to-mosaic lineage"},
    "Processing versions": {"processing_level_counts":"Versions across stages", "processing_level_tile_counts":"Versions by tile", "product_version_audit_rows":"Version findings"},
    "Mosaics": {"mosaic_manifest":"Every recorded mosaic", "mosaic_output_grid_counts":"Mosaics by output grid", "mosaic_source_tile_counts":"Mosaics by source tile", "mosaic_exclusion_rows":"Excluded source files"},
    "Uploads": {"cloud":"Cloud transfers, ingestions and cleanup", "upload_status_counts":"Upload outcomes", "uploaded_tile_counts":"Verified assets by source tile", "uploaded_date_counts":"Verified assets by date", "uploaded_processing_level_counts":"Source versions in EE assets", "uploaded_grid_counts":"EE output grids", "upload_error_counts":"Upload errors", "ready_not_uploaded_rows":"Ready mosaics awaiting upload", "collection_unknown":"Untracked collection assets", "collection_conflicts":"Duplicate memberships"},
    "NASA history": {"nasa_searches":"All catalogue searches", "nasa_candidates":"Selected search: filenames and version choices", "nasa_events":"Selected search: download events", "nasa_versions":"Selected search: NASA versus recorded EE versions"},
    "Runs and updates": {"plan_revisions":"Lite plan history", "stage_history":"Stage results and recovery attempts", "update_runs":"Engine update runs", "update_campaigns":"Engine update windows", "update_campaign_details":"Update window details", "update_coverage_tile_rows":"Engine update coverage", "all_update_coverage":"All recorded update windows"},
    "Storage and cleanup": {"cleanup":"Disk and cleanup totals", "cleanup_history":"Recorded local cleanup results", "cloud":"Cloud copies and cleanup timestamps"},
    "Consolidation": {"consolidation_tiles":"Registered tile coverage", "consolidation_products":"Replacement register", "consolidation_conflicts":"Registered conflicts", "consolidation_summary":"Register totals", "consolidation_untracked":"Untracked registered assets"},
}

DEFAULT_NOTES = {
    "download_manifest":"Cumulative exact download filenames and recorded status. Files removed after processing remain in history.",
    "extract_manifest":"Cumulative extraction records. A removed intermediate does not erase completed processing history.",
    "mosaic_manifest":"Cumulative mosaic records, including source membership, versions and acquisition intervals. Local presence is separate from historical completion.",
    "mosaic_lineage_rows":"Source-to-output processing history. Filter by filename, tile, version or status; all rows are available through pagination and export.",
    "batches":"Current plan batch checkpoints; a saved running state does not prove that a worker is currently alive.",
    "nasa_candidates":"Choose a row in All catalogue searches, then Load NASA search. Includes lower versions excluded by the existing priority rules.",
    "nasa_events":"Download and transfer events from the selected catalogue search. Original filenames remain in the durable NASA history database.",
    "nasa_versions":"Saved NASA search versus loaded EE lineage, respecting processing-version priority. This is metadata history, not a fresh NASA query or a spatial/pixel-gap assessment.",
    "update_runs":"Full-engine update records when present. Lite's current scope revisions and stage attempts are shown under Lite plan history and Stage results.",
}

LEADING_COLUMNS = {
    "tiles":("tile","state","expected","verified","pending","years_checked","years_requested","start","end"),
    "years":("tile","year","state","expected","verified","pending","catalogue_checked","start","end"),
    "batches":("order","tile","start","end","processing_window","state","mosaics","expected","verified","detail"),
    "zones":("grid","source_tiles","state","expected","verified","mosaics","batches","locally_ready_batches","verified_batches","start","end"),
    "preferred_inputs":("filename","tile","crid","counter","ee_verified","download_status","extraction_status"),
    "download_manifest":("file_name","utm_tile","last_status","downloaded","last_downloaded","raw_exists"),
    "extract_manifest":("input_nc","output_tif","status","updated_at"),
    "cloud":("asset_id","state","route","source_count","cloud_deleted_at","manual_deleted_at","error"),
    "nasa_searches":("start","end","tiles","status","candidates","finished","id"),
    "nasa_candidates":("filename","tile","crid","counter","selected","preferred","reason","collection"),
    "nasa_events":("filename","utc","action","status","local_path"),
    "nasa_versions":("tile","date","status","preferred_nasa","best_recorded_ee","preferred_downloaded"),
    "stage_history":("tile","batch","stage","status","start_time","end_time","message"),
    "cleanup_history":("tile","batch","stage","status","deleted_files","deleted_bytes","end_time","message"),
}


def display(value: object) -> str:
    """Keep nested metadata available without changing its stored structure."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True) if isinstance(value, (dict, list)) else str(value if value is not None else "")


class StatisticsPanel(ttk.Frame):
    """One searchable, scrollable table per view; export and detail retain all fields."""
    page_size = 200

    def __init__(self, parent: tk.Misc, refresh: Callable, export: Callable, load_search: Callable) -> None:
        super().__init__(parent)
        self.result = {}; self.rows = []; self.filtered = []; self.page = 0; self.columns = []
        self.load_search = load_search
        self.columnconfigure(0, weight=1); self.rowconfigure(5, weight=1)
        self.summary = tk.StringVar(value="Open a Lite project to load its Statistics.")
        self.summary_label = ttk.Label(self, textvariable=self.summary, font=("Segoe UI",10,"bold"), wraplength=950)
        self.summary_label.grid(row=0,column=0,sticky="ew",pady=(0,5))
        actions=ttk.Frame(self);actions.grid(row=1,column=0,sticky="ew",pady=4)
        ttk.Button(actions,text="Refresh Statistics",command=refresh).pack(side="left")
        ttk.Button(actions,text="Status map / plots",command=self.open_map).pack(side="left",padx=5)
        ttk.Button(actions,text="Export all tables",command=export).pack(side="left")
        ttk.Button(actions,text="Export displayed table",command=self.export_table).pack(side="left",padx=5)
        ttk.Button(actions,text="Load NASA search",command=self.selected_search).pack(side="left")
        choices=ttk.Frame(self);choices.grid(row=2,column=0,sticky="ew",pady=5)
        self.group=tk.StringVar(value="Overview"); self.view=tk.StringVar()
        self.group_combo=ttk.Combobox(choices,textvariable=self.group,values=list(GROUPS),state="readonly",width=23)
        self.group_combo.pack(side="left")
        self.view_combo=ttk.Combobox(choices,textvariable=self.view,state="readonly",width=46)
        self.view_combo.pack(side="left",padx=8)
        self.group_combo.bind("<<ComboboxSelected>>",lambda e:self.group_changed())
        self.view_combo.bind("<<ComboboxSelected>>",lambda e:self.select_table())
        self.note=tk.StringVar(); self.note_label=ttk.Label(self,textvariable=self.note,wraplength=950)
        self.note_label.grid(row=3,column=0,sticky="ew",pady=4)
        find=ttk.Frame(self);find.grid(row=4,column=0,sticky="ew",pady=4)
        ttk.Label(find,text="Filter rows:").pack(side="left")
        self.query=tk.StringVar();entry=ttk.Entry(find,textvariable=self.query,width=40);entry.pack(side="left",padx=5)
        entry.bind("<Return>",lambda e:self.filter_rows())
        ttk.Button(find,text="Find",command=self.filter_rows).pack(side="left")
        ttk.Button(find,text="Clear filter",command=self.clear_filter).pack(side="left",padx=5)
        self.page_label=tk.StringVar();ttk.Label(find,textvariable=self.page_label).pack(side="right")
        ttk.Button(find,text="Next →",command=lambda:self.move_page(1)).pack(side="right")
        ttk.Button(find,text="← Previous",command=lambda:self.move_page(-1)).pack(side="right",padx=5)
        table=ttk.Frame(self);table.grid(row=5,column=0,sticky="nsew")
        table.columnconfigure(0,weight=1);table.rowconfigure(0,weight=1)
        self.tree=ttk.Treeview(table,show="headings",selectmode="browse",height=13)
        self.tree.grid(row=0,column=0,sticky="nsew")
        y=ttk.Scrollbar(table,orient="vertical",command=self.tree.yview);y.grid(row=0,column=1,sticky="ns")
        x=ttk.Scrollbar(table,orient="horizontal",command=self.tree.xview);x.grid(row=1,column=0,sticky="ew")
        self.tree.configure(yscrollcommand=y.set,xscrollcommand=x.set)
        self.tree.bind("<<TreeviewSelect>>",lambda e:self.show_details())
        detail=ttk.LabelFrame(self,text="Selected row — full filenames and metadata",padding=4)
        detail.grid(row=6,column=0,sticky="ew",pady=(8,0));detail.columnconfigure(0,weight=1)
        self.detail=tk.Text(detail,height=5,wrap="word",state="disabled")
        self.detail.grid(row=0,column=0,sticky="ew")
        dy=ttk.Scrollbar(detail,command=self.detail.yview);dy.grid(row=0,column=1,sticky="ns")
        self.detail.configure(yscrollcommand=dy.set)
        self.bind("<Configure>",self.resize,add="+")
        self.group_changed()

    def resize(self,event: tk.Event) -> None:
        if event.widget is self:
            for label in (self.summary_label,self.note_label):label.configure(wraplength=max(250,event.width-10))

    def clear(self, message: str="Loading Statistics…") -> None:
        self.result={};self.summary.set(message);self.select_table()

    def render(self,result: dict) -> None:
        if self.result.get("selected_scan"):
            result["selected_scan"]=self.result["selected_scan"]
            result["nasa_version_comparison"]=self.result.get("nasa_version_comparison",{})
            for key in ("nasa_candidates","nasa_events","nasa_versions"):
                result.setdefault("tables",{})[key]=self.result.get("tables",{}).get(key,[])
        self.result=result
        scope=result.get("requested_scope",{})
        verified=result.get("metrics",{}).get("Lite originals represented in last verified EE assets","0")
        expected=result.get("metrics",{}).get("Lite preferred NASA originals in current plan","0")
        stamp=result.get("generated_at", "unknown")
        inventory=result.get("collection_lineage",{})
        text=(f"{result.get('finished_tiles',0)}/{len(result.get('tiles',[]))} tiles finished for the ENTIRE period · "
              f"{verified}/{expected} preferred NASA inputs from saved plan verified in EE\n"
              f"Scope: {scope.get('start','')} to {scope.get('end','')} · Updated {stamp} · "
              f"EE inventory: {inventory.get('status','not checked')} ({inventory.get('checked_at','') or 'not checked'})")
        if not result.get("scope_matches"):text+="\nScope changed or not planned: refresh Catalogue / plan."
        if result.get("warnings"):text+="\n"+"; ".join(result["warnings"])
        self.summary.set(text);self.select_table(reset=False)

    def group_changed(self) -> None:
        self.view_combo.configure(values=list(GROUPS[self.group.get()].values()))
        self.view.set(next(iter(GROUPS[self.group.get()].values())))
        self.query.set("");self.select_table()

    def key(self) -> str:
        return next((k for k,v in GROUPS[self.group.get()].items() if v==self.view.get()),"metrics")

    def select_table(self,reset: bool=True) -> None:
        key=self.key();self.rows=self.result.get("tables",{}).get(key,[])
        available=list(dict.fromkeys(k for row in self.rows for k in row))
        self.columns=[k for k in LEADING_COLUMNS.get(key,()) if k in available]
        self.columns.extend(k for k in available if k not in self.columns)
        self.tree.configure(columns=self.columns)
        for column in self.columns:
            self.tree.heading(column,text=column.replace("_"," ").capitalize())
            self.tree.column(column,width=360 if any(w in column for w in ("file","path","message","detail","metric")) else 145,
                             minwidth=70,stretch=False)
        note=self.result.get("definitions",{}).get(key,DEFAULT_NOTES.get(key,"Saved project records. Stage records, source granules and mosaic assets use different units; they must not be added together."))
        if key.startswith("consolidation_") and not self.rows:note+=" No saved consolidation rows in this Lite installation."
        if key.startswith("nasa_") and self.result.get("selected_scan") and key!="nasa_searches":
            note+=" Selected search: "+self.result["selected_scan"]
        if key=="nasa_versions":
            comparison=self.result.get("nasa_version_comparison",{})
            if comparison.get("catalogue_status"):
                note+=f" Search status: {comparison['catalogue_status']}; catalogue: {comparison.get('catalogue_time','')}; EE inventory: {comparison.get('inventory_time','') or 'not checked'}."
            if comparison.get("note"):note+=" "+comparison["note"]
            if comparison.get("limitations"):note+=" "+display(comparison["limitations"])
        self.note.set(note);self.filter_rows(reset=reset)

    def filter_rows(self,reset: bool=True) -> None:
        query=self.query.get().strip().casefold()
        self.filtered=[row for row in self.rows if not query or query in display(row).casefold()]
        if reset:self.page=0
        self.page=min(self.page,max(0,(len(self.filtered)-1)//self.page_size));self.draw_page()

    def clear_filter(self) -> None:
        self.query.set("");self.filter_rows()

    def move_page(self,step: int) -> None:
        self.page=max(0,min(self.page+step,max(0,(len(self.filtered)-1)//self.page_size)));self.draw_page()

    def draw_page(self) -> None:
        self.tree.delete(*self.tree.get_children())
        first=self.page*self.page_size;last=min(first+self.page_size,len(self.filtered))
        for index in range(first,last):
            self.tree.insert("","end",iid=str(index),values=[display(self.filtered[index].get(k,"")) for k in self.columns])
        self.page_label.set(f" {first+1 if self.filtered else 0}–{last} / {len(self.filtered):,} ({len(self.rows):,} total)")
        self.detail.configure(state="normal");self.detail.delete("1.0","end");self.detail.configure(state="disabled")

    def selected_row(self) -> dict:
        selected=self.tree.selection()
        return self.filtered[int(selected[0])] if selected else {}

    def show_details(self) -> None:
        row=self.selected_row()
        self.detail.configure(state="normal");self.detail.delete("1.0","end")
        self.detail.insert("end",json.dumps(row,ensure_ascii=False,indent=2));self.detail.configure(state="disabled")

    def selected_search(self) -> None:
        row=self.selected_row()
        if self.key()!="nasa_searches" or not row:
            messagebox.showinfo("NASA history","Choose NASA history → All catalogue searches, select a row, then Load NASA search.",parent=self);return
        self.load_search(row["id"])

    def show_search(self,value: dict) -> None:
        self.result.setdefault("tables",{}).update(nasa_candidates=value["candidates"],nasa_events=value["events"])
        self.result["tables"]["nasa_versions"]=value.get("comparison",{}).get("rows",[])
        self.result["nasa_version_comparison"]=value.get("comparison",{})
        self.result["selected_scan"]=value["scan_id"]
        self.group.set("NASA history");self.group_changed()
        self.view.set(GROUPS["NASA history"]["nasa_candidates"]);self.select_table()

    def export_table(self) -> None:
        if not self.rows:return
        path=filedialog.asksaveasfilename(parent=self,title="Export complete table (all rows)",defaultextension=".csv",initialfile=self.key()+".csv")
        if not path:return
        try:
            with Path(path).open("w",encoding="utf-8-sig",newline="") as stream:
                writer=csv.DictWriter(stream,self.columns);writer.writeheader()
                writer.writerows({k:display(v) for k,v in row.items()} for row in self.rows)
        except OSError as exc:messagebox.showerror("Export",str(exc),parent=self)

    def open_map(self) -> None:
        if self.result:CoverageWindow(self,self.result)


STYLES={"complete":("#397fa8","Complete"), "pending":("#efc575","Pending / in progress"),
        "attention":("#bc6543","Needs attention"),"stale":("#a699ba","Refresh / review evidence"),
        "empty":("#d1d5d8","No available acquisitions"),"unplanned":("#aeb6bc","Plan required")}


def status_style(state: str) -> str:
    if state=="complete":return "complete"
    if state=="no_available_acquisitions":return "empty"
    if state=="plan_required":return "unplanned"
    if state=="attention":return "attention"
    if state in {"verification_stale","collection_review_required"}:return "stale"
    return "pending"


class CoverageWindow(tk.Toplevel):
    """Read-only full-period map, and historical stage-record plots with explicit units."""
    def __init__(self,parent: tk.Misc,result: dict) -> None:
        super().__init__(parent);self.title("SWOTFlow Lite — full-period coverage")
        self.geometry("1120x820+20+20");self.minsize(800,600)
        self.data=result;self.tiles={r["tile"]:r for r in result.get("tiles",[])}
        self.geometry_data=selection_geometry();self.view=WORLD;self.transform=None;self.pan=None
        scope=result.get("requested_scope",{})
        ttk.Label(self,text=f"Tile completion: {scope.get('start','')} to {scope.get('end','')} · saved evidence {result.get('generated_at','')}",wraplength=1000).pack(anchor="w",padx=12,pady=8)
        controls=ttk.Frame(self);controls.pack(fill="x",padx=12)
        for label,fn in (("Fit tiles",self.fit),("World",self.world),("Zoom +",lambda:self.zoom(.65)),("Zoom −",lambda:self.zoom(1/.65))):
            ttk.Button(controls,text=label,command=fn).pack(side="left",padx=(0,5))
        ttk.Label(controls,text="Hover for counts · Right-drag to pan · Map does not measure spatial data gaps").pack(side="left",padx=8)
        legend=ttk.Frame(self);legend.pack(fill="x",padx=12,pady=5)
        for color,label in STYLES.values():
            tk.Label(legend,text="  ",background=color,relief="solid",borderwidth=1).pack(side="left",padx=(0,3))
            ttk.Label(legend,text=label).pack(side="left",padx=(0,10))
        self.canvas=tk.Canvas(self,background="#eaf2f5",highlightthickness=0,height=400)
        self.canvas.pack(fill="both",expand=True,padx=12)
        self.canvas.bind("<Configure>",lambda e:self.draw())
        self.canvas.bind("<Motion>",self.hover)
        self.canvas.bind("<MouseWheel>",lambda e:self.zoom(.75 if e.delta>0 else 1/.75))
        self.canvas.bind("<ButtonPress-3>",lambda e:setattr(self,"pan",(e.x,e.y,self.view)))
        self.canvas.bind("<B3-Motion>",self.drag)
        self.info=tk.StringVar(value="Only current-scope tiles are coloured. No colour means outside the requested scope.")
        ttk.Label(self,textvariable=self.info,wraplength=1050).pack(anchor="w",padx=12,pady=5)
        self.chart=tk.Canvas(self,height=160,background="white",highlightthickness=0)
        self.chart.pack(fill="x",padx=12);self.chart.bind("<Configure>",lambda e:self.plot())
        ttk.Label(self,text="Longitude/latitude view · UTM 80°S–84°N · Natural Earth 1:110m reference boundaries · Refresh Statistics reads local evidence; Cloud Sync refreshes EE.",wraplength=1050).pack(anchor="w",padx=12,pady=8)
        self.fit();self.transient(parent.winfo_toplevel())

    def fit(self) -> None:
        boxes=[self.geometry_data.tiles[k].bounds for k in self.tiles if k in self.geometry_data.tiles]
        if boxes:
            self.view=(min(b[0] for b in boxes)-4,min(b[1] for b in boxes)-4,max(b[2] for b in boxes)+4,max(b[3] for b in boxes)+4)
        else:self.view=WORLD
        self.draw()

    def world(self) -> None:
        self.view=WORLD;self.draw()

    def zoom(self,factor: float) -> None:
        a,b,c,d=self.view;x,y=(a+c)/2,(b+d)/2
        if 3<(c-a)*factor<=400:
            self.view=(x+(a-x)*factor,y+(b-y)*factor,x+(c-x)*factor,y+(d-y)*factor);self.draw()

    def drag(self,event: tk.Event) -> None:
        if self.pan and self.transform:
            x,y,(a,b,c,d)=self.pan;dx=(event.x-x)/self.transform.scale;dy=(event.y-y)/self.transform.scale
            self.view=(a-dx,b+dy,c-dx,d+dy);self.draw()

    def draw(self) -> None:
        if not hasattr(self,"canvas"):return
        self.canvas.delete("all");t=self.transform=CanvasTransform(self.view,self.canvas.winfo_width(),self.canvas.winfo_height())
        viewport=(*t.canvas_to_world((0,self.canvas.winfo_height())),*t.canvas_to_world((self.canvas.winfo_width(),0)))
        for land in self.geometry_data.continents:
            if visible(land.bounds,viewport):
                for ring in land.polygons:self.canvas.create_polygon(ring_to_canvas_points(t,ring),fill="#e5e3d9",outline="#aeb5ae")
        for token,tile in self.geometry_data.tiles.items():
            if not visible(tile.bounds,viewport):continue
            color=STYLES[status_style(self.tiles[token]["state"])][0] if token in self.tiles else ""
            for ring in tile.polygons:self.canvas.create_polygon(ring_to_canvas_points(t,ring),fill=color,outline="#536b7b" if color else "#b9c6ce",width=1 if color else .5)
        for country in country_reference():
            for ring in country["rings"]:
                for line in line_segments(ring):self.canvas.create_line(ring_to_canvas_points(t,line),fill="#727a70",width=.7)
        for token,row in self.tiles.items():
            tile=self.geometry_data.tiles.get(token)
            if tile and visible(tile.bounds,viewport):
                a,b,c,d=tile.bounds
                if (c-a)*t.scale>42 and (d-b)*t.scale>25:
                    x,y=t.world_to_canvas(((a+c)/2,(b+d)/2))
                    self.canvas.create_text(x,y,text=token[3:],font=("Segoe UI",9,"bold"),fill="#142c3a")

    def hover(self,event: tk.Event) -> None:
        if self.transform:
            tile=hit_test_tile(self.geometry_data,self.transform.canvas_to_world((event.x,event.y)))
            row=self.tiles.get(tile)
            if row:self.info.set(f"{tile}: {row['state'].replace('_',' ')} · {row['verified']}/{row['expected']} preferred inputs verified · {row['pending']} pending · {row['years_checked']}/{row['years_requested']} yearly catalogue windows checked")
            else:self.info.set(f"{tile or 'Outside UTM coverage'}: outside the requested tile scope.")

    def plot(self) -> None:
        self.chart.delete("all");width=self.chart.winfo_width();half=width/2
        counts=Counter(status_style(row["state"]) for row in self.tiles.values())
        self.chart.create_text(12,12,text="Tiles by completion category (entire requested period)",anchor="w",font=("Segoe UI",10,"bold"))
        for index,(key,count) in enumerate(counts.items()):
            y=32+index*19;color,label=STYLES[key]
            self.chart.create_text(12,y,text=label,anchor="w",font=("Segoe UI",8))
            length=(half-240)*count/max(1,max(counts.values()))
            self.chart.create_rectangle(205,y-5,205+length,y+6,fill=color,outline="")
            self.chart.create_text(211+length,y,text=str(count),anchor="w")
        months=Counter()
        for row in self.data.get("tables",{}).get("uploaded_date_counts",[]):months[str(row["date"])[:7]]+=row["count"]
        self.chart.create_text(half+15,12,text="Historical verified assets by acquisition month",anchor="w",font=("Segoe UI",10,"bold"))
        if not months:
            self.chart.create_text(half+15,50,text="No recorded verified asset dates yet.",anchor="w");return
        ordered=sorted(months.items());step=(half-45)/len(ordered);peak=max(months.values())
        for i,(month,count) in enumerate(ordered):
            x=half+20+i*step;y=130-count/peak*90
            self.chart.create_rectangle(x,y,x+max(1,step-2),130,fill="#397fa8",outline="")
            if len(ordered)<=12 or i in {0,len(ordered)-1}:self.chart.create_text(x,143,text=month,anchor="w",font=("Segoe UI",8))
        self.chart.create_text(half+20,28,text=f"Maximum: {peak} assets/month",anchor="w",font=("Segoe UI",8))
