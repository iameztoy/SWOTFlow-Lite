"""Manual bucket import never uploads local bytes or deletes uncertain copies."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
from unittest import mock
import unittest

from tests import test_cloud_upload as fixtures
from swotflow.earthengine.cloud.journal import cloud_metrics
from swotflow.earthengine.cloud.transport import CloudHTTPError
from swotflow.verification.pipeline import digest
from swotflow.earthengine.uploader import UploadItem
from swotflow_lite.manual_import import (
    ManualObjectTransport, WAITING, import_manual_batch, prepare_manual_batch, sync_manual_batches,
)


class FakeManualObjects:
    def __init__(self, worker):
        self.worker = worker
        self.transport = worker.transport
        self.copies = 0
        self.lost_copy_response = False
        self.overwrite_before_copy = False

    def source_object(self, row):
        return deepcopy(self.transport.objects.get(row['manual_import']['object']))

    def copy_to_owned(self, row, checkpoint):
        source = row['manual_import']
        obj = self.source_object(row)
        if self.overwrite_before_copy:
            self.transport.objects[source['object']]['generation'] = '88'
            obj['generation'] = '88'
        if obj['generation'] != source['generation']:
            raise CloudHTTPError('Copy precondition', 412)
        if row['object'] in self.transport.objects:
            raise CloudHTTPError('Destination precondition', 412)
        copied = {'size': str(row['size']), 'md5Hash': row['md5'], 'generation': '123',
                  'metadata': {'sha256': row['sha256'], 'swotflow_owner': row['owner']}}
        self.transport.objects[row['object']] = copied
        self.copies += 1
        self.transport.events.append(('server_copy', row['asset_id']))
        if self.lost_copy_response:
            self.lost_copy_response = False
            raise RuntimeError('response lost')
        return copied

    def delete_source(self, row):
        source = row['manual_import']
        obj = self.source_object(row)
        if obj and obj['generation'] != source['generation']:
            raise CloudHTTPError('Original deletion precondition', 412)
        self.transport.objects.pop(source['object'], None)
        self.transport.events.append(('delete_manual', row['asset_id']))


class ManualImportTests(unittest.TestCase):
    def setUp(self):
        fixtures.CloudWorkflowTests.setUp(self)
        self.worker.build_upload_plan = mock.Mock(return_value=[self.item])
        self.config.execution.task_poll_seconds = .01
        self.config.execution.wait_timeout_minutes = .05
        self.transport.complete_after = 0
        self.plan_path = self.root / 'manual' / 'batch.json'
        self.adapter = FakeManualObjects(self.worker)
        self.plan = prepare_manual_batch(self.worker, self.plan_path, 'manual-upload/batch-one')

    def upload_by_browser(self):
        entry = self.plan['files'][0]
        self.transport.objects[entry['source_object']] = {
            'size': str(entry['size']), 'md5Hash': entry['md5'], 'generation': '7'}
        return entry

    def run_import(self, wait=True):
        return import_manual_batch(self.worker, self.plan_path, wait_for_ee=wait, object_transport=self.adapter)

    def add_second_item(self):
        path = self.path.with_name(self.path.name.replace('_555_', '_556_'))
        path.write_bytes(self.path.read_bytes())
        proof = {**self.proof, 'path': str(path.resolve())}
        with self.worker.store.connection(True) as db:
            db.execute('INSERT INTO artifacts(path,stage,utc,payload) VALUES (?,?,?,?)',
                       (str(path.resolve()), 'mosaic', proof['utc'], json.dumps(proof)))
        item = UploadItem(path, path.stem, self.config.destination_parent + '/' + path.stem)
        self.worker.build_upload_plan.return_value = [self.item, item]
        return item

    def test_preparation_has_metadata_and_history_but_no_remote_write(self):
        self.assertEqual(self.transport.events, [])
        entry = self.plan['files'][0]
        self.assertIn('original.nc', entry['receipt']['sources'])
        self.assertEqual(entry['manifest']['startTime'], '2023-09-20T18:26:43Z')
        self.assertNotIn('session_uri', json.dumps(self.plan))
        self.assertNotIn('secret_id', json.dumps(self.plan))
        self.assertEqual(self.worker.rows()[0]['manual_import']['status'], WAITING)

    def test_missing_upload_is_waiting_not_failure_or_complete(self):
        result = self.run_import(False)
        self.assertEqual(result['waiting'], 1)
        self.assertEqual(result['failed_or_blocked'], 0)
        self.assertFalse(result['complete'])
        self.assertEqual(self.transport.events, [])

    def test_automatic_mode_cannot_take_over_failed_or_blocked_manual_batch(self):
        for state in ('PREPARED', 'FAILED', 'BLOCKED'):
            with self.subTest(state=state):
                row = self.worker.journal.get(self.item.asset_id)
                row.update(state=state, error='retained manual review')
                self.worker.save(row)
                before = self.worker.journal.get(self.item.asset_id)
                with self.assertRaisesRegex(ValueError, 'manual bucket batch'):
                    self.worker._run()
                self.assertEqual(self.worker.journal.get(self.item.asset_id), before)
                self.assertFalse(self.transport.requests)
                self.assertEqual(self.transport.events, [])

    def test_complete_import_uses_server_copy_and_shared_statistics(self):
        self.upload_by_browser()
        result = self.run_import()
        self.assertTrue(result['complete'])
        self.assertTrue(result['cleanup_complete'])
        self.assertEqual(result['manual_source_bytes'], 0)
        self.assertEqual(result['owned_staging_bytes'], 0)
        self.assertTrue(self.path.exists())  # Local cleanup stays a separate proven step.
        self.assertFalse(self.transport.objects)
        kinds = [e[0] for e in self.transport.events]
        self.assertNotIn('transfer', kinds)
        self.assertLess(kinds.index('server_copy'), kinds.index('submit'))
        self.assertLess(kinds.index('delete'), kinds.index('delete_manual'))
        self.assertEqual(cloud_metrics(self.config.artifacts.report_csv)['Cloud EE ingestions verified'], '1')
        asset = self.transport.assets[self.item.asset_id]
        self.assertEqual(asset['properties'], self.plan['files'][0]['manifest']['properties'])
        self.assertEqual(asset['bands'], self.plan['files'][0]['manifest']['bands'])

    def test_wrong_checksum_retains_original_and_never_copies(self):
        entry = self.upload_by_browser()
        self.transport.objects[entry['source_object']]['md5Hash'] = 'wrong'
        result = self.run_import()
        self.assertEqual(result['failed_or_blocked'], 1)
        self.assertEqual(self.adapter.copies, 0)
        self.assertIn(entry['source_object'], self.transport.objects)
        self.assertFalse(self.transport.requests)

    def test_copy_precondition_catches_source_overwrite_and_resume_blocks(self):
        self.upload_by_browser()
        self.adapter.overwrite_before_copy = True
        first = self.run_import(False)
        self.assertFalse(first['complete'])
        self.assertEqual(self.adapter.copies, 0)
        second = self.run_import(False)
        self.assertEqual(second['failed_or_blocked'], 1)
        self.assertFalse(self.transport.requests)

    def test_lost_copy_response_reuses_owned_bytes_without_duplicate_copy(self):
        self.upload_by_browser()
        self.adapter.lost_copy_response = True
        self.assertFalse(self.run_import(False)['complete'])
        result = self.run_import()
        self.assertTrue(result['complete'])
        self.assertEqual(self.adapter.copies, 1)
        self.assertEqual(len(self.transport.operations), 1)

    def test_ingesting_retains_both_copies(self):
        self.upload_by_browser()
        self.transport.complete_after = 999
        result = self.run_import(False)
        self.assertEqual(result['ingesting'], 1)
        self.assertEqual(len(self.transport.objects), 2)
        self.assertEqual(result['manual_sources_removed'], 0)

    def test_original_overwrite_after_copy_is_retained_without_invalidating_verified_asset(self):
        entry = self.upload_by_browser()
        self.run_import(False)
        self.transport.objects[entry['source_object']]['generation'] = 'new-generation'
        result = self.run_import()
        self.assertTrue(result['complete'])
        self.assertFalse(result['cleanup_complete'])
        self.assertIn(entry['source_object'], self.transport.objects)
        self.assertTrue(result['details'][0]['manual']['cleanup_error'])

    def test_resume_after_local_and_bucket_cleanup_never_retransfers(self):
        self.upload_by_browser()
        self.assertTrue(self.run_import()['cleanup_complete'])
        self.path.unlink()
        before = list(self.transport.requests)
        self.assertTrue(self.run_import()['cleanup_complete'])
        self.assertEqual(self.transport.requests, before)
        self.assertEqual(self.adapter.copies, 1)

    def test_resume_failed_ingestion_uses_new_request_but_same_copy(self):
        self.upload_by_browser()
        self.run_import(False)
        first = self.transport.requests[0]
        self.transport.operations[first]['failure'] = True
        self.assertEqual(self.run_import(False)['failed_or_blocked'], 1)
        result = self.run_import()
        self.assertTrue(result['complete'])
        self.assertEqual(self.adapter.copies, 1)
        self.assertEqual(len(set(self.transport.requests)), 2)

    def test_edited_plan_cannot_adopt_an_unrelated_source(self):
        plan = deepcopy(self.plan)
        plan['files'][0]['source_object'] = 'someone-else/file.tif'
        plan['files_digest'] = digest(plan['files'])
        self.plan_path.write_text(json.dumps(plan), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'planned file paths|provenance journal'):
            self.run_import(False)
        self.assertEqual(self.transport.events, [])

    def test_preparation_recovers_journal_commit_before_json_checkpoint(self):
        self.plan_path.unlink()
        recovered = prepare_manual_batch(self.worker, self.plan_path, 'manual-upload/batch-one')
        self.assertEqual(recovered['batch_id'], self.plan['batch_id'])
        self.assertEqual(recovered['files'], self.plan['files'])
        self.assertEqual(len(self.worker.rows()), 1)

    def test_same_upload_lock_blocks_manual_import(self):
        from swotflow.project.lock import _operation_lock
        with _operation_lock(self.config.artifacts.report_csv.parent / '.upload.lock', 'busy'):
            with self.assertRaisesRegex(RuntimeError, 'Another upload'):
                self.run_import(False)

    def test_unselected_manual_batch_is_not_copied_or_deleted(self):
        second = self.add_second_item()
        other = prepare_manual_batch(self.worker, self.root / 'manual' / 'other.json', 'manual-upload/other')
        self.upload_by_browser()
        entry = other['files'][0]
        self.transport.objects[entry['source_object']] = {'size': str(entry['size']), 'md5Hash': entry['md5'], 'generation': '9'}
        self.assertTrue(self.run_import()['complete'])
        retained = self.worker.journal.get(second.asset_id)
        self.assertEqual(retained['state'], 'PREPARED')
        self.assertNotIn('generation', retained['manual_import'])
        self.assertIn(entry['source_object'], self.transport.objects)
        self.assertNotIn(entry['owned_object'], self.transport.objects)

    def test_manual_source_does_not_bypass_owned_copy_storage_cap(self):
        self.upload_by_browser()
        self.worker.cloud = replace(self.worker.cloud, staging_limit_gib=1e-9)
        result = self.run_import(False)
        self.assertFalse(result['complete'])
        self.assertEqual(self.adapter.copies, 0)
        self.assertEqual(result['details'][0]['manual']['status'], 'WAITING_FOR_STAGING_SPACE')
        self.assertEqual(result['manual_source_bytes'], self.path.stat().st_size)
        self.assertEqual(result['owned_staging_bytes'], 0)

    def test_first_queue_commit_already_has_manual_ownership_for_crash_recovery(self):
        second = self.add_second_item()
        path = self.root / 'manual' / 'crash.json'
        save = self.worker.save
        def interrupted(row):
            save(row)
            raise RuntimeError('crash after first queue commit')
        with mock.patch.object(self.worker, 'save', side_effect=interrupted):
            with self.assertRaisesRegex(RuntimeError, 'crash after'):
                prepare_manual_batch(self.worker, path, 'manual-upload/crash')
        self.assertFalse(path.exists())
        row = self.worker.journal.get(second.asset_id)
        self.assertIn('manual_import', row)
        recovered = prepare_manual_batch(self.worker, path, 'manual-upload/crash')
        self.assertEqual(recovered['files'][0]['asset_id'], second.asset_id)
        self.assertEqual(len(self.worker.rows()), 2)

    def test_http_copy_and_delete_bind_exact_generations(self):
        row = self.worker.rows()[0]
        row['manual_import']['generation'] = '7'
        response = mock.Mock(status_code=200)
        response.json.return_value = {'done': True, 'resource': {'generation': '123'}}
        self.transport.request = mock.Mock(return_value=response)
        self.transport.object_url = mock.Mock(return_value='https://storage.googleapis.com/exact-object')
        adapter = ManualObjectTransport(self.worker)
        adapter.copy_to_owned(row, lambda: None)
        call = self.transport.request.call_args
        self.assertEqual(call.kwargs['params'], {'ifSourceGenerationMatch': '7', 'ifGenerationMatch': '0'})
        self.assertEqual(call.kwargs['json']['metadata']['sha256'], row['sha256'])
        response.status_code = 204
        adapter.delete_source(row)
        self.assertEqual(self.transport.request.call_args.kwargs['params'], {'ifGenerationMatch': '7'})

    def test_expired_rewrite_token_is_cleared_for_safe_generation_bound_resume(self):
        row = self.worker.rows()[0]
        row['manual_import'].update(generation='7', rewrite_token='expired-token')
        self.transport.request = mock.Mock(return_value=mock.Mock(status_code=410))
        checkpoint = mock.Mock()
        with self.assertRaises(CloudHTTPError):
            ManualObjectTransport(self.worker).copy_to_owned(row, checkpoint)
        self.assertNotIn('rewrite_token', row['manual_import'])
        checkpoint.assert_called_once()
        self.assertEqual(self.transport.request.call_args.kwargs['params']['ifSourceGenerationMatch'], '7')
        self.assertEqual(self.transport.request.call_args.kwargs['params']['ifGenerationMatch'], '0')

    def test_sync_does_not_adopt_or_submit_a_waiting_browser_upload(self):
        self.upload_by_browser()
        results = sync_manual_batches(self.worker, [self.plan_path], object_transport=self.adapter)
        self.assertEqual(results[0]['waiting'], 1)
        self.assertEqual(self.adapter.copies, 0)
        self.assertFalse(self.transport.requests)
        self.assertEqual(len(self.transport.objects), 1)

    def test_sync_finishes_existing_task_and_cleans_without_new_submission(self):
        self.upload_by_browser()
        self.run_import(False)
        before = list(self.transport.requests)
        sync_manual_batches(self.worker, [self.plan_path], object_transport=self.adapter)
        result = sync_manual_batches(self.worker, [self.plan_path], object_transport=self.adapter)[0]
        self.assertTrue(result['cleanup_complete'])
        self.assertEqual(self.transport.requests, before)
        self.assertEqual(self.adapter.copies, 1)

    def test_original_cleanup_rechecks_ee_after_owned_copy_was_already_removed(self):
        entry = self.upload_by_browser()
        original_delete = self.adapter.delete_source
        self.adapter.delete_source = mock.Mock(side_effect=RuntimeError('permission temporarily missing'))
        result = self.run_import()
        self.assertTrue(result['complete'])
        self.assertFalse(result['cleanup_complete'])
        self.assertTrue(self.worker.rows()[0]['deleted_at'])
        self.transport.assets.clear()
        self.adapter.delete_source = original_delete
        result = sync_manual_batches(self.worker, [self.plan_path], object_transport=self.adapter)[0]
        self.assertFalse(result['complete'])
        self.assertEqual(result['failed_or_blocked'], 1)
        self.assertIn(entry['source_object'], self.transport.objects)

    def test_sync_rejects_changed_owned_generation_before_metadata_promotion(self):
        entry = self.upload_by_browser()
        self.run_import(False)
        row = self.worker.rows()[0]
        self.transport.objects[row['object']]['generation'] = 'replaced'
        result = sync_manual_batches(self.worker, [self.plan_path], object_transport=self.adapter)[0]
        self.assertEqual(result['failed_or_blocked'], 1)
        self.assertFalse(result['complete'])
        self.assertIn(entry['source_object'], self.transport.objects)
        self.assertIn(row['object'], self.transport.objects)


if __name__ == '__main__':
    unittest.main()
