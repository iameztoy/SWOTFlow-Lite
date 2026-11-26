"""Offline selection-only map; the project tile list remains the scope authority."""
from __future__ import annotations

from functools import lru_cache
import json
import math
import tkinter as tk
from tkinter import ttk, messagebox

from swotflow.paths import APP_ROOT
from swotflow.processing.download import normalize_utm_tiles
from swotflow.project.model import load_builtin_tile_presets
from swotflow.ui.utm_map import (CanvasTransform, DisplayTile, DisplayContinent,
                               UTMDisplayGeometry, load_display_geometry,
                               hit_test_tile, ring_to_canvas_points)

WORLD = (-180.0, -80.0, 180.0, 84.0)


def combine_continents(current, names, *, replace=False):
    """Union whole presets, preserving manual additions unless replacement is explicit."""
    presets = load_builtin_tile_presets()
    names = list(names)
    if not names:
        raise ValueError("Check one or more continents first.")
    unknown = set(names) - presets.keys()
    if unknown:
        raise ValueError("Unknown continent: " + ", ".join(sorted(unknown)))
    tiles = [] if replace else normalize_utm_tiles(current)
    for name in names:
        tiles.extend(presets[name].tiles)
    return sorted(set(tiles))


def lonlat(point):
    """Invert the bundled EPSG:3857 display coordinates, not scientific raster grids."""
    x, y = point
    return (math.degrees(x / 6378137), math.degrees(math.atan(math.sinh(y / 6378137))))


@lru_cache(maxsize=1)
def selection_geometry():
    """Use geographic display coordinates so a wide world map fits the desktop."""
    original = load_display_geometry()
    def bounds(b):
        return (*lonlat(b[:2]), *lonlat(b[2:]))
    def rings(polygons):
        return [[lonlat(p) for p in ring] for ring in polygons]
    return UTMDisplayGeometry(WORLD,
        {k: DisplayTile(k, bounds(t.bounds), rings(t.polygons)) for k, t in original.tiles.items()},
        [DisplayContinent(c.name, bounds(c.bounds), rings(c.polygons)) for c in original.continents])


@lru_cache(maxsize=1)
def country_reference():
    return json.loads((APP_ROOT / "spatial_presets/country_reference.json").read_text(encoding="utf-8"))["countries"]


def zone_tiles(zone, hemisphere="Both"):
    """Select latitude-band tiles, accounting for N as the first northern band."""
    zone = int(zone)
    if not 1 <= zone <= 60 or hemisphere not in {"North", "South", "Both"}:
        raise ValueError("Choose a zone from 1 to 60 and North, South or Both.")
    return sorted(t for t in selection_geometry().tiles
                  if int(t[3:-1]) == zone and (hemisphere == "Both" or
                  (t[-1] >= "N") == (hemisphere == "North")))


def visible(bounds, view):
    return not (bounds[2] < view[0] or bounds[0] > view[2] or
                bounds[3] < view[1] or bounds[1] > view[3])


def line_segments(ring):
    """Do not join opposite sides of the date line across the entire map."""
    segment = []
    for point in ring:
        if segment and abs(point[0] - segment[-1][0]) > 180:
            if len(segment) > 1:
                yield segment
            segment = []
        segment.append(point)
    if len(segment) > 1:
        yield segment


class ContinentPicker(ttk.LabelFrame):
    """Several checkboxes feed an explicit add/replace action, not hidden selection state."""
    def __init__(self, parent, command, register=None):
        super().__init__(parent, text="Continent presets — check one or several", padding=8)
        self.choices = {}
        for i, (name, preset) in enumerate(load_builtin_tile_presets().items()):
            value = tk.BooleanVar(self, value=False); self.choices[name] = value
            ttk.Checkbutton(self, text=f"{name} ({len(preset.tiles)})", variable=value).grid(
                row=i//4, column=i%4, sticky="w", padx=(0, 14), pady=2)
        actions = ttk.Frame(self); actions.grid(row=2, column=0, columnspan=4, sticky="w", pady=(7, 0))
        for label, replace in (("Add checked continents", False), ("Use only checked continents", True)):
            button = ttk.Button(actions, text=label, command=lambda r=replace: command(self.selected(), r))
            button.pack(side="left", padx=(0, 8))
            if register is not None:
                register.append(button)

    def selected(self):
        return [name for name, value in self.choices.items() if value.get()]

    def reset(self):
        for value in self.choices.values():
            value.set(False)


class TileMapDialog(tk.Toplevel):
    """Edit a private selection; Apply commits it and Cancel leaves the project untouched."""
    def __init__(self, parent, selected, on_apply):
        super().__init__(parent)
        self.title("Select UTM tiles — SWOTFlow Lite")
        width=min(1120,parent.winfo_screenwidth()-40); height=min(820,parent.winfo_screenheight()-80)
        self.geometry(f"{width}x{height}+20+20"); self.minsize(760, 600)
        self.geometry_data = selection_geometry()
        self.selected = set(normalize_utm_tiles(selected)); self.on_apply = on_apply
        self.view = WORLD; self.transform = None; self._draw_job = None; self._pan = None
        self.boundaries = tk.BooleanVar(self, value=True)
        self.labels = tk.BooleanVar(self, value=True)
        self.country_labels = tk.BooleanVar(self, value=True)
        self.info = tk.StringVar(self)
        ttk.Label(self, text="Click tiles to select / deselect · Wheel to zoom · Right-drag to pan",
                  font=("Segoe UI", 11, "bold")).pack(anchor="w", padx=12, pady=(10, 6))
        self.picker = ContinentPicker(self, self.continents); self.picker.pack(fill="x", padx=12)
        bar = ttk.Frame(self); bar.pack(fill="x", padx=12, pady=6)
        for label, command in (("Zoom +", lambda: self.zoom(0.65)), ("Zoom −", lambda: self.zoom(1/0.65)),
                               ("World", self.world), ("Fit selection", self.fit), ("Clear tiles", self.clear)):
            ttk.Button(bar, text=label, command=command).pack(side="left", padx=(0, 4))
        for label, var in (("Boundaries", self.boundaries), ("Country names", self.country_labels), ("Tile labels", self.labels)):
            ttk.Checkbutton(bar, text=label, variable=var, command=self.redraw).pack(side="left")
        zonebar = ttk.Frame(self); zonebar.pack(fill="x", padx=12, pady=(0, 6))
        ttk.Label(zonebar, text="Whole UTM zone:").pack(side="left")
        self.zone = tk.StringVar(self, value="35")
        ttk.Spinbox(zonebar, from_=1, to=60, textvariable=self.zone, width=4).pack(side="left", padx=5)
        self.hemisphere = tk.StringVar(self, value="Both")
        ttk.Combobox(zonebar, textvariable=self.hemisphere, values=("North", "South", "Both"),
                     state="readonly", width=8).pack(side="left")
        ttk.Button(zonebar, text="Add zone", command=self.add_zone).pack(side="left", padx=5)
        ttk.Label(zonebar, text="Blue = selected scope, not uploaded coverage").pack(side="right")
        self.canvas = tk.Canvas(self, background="#eaf2f5", highlightthickness=1, highlightbackground="#aebdc5")
        self.canvas.pack(fill="both", expand=True, padx=12)
        self.canvas.bind("<Configure>", lambda e: self.schedule_draw())
        self.canvas.bind("<Button-1>", self.click)
        self.canvas.bind("<Motion>", self.hover)
        self.canvas.bind("<MouseWheel>", self.wheel)
        self.canvas.bind("<ButtonPress-3>", self.pan_start)
        self.canvas.bind("<B3-Motion>", self.pan_move)
        ttk.Label(self, textvariable=self.info).pack(anchor="w", padx=12, pady=4)
        ttk.Label(self, text="Longitude/latitude reference view · UTM coverage: 80°S–84°N · Natural Earth 1:110m, v5.1.2 boundaries",
                  foreground="#52616b", wraplength=730).pack(anchor="w", padx=12)
        bottom = ttk.Frame(self); bottom.pack(fill="x", padx=12, pady=10)
        ttk.Label(bottom, text="Presets include intersecting grids; NASA availability is checked by Catalogue / plan.",
                  wraplength=430).pack(side="left")
        ttk.Button(bottom, text="Cancel", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(bottom, text="Apply selection", command=self.apply).pack(side="right")
        self.bind("<Escape>", lambda e: self.destroy())
        self.transient(parent); self.grab_set(); self.fit()

    def schedule_draw(self):
        if self._draw_job:
            self.after_cancel(self._draw_job)
        self._draw_job = self.after(30, self.redraw)

    def redraw(self):
        if self._draw_job:
            self.after_cancel(self._draw_job); self._draw_job = None
        self.canvas.delete("all")
        t = self.transform = CanvasTransform(self.view, self.canvas.winfo_width(), self.canvas.winfo_height())
        # Aspect-preserving fit leaves margins. Render every grid visible there too,
        # rather than leaving clickable land without its UTM outlines.
        viewport = (*t.canvas_to_world((0, self.canvas.winfo_height())),
                    *t.canvas_to_world((self.canvas.winfo_width(), 0)))
        for continent in self.geometry_data.continents:
            if visible(continent.bounds, viewport):
                for ring in continent.polygons:
                    self.canvas.create_polygon(ring_to_canvas_points(t, ring), fill="#e5e3d9", outline="#a7ada9")
        for token, tile in self.geometry_data.tiles.items():
            if not visible(tile.bounds, viewport):
                continue
            for ring in tile.polygons:
                self.canvas.create_polygon(ring_to_canvas_points(t, ring), fill="#93c4e2" if token in self.selected else "",
                    outline="#17649a" if token in self.selected else "#b4c3ca", width=1.5 if token in self.selected else 0.5,
                    tags=("tile", "tile:"+token))
        if self.boundaries.get():
            for country in country_reference():
                for ring in country["rings"]:
                    for line in line_segments(ring):
                        if visible((min(p[0] for p in line), min(p[1] for p in line),
                                    max(p[0] for p in line), max(p[1] for p in line)), viewport):
                            self.canvas.create_line(ring_to_canvas_points(t, line), fill="#697570", width=1)
        if self.country_labels.get() and self.view[2] - self.view[0] < 150:
            placed = []
            for country in country_reference():
                x, y = t.world_to_canvas(country["label"])
                if 35 < x < self.canvas.winfo_width()-35 and 12 < y < self.canvas.winfo_height()-12:
                    if any(abs(x-px) < 85 and abs(y-py) < 22 for px, py in placed):
                        continue
                    self.canvas.create_text(x, y, text=country["name"], fill="#424b47", font=("Segoe UI", 9, "italic"))
                    placed.append((x, y))
        if self.labels.get():
            for token, tile in self.geometry_data.tiles.items():
                a, b, c, d = tile.bounds
                if visible(tile.bounds, viewport) and (c-a)*t.scale > 43 and (d-b)*t.scale > 35:
                    x, y = t.world_to_canvas(((a+c)/2, (b+d)/2))
                    self.canvas.create_text(x, y, text=token[3:], fill="#123c5a", font=("Segoe UI", 9, "bold"))
        self.info.set(f"{len(self.selected)} tiles selected. Hover over a tile to identify it.")

    def click(self, event):
        if self.transform:
            token = hit_test_tile(self.geometry_data, self.transform.canvas_to_world((event.x, event.y)))
            if token:
                self.selected.symmetric_difference_update({token}); self.redraw()

    def hover(self, event):
        if self.transform:
            point = self.transform.canvas_to_world((event.x, event.y))
            tile = hit_test_tile(self.geometry_data, point)
            if tile:
                self.info.set(f"{len(self.selected)} tiles selected · {tile} · {'Northern' if tile[-1] >= 'N' else 'Southern'} hemisphere · "
                              f"{point[0]:.2f}°, {point[1]:.2f}°")

    def wheel(self, event):
        if self.transform and event.delta:
            self.zoom(0.75 if event.delta > 0 else 1/0.75, self.transform.canvas_to_world((event.x, event.y)))

    def zoom(self, factor, anchor=None):
        a, b, c, d = self.view
        if (c-a)*factor < 3:
            return
        if (c-a)*factor >= 360:
            self.world(); return
        x, y = anchor or ((a+c)/2, (b+d)/2)
        self.view = (x+(a-x)*factor, y+(b-y)*factor, x+(c-x)*factor, y+(d-y)*factor)
        self.redraw()

    def pan_start(self, event):
        self._pan = (event.x, event.y, self.view)

    def pan_move(self, event):
        if self._pan and self.transform:
            x, y, (a, b, c, d) = self._pan
            dx = (event.x-x)/self.transform.scale; dy = (event.y-y)/self.transform.scale
            self.view = (a-dx, b+dy, c-dx, d+dy); self.schedule_draw()

    def world(self):
        self.view = WORLD; self.redraw()

    def fit(self):
        boxes = [self.geometry_data.tiles[t].bounds for t in self.selected if t in self.geometry_data.tiles]
        if not boxes:
            self.world(); return
        a = min(b[0] for b in boxes); b = min(b[1] for b in boxes)
        c = max(b[2] for b in boxes); d = max(b[3] for b in boxes)
        dx = max(2, (c-a)*0.08); dy = max(2, (d-b)*0.08)
        self.view = (max(-180, a-dx), max(-80, b-dy), min(180, c+dx), min(84, d+dy)); self.redraw()

    def continents(self, names, replace):
        try:
            self.selected = set(combine_continents(self.selected, names, replace=replace)); self.fit()
        except ValueError as exc:
            messagebox.showerror("Continent selection", str(exc), parent=self)

    def add_zone(self):
        try:
            self.selected.update(zone_tiles(self.zone.get(), self.hemisphere.get())); self.fit()
        except ValueError as exc:
            messagebox.showerror("UTM zone", str(exc), parent=self)

    def clear(self):
        self.selected.clear(); self.redraw()

    def apply(self):
        self.on_apply(sorted(self.selected)); self.destroy()

    def destroy(self):
        if self._draw_job:
            self.after_cancel(self._draw_job); self._draw_job = None
        super().destroy()
