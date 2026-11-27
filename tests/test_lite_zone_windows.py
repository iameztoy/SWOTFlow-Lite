"""Zone schedules preserve whole days, source accounting and started checkpoints."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import unittest
from unittest import mock
from types import SimpleNamespace

from swotflow_lite import project as model, planner, runner, grouping, statistics
from swotflow_lite.statistics_details import period_rows, requested_scope
from swotflow.processing.download import DownloadGranule
from tests.test_lite_grouping import name


class ZoneWindowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        with mock.patch.object(model,'defaults_path',return_value=self.root/'none.json'):
            self.project=model.create(self.root/'project','Zone windows')
        self.config=self.project.config
        self.config['gdal']['python']=sys.executable
        self.config['download'].update(utm_tiles=['UTM35N','UTM35P'],start_date='2023-01-01',end_date='2024-12-31')
        self.config['mosaic']['grouping_mode']=grouping.HEMISPHERE
        self.proof={'algorithm':'md5','hash':'fixture','size':5}

    def granules(self, days, tiles=('UTM35N','UTM35P')):
        return [DownloadGranule(str(i)+t,name(t,day=d),t,d[:4]+'-'+d[4:6]+'-'+d[6:]+'T18:26:43Z') for i,d in enumerate(days) for t in tiles]

    def batches(self, files, window='adaptive', **kwargs):
        return planner.group_batches(files,target=kwargs.get('target',50),source_gib=kwargs.get('source_gib',2),
            expected={g.file_name:self.proof for g in files},grouping_mode=grouping.HEMISPHERE,window=window)

    def replan(self, files, previous, window='half_month'):
        return planner.plan_zone_batches(files,previous=previous,token='UTM35N',start='2023-01-01',end='2023-12-31',
            expected={g.file_name:self.proof for g in files},target=50,source_gib=2,window=window)

    def test_half_month_keeps_all_bands_and_passes_on_boundary_days(self):
        files=self.granules(['20230101','20230115','20230116','20230131','20230201'])
        extra=name('UTM35P',day='20230115',orbit='180')
        files.append(DownloadGranule('other-pass',extra,'UTM35P','2023-01-15T18:26:43Z'))
        batches=self.batches(files,'half_month')
        self.assertEqual([(b['start'],b['end']) for b in batches],[('2023-01-01','2023-01-15'),('2023-01-16','2023-01-31'),('2023-02-01','2023-02-01')])
        self.assertEqual([b['groups'] for b in batches],[3,2,1])
        self.assertEqual(sum(len(b['expected']) for b in batches),len(files))
        self.assertEqual(set().union(*(set(b['expected']) for b in batches)),{g.file_name for g in files})

    def test_calendar_month_and_leap_day_never_form_monthly_mosaics(self):
        files=self.granules(['20240131','20240201','20240229','20240301'])
        batches=self.batches(files,'month')
        self.assertEqual([b['groups'] for b in batches],[1,2,1])
        self.assertEqual([len(b['expected']) for b in batches],[2,4,2])
        self.assertEqual(sum(b['groups'] for b in batches),4)

    def test_smaller_byte_limit_wins_without_splitting_a_date(self):
        files=self.granules(['20230101','20230102'])
        batches=self.batches(files,'month',source_gib=5/2**30)
        self.assertEqual(len(batches),2)
        self.assertTrue(all(b['oversized_day'] and len(b['expected'])==2 for b in batches))

    def test_unordered_dates_are_stable_and_invalid_window_rejected(self):
        files=self.granules(['20230301','20230115','20230101'])
        self.assertEqual(self.batches(files,'month'),self.batches(list(reversed(files)),'month'))
        with self.assertRaises(ValueError):self.batches(files,'unknown')

    def test_same_zone_hemispheres_stay_together_in_first_zone_order(self):
        self.config['download']['utm_tiles']=['UTM35P','UTM34L','UTM35M','UTM34N','UTM35N']
        self.assertEqual(list(grouping.scope_groups(self.config)),['UTM35N','UTM35S','UTM34S','UTM34N'])
        self.config['mosaic']['grouping_mode']=grouping.EXACT
        self.assertEqual(list(grouping.scope_groups(self.config)),self.config['download']['utm_tiles'])

    def test_started_batch_id_and_cleanup_history_survive_new_window(self):
        files=self.granules(['20230101','20230120','20230201','20230216'])
        old=self.batches(files[:4])[0]
        old.update(state='locally_ready',run_dir=str(self.root/'previous'),run_mode='prepare',detail='retained cleanup evidence')
        replanned=self.replan(files,[old])
        self.assertEqual(replanned[0],old)
        self.assertEqual(len(replanned),3)
        self.assertEqual(sum(len(b['expected']) for b in replanned),len(files))
        self.assertTrue(all(a['end']<b['start'] for a,b in zip(replanned,replanned[1:])))

    def test_pending_work_either_side_of_started_window_cannot_overlap_it(self):
        files=self.granules(['20230101','20230115','20230125'])
        old=self.batches(files[2:4])[0];old.update(state='paused',run_dir='checkpoint')
        result=self.replan(files,[old],window='month')
        self.assertEqual([b['start'] for b in result],['2023-01-01','2023-01-15','2023-01-25'])
        self.assertEqual(result[1],old)

    def test_added_or_missing_source_inside_started_batch_keeps_saved_plan(self):
        files=self.granules(['20230101','20230120'])
        old=self.batches(files)[0];old['state']='locally_ready'
        for changed in [files[:-1],files+self.granules(['20230110'])]:
            with self.subTest(count=len(changed)),self.assertRaisesRegex(ValueError,'NASA inputs changed'):
                self.replan(changed,[old])
        self.assertEqual(old['state'],'locally_ready')

    def test_unstarted_storage_pause_can_be_rebatched(self):
        files=self.granules(['20230101','20230120'])
        old=self.batches(files)[0];old['state']='storage_pause'
        self.assertEqual(len(self.replan(files,[old])),2)

    def build_mock_plan(self):
        scans={}
        def preview(config):
            year=config.start_date[:4]
            files=self.granules([year+'0115',year+'0116',year+'0201'],config.utm_tiles)
            scan='-'.join(config.utm_tiles)+'-'+year;scans[scan]=files
            return SimpleNamespace(history_scan_id=scan,selected_granules=files,granules=files)
        def snapshot(scan):
            return {'status':'complete','candidates':[{'filename':g.file_name} for g in scans[scan]]}
        with mock.patch.object(planner,'build_download_preview',side_effect=preview) as queries, \
             mock.patch.object(planner.CatalogHistory,'snapshot',side_effect=snapshot), \
             mock.patch.object(planner,'expected_checksum',return_value=self.proof):
            result=planner.build_plan(self.project)
        return result,queries

    def test_entire_zone_period_before_next_zone_with_full_tile_year_accounting(self):
        self.config['download']['utm_tiles']=['UTM35N','UTM34L','UTM35M','UTM35P','UTM34M']
        self.config['lite']['zone_batch_window']='half_month'
        plan,queries=self.build_mock_plan()
        order=[(c.args[0].utm_tiles,c.args[0].start_date) for c in queries.call_args_list]
        self.assertEqual(order,[(['UTM35N','UTM35P'],'2023-01-01'),(['UTM35N','UTM35P'],'2024-01-01'),
            (['UTM35M'],'2023-01-01'),(['UTM35M'],'2024-01-01'),(['UTM34L','UTM34M'],'2023-01-01'),(['UTM34L','UTM34M'],'2024-01-01')])
        self.assertEqual(len(plan['batches']),18)
        expected={n:p for b in plan['batches'] for n,p in b['expected'].items()}
        self.assertEqual(len(expected),30)
        lineage={'status':'current','conflicts':[],'unresolved_assets':[],'observed_sources':expected}
        tiles,years=period_rows(self.project,plan,expected,lineage)
        self.assertEqual(len(years),10);self.assertTrue(all(t['state']=='complete' for t in tiles))
        with mock.patch.object(statistics,'collect_project_insights',return_value=SimpleNamespace(metrics={})), \
             mock.patch.object(statistics,'verified_source_evidence',return_value=(expected,[])), \
             mock.patch.object(statistics,'collection_lineage',return_value=lineage):
            result=statistics.snapshot(self.project)
        self.assertTrue(all(z['state']=='complete' for z in result['tables']['zones']))
        self.assertEqual(sum(z['expected'] for z in result['tables']['zones']),30)
        self.assertEqual(result['metrics']['Lite planned mosaics'],'18')
        self.assertEqual(result['metrics']['Lite mosaics with tile-by-tile grouping'],'30')
        self.assertEqual(result['metrics']['Lite planned asset reduction from grouping'],'12')
        # Simulate a completed prefix, then re-plan with larger windows. Its IDs,
        # cleanup receipts and Resume status must survive exactly.
        plan['batches'][0].update(state='locally_ready',run_dir=str(self.root/'saved'))
        model.write_json(self.project.root/'00_logs/lite_plan.json',plan)
        self.config['lite']['zone_batch_window']='month'
        revised,_=self.build_mock_plan()
        self.assertEqual(revised['batches'][0],plan['batches'][0])
        self.assertEqual({n for b in revised['batches'] for n in b['expected']},set(expected))
        tiles,years=period_rows(self.project,revised,{},lineage)
        self.assertTrue(all(t['state']!='complete' for t in tiles))
        self.assertTrue(all(y['catalogue_checked'] for y in years))

    def test_prepare_resume_skips_protected_ready_batch_then_runs_remaining_zone(self):
        self.config['lite']['zone_batch_window']='half_month'
        plan,_=self.build_mock_plan();plan['batches'][0]['state']='locally_ready'
        model.write_json(self.project.root/'00_logs/lite_plan.json',plan)
        with mock.patch.object(runner,'storage_problem',return_value=''), \
             mock.patch('swotflow_lite.grouped_runner.run_group_batch',return_value=SimpleNamespace(stopped=False,errors=[],preflight_ok=True,year_batches=[])) as run:
            result=runner.run(self.project,threading.Event())
        self.assertEqual(run.call_count,len(plan['batches'])-1)
        self.assertTrue(all(b['state']=='locally_ready' for b in result['batches']))
        self.assertNotIn(plan['batches'][0]['id'],[c.args[1]['id'] for c in run.call_args_list])

    def test_retained_cap_is_explained_even_with_free_space(self):
        (self.project.root/'03_mosaics/test.tif').write_bytes(b'1234')
        self.config['lite']['max_prepared_gib']=3/2**30
        with mock.patch.object(shutil,'disk_usage',return_value=SimpleNamespace(free=70*2**30)):
            message=runner.storage_problem(self.project,{'source_bytes':1})
        self.assertIn('70.0 GiB free',message);self.assertIn('not a full disk',message)
        self.assertIn('Keep unuploaded mosaics',message)


if __name__=='__main__':unittest.main()
