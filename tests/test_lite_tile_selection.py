"""Selection changes scope only; presets, clicks and text share one tile list."""
import tkinter as tk
from types import SimpleNamespace
import unittest
from unittest import mock

from swotflow.project.model import load_builtin_tile_presets
from swotflow.ui.utm_map import hit_test_tile
from swotflow_lite.tile_selection import (combine_continents, selection_geometry, country_reference,
    zone_tiles, line_segments, TileMapDialog)


class SelectionDataTests(unittest.TestCase):
    def test_multiple_continents_union_and_keep_manual_extras(self):
        presets = load_builtin_tile_presets()
        expected = set(presets['Africa'].tiles) | set(presets['Europe'].tiles)
        combined = combine_continents('UTM56H, UTM35L', ['Africa', 'Europe'])
        self.assertEqual(set(combined), expected | {'UTM56H', 'UTM35L'})
        self.assertEqual(len(combined), len(set(combined)))
        self.assertEqual(set(combine_continents(combined, ['Africa','Europe'], replace=True)), expected)
        self.assertEqual(combine_continents(combined, ['Africa','Europe']), combined)

    def test_empty_unknown_or_invalid_selection_is_not_silently_discarded(self):
        for current, names in [('UTM35L', []), ('UTM35L', ['Unknown']), ('typo', ['Africa'])]:
            with self.assertRaises(ValueError):combine_continents(current, names)

    def test_presets_all_have_clickable_geometry(self):
        geometry = selection_geometry()
        for preset in load_builtin_tile_presets().values():
            self.assertTrue(set(preset.tiles) <= geometry.tiles.keys())

    def test_reference_coordinates_and_utm_special_zones(self):
        geometry = selection_geometry()
        for point, expected in [((2.35,48.85),'UTM31U'), ((36.8,-1.3),'UTM37M'),
                                ((151.2,-33.9),'UTM56H'), ((6.5,60),'UTM32V'), ((18,78),'UTM33X')]:
            self.assertEqual(hit_test_tile(geometry, point), expected)
        self.assertIsNone(hit_test_tile(geometry,(0,88)))
        countries = {c['name']:c for c in country_reference()}
        for name, bounds in [('Kenya',(33,-5,42,5)),('France',(-6,41,10,52)),('Australia',(110,-45,155,-10))]:
            x,y = countries[name]['label']; a,b,c,d=bounds
            self.assertTrue(a<x<c and b<y<d, name)

    def test_zone_selection_distinguishes_latitude_band_from_hemisphere(self):
        north = zone_tiles(36,'North'); south = zone_tiles(36,'South')
        self.assertIn('UTM36S',north);self.assertNotIn('UTM36S',south)
        self.assertIn('UTM36M',south);self.assertIn('UTM36N',north)
        self.assertFalse(set(north)&set(south))
        self.assertEqual(set(zone_tiles(36)),set(north)|set(south))
        with self.assertRaises(ValueError):zone_tiles(61)

    def test_reference_line_does_not_bridge_antimeridian(self):
        self.assertEqual(list(line_segments([(170,0),(180,0),(-180,0),(-170,0)])),
                         [[(170,0),(180,0)],[(-180,0),(-170,0)]])


class SelectionDialogTests(unittest.TestCase):
    def setUp(self):
        self.root=tk.Tk();self.root.withdraw();self.applied=[]
        self.dialog=TileMapDialog(self.root,['UTM35L'],self.applied.append)
        self.root.update_idletasks();self.dialog.redraw()
        self.addCleanup(self.root.destroy)

    def test_click_and_apply_return_exact_selection(self):
        x,y=self.dialog.transform.world_to_canvas((27.5,-12))
        self.dialog.click(SimpleNamespace(x=x,y=y))
        self.assertNotIn('UTM35L',self.dialog.selected)
        self.dialog.view=(24,-18,36,-6);self.dialog.redraw()
        x,y=self.dialog.transform.world_to_canvas((27.5,-12))
        token=hit_test_tile(self.dialog.geometry_data,(27.5,-12))
        before=set(self.dialog.selected);self.dialog.click(SimpleNamespace(x=x,y=y))
        self.assertEqual(self.dialog.selected,before^{token})
        expected=sorted(self.dialog.selected);self.dialog.apply()
        self.assertEqual(self.applied,[expected])

    def test_cancel_and_preset_edit_do_not_commit(self):
        self.dialog.continents(['Africa','Europe'],True)
        self.assertGreater(len(self.dialog.selected),100)
        self.assertFalse(self.applied)
        self.dialog.destroy();self.assertFalse(self.applied)

    def test_panning_zoom_and_fit_do_not_change_selection(self):
        original=set(self.dialog.selected)
        self.dialog.zoom(0.75);self.dialog.world();self.dialog.fit()
        self.dialog.pan_start(SimpleNamespace(x=100,y=100))
        self.dialog.pan_move(SimpleNamespace(x=150,y=120));self.root.update_idletasks()
        self.assertEqual(self.dialog.selected,original)

    def test_grids_in_aspect_fit_margins_are_drawn_and_clickable(self):
        self.dialog.view=(24,-16,30,-8)
        # A withdrawn test root does not receive a real screen size.
        with mock.patch.object(self.dialog.canvas,'winfo_width',return_value=1100), \
             mock.patch.object(self.dialog.canvas,'winfo_height',return_value=500):
            self.dialog.redraw()
        point=self.dialog.transform.canvas_to_world((1075,250))
        token=hit_test_tile(self.dialog.geometry_data,point)
        self.assertIsNotNone(token)
        self.assertTrue(self.dialog.canvas.find_withtag('tile:'+token))


if __name__=='__main__':unittest.main()
