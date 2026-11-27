"""Optional hemisphere scheduling: exact membership, safe Resume and attribution."""
import gc
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import threading
import tkinter as tk
from types import SimpleNamespace
import unittest
from unittest import mock

from swotflow_lite import project as model, planner, runner, grouping as g, grouped_runner as grouped
from swotflow_lite.statistics_details import period_rows, requested_scope, input_rows
from swotflow.processing.download import DownloadGranule
from swotflow.processing import automation as engine
from swotflow_lite.app import LiteApp


def name(tile='UTM36P', day='20230920', scene='001F', orbit='555', cycle='003'):
    return f'SWOT_L2_HR_Raster_100m_{tile}_N_x_x_x_{cycle}_{orbit}_{scene}_{day}T182643_{day}T182904_PGD0_01.nc'


class GroupingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        with mock.patch.object(model,'defaults_path',return_value=self.root/'absent.json'):
            self.project=model.create(self.root/'project','Grouping fixture')
        self.config=self.project.config
        self.config['gdal']['python']=sys.executable
        self.config['download'].update(utm_tiles=['UTM36N','UTM36P'],start_date='2023-01-01',end_date='2023-12-31')
        self.config['mosaic']['grouping_mode']=g.HEMISPHERE
        self.checksum={'algorithm':'md5','hash':'source-checksum','size':5}
        self.batch={'id':'fixture','tile':'UTM36N','tiles':['UTM36N','UTM36P'],'grouping_mode':g.HEMISPHERE,
            'start':'2023-09-20','end':'2023-09-20','expected':{name(t):self.checksum for t in ('UTM36N','UTM36P')},
            'groups':1,'source_bytes':10,'state':'pending'}

    def plan(self):
        return {'science':planner.science_identity(self.config),'scope':requested_scope(self.config),
            'batches':[self.batch], 'scans':[{'tile':t,'start':'2023-01-01','end':'2023-12-31',
                'preferred_files':1,'scan_id':'scope'} for t in self.batch['tiles']]}

    def test_partition_uses_latitude_band_not_letter_as_hemisphere(self):
        self.config['download']['utm_tiles']=['UTM36L','UTM36M','UTM36N','UTM36P','UTM36S','UTM35P']
        self.assertEqual(g.scope_groups(self.config),{'UTM36S':['UTM36L','UTM36M'],
            'UTM36N':['UTM36N','UTM36P','UTM36S'],'UTM35N':['UTM35P']})
        self.config['mosaic']['grouping_mode']=g.EXACT
        self.assertEqual(list(g.scope_groups(self.config)),self.config['download']['utm_tiles'])

    def test_whole_day_grouping_reduces_assets_without_combining_passes_cycles_or_dates(self):
        names=[name(t) for t in self.batch['tiles']]+[name(orbit='180'),name(cycle='004'),name(day='20230921')]
        granules=[DownloadGranule(str(i),n,g.source_tile(n),'2023-09-20T18:26:43Z') for i,n in enumerate(names)]
        batches=planner.group_batches(granules,target=1,source_gib=1,expected={n:self.checksum for n in names},grouping_mode=g.HEMISPHERE)
        self.assertEqual([b['groups'] for b in batches],[3,1])
        self.assertEqual(len(batches[0]['expected']),4)
        self.assertEqual(batches[0]['tile'],'UTM36N')
        self.assertTrue(batches[0]['oversized_day'])
        with self.assertRaisesRegex(ValueError,'one native'):
            planner.group_batches(granules,target=50,source_gib=1,expected={n:self.checksum for n in names})

    def test_project_default_and_existing_exact_batch_identity_stay_unchanged(self):
        with mock.patch.object(model,'defaults_path',return_value=self.root/'absent.json'):
            other=model.create(self.root/'default','Default')
        self.assertEqual(other.config['mosaic']['grouping_mode'],g.EXACT)
        n=name();granules=[DownloadGranule('one',n,'UTM36P','2023-09-20T18:26:43Z')]
        import hashlib
        digest=hashlib.sha256(json.dumps({n:self.checksum},sort_keys=True).encode()).hexdigest()[:16]
        self.assertEqual(planner.group_batches(granules,target=50,source_gib=1,expected={n:self.checksum})[0]['id'],
                         'UTM36P_2023-09-20_'+digest)

    def test_expansion_never_silently_replaces_a_started_shared_mosaic(self):
        old=deepcopy(self.batch);old.update(state='ee_verified')
        changed=deepcopy(self.batch);changed['expected'][name('UTM36Q')]=self.checksum
        with self.assertRaisesRegex(ValueError,'membership changed'):
            g.protect_started_groups({'batches':[old]},[changed])
        future=deepcopy(changed);future['expected']={name('UTM36Q',day='20240920'):self.checksum}
        g.protect_started_groups({'batches':[old]},[self.batch,future])
        g.protect_started_groups({'batches':[self.batch]},[changed])

    def test_statistics_attributes_shared_mosaic_to_original_tiles(self):
        plan=self.plan();lineage={'status':'current','conflicts':[],'unresolved_assets':[]}
        tiles,windows=period_rows(self.project,plan,self.batch['expected'],lineage)
        self.assertEqual([(r['tile'],r['expected'],r['state']) for r in tiles],
            [('UTM36N',1,'complete'),('UTM36P',1,'complete')])
        represented={name('UTM36N'):self.checksum}
        tiles,_=period_rows(self.project,plan,represented,lineage)
        self.assertEqual([r['pending'] for r in tiles],[0,1])
        rows=input_rows(plan,represented,{'download_manifest':[],'extract_manifest':[]})
        self.assertEqual({r['tile'] for r in rows},{'UTM36N','UTM36P'})
        self.config['download']['end_date']='2024-12-31'
        self.assertTrue(all(r['state']=='plan_required' for r in period_rows(self.project,plan,represented,lineage)[0]))

    def test_group_config_scopes_every_stage_and_never_reprojects(self):
        config=grouped.group_config(self.project,self.batch,self.root/'run',True)
        for section in ('download','duplicates','extract','mosaic','upload'):
            self.assertEqual(config[section]['utm_tiles'],self.batch['tiles'])
        self.assertEqual(config['extract']['target_crs_mode'],'original')
        self.assertEqual(config['mosaic']['grouping_mode'],g.HEMISPHERE)
        self.assertFalse(config['automation']['yearly_batch'])

    def test_changed_catalogue_fails_before_partial_mosaic(self):
        config=grouped.group_config(self.project,self.batch,self.root/'run',False)
        with mock.patch.object(grouped,'catalogue_selection',return_value=('new',{})):
            with self.assertRaisesRegex(ValueError,'NASA selection differs'):
                grouped.bind_selection(config,self.batch)

    def test_catalogue_plans_all_bands_together_but_records_each_tile(self):
        self.config['download']['utm_tiles']=['UTM36N','UTM36P','UTM36Q','UTM36M']
        def preview(config):
            files=[name(t) for t in config.utm_tiles if t!='UTM36Q']
            granules=[DownloadGranule(str(i),n,g.source_tile(n),'2023-09-20T18:26:43Z') for i,n in enumerate(files)]
            return SimpleNamespace(history_scan_id='-'.join(config.utm_tiles),selected_granules=granules,granules=granules)
        def snapshot(scan):
            names=[name(t) for t in scan.split('-') if t!='UTM36Q']
            return {'status':'complete','candidates':[{'filename':n} for n in names]}
        with mock.patch.object(planner,'build_download_preview',side_effect=preview) as searches, \
             mock.patch.object(planner.CatalogHistory,'snapshot',side_effect=snapshot), \
             mock.patch.object(planner,'expected_checksum',return_value=self.checksum):
            plan=planner.build_plan(self.project)
        self.assertEqual([call.args[0].utm_tiles for call in searches.call_args_list],
                         [['UTM36N','UTM36P','UTM36Q'],['UTM36M']])
        self.assertEqual([b['tile'] for b in plan['batches']],['UTM36N','UTM36S'])
        self.assertEqual([b['groups'] for b in plan['batches']],[1,1])
        self.assertEqual([s['preferred_files'] for s in plan['scans']],[1,1,0,1])
        old=(self.project.root/'00_logs/lite_plan.json').read_bytes()
        with mock.patch.object(planner,'build_download_preview',side_effect=RuntimeError('incomplete search')):
            with self.assertRaises(RuntimeError):planner.build_plan(self.project)
        self.assertEqual((self.project.root/'00_logs/lite_plan.json').read_bytes(),old)

    def test_partial_mosaic_membership_cannot_pass_group_accounting(self):
        config=grouped.group_config(self.project,self.batch,self.root/'run',False)
        from swotflow.verification.pipeline import settings_key
        mo=SimpleNamespace(manifest_csv=Path(config['mosaic']['manifest_csv']),
            output_folder=Path(config['mosaic']['output_folder']),grouping_mode=g.HEMISPHERE)
        proof={'path':str(mo.output_folder/'partial.tif'),'stage':'mosaic','inputs':{},
            'sources':{name('UTM36N'):self.checksum},'settings':settings_key('mosaic',mo)}
        with mock.patch.object(grouped,'mosaic_config',return_value=mo), \
             mock.patch.object(grouped.VerificationStore,'artifacts',return_value={proof['path']:proof}), \
             mock.patch.object(grouped,'artifact_current',return_value=True):
            with self.assertRaisesRegex(ValueError,'coverage is incomplete'):
                grouped.verify_group_outputs(config,self.batch,self.project.root)

    def run_fake(self, *, automatic=False, failure='', stop=None, reusable=None):
        events=[];stop=stop or threading.Event()
        def execute(state,tile,stage,*args,**kwargs):
            events.append((stage,tile))
            return engine.AutomationStageResult(state.run_id,tile,stage,'failed' if stage==failure else 'success',
                                               engine.now_text(),engine.now_text(),message=stage)
        with mock.patch.object(engine,'execute_download_result',side_effect=lambda s,t,*a,**k:execute(s,t,'download')), \
             mock.patch.object(engine,'execute_command_result',side_effect=execute), \
             mock.patch.object(engine,'execute_cleanup_result',side_effect=lambda s,c,t,stage:execute(s,t,stage)), \
             mock.patch.object(grouped,'bind_selection',side_effect=lambda c,b,*a:c['mosaic'].update(selection_scan_id='bound')), \
             mock.patch.object(grouped,'verify_group_outputs',side_effect=lambda *a,**k:events.append(('proof',''))), \
             mock.patch.object(grouped,'storage_reserve_failure',return_value=None), \
             mock.patch.object(grouped,'verified_resume_stages',return_value=(reusable or set(),'')), \
             mock.patch.object(engine,'execute_deferred_upload_repair_if_needed',return_value=[]) as repair:
            state=grouped.run_group_batch(self.project,self.batch,self.root/'run',automatic,stop,lambda _:None)
        return state,events,repair.call_count

    def test_group_stage_order_preserves_all_inputs_until_one_mosaic(self):
        state,events,_=self.run_fake()
        self.assertFalse(state.errors)
        self.assertEqual([x for x in events if x[0]=='mosaic'],[('mosaic','UTM36N')])
        self.assertGreater(events.index(('mosaic','UTM36N')),events.index(('extract','UTM36N')))
        self.assertGreater(events.index(('extracted_cleanup','UTM36P')),events.index(('mosaic','UTM36N')))

    def test_failed_mosaic_retains_extracted_inputs_and_prevents_upload(self):
        state,events,_=self.run_fake(automatic=True,failure='mosaic')
        self.assertTrue(state.errors)
        self.assertFalse(any(s in {'extracted_cleanup','upload','mosaic_cleanup'} for s,_ in events))

    def test_prepare_to_automatic_resume_reuses_local_prefix(self):
        self.run_fake()
        state,events,repairs=self.run_fake(automatic=True,reusable={'download','duplicates','extract','raw_cleanup','mosaic','extracted_cleanup'})
        self.assertFalse(state.errors)
        self.assertFalse(any(s in {'download','extract','mosaic'} for s,_ in events))
        self.assertIn(('upload','UTM36N'),events)
        self.assertEqual(repairs,1)

    def test_stop_prevents_next_stage(self):
        stop=threading.Event();stop.set()
        state,events,_=self.run_fake(stop=stop)
        self.assertTrue(state.stopped);self.assertFalse(events)

    def test_grouped_overlap_preserves_stages_and_passes_throughput_mode(self):
        self.config['lite'].update(mode='automatic',overlap_ee_ingestion=True,max_pending_batches=2)
        before=planner.science_identity(self.config)
        config=grouped.group_config(self.project,self.batch,self.root/'run',True)
        self.assertEqual(config['upload']['completion_mode'],'submit_and_continue')
        state,events,_=self.run_fake(automatic=True)
        self.assertFalse(state.errors)
        self.assertIn(('upload','UTM36N'),events)
        self.assertIn(('ee_sync','UTM36N'),events)
        self.assertEqual(planner.science_identity(self.config),before)

    def test_ui_persists_mode_and_refuses_switching_existing_plan(self):
        root=tk.Tk();root.withdraw()
        def dispose():
            for timer in root.tk.call('after','info'):root.after_cancel(timer)
            root.update_idletasks();root.destroy();gc.collect()
        self.addCleanup(dispose)
        app=LiteApp(root,auto_statistics=False);app.apply(self.project)
        self.assertEqual(g.LABELS[app.vars['grouping'].get()],g.HEMISPHERE)
        self.assertTrue(app.save())
        model.write_json(self.project.root/'00_logs/lite_plan.json',self.plan())
        app.vars['grouping'].set(next(iter(g.LABELS)))
        with mock.patch('swotflow_lite.app.messagebox.showerror'):
            self.assertFalse(app.save())
        self.assertEqual(self.project.config['mosaic']['grouping_mode'],g.HEMISPHERE)


if __name__=='__main__':unittest.main()
