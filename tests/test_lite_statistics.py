"""Full-period coverage, durable history and the Lite Statistics interface."""
from copy import deepcopy
import csv
import json
from pathlib import Path
import tempfile
import tkinter as tk
from types import SimpleNamespace
import unittest
from unittest import mock

from swotflow_lite import planner, project as model, statistics
from swotflow_lite import statistics_details as details
from swotflow_lite.app import LiteApp
from swotflow_lite.statistics_ui import StatisticsPanel, CoverageWindow, GROUPS, status_style
from swotflow.catalog.history import CatalogHistory
from swotflow.core.metadata import product_identity_key
from swotflow.processing.download import DownloadGranule
from swotflow.project.insights import collect_project_insights
from tests.test_lite_review import name


class StatisticsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name)
        with mock.patch.object(model,'defaults_path',return_value=self.folder/'absent.json'):
            self.project=model.create(self.folder/'project','Statistics fixture')
        self.project.config['download'].update(utm_tiles=['UTM35L'],start_date='2023-01-01',end_date='2024-12-31')
        self.project.config['destination_parent']='projects/example/assets/statistics'
        self.proof={'algorithm':'md5','hash':'original-source','size':5}
        self.names=[name(day='20230920'),name(day='20240920')]
        self.plan={'science':planner.science_identity(self.project.config),'scope':details.requested_scope(self.project.config),
                   'scans':[],'batches':[]}
        for year,filename in zip((2023,2024),self.names):
            self.plan['scans'].append({'tile':'UTM35L','start':f'{year}-01-01','end':f'{year}-12-31','preferred_files':1,'scan_id':str(year)})
            self.plan['batches'].append({'id':str(year),'tile':'UTM35L','start':f'{year}-09-20','end':f'{year}-09-20',
                'expected':{filename:self.proof},'state':'locally_ready','detail':''})
        self.represented={n:self.proof for n in self.names}
        self.lineage={'status':'current','conflicts':[],'unresolved_assets':[],'observed_sources':self.represented}

    def periods(self):
        return details.period_rows(self.project,self.plan,self.represented,self.lineage)

    def test_one_year_is_not_a_finished_tile(self):
        self.represented.pop(self.names[1])
        tiles,years=self.periods()
        self.assertEqual(tiles[0]['state'],'upload_pending')
        self.assertEqual((tiles[0]['verified'],tiles[0]['pending']),(1,1))
        self.assertEqual([r['state'] for r in years],['inputs_verified','pending'])

    def test_full_scope_and_empty_years_are_accounted_separately(self):
        self.assertEqual(self.periods()[0][0]['state'],'complete')
        self.plan['batches'].pop();self.plan['scans'][1]['preferred_files']=0
        tiles,years=self.periods()
        self.assertEqual(tiles[0]['state'],'complete')
        self.assertEqual(tiles[0]['years_without_acquisitions'],1)
        self.plan['batches']=[];self.plan['scans'][0]['preferred_files']=0
        self.assertEqual(self.periods()[0][0]['state'],'no_available_acquisitions')

    def test_missing_or_duplicate_window_is_not_complete(self):
        original=deepcopy(self.plan)
        for scans in (original['scans'][:1],original['scans']+[original['scans'][0]]):
            self.plan['scans']=scans
            self.assertEqual(self.periods()[0][0]['state'],'plan_required')

    def test_unassigned_or_duplicate_inputs_cannot_make_complete(self):
        original=deepcopy(self.plan)
        self.plan['batches'].append(deepcopy(self.plan['batches'][0]))
        self.assertEqual(self.periods()[0][0]['state'],'plan_required')
        self.plan=original;self.plan['batches'][0]['start']='2022-09-20'
        self.assertEqual(self.periods()[0][0]['state'],'plan_required')

    def test_new_tile_or_extended_dates_requires_new_plan(self):
        self.project.config['download']['utm_tiles'].append('UTM36L')
        self.assertTrue(all(t['state']=='plan_required' for t in self.periods()[0]))
        self.project.config['download']['utm_tiles']=['UTM35L']
        self.project.config['download']['end_date']='2025-12-31'
        self.assertEqual(self.periods()[0][0]['state'],'plan_required')

    def test_stale_and_conflicting_evidence_never_colours_complete(self):
        self.lineage['status']='stale'
        self.assertEqual(self.periods()[0][0]['state'],'verification_stale')
        self.lineage['status']='current';self.lineage['unresolved_assets']=[{'asset_id':'foreign'}]
        self.assertEqual(self.periods()[0][0]['state'],'collection_review_required')
        self.assertEqual(status_style(self.periods()[0][0]['state']),'stale')

    def test_latest_inventory_can_invalidate_verified_queue_without_erasing_history(self):
        model.write_json(self.project.root/'00_logs/lite_plan.json',self.plan)
        lineage={**self.lineage,'observed_sources':{}}
        with mock.patch.object(statistics,'collect_project_insights',return_value=SimpleNamespace(metrics={'Downloaded historical':'2'})), \
             mock.patch.object(statistics,'collection_lineage',return_value=lineage), \
             mock.patch.object(statistics,'verified_source_evidence',return_value=(self.represented,[])):
            result=statistics.snapshot(self.project)
        self.assertEqual(result['finished_tiles'],0)
        self.assertEqual(result['tiles'][0]['pending'],2)
        self.assertEqual(result['metrics']['Downloaded historical'],'2')

    def test_complete_inventory_but_missing_catalogue_window_is_plan_required(self):
        self.plan['scans'].pop();model.write_json(self.project.root/'00_logs/lite_plan.json',self.plan)
        with mock.patch.object(statistics,'collect_project_insights',return_value=SimpleNamespace(metrics={})), \
             mock.patch.object(statistics,'collection_lineage',return_value=self.lineage), \
             mock.patch.object(statistics,'verified_source_evidence',return_value=(self.represented,[])):
            result=statistics.snapshot(self.project)
        self.assertEqual(result['status'],'plan_required');self.assertFalse(result['complete'])

    def test_all_lineage_rows_export_past_old_preview_limit(self):
        insights=collect_project_insights(self.project.config,include_cleanup=False,include_all_rows=True)
        insights.mosaic_lineage_rows=[{'filename':f'source-{i}'} for i in range(1105)]
        insights.product_version_audit_rows=deepcopy(insights.mosaic_lineage_rows)
        tables,_=details.engine_tables(insights)
        for key in ('mosaic_lineage_rows','product_version_audit_rows'):
            self.assertEqual(len(tables[key]),1105)
        result={'tables':tables};output=self.folder/'export'
        details.export_statistics(result,output)
        with (output/'mosaic_lineage_rows.csv').open(encoding='utf-8-sig',newline='') as stream:
            self.assertEqual(len(list(csv.DictReader(stream))),1105)

    def test_cleaned_files_retain_exact_download_and_extraction_records(self):
        history={'download_manifest':[{'file_name':self.names[0],'last_status':'DOWNLOADED',
            'last_downloaded':'2026-11-26T12:00:00Z','raw_exists':'no'}],
            'extract_manifest':[{'input_nc':str(self.folder/self.names[0]),'status':'EXTRACTED'}]}
        rows=details.input_rows(self.plan,self.represented,history)
        self.assertEqual(rows[0]['filename'],self.names[0]);self.assertTrue(rows[0]['ee_verified'])
        self.assertEqual(rows[0]['downloaded_at'],'2026-11-26T12:00:00Z')
        self.assertEqual(rows[0]['extraction_status'],'EXTRACTED')
        self.assertEqual(rows[1]['download_status'],'not recorded')

    def test_manual_and_automatic_cloud_history_preserves_cleanup_fields_without_session(self):
        rows=[{'asset_id':'a','state':'VERIFIED','receipt':{'sources':self.represented},'deleted_at':'today','session_uri':'SECRET'},
              {'asset_id':'b','state':'FAILED','manual_import':{'generation':12,'cleanup_error':'retained'},'size':50}]
        table=details.cloud_table(rows)
        self.assertEqual(table[0]['cloud_deleted_at'],'today');self.assertEqual(table[0]['source_count'],2)
        self.assertEqual(table[1]['route'],'manual import');self.assertEqual(table[1]['cleanup_error'],'retained')
        self.assertNotIn('SECRET',json.dumps(table))

    def test_nasa_search_retains_lower_versions_and_download_events(self):
        old,new=name(processing='PID0'),name(processing='PGD0')
        granules=[DownloadGranule('old',old,'UTM35L','2023-09-20T18:26:43Z'),DownloadGranule('new',new,'UTM35L','2023-09-20T18:26:43Z')]
        granules[0].selected_for_download=False;granules[0].preferred_file_name=new
        granules[0].duplicate_filter_status='excluded';granules[1].selected_for_download=True
        history=CatalogHistory(self.project.root/'00_logs/nasa_catalog_history.sqlite3')
        scan=history.begin(details.requested_scope(self.project.config))
        history.page(scan,'official',1,{}, {'hits':2},[{'filename':g.file_name,'identity':product_identity_key(g.file_name)} for g in granules])
        history.finish(scan,granules,'complete');history.transfer(scan,[granules[1]],{'new':('DOWNLOADED','removed.nc')},'download_result')
        before=history.path.read_bytes();value=details.nasa_search_details(self.project,scan)
        self.assertEqual(len(value['candidates']),2);self.assertEqual(value['events'][0]['filename'],new)
        self.assertEqual(next(r for r in value['candidates'] if r['filename']==old)['selected'],0)
        self.assertEqual(len(value['comparison']['rows']),1)
        self.assertEqual(value['comparison']['rows'][0]['preferred_nasa'],new)
        self.assertEqual(before,history.path.read_bytes())

    def test_run_and_cleanup_history_survive_archived_plan_without_duplicates(self):
        folder=self.project.root/'00_logs/lite_runs/first/automatic';folder.mkdir(parents=True)
        self.plan['batches'][0].update(run_dir=str(folder),run_mode='automatic')
        model.write_json(folder/'automation_run.json',{'stage_results':[{'stage':'cleanup','status':'success','deleted_files':4,'deleted_bytes':500}]})
        model.write_json(self.project.root/'00_logs/lite_plan_history/previous.json',self.plan)
        revisions,stages=details.run_history(self.project,self.plan)
        self.assertEqual(len(revisions),2);self.assertEqual(len(stages),1)
        self.assertEqual(stages[0]['deleted_files'],4)
        self.plan['batches'][1]['run_dir']=str(self.folder/'outside')
        self.assertEqual(len(details.run_history(self.project,self.plan)[1]),1)


class StatisticsUITests(unittest.TestCase):
    def setUp(self):
        self.root=tk.Tk();self.root.withdraw();self.addCleanup(self.dispose)

    def dispose(self):
        self.root.update_idletasks()
        for timer in self.root.tk.call('after','info'):self.root.after_cancel(timer)
        self.root.destroy()

    def test_pagination_filter_and_details_include_every_filename(self):
        panel=StatisticsPanel(self.root,lambda:None,lambda:None,lambda x:None)
        result={'tables':{'download_manifest':[{'nested':{'revision':i},'file_name':f'original-{i:04}'} for i in range(1105)]}}
        panel.render(result);panel.group.set('Files and lineage');panel.group_changed()
        panel.view.set(GROUPS['Files and lineage']['download_manifest']);panel.select_table()
        self.assertEqual(len(panel.tree.get_children()),200)
        self.assertEqual(panel.columns[0],'file_name')
        panel.move_page(5);self.assertEqual(len(panel.tree.get_children()),105)
        panel.query.set('original-1104');panel.filter_rows()
        self.assertEqual(len(panel.tree.get_children()),1)
        panel.tree.selection_set('0');panel.show_details()
        self.assertIn('1104',panel.detail.get('1.0','end'))

    def test_all_groups_and_coverage_map_render(self):
        panel=StatisticsPanel(self.root,lambda:None,lambda:None,lambda x:None)
        result={'tiles':[{'tile':'UTM35L','state':'complete','expected':2,'verified':2,'pending':0,'years_checked':2,'years_requested':2}],
                'requested_scope':{'start':'2023-01-01','end':'2024-12-31'},'tables':{'uploaded_date_counts':[{'date':'2023-09-20','count':2}]}}
        panel.render(result)
        for group,views in GROUPS.items():
            panel.group.set(group);panel.group_changed()
            for view in views.values():panel.view.set(view);panel.select_table()
        window=CoverageWindow(self.root,result);self.root.update_idletasks();window.draw();window.plot()
        self.assertGreater(len(window.canvas.find_all()),10)
        self.assertGreater(len(window.chart.find_all()),4)
        window.destroy()

    def test_history_search_is_preserved_on_refresh_but_not_project_change(self):
        panel=StatisticsPanel(self.root,lambda:None,lambda:None,lambda x:None)
        panel.show_search({'scan_id':'one','candidates':[{'filename':'original'}],'events':[],
                           'comparison':{'rows':[{'status':'preferred_version_recorded'}],'inventory_time':'today'}})
        panel.render({'tables':{}})
        self.assertEqual(panel.result['tables']['nasa_versions'][0]['status'],'preferred_version_recorded')
        self.assertEqual(panel.result['nasa_version_comparison']['inventory_time'],'today')
        panel.clear();panel.render({'tables':{}})
        self.assertNotIn('selected_scan',panel.result)

    def test_statistics_results_do_not_change_running_workflow_and_old_results_are_ignored(self):
        app=LiteApp(self.root,auto_statistics=False)
        app.project=SimpleNamespace(root=Path('example'));app.busy=True
        app.events.put(('stats_error',(app.stats_context(),'temporary read failure')))
        app.drain();self.assertTrue(app.busy);self.assertFalse(app.stop.is_set())
        self.assertIn('Processing was not stopped',app.statistics_panel.summary.get())
        app.stats_generation+=1
        app.events.put(('stats',(('old-project',0),{'tables':{},'finished_tiles':99})))
        app.drain();self.assertNotEqual(app.statistics_panel.result.get('finished_tiles'),99)


if __name__=='__main__':unittest.main()
