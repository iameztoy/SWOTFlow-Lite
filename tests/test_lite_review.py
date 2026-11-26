"""Independent workflow review: complete groups, recovery, coverage and cleanup."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest import mock

from swotflow.processing.download import DownloadGranule
from swotflow_lite import planner, runner, statistics
from swotflow_lite.project import write_json


def name(day="20230920", scene="001F", processing="PGD0"):
    return f"SWOT_L2_HR_Raster_100m_UTM35L_N_x_x_x_003_555_{scene}_{day}T182643_{day}T182904_{processing}_01.nc"


class LiteReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / '00_logs').mkdir(); (self.root / '03_mosaics').mkdir()
        self.config = {'destination_parent': 'projects/example/assets/collection', 'metadata': {},
            'download': {'start_date':'2023-01-01','end_date':'2026-12-31','utm_tiles':['UTM35L'],'product_version_filter':'best'},
            'extract': {'target_crs_mode':'original','resampling_alg':'near','workers':4},
            'mosaic': {'grouping_mode':'utm_zone','workers':4},
            'upload': {'backend':'gcs','pyramiding_policy':{'default':'SAMPLE'},'max_active_ingestions':2},
            'execution': {}, 'processing': {}, 'cleanup': {'mosaics_enabled':True},
            'lite': {'mode':'prepare','batch_mosaics':50,'batch_source_gib':2,'max_prepared_gib':20,
                     'min_free_gib':10,'cleanup_intermediates':True,'cleanup_mosaics':True}}
        self.project = SimpleNamespace(root=self.root, config=self.config)
        self.checksum = {'algorithm':'md5','hash':'source-checksum','size':4}

    def batch(self, *, state='pending', day='2023-09-20', filename=None):
        return {'id':'batch-'+day, 'tile':'UTM35L','start':day,'end':day,'expected':{filename or name():self.checksum},
                'groups':1,'source_bytes':4,'state':state,'detail':''}

    def save_plan(self, batches):
        plan = {'schema_version':1,'science':planner.science_identity(self.config),
                'scope':{'tiles':['UTM35L'],'start':'2023-01-01','end':'2026-12-31'},
                'batches':batches,'scans':[]}
        write_json(self.root/'00_logs/lite_plan.json',plan)
        return plan

    def test_complete_mosaic_day_is_not_split_at_source_byte_limit(self):
        files=[name(scene='001F'),name(scene='002F')]
        granules=[DownloadGranule(str(i),n,'UTM35L','2023-09-20T18:26:43Z') for i,n in enumerate(files)]
        batches=planner.group_batches(granules,target=1,source_gib=4/2**30,expected={n:self.checksum for n in files})
        self.assertEqual(len(batches),1)
        self.assertEqual(batches[0]['groups'],1)
        self.assertEqual(len(batches[0]['expected']),2)
        self.assertTrue(batches[0]['oversized_day'])

    def test_day_boundary_uses_same_filename_rule_as_mosaic_grouping(self):
        files=[name(scene='001F'),name(scene='002F')]
        granules=[DownloadGranule('one',files[0],'UTM35L','2023-09-20T23:59:59Z'),
                  DownloadGranule('two',files[1],'UTM35L','2023-09-21T00:00:01Z')]
        batches=planner.group_batches(granules,target=1,source_gib=4/2**30,expected={n:self.checksum for n in files})
        self.assertEqual(len(batches),1)
        self.assertEqual(batches[0]['start'],'2023-09-20')
        self.assertEqual(batches[0]['end'],'2023-09-20')

    def test_batch_limit_finishes_whole_days_before_starting_next(self):
        files=[name(day='20230920'),name(day='20230921')]
        granules=[DownloadGranule(str(i),n,'UTM35L',f'2023-09-{20+i}T18:26:43Z') for i,n in enumerate(files)]
        batches=planner.group_batches(granules,target=1,source_gib=2,expected={n:self.checksum for n in files})
        self.assertEqual(len(batches),2)
        self.assertEqual(set().union(*(set(b['expected']) for b in batches)),set(files))

    def test_runtime_worker_changes_preserve_science_identity(self):
        changed=deepcopy(self.config)
        changed['download']['threads']=20;changed['extract']['workers']=1;changed['mosaic']['workers']=8
        changed['lite']['cleanup_mosaics']=False
        self.assertEqual(planner.science_identity(changed),planner.science_identity(self.config))
        changed['upload']['pyramiding_policy']={'default':'MEAN'}
        self.assertNotEqual(planner.science_identity(changed),planner.science_identity(self.config))

    def test_duplicate_assets_do_not_count_as_verified_coverage(self):
        rows=[{'state':'VERIFIED','asset_id':a,'receipt':{'sources':{name():self.checksum}}} for a in ('asset-one','asset-two')]
        with mock.patch.object(runner,'cloud_rows',return_value=rows):
            represented,conflicts=runner.verified_source_evidence(self.project)
        self.assertFalse(represented)
        self.assertEqual(len(conflicts),1)

    def test_processing_versions_of_one_acquisition_are_a_conflict(self):
        rows=[{'state':'VERIFIED','asset_id':a,'receipt':{'sources':{n:self.checksum}}}
              for a,n in [('old',name(processing='PGD0')),('new',name(processing='PID0'))]]
        with mock.patch.object(runner,'cloud_rows',return_value=rows):
            represented,conflicts=runner.verified_source_evidence(self.project)
        self.assertFalse(represented)
        self.assertEqual(len(conflicts),1)

    def test_statistics_requires_full_plan_not_one_finished_year(self):
        second=name(day='20240920')
        self.save_plan([self.batch(state='ee_verified'),self.batch(state='locally_ready',day='2024-09-20',filename=second)])
        with mock.patch.object(statistics,'collect_project_insights',return_value=SimpleNamespace(metrics={})), \
             mock.patch.object(statistics,'verified_source_evidence',return_value=({name():self.checksum},[])):
            result=statistics.snapshot(self.project)
        self.assertFalse(result['complete'])
        self.assertEqual(result['metrics']['Lite originals still awaiting verified EE coverage'],'1')
        self.assertEqual([b['state'] for b in result['batches']],['ee_verified','locally_ready'])

    def test_empty_catalogue_is_not_falsely_reported_complete(self):
        self.save_plan([])
        with mock.patch.object(statistics,'collect_project_insights',return_value=SimpleNamespace(metrics={})), \
             mock.patch.object(statistics,'verified_source_evidence',return_value=({},[])):
            result=statistics.snapshot(self.project)
        self.assertFalse(result['complete'])
        self.assertEqual(result['status'],'no_available_acquisitions')

    def test_unknown_collection_asset_blocks_completeness_but_preserves_project_counts(self):
        from swotflow.consolidation.core import snapshot_asset
        from swotflow.verification.pipeline import VerificationStore, ingestion_properties, digest, utc_now
        self.save_plan([self.batch(state='ee_verified')])
        collection=self.config['destination_parent']
        own={'id':collection+'/own_mosaic','type':'IMAGE'}
        foreign={'id':collection+'/foreign_mosaic','type':'IMAGE'}
        receipt={'asset_id':own['id'],'token':'revision','local_sha256':'mosaic-hash',
                 'sources':{name():self.checksum},'phase':'confirmed'}
        own['properties']=ingestion_properties(receipt)
        receipt['asset_fingerprint']=digest(snapshot_asset(own))
        VerificationStore(self.root/'00_logs').record_ingestion(receipt)
        inventory={'collection':collection,'assets':[own,foreign],'finished_utc':utc_now()}
        write_json(self.root/'00_logs/verification_ee_inventory.json',inventory)
        with mock.patch.object(statistics,'collect_project_insights',return_value=SimpleNamespace(metrics={})), \
             mock.patch.object(statistics,'verified_source_evidence',return_value=({name():self.checksum},[])):
            result=statistics.snapshot(self.project)
            self.assertFalse(result['complete'])
            self.assertTrue(result['project_inputs_complete'])
            self.assertEqual(result['status'],'collection_review_required')
            self.assertEqual(result['metrics']['Lite originals represented in last verified EE assets'],'1')
            self.assertEqual(result['batches'][0]['state'],'ee_verified')
            self.assertEqual([r['asset_id'] for r in result['collection_lineage']['unresolved_assets']],[foreign['id']])
            inventory['assets']=[own]
            write_json(self.root/'00_logs/verification_ee_inventory.json',inventory)
            result=statistics.snapshot(self.project)
        self.assertTrue(result['complete'])
        self.assertEqual(result['status'],'ee_verified')

    def test_missing_inventory_requires_collection_review_without_erasing_own_receipts(self):
        self.save_plan([self.batch(state='ee_verified')])
        with mock.patch.object(statistics,'collect_project_insights',return_value=SimpleNamespace(metrics={})), \
             mock.patch.object(statistics,'verified_source_evidence',return_value=({name():self.checksum},[])):
            result=statistics.snapshot(self.project)
        self.assertFalse(result['complete'])
        self.assertTrue(result['project_inputs_complete'])
        self.assertEqual(result['collection_lineage']['status'],'not_checked')
        self.assertEqual(result['metrics']['Lite originals represented in last verified EE assets'],'1')

    def test_duplicate_collection_membership_outside_cloud_queue_blocks_complete(self):
        from swotflow.consolidation.core import snapshot_asset
        from swotflow.verification.pipeline import VerificationStore, ingestion_properties, digest, utc_now
        self.save_plan([self.batch(state='ee_verified')])
        collection=self.config['destination_parent'];assets=[]
        store=VerificationStore(self.root/'00_logs')
        for suffix in ('own_mosaic','legacy_mosaic_without_cloud_queue_row'):
            asset={'id':collection+'/'+suffix,'type':'IMAGE'}
            receipt={'asset_id':asset['id'],'token':suffix,'local_sha256':'hash-'+suffix,
                     'sources':{name():self.checksum},'phase':'confirmed'}
            asset['properties']=ingestion_properties(receipt)
            receipt['asset_fingerprint']=digest(snapshot_asset(asset))
            store.record_ingestion(receipt);assets.append(asset)
        write_json(self.root/'00_logs/verification_ee_inventory.json',
                   {'collection':collection,'assets':assets,'finished_utc':utc_now()})
        with mock.patch.object(statistics,'collect_project_insights',return_value=SimpleNamespace(metrics={})), \
             mock.patch.object(statistics,'verified_source_evidence',return_value=({name():self.checksum},[])):
            result=statistics.snapshot(self.project)
        self.assertFalse(result['complete'])
        self.assertTrue(result['project_inputs_complete'])
        self.assertEqual(result['collection_lineage']['unresolved_assets'],[])
        self.assertEqual(len(result['collection_lineage']['conflicts']),1)
        self.assertEqual(result['metrics']['Lite collection conflicting acquisition ownership'],'1')
        self.assertEqual(result['metrics']['Lite originals represented in last verified EE assets'],'1')

    def test_completed_local_checkpoint_permits_recovery_without_second_storage_allowance(self):
        self.config['lite']['mode']='automatic'
        batch=self.batch(state='paused');self.save_plan([batch])
        folder=self.root/'00_logs/lite_runs'/batch['id']/'automatic'
        folder.mkdir(parents=True);(folder/'automation_run.json').write_text('{}',encoding='utf-8')
        saved=SimpleNamespace(stage_results=[SimpleNamespace(stage='mosaic',status='success')])
        result=SimpleNamespace(stopped=False,errors=[],preflight_ok=True,year_batches=[{'status':'complete'}])
        with mock.patch.object(runner,'validate'), mock.patch.object(runner,'sync_and_cleanup'), \
             mock.patch.object(runner,'verified_sources',return_value={}), \
             mock.patch.object(runner,'storage_problem',side_effect=AssertionError('must recover before storage headroom')) as storage, \
             mock.patch.object(runner.engine,'load_automation_run_state',return_value=saved), \
             mock.patch.object(runner.engine,'run_automation',return_value=result) as run:
            outcome=runner.run(self.project,threading.Event())
        storage.assert_not_called()
        self.assertIs(run.call_args.kwargs['preflight_state'],saved)
        self.assertEqual(outcome['batches'][0]['state'],'ee_pending')

    def test_locally_ready_prepare_resume_does_not_repeat_processing(self):
        self.save_plan([self.batch(state='locally_ready')])
        with mock.patch.object(runner,'validate'), mock.patch.object(runner,'verified_sources',return_value={}), \
             mock.patch.object(runner.engine,'run_automation') as run:
            result=runner.run(self.project,threading.Event())
        run.assert_not_called()
        self.assertEqual(result['batches'][0]['state'],'locally_ready')

    def test_cleanup_excludes_status_files_and_covers_earlier_batch_windows(self):
        folder=self.root/'00_logs/manual_batches';folder.mkdir()
        (folder/'batch.json').write_text('{}',encoding='utf-8')
        (folder/'batch.status.json').write_text('{}',encoding='utf-8')
        self.config['processing'].update(acquisition_start_date='2024-01-01',acquisition_end_date='2024-12-31')
        self.config['download'].update(acquisition_start_date='2024-01-01',acquisition_end_date='2024-12-31')
        with mock.patch('swotflow.earthengine.uploader.main',return_value=0), \
             mock.patch.object(runner,'make_cloud_worker',return_value=mock.Mock()), \
             mock.patch('swotflow_lite.manual_import.sync_manual_batches',return_value=[]) as sync, \
             mock.patch.object(runner.engine,'cleanup_stage',return_value=(0,0,[])) as cleanup:
            runner.sync_and_cleanup(self.project)
        self.assertEqual([p.name for p in sync.call_args.args[1]],['batch.json'])
        config,tile,stage=cleanup.call_args.args
        self.assertEqual((tile,stage),('','mosaic'))
        self.assertNotIn('acquisition_start_date',config['processing'])
        self.assertNotIn('acquisition_start_date',config['download'])
        self.assertEqual(config['download']['start_date'],'2023-01-01')
        self.assertEqual(config['download']['end_date'],'2026-12-31')


if __name__ == '__main__':
    unittest.main()
