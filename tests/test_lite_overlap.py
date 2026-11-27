"""Small deterministic scheduler examples; no NASA/Cloud network or billing."""
from copy import deepcopy
import threading
from types import SimpleNamespace
import unittest
from unittest import mock

from swotflow_lite import overlap, runner, statistics, planner
from tests import test_lite_review as fixtures
from tests.test_lite_review import name


class OverlapTests(unittest.TestCase):
    setUp = fixtures.LiteReviewTests.setUp
    batch = fixtures.LiteReviewTests.batch
    save_plan = fixtures.LiteReviewTests.save_plan

    def row(self, batch, state='INGESTING'):
        return {'asset_id':batch['id'],'state':state,'operation':'task/'+batch['id'],
                'receipt':{'sources':batch['expected']}}

    def automatic(self):
        self.config['lite'].update(mode='automatic',overlap_ee_ingestion=True,max_pending_batches=2)

    def test_default_and_manual_do_not_enable_overlap(self):
        self.assertEqual(overlap.completion_mode(self.config),'wait_for_ee')
        self.config['lite']['overlap_ee_ingestion']=True
        self.assertFalse(overlap.enabled(self.config))
        self.automatic()
        self.assertEqual(overlap.completion_mode(self.config),'submit_and_continue')

    def test_settings_do_not_invalidate_existing_scientific_receipts(self):
        before=planner.science_identity(self.config)
        self.automatic();self.config['lite']['max_pending_batches']=4
        self.assertEqual(before,planner.science_identity(self.config))

    def test_only_exact_sources_with_saved_ingestion_are_skipped(self):
        batch=self.batch();row=self.row(batch)
        self.assertTrue(overlap.submitted(batch,{},[row]))
        for state in ('PREPARED','TRANSFERRING','STAGED','SUBMITTING','FAILED','BLOCKED'):
            self.assertFalse(overlap.submitted(batch,{},[{**row,'state':state}]))
        self.assertFalse(overlap.submitted(batch,{},[{**row,'operation':''}]))
        wrong=deepcopy(row);wrong['receipt']['sources'][name()]['hash']='changed'
        self.assertFalse(overlap.submitted(batch,{},[wrong]))

    def test_next_batch_prepares_before_previous_ingestion_finishes_then_drains(self):
        self.automatic()
        batches=[self.batch(),self.batch(day='2023-09-21',filename=name(day='20230921'))]
        self.save_plan(batches);rows=[];events=[];represented={}
        def process(automation,**kwargs):
            index=len(rows)
            self.assertEqual(automation.base_config['upload']['completion_mode'],'submit_and_continue')
            if index==1:self.assertEqual(rows[0]['state'],'INGESTING')
            events.append('prepare-'+str(index));rows.append(self.row(batches[index]))
            return SimpleNamespace(stopped=False,errors=[],preflight_ok=True,year_batches=[{'status':'upload_pending'}])
        def reconcile(*args,**kwargs):
            if len(rows)==2:
                for row in rows:
                    row['state']='VERIFIED';represented.update(row['receipt']['sources'])
                events.append('verify-both')
        with mock.patch.object(runner,'validate'),mock.patch.object(runner,'sync_and_cleanup'), \
             mock.patch.object(runner,'storage_problem',return_value=''), \
             mock.patch.object(runner,'cloud_rows',side_effect=lambda p:rows), \
             mock.patch.object(runner,'verified_sources',side_effect=lambda p:dict(represented)), \
             mock.patch.object(runner,'verified_source_evidence',side_effect=lambda p:(dict(represented),[])), \
             mock.patch.object(overlap,'reconcile',side_effect=reconcile), \
             mock.patch.object(runner.engine,'run_automation',side_effect=process) as execute:
            result=runner.run(self.project,threading.Event())
            self.assertEqual(execute.call_count,2)
            self.assertEqual(events,['prepare-0','prepare-1','verify-both'])
            self.assertEqual(result['pipeline']['state'],'complete')
            self.assertEqual([b['state'] for b in result['batches']],['ee_verified','ee_verified'])
            runner.run(self.project,threading.Event())
            self.assertEqual(execute.call_count,2)  # Resume does not repeat local work/uploads.

    def test_pending_resume_polls_saved_task_without_repeating_processing(self):
        self.automatic();batch=self.batch(state='ee_pending');self.save_plan([batch])
        row=self.row(batch);calls=[];represented={}
        def reconcile(*args,**kwargs):
            calls.append('poll')
            if len(calls)>1:
                row['state']='VERIFIED';represented.update(batch['expected'])
        with mock.patch.object(runner,'validate'),mock.patch.object(runner,'sync_and_cleanup'), \
             mock.patch.object(runner,'cloud_rows',return_value=[row]), \
             mock.patch.object(runner,'verified_sources',side_effect=lambda p:dict(represented)), \
             mock.patch.object(runner,'verified_source_evidence',side_effect=lambda p:(dict(represented),[])), \
             mock.patch.object(overlap,'reconcile',side_effect=reconcile), \
             mock.patch.object(runner.engine,'run_automation') as execute:
            result=runner.run(self.project,threading.Event())
        execute.assert_not_called();self.assertEqual(result['batches'][0]['state'],'ee_verified')

    def test_limit_wait_stop_and_timeout_preserve_pending_evidence(self):
        self.automatic();self.config['lite']['max_pending_batches']=1
        batch=self.batch(state='ee_pending');plan=self.save_plan([batch]);row=self.row(batch)
        stop=threading.Event()
        with mock.patch.object(overlap,'reconcile'),mock.patch.object(runner,'cloud_rows',return_value=[row]), \
             mock.patch.object(runner,'verified_source_evidence',return_value=({},[])), \
             mock.patch.object(stop,'wait',side_effect=lambda _:stop.set()) as wait:
            self.assertFalse(overlap.wait_for_room(self.project,plan,stop,lambda _:None))
            wait.assert_called_once()
        self.assertEqual(plan['pipeline']['state'],'paused')
        self.assertEqual(row['state'],'INGESTING')
        stop.clear()
        with mock.patch.object(overlap,'reconcile'),mock.patch.object(runner,'cloud_rows',return_value=[row]), \
             mock.patch.object(runner,'verified_source_evidence',return_value=({},[])), \
             mock.patch.object(overlap.time,'monotonic',side_effect=[0,50000]):
            self.assertFalse(overlap.wait_for_room(self.project,plan,stop,lambda _:None,drain=True))
        self.assertEqual(plan['pipeline']['state'],'verification_pending')

    def test_failed_task_is_attention_not_complete_and_statistics_keeps_gap(self):
        self.automatic();batch=self.batch(state='ee_pending');plan=self.save_plan([batch])
        row=self.row(batch,'FAILED')
        with mock.patch.object(runner,'cloud_rows',return_value=[row]), \
             mock.patch.object(runner,'verified_source_evidence',return_value=({},[])):
            overlap.refresh(self.project,plan)
        self.assertEqual(plan['batches'][0]['state'],'attention')
        with mock.patch.object(statistics,'collect_project_insights',return_value=SimpleNamespace(metrics={})), \
             mock.patch.object(statistics,'verified_source_evidence',return_value=({},[])):
            result=statistics.snapshot(self.project)
        self.assertFalse(result['complete'])
        self.assertEqual(result['metrics']['Lite originals still awaiting verified EE coverage'],'1')

    def test_reconciliation_uses_existing_cleanup_and_retains_disabled_local_files(self):
        worker=mock.Mock()
        worker.rows.return_value=[]
        with mock.patch.object(runner,'make_cloud_worker',return_value=worker), \
             mock.patch.object(runner.engine,'cleanup_stage',return_value=(0,0,[])) as cleanup:
            overlap.reconcile(self.project,lambda _:None)
            worker.reconcile.assert_called_once();worker.report.write.assert_called_once()
            self.assertEqual(cleanup.call_args.args[0]['cleanup']['mosaic_policy'],'confirmed_ingestion')
            self.config['lite']['cleanup_mosaics']=False
            overlap.reconcile(self.project,lambda _:None)
            self.assertEqual(cleanup.call_count,1)

    def test_statistics_counts_partially_submitted_attention_batch_as_pending(self):
        self.automatic();batch=self.batch(state='attention');self.save_plan([batch])
        row=self.row(batch)
        row.update(manual_import={},size=1)
        with mock.patch.object(statistics,'collect_project_insights',return_value=SimpleNamespace(metrics={})), \
             mock.patch.object(statistics,'verified_source_evidence',return_value=({},[])), \
             mock.patch.object(statistics,'cloud_rows',return_value=[row]):
            result=statistics.snapshot(self.project)
        self.assertFalse(result['complete'])
        self.assertEqual(result['metrics']['Lite ingestion batches awaiting verification'],'1')

    def test_wait_poll_reuses_owner_and_does_not_rescan_unchanged_cleanup(self):
        worker=mock.Mock();worker.rows.return_value=[];context={}
        with mock.patch.object(runner,'make_cloud_worker',return_value=worker) as create, \
             mock.patch.object(runner.engine,'cleanup_stage',return_value=(0,0,[])) as cleanup:
            overlap.reconcile(self.project,lambda _:None,context=context)
            overlap.reconcile(self.project,lambda _:None,context=context)
        self.assertEqual(create.call_count,1)
        self.assertEqual(cleanup.call_count,1)
        self.assertEqual(worker.reconcile.call_count,2)

    def test_storage_pressure_waits_for_guarded_cleanup_before_new_work(self):
        self.automatic()
        batches=[self.batch(),self.batch(day='2023-09-21',filename=name(day='20230921'))]
        self.save_plan(batches);rows=[];represented={};events=[]
        def process(automation,**kwargs):
            batch=batches[len(rows)];events.append('prepare');rows.append(self.row(batch))
            return SimpleNamespace(stopped=False,errors=[],preflight_ok=True,year_batches=[])
        def wait(project,plan,stop,progress,**kwargs):
            if kwargs.get('drain'):
                events.append('drain')
                for row in rows:row['state']='VERIFIED';represented.update(row['receipt']['sources'])
                overlap.refresh(project,plan)
            return True
        with mock.patch.object(runner,'validate'),mock.patch.object(runner,'sync_and_cleanup'), \
             mock.patch.object(runner,'storage_problem',side_effect=['','Retained cap','']), \
             mock.patch.object(runner,'cloud_rows',side_effect=lambda p:rows), \
             mock.patch.object(runner,'verified_sources',side_effect=lambda p:dict(represented)), \
             mock.patch.object(runner,'verified_source_evidence',side_effect=lambda p:(dict(represented),[])), \
             mock.patch.object(overlap,'wait_for_room',side_effect=wait), \
             mock.patch.object(runner.engine,'run_automation',side_effect=process):
            result=runner.run(self.project,threading.Event())
        self.assertEqual(events,['prepare','drain','prepare','drain'])
        self.assertEqual(result['pipeline']['state'],'complete')


class CloudOverlapIntegrationTests(unittest.TestCase):
    """Real uploader/journal/provenance with a deterministic remote transport."""
    def setUp(self):
        from tests.test_cloud_parallel import CloudParallelTests
        CloudParallelTests.setUp(self)

    def test_two_mosaics_saved_tasks_source_history_cleanup_and_resume(self):
        from tests.test_cloud_parallel import CloudParallelTests
        CloudParallelTests.add_items(self,2)
        self.transport.complete_after=10000
        project=SimpleNamespace(root=self.root,config={'lite':{'cleanup_mosaics':False}})
        with mock.patch.object(self.worker,'build_upload_plan',return_value=self.items):
            self.assertEqual(self.worker._run(),0)
        rows=self.worker.rows()
        self.assertEqual(len(rows),2)
        self.assertTrue(all(r['state']=='INGESTING' and r['operation'] for r in rows))
        sources={n:c for r in rows for n,c in r['receipt']['sources'].items()}
        requests=list(self.transport.requests)
        self.transport.complete_after=0
        with mock.patch.object(runner,'make_cloud_worker',return_value=self.worker):
            context={}
            for _ in range(3):overlap.reconcile(project,lambda _:None,context=context)
        rows=self.worker.rows()
        self.assertTrue(all(r['state']=='VERIFIED' and r.get('deleted_at') for r in rows))
        self.assertFalse(self.transport.objects)
        self.assertEqual(sources,{n:c for r in rows for n,c in r['receipt']['sources'].items()})
        with mock.patch.object(self.worker,'build_upload_plan',return_value=self.items):
            self.assertEqual(self.worker._run(),0)
        self.assertEqual(self.transport.requests,requests)
        self.assertEqual(len([e for e in self.transport.events if e[0]=='transfer']),2)


if __name__=='__main__':unittest.main()
