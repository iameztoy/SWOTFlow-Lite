"""A focused zone workflow view over the same project and processing controller."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk, messagebox
from swotflow.processing.download import normalize_utm_tiles
from swotflow_lite.grouping import HEMISPHERE, LABELS, WINDOWS, scope_groups
from swotflow_lite import planner, runner
from swotflow.processing.encoding import COMPRESSION_LABELS


class ZonePanel:
    """Share transfer/cleanup settings and locks; never start a second workflow."""

    def __init__(self, app: object, frame: ttk.Frame) -> None:
        self.app = app
        self.summary = tk.StringVar()
        ttk.Label(frame, textvariable=self.summary, wraplength=950).grid(row=0, column=0, columnspan=2, sticky="w", pady=8)
        actions = ttk.Frame(frame); actions.grid(row=1, column=0, columnspan=2, sticky="w", pady=6)
        app.button(actions, "Use zone/hemisphere grouping", self.activate)
        app.button(actions, "Storage / workers / cleanup…", lambda: app.notebook.select(1))
        ttk.Label(frame, text="Processing window for new zone batches").grid(row=2, column=0, sticky="w", pady=6)
        app.vars['zone_window'] = tk.StringVar(value=next(iter(WINDOWS)))
        ttk.Combobox(frame, textvariable=app.vars['zone_window'], values=list(WINDOWS), state="readonly", width=40).grid(row=2, column=1, sticky="ew", pady=6)
        ttk.Label(frame, text="Half-month/month limits control how much is prepared at once, not the mosaic date. "
            "The source-byte and mosaic-count limits in Process can create smaller batches. Complete UTC dates are never split. "
            "Refresh Catalogue / plan to apply a new window to unstarted work; Resume alone keeps the saved queue.",
            wraplength=950).grid(row=3, column=0, columnspan=2, sticky="w", pady=8)
        ttk.Radiobutton(frame, text="Prepare locally for manual bucket upload", variable=app.mode, value="prepare").grid(row=4, column=0, columnspan=2, sticky="w")
        ttk.Radiobutton(frame, text="Fully automatic: process → bucket → EE → verified cleanup", variable=app.mode, value="automatic").grid(row=5, column=0, columnspan=2, sticky="w")
        table = ttk.Frame(frame); table.grid(row=6, column=0, columnspan=2, sticky="ew", pady=10)
        table.columnconfigure(0, weight=1)
        self.tree = ttk.Treeview(table, columns=('order','grid','bands'), show='headings', height=7)
        for key, label, width in [('order','Order',55),('grid','Output zone / hemisphere',190),('bands','Selected original tiles',610)]:
            self.tree.heading(key,text=label); self.tree.column(key,width=width,stretch=key=='bands')
        self.tree.grid(row=0,column=0,sticky='ew')
        bar=ttk.Scrollbar(table,orient='vertical',command=self.tree.yview);bar.grid(row=0,column=1,sticky='ns');self.tree.configure(yscrollcommand=bar.set)
        x=ttk.Scrollbar(table,orient='horizontal',command=self.tree.xview);x.grid(row=1,column=0,sticky='ew');self.tree.configure(xscrollcommand=x.set)
        actions=ttk.Frame(frame);actions.grid(row=7,column=0,columnspan=2,sticky='w',pady=8)
        app.button(actions,'Authenticate NASA',lambda:app.launch('NASA sign-in',self.authenticate,save=False,needs_project=False))
        app.button(actions,'Catalogue / plan zones',lambda:self.launch('Zone catalogue planning',lambda p:planner.build_plan(p,app.emit)))
        app.button(actions,'Start / Resume zones',lambda:self.launch('Zone processing',lambda p:runner.run(p,app.stop,app.emit)))
        ttk.Button(actions,text='Stop after current stage',command=app.stop.set).pack(side='left')
        ttk.Label(frame,text="The table previews selected scope, not completion. Each hemisphere runs through the full date range before the next group; "
            "both selected hemispheres of a zone stay together. NASA history still records each original tile, filename, version and checksum. "
            "Statistics → Tiles and dates shows zone coverage and the saved batch queue. Cloud settings and all cleanup options are shared with Process. "
            "Prepared-only mosaics remain local until imported and verified in EE.",wraplength=950).grid(row=8,column=0,columnspan=2,sticky='w',pady=8)
        ttk.Label(frame,text="Mosaic compression (shared with Process)").grid(row=9,column=0,sticky='w',pady=6)
        self.compression_combo=ttk.Combobox(frame,textvariable=app.vars['compression'],values=list(COMPRESSION_LABELS),state='readonly',width=42)
        self.compression_combo.grid(row=9,column=1,sticky='ew',pady=6)
        for key in ('tiles','grouping','start','end'):
            app.vars[key].trace_add('write',lambda *args:self.refresh())
        self.refresh()

    @staticmethod
    def authenticate(project: object) -> None:
        """Use the same memory-only NASA sign-in as Process."""
        from swotflow.processing.download import authenticate
        authenticate(strategy='interactive',persist=False)

    def activate(self) -> None:
        """Select grouping only before a project's first plan."""
        app=self.app
        if app.busy:return
        label=next(k for k,v in LABELS.items() if v==HEMISPHERE)
        if app.project and (app.project.root/'00_logs/lite_plan.json').exists() and app.project.config['mosaic'].get('grouping_mode')!=HEMISPHERE:
            messagebox.showerror('Existing project','This project already has a tile-by-tile plan. Use a new project/collection for zone mosaics; its recorded work remains unchanged.',parent=app.root)
            return
        app.vars['grouping'].set(label)

    def launch(self, title: str, action: object) -> None:
        """Guard mode explicitly; delegate to the existing frozen-settings worker."""
        if self.app.busy:return
        if LABELS[self.app.vars['grouping'].get()] != HEMISPHERE:
            messagebox.showerror('Zone processing','Choose Use zone/hemisphere grouping before planning or starting this workflow.',parent=self.app.root)
            return
        self.app.launch(title,action)

    def refresh(self) -> None:
        """Preview selected bands without reading rasters or contacting NASA."""
        app=self.app
        grouped=LABELS.get(app.vars['grouping'].get())==HEMISPHERE
        self.summary.set(('Zone/hemisphere grouping selected. ' if grouped else 'Zone processing is not selected. ')+
            'One native 100 m mosaic per zone, hemisphere, UTC date, cycle and pass. Select all desired bands in Project first; grouping does not add unselected tiles.')
        for row in self.tree.get_children():self.tree.delete(row)
        try:
            config={'download':{'utm_tiles':normalize_utm_tiles(app.vars['tiles'].get())},'mosaic':{'grouping_mode':HEMISPHERE}}
            for i,(token,tiles) in enumerate(scope_groups(config).items(),1):
                self.tree.insert('', 'end',values=(i,token,', '.join(tiles)))
        except ValueError:
            self.summary.set('Enter valid UTM tiles in Project to preview zone processing.')
