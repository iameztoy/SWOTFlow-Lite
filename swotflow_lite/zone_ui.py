"""Selected zone order and preparation window in the shared Process tab."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from swotflow.processing.download import normalize_utm_tiles
from swotflow_lite.grouping import HEMISPHERE, LABELS, WINDOWS, scope_groups


class ZonePanel(ttk.LabelFrame):
    """Preview the exact selected bands using the same ordering as the planner."""

    def __init__(self, app, parent: ttk.Frame) -> None:
        super().__init__(parent, text="Zone processing", padding=8)
        self.app = app
        self.columnconfigure(1, weight=1)
        app.vars["zone_window"] = tk.StringVar(value=next(iter(WINDOWS)))
        ttk.Label(self, text="Preparation window").grid(row=0, column=0, sticky="w", padx=(0, 12))
        ttk.Combobox(self, textvariable=app.vars["zone_window"], values=list(WINDOWS),
                     state="readonly").grid(row=0, column=1, sticky="ew")
        ttk.Label(self, text="Each mosaic still uses one UTC date, cycle and pass. "
                  "Size limits can shorten a batch. Use Catalogue / plan to apply window changes to unstarted work.",
                  wraplength=750).grid(row=1, column=0, columnspan=2, sticky="w", pady=5)
        self.summary = tk.StringVar()
        ttk.Label(self, textvariable=self.summary, wraplength=750).grid(row=2, column=0, columnspan=2, sticky="w")
        table = ttk.Frame(self)
        table.grid(row=3, column=0, columnspan=2, sticky="ew", pady=4)
        table.columnconfigure(0, weight=1)
        self.tree = ttk.Treeview(table, columns=("order", "grid", "bands"), show="headings", height=4)
        for key, label, width in (("order", "Order", 55), ("grid", "Output zone / hemisphere", 175),
                                  ("bands", "Selected input tiles", 310)):
            self.tree.heading(key, text=label)
            self.tree.column(key, width=width, stretch=key == "bands")
        self.tree.grid(row=0, column=0, sticky="ew")
        for orientation, command, row, col, sticky, option in (
            ("vertical", self.tree.yview, 0, 1, "ns", "yscrollcommand"),
            ("horizontal", self.tree.xview, 1, 0, "ew", "xscrollcommand"),
        ):
            bar = ttk.Scrollbar(table, orient=orientation, command=command)
            bar.grid(row=row, column=col, sticky=sticky)
            self.tree.configure(**{option: bar.set})
        for key in ("tiles", "grouping"):
            app.vars[key].trace_add("write", self.refresh)

    def refresh(self, *_args) -> None:
        variables = self.app.vars
        if LABELS.get(variables["grouping"].get()) != HEMISPHERE:
            self.grid_remove()
            return
        self.grid()
        self.tree.delete(*self.tree.get_children())
        try:
            tiles = normalize_utm_tiles(variables["tiles"].get())
        except ValueError:
            self.summary.set("Check the tile names in Project to preview the zone order.")
            return
        groups = scope_groups({"download": {"utm_tiles": tiles}, "mosaic": {"grouping_mode": HEMISPHERE}})
        self.summary.set(f"Selected scope: {len(groups)} zone/hemisphere groups. "
                         "Each group covers the requested date range before the next. See Statistics for progress.")
        for index, (grid, bands) in enumerate(groups.items(), 1):
            self.tree.insert("", "end", values=(index, grid, ", ".join(bands)))
