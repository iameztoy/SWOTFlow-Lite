"""Lite settings and GUI entry points preserve project data across operations."""
import gc
from copy import deepcopy
from pathlib import Path
import tempfile
import tkinter as tk
import unittest
from unittest import mock

from swotflow_lite import project as model
from swotflow_lite.app import LiteApp


class LiteAppTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        with mock.patch.object(model, 'defaults_path', return_value=self.folder/'absent.json'):
            self.project = model.create(self.folder/'data', 'Test Lite')
        self.root = tk.Tk(); self.root.withdraw()
        self.app = LiteApp(self.root,auto_statistics=False)
        self.app.apply(self.project)
        self.addCleanup(self.dispose)

    def dispose(self):
        for timer in self.root.tk.call('after', 'info'):
            self.root.after_cancel(timer)
        self.root.update_idletasks()
        self.root.destroy()
        self.app=None; self.root=None
        gc.collect()

    def test_compression_is_shared_and_does_not_change_plan_science_or_history(self):
        from swotflow_lite.planner import science_identity
        from swotflow.processing.encoding import COMPRESSION_LABEL_BY_VALUE
        before=science_identity(self.project.config)
        evidence=self.project.root/'00_logs'/'retained.json';evidence.write_text('{"unchanged":true}')
        self.assertEqual(self.project.config['mosaic']['compression'],'zstd')
        for codec in ('none','deflate','zstd'):
            self.app.vars['compression'].set(COMPRESSION_LABEL_BY_VALUE[codec])
            self.assertEqual(self.app.compression_combo.get(),COMPRESSION_LABEL_BY_VALUE[codec])
            self.assertTrue(self.app.save())
            restored=model.open_project(self.project.root)
            self.assertEqual(restored.config['mosaic']['compression'],codec)
            self.assertEqual(science_identity(restored.config),before)
            self.assertEqual(evidence.read_text(),'{"unchanged":true}')
        del self.project.config['mosaic']['compression']
        self.app.apply(self.project)
        self.assertEqual(self.app.vars['compression'].get(),COMPRESSION_LABEL_BY_VALUE['none'])

    def test_saved_worker_and_route_choices_preserve_paths_and_metadata(self):
        original = deepcopy(self.project.config)
        self.app.mode.set('automatic')
        self.app.vars['transfers'].set('8')
        self.app.vars['download_threads'].set('20')
        self.app.vars['tiles'].set('UTM35L, UTM36L')
        self.app.vars['start'].set('2023-07-01'); self.app.vars['end'].set('2026-09-30')
        self.app.mosaic_cleanup.set(False)
        self.assertTrue(self.app.save())
        restored = model.open_project(self.project.root)
        self.assertEqual(restored.config['cloud_upload']['concurrent_uploads'], 8)
        self.assertEqual(restored.config['download']['threads'], 20)
        self.assertEqual(restored.config['lite']['mode'], 'automatic')
        self.assertFalse(restored.config['lite']['cleanup_mosaics'])
        for section in ('processing', 'metadata', 'artifacts'):
            self.assertEqual(restored.config[section], original[section])
        self.assertEqual(restored.config['download']['manifest_csv'], original['download']['manifest_csv'])
        self.assertEqual(restored.config['upload']['completion_mode'], 'wait_for_ee')

    def test_operation_uses_frozen_settings_and_blocks_overlapping_launch(self):
        saved = []
        with mock.patch('swotflow_lite.app.threading.Thread') as thread, \
             mock.patch.object(self.app, 'show_stats'):
            self.app.launch('Test', lambda p: saved.append(p.config['lite']['mode']), save=False)
            task = thread.call_args.kwargs['target']
            self.project.config['lite']['mode'] = 'automatic'
            self.app.launch('Second', lambda p: None, save=False)
            self.assertEqual(thread.call_count, 1)
            task()
        self.assertEqual(saved, ['prepare'])
        self.assertTrue(self.app.busy)
        self.app.drain()
        self.assertFalse(self.app.busy)

    def test_invalid_number_cannot_partially_save_project(self):
        before = (self.project.root/'project.yaml').read_bytes()
        self.app.vars['transfers'].set('not a number')
        with mock.patch('swotflow_lite.app.messagebox.showerror'):
            self.assertFalse(self.app.save())
        self.assertEqual((self.project.root/'project.yaml').read_bytes(), before)

    def test_continents_manual_and_map_selection_save_same_scope_without_history_changes(self):
        original = deepcopy(self.project.config)
        evidence = self.project.root/'00_logs'/'retained_history.json'
        evidence.write_text('{"existing":true}')
        self.app.vars['tiles'].set('UTM56H')
        self.app.select_continents(['Africa','Europe'])
        selected = self.app.vars['tiles'].get().split(', ')
        self.assertIn('UTM56H', selected)
        selected.remove('UTM35L'); self.app.set_tiles(selected)
        self.assertTrue(self.app.save())
        restored = model.open_project(self.project.root)
        self.assertEqual(restored.config['download']['utm_tiles'],selected)
        self.assertEqual(evidence.read_text(),'{"existing":true}')
        for section in ('artifacts','processing','metadata','lite','cloud_upload'):
            self.assertEqual(restored.config[section],original[section])
        self.assertNotIn('UTM35L',restored.config['download']['utm_tiles'])

    def test_selection_actions_do_not_mutate_active_worker_scope(self):
        self.app.busy=True
        before=self.app.vars['tiles'].get()
        self.app.select_continents(['Africa']);self.app.set_tiles([])
        with mock.patch('swotflow_lite.app.TileMapDialog') as dialog:
            self.app.select_map();dialog.assert_not_called()
        self.assertEqual(self.app.vars['tiles'].get(),before)

    def test_zone_view_shares_route_settings_and_saves_window_without_cloud_changes(self):
        from swotflow_lite.grouping import HEMISPHERE, WINDOWS
        original=deepcopy(self.project.config)
        self.assertEqual(str(self.app.zone_panel.compression_combo.cget("textvariable")), str(self.app.vars["compression"]))
        self.app.zone_panel.activate()
        self.app.vars['zone_window'].set(next(k for k,v in WINDOWS.items() if v=='half_month'))
        self.app.mode.set('prepare')
        self.assertTrue(self.app.save())
        restored=model.open_project(self.project.root)
        self.assertEqual(restored.config['mosaic']['grouping_mode'],HEMISPHERE)
        self.assertEqual(restored.config['lite']['zone_batch_window'],'half_month')
        self.assertEqual(restored.config['cloud_upload'],original['cloud_upload'])
        for section in ('processing','artifacts','metadata'):
            self.assertEqual(restored.config[section],original[section])
        self.app.apply(restored)
        self.assertEqual(WINDOWS[self.app.vars['zone_window'].get()],'half_month')
        self.assertIn('Process Zones',[self.app.notebook.tab(t,'text') for t in self.app.notebook.tabs()])

    def test_zone_actions_protect_existing_exact_plan_and_running_worker(self):
        from swotflow_lite.grouping import EXACT
        model.write_json(self.project.root/'00_logs/lite_plan.json',{'batches':[]})
        with mock.patch('swotflow_lite.zone_ui.messagebox.showerror') as error:
            self.app.zone_panel.activate()
            self.assertEqual(error.call_count,1)
        self.assertEqual(self.project.config['mosaic']['grouping_mode'],EXACT)
        with mock.patch.object(self.app,'launch') as launch, mock.patch('swotflow_lite.zone_ui.messagebox.showerror'):
            self.app.zone_panel.launch('Zone processing',lambda p:None)
            launch.assert_not_called()
            self.app.busy=True
            self.app.zone_panel.launch('Zone processing',lambda p:None)
            launch.assert_not_called()

    def test_opening_engine_project_without_lite_marker_is_rejected(self):
        from swotflow.project.model import save_project
        del self.project.config['lite']; save_project(self.project)
        before = (self.project.root/'project.yaml').read_bytes()
        with self.assertRaisesRegex(ValueError, 'Existing GeeUp projects remain separate'):
            model.open_project(self.project.root)
        self.assertEqual((self.project.root/'project.yaml').read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
