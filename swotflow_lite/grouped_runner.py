"""Execute one bounded native zone/hemisphere batch with the shared stage engines.

All selected bands reach extraction before the common mosaic stage. No per-tile
mosaic or upload is created along the way. Scientific receipts still own Resume
and deletion decisions; this module only schedules their existing operations.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sqlite3
import threading
from typing import Callable
import yaml

from swotflow.processing import automation as engine
from swotflow.processing.mosaic import parse_config as mosaic_config
from swotflow.processing.automation_years import storage_reserve_failure
from swotflow.verification.pipeline import (VerificationStore, catalogue_selection, artifact_current,
    settings_key, active_proofs)
from swotflow.verification.resume import verified_resume_stages
from swotflow.verification.retention import source_proof_matches
from swotflow.verification.download import assert_project_not_reset
from swotflow.verification.file_cache import CleanupHashCache
from swotflow_lite.grouping import HEMISPHERE, batch_tiles, input_groups


def group_config(project: object, batch: dict, folder: Path, automatic: bool) -> dict:
    """Keep original inputs/metadata paths but scope every stage to all member bands."""
    config = engine.build_tile_config_dict(project.config, batch['tile'], folder,
        start_date=batch['start'], end_date=batch['end'], include_upload=automatic)
    tiles = batch_tiles(batch)
    for section in ('download','duplicates','extract','mosaic','upload'):
        config[section]['utm_tiles'] = list(tiles)
    for section in ('processing','download'):
        config[section].update(acquisition_start_date=batch['start'],acquisition_end_date=batch['end'])
    config['mosaic'].update(grouping_mode=HEMISPHERE, target_crs_label='')
    config['upload'].update(backend='gcs',completion_mode='wait_for_ee')
    config['cleanup'].update(mosaics_enabled=project.config['lite']['cleanup_mosaics'],mosaic_policy='confirmed_ingestion')
    # Raw/extracted cleanup is explicitly member-scoped below. Do not mistake the
    # output's N/S hemisphere token for a source latitude-band tile.
    config['automation']['yearly_batch'] = False
    return config


def bind_selection(config: dict, batch: dict, scan_id: str = '') -> str:
    """Fail before mosaicking if a new NASA response differs from the frozen plan."""
    logs = Path(config['mosaic']['manifest_csv']).parent
    selection = catalogue_selection(logs, config['download'], scan_id)
    if selection is None or selection[1] != batch['expected']:
        raise ValueError('NASA selection differs from the saved batch. Refresh Catalogue / plan; no partial grouped mosaic is accepted.')
    config['mosaic']['selection_scan_id'] = selection[0]
    return selection[0]


def verify_group_outputs(config: dict, batch: dict, root: Path, *, hash_cache=None) -> None:
    """Require exact membership of every group, with current local or bound EE bytes."""
    mo = mosaic_config(config, root)
    store = VerificationStore(mo.manifest_csv.parent)
    expected = {frozenset(sources): sources for sources in input_groups(batch['expected']).values()}
    if not expected:
        raise ValueError('A grouped processing batch must contain expected original inputs.')
    covered = set()
    active = None
    artifacts=store.artifacts()
    for proof in artifacts.values():
        sources = proof.get('sources', {})
        membership = frozenset(sources)
        if (proof.get('stage') != 'mosaic' or Path(proof['path']).parent != mo.output_folder.resolve()
                or proof.get('settings') != settings_key('mosaic', mo) or expected.get(membership) != sources):
            continue
        if any(not artifacts.get(p) or artifacts[p]['sha256'] != h for p,h in proof['inputs'].items()):
            continue
        if artifact_current(proof,hash_cache=hash_cache):
            covered.add(membership)
        elif not Path(proof['path']).exists():
            if active is None:
                active = active_proofs(store, config.get('destination_parent',''), include_ingestion=True)
            if source_proof_matches(proof, active):
                covered.add(membership)
    if covered != set(expected):
        raise ValueError('Grouped mosaic coverage is incomplete or changed. Expected full date/pass source membership; retain files for Resume.')


def run_group_batch(project: object, batch: dict, folder: Path, automatic: bool,
                    stop: threading.Event, progress: Callable[[str],None]) -> engine.AutomationRunState:
    """Resume shared stages, checking headroom, source selection and group completeness."""
    assert_project_not_reset(project.root/'00_logs')
    config = group_config(project, batch, folder, automatic)
    automation = engine.AutomationConfig(project.root, deepcopy(config), batch_tiles(batch), batch['start'], batch['end'],
        include_upload=automatic,cleanup_enabled=project.config['lite']['cleanup_intermediates'],
        min_free_space_gb=project.config['lite']['min_free_gib'],run_id=batch['id']+'_'+('automatic' if automatic else 'prepare'),run_dir=folder)
    path = folder/'group_config.yaml'
    hash_cache=CleanupHashCache()
    def verify():
        verify_group_outputs(config,batch,project.root,hash_cache=hash_cache)
    with engine.automation_lock(project.root), engine.keep_system_awake(enabled=True,keep_display_awake=False):
        state = engine.load_automation_run_state(folder/'automation_run.json') if (folder/'automation_run.json').exists() else engine.ensure_run_state(automation)
        state.config=automation;state.errors=[];state.stopped=False;state.stop_reason=''
        state.preflight_ok=True;state.started_at=engine.now_text();state.finished_at=''
        completed={r.stage for r in engine.latest_stage_results_by_key(state).values() if r.status=='success'}
        reusable=set()
        if path.exists():
            saved=yaml.safe_load(path.read_text(encoding='utf-8')) or {}
            try:
                reusable,scan=verified_resume_stages(config,saved,completed,project.root)
                if scan:bind_selection(config,batch,scan)
            except (OSError,ValueError,sqlite3.Error,yaml.YAMLError) as exc:
                reusable=set();progress('Rechecking grouped stage evidence: '+str(exc))
        engine.write_tile_config(config,path);engine.write_run_state(state)
        stages=['download','duplicates','extract','raw_cleanup','mosaic','extracted_cleanup']
        if automatic:stages.extend(['upload','ee_sync','mosaic_cleanup'])
        callback=lambda tile,stage,status,message:progress(f'{tile} / {stage}: {message}')
        try:
            for stage in stages:
                if stop.is_set():
                    state.stopped=True;state.stop_reason='Stop requested after current stage';break
                if stage in reusable:
                    progress(f'{batch["tile"]} / {stage}: verified Resume evidence reused.');continue
                blocked=storage_reserve_failure(state,config,batch['tile'],stage)
                if blocked:
                    engine.append_stage_result(state,blocked)
                    state.stopped=True;state.stop_reason=blocked.message;break
                progress(f'{batch["tile"]} / {stage}: starting across {", ".join(batch_tiles(batch))}')
                if stage.endswith('_cleanup'):
                    enabled=project.config['lite']['cleanup_mosaics'] if stage=='mosaic_cleanup' else project.config['lite']['cleanup_intermediates']
                    if not enabled:
                        engine.append_stage_result(state,engine.stage_skipped_result(state,batch['tile'],stage,'Cleanup disabled.'))
                        continue
                    # Recheck every grouped output before deleting any extracted source.
                    if stage=='extracted_cleanup':verify()
                    members=['ALL'] if stage=='mosaic_cleanup' else batch_tiles(batch)
                    for tile in members:
                        result=engine.execute_cleanup_result(state,config,tile,stage)
                        engine.append_stage_result(state,result);callback(tile,stage,result.status,result.message)
                    continue
                if stage=='download':
                    result=engine.execute_download_result(state,batch['tile'],path,progress_callback=callback,stop_event=stop)
                else:
                    if stage=='upload':verify()
                    result=engine.execute_command_result(state,batch['tile'],stage,path,Path(config['gdal']['python']),progress_callback=callback)
                engine.append_stage_result(state,result);callback(batch['tile'],stage,result.status,result.message)
                if result.status=='failed':
                    if stop.is_set():
                        state.stopped=True;state.stop_reason='Stop requested during current stage'
                    else:state.errors.append(result.message)
                    break
                if stage=='download':
                    bind_selection(config,batch);engine.write_tile_config(config,path)
                elif stage=='mosaic':verify()
                elif stage=='ee_sync':
                    engine.execute_deferred_upload_repair_if_needed(state,automation,Path(config['gdal']['python']),callback,stop)
            if not state.errors and not state.stopped:verify()
        except (ValueError,OSError,sqlite3.Error,yaml.YAMLError) as exc:
            state.errors.append(str(exc))
            engine.append_stage_result(state,engine.AutomationStageResult(state.run_id,batch['tile'],'group_accounting','failed',
                engine.now_text(),engine.now_text(),return_code=1,message=str(exc)))
        finally:
            state.finished_at=engine.now_text();engine.write_run_state(state)
        return state
