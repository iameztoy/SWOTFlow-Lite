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

    def test_overlap_and_worker_settings_roundtrip_without_science_changes(self):
        from swotflow_lite.planner import science_identity
        before=science_identity(self.project.config)
        self.app.mode.set('automatic');self.app.overlap_ee.set(True)
        for key,value in {'max_pending_batches':'2','transfers':'16','download_threads':'30',
                          'extract_workers':'4','mosaic_workers':'4'}.items():
            self.app.vars[key].set(value)
        self.assertTrue(self.app.save())
        restored=model.open_project(self.project.root)
        self.assertEqual(science_identity(restored.config),before)
        self.assertEqual(restored.config['upload']['completion_mode'],'submit_and_continue')
        self.assertEqual(restored.config['cloud_upload']['concurrent_uploads'],16)
        self.app.apply(restored)
        self.assertTrue(self.app.overlap_ee.get())
        self.assertEqual(self.app.vars['max_pending_batches'].get(),'2')
        self.app.mode.set('prepare');self.assertTrue(self.app.save())
        self.assertEqual(self.app.project.config['upload']['completion_mode'],'wait_for_ee')

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
        from swotflow_lite.grouping import HEMISPHERE, WINDOWS, LABELS
        original=deepcopy(self.project.config)
        self.assertFalse(self.app.zone_panel.winfo_manager())
        self.app.vars["tiles"].set("UTM35L, UTM35M, UTM35P")
        self.app.vars["grouping"].set(next(k for k, v in LABELS.items() if v == HEMISPHERE))
        self.assertEqual(self.app.zone_panel.winfo_manager(), "grid")
        self.assertEqual(len(self.app.zone_panel.tree.get_children()), 2)
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
        self.assertEqual([self.app.notebook.tab(t, "text") for t in self.app.notebook.tabs()],
                         ["Project", "Process", "Cloud", "Statistics"])

    def test_existing_plan_locks_grouping_and_keeps_window_setting(self):
        from swotflow_lite.grouping import EXACT, HEMISPHERE, LABELS
        model.write_json(self.project.root / "00_logs/lite_plan.json", {"batches": []})
        self.app.apply(self.project)
        self.assertTrue(self.app.grouping_combo.instate(["disabled"]))
        self.app.vars["grouping"].set(next(k for k, v in LABELS.items() if v == HEMISPHERE))
        with mock.patch("swotflow_lite.app.messagebox.showerror"):
            self.assertFalse(self.app.save())
        self.assertEqual(model.open_project(self.project.root).config["mosaic"]["grouping_mode"], EXACT)

    def test_overlap_options_follow_route_without_erasing_saved_values(self):
        self.app.mode.set("automatic")
        self.app.overlap_ee.set(True)
        self.app.vars["max_pending_batches"].set("3")
        self.assertEqual(self.app.pending_options.winfo_manager(), "grid")
        self.app.mode.set("prepare")
        self.assertFalse(self.app.pending_options.winfo_manager())
        self.assertFalse(self.app.overlap_control.winfo_manager())
        self.assertTrue(self.app.save())
        self.app.apply(model.open_project(self.project.root))
        self.app.mode.set("automatic")
        self.assertTrue(self.app.overlap_ee.get())
        self.assertEqual(self.app.vars["max_pending_batches"].get(), "3")
        self.assertEqual(self.app.pending_options.winfo_manager(), "grid")

    def test_hidden_invalid_overlap_edit_reuses_saved_limit(self):
        self.app.mode.set("automatic")
        self.app.overlap_ee.set(True)
        self.app.vars["max_pending_batches"].set("three")
        with mock.patch("swotflow_lite.app.messagebox.showerror"):
            self.assertFalse(self.app.save())
        self.app.mode.set("prepare")
        self.assertTrue(self.app.save())
        self.assertEqual(self.app.vars["max_pending_batches"].get(), "2")
        self.assertEqual(model.open_project(self.project.root).config["lite"]["max_pending_batches"], 2)

    def test_bucket_in_project_field_flags_error_without_launching_cloud_work(self):
        self.app.vars["bucket"].set("swot_hr100m")
        for value in ("gs://swot_hr100m", "swot_hr100m"):
            self.app.vars["cloud_project"].set(value)
            self.assertIn("bucket", self.app.cloud_hint.get())
            self.assertTrue(self.app.project_field.instate(["invalid"]))
            with mock.patch("swotflow_lite.app.threading.Thread") as thread, mock.patch(
                    "swotflow_lite.app.messagebox.showerror") as error:
                self.app.launch("Sync", lambda p: None, cloud=True)
                thread.assert_not_called()
                error.assert_called_once()
            self.assertEqual(self.app.notebook.select(), str(self.app.cloud_page))
        self.assertTrue(self.app.save())  # local-only preparation can save incomplete Cloud details
        self.app.vars["cloud_project"].set("shared-name")
        self.app.vars["bucket"].set("shared-name")
        self.assertIn("Confirm", self.app.cloud_hint.get())
        self.assertFalse(self.app.project_field.instate(["invalid"]))

    def test_opening_engine_project_without_lite_marker_is_rejected(self):
        from swotflow.project.model import save_project
        del self.project.config['lite']; save_project(self.project)
        before = (self.project.root/'project.yaml').read_bytes()
        with self.assertRaisesRegex(ValueError, 'Existing GeeUp projects remain separate'):
            model.open_project(self.project.root)
        self.assertEqual((self.project.root/'project.yaml').read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
