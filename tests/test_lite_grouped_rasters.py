"""Small real-GDAL grouped workflow; NASA transport is a recorded synthetic fixture."""
import hashlib
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock
try:
    from osgeo import gdal, osr
    import numpy as np
except ImportError:
    gdal=None


@unittest.skipIf(gdal is None,'Run with configured GDAL Python')
class GroupedRasterTests(unittest.TestCase):
    def test_north_south_paired_pixels_interruption_resume_and_cleanup(self):
        from swotflow_lite import project as model, grouped_runner as grouped, grouping as g
        from swotflow.processing import automation as engine
        from swotflow.processing.download import normalize_granule
        from swotflow.catalog.history import CatalogHistory, product_record
        from swotflow.verification.download import verified_file
        from swotflow.verification.pipeline import VerificationStore, expected_checksum
        from swotflow.verification.source import check_sources
        from tests.test_download_tool import FakeGranule
        from tests.test_lite_grouping import name
        gdal.UseExceptions()
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            for tiles,epsg,token in [(['UTM36N','UTM36P'],32636,'UTM36N'),(['UTM36L','UTM36M'],32736,'UTM36S')]:
                with self.subTest(hemisphere=token):
                    with mock.patch.object(model,'defaults_path',return_value=root/'none.json'):
                        project=model.create(root/token,token)
                    c=project.config;c['gdal']['python']=sys.executable
                    c['download'].update(utm_tiles=tiles,start_date='2023-09-20',end_date='2023-09-20')
                    c['extract']['workers']=1;c['mosaic'].update(workers=1,grouping_mode=g.HEMISPHERE)
                    c['lite'].update(cleanup_intermediates=False,min_free_gib=0.001)
                    logs=project.root/'00_logs';raw=project.root/'01_downloads'
                    # Use the real project path mapping, not a separate test pipeline.
                    raw=Path(c['processing']['raw_downloads']);raw.mkdir(parents=True,exist_ok=True)
                    history=CatalogHistory(logs/'nasa_catalog_history.sqlite3')
                    scan=history.begin({'tiles':tiles,'start':'2023-09-20','end':'2023-09-20',
                        'acquisition_start_date':'2023-09-20','acquisition_end_date':'2023-09-20'})
                    candidates=[];granules=[]
                    for index,tile in enumerate(tiles):
                        filename=name(tile,scene=f'{index+1:03d}F');path=raw/filename
                        mem=gdal.GetDriverByName('MEM').Create('',8,6,2,gdal.GDT_Float32)
                        crs=osr.SpatialReference();crs.ImportFromEPSG(epsg)
                        mem.SetProjection(crs.ExportToWkt());mem.SetGeoTransform((500050+index*400,100,0,900050,0,-100))
                        for bandno,var,value in ((1,'wse',100+100*index),(2,'wse_qual',2-index)):
                            band=mem.GetRasterBand(bandno);band.SetMetadataItem('NETCDF_VARNAME',var)
                            fill=-9999 if bandno==1 else 255
                            band.SetNoDataValue(fill);band.Fill(value)
                            band.WriteArray(np.array([[fill]],np.float32),0,0)
                        nc=gdal.GetDriverByName('netCDF').CreateCopy(str(path),mem,options=['FORMAT=NC4'])
                        nc=mem=band=None
                        ds=gdal.OpenEx(str(path),gdal.OF_MULTIDIM_RASTER|gdal.OF_UPDATE)
                        group=ds.GetRootGroup()
                        for var,b in [('wse',1),('wse_qual',2)]:
                            arr=group.OpenMDArray(var+str(b));arr.Rename(var);arr=None
                        ds=group=None
                        fake=FakeGranule(filename,concept_id=str(index))
                        fake['umm']['DataGranule']={'ArchiveAndDistributionInformation':[{'Name':filename,'SizeInBytes':path.stat().st_size,
                            'Checksum':{'Algorithm':'MD5','Value':hashlib.md5(path.read_bytes()).hexdigest()}}]}
                        granule=normalize_granule(fake);granules.append(granule)
                        self.assertTrue(verified_file(path,granule,logs))
                        candidates.append(product_record(fake,'synthetic-originals'))
                    history.page(scan,'synthetic',1,{}, {'hits':2},candidates);history.finish(scan,granules,'complete')
                    batch={'id':token,'tile':token,'tiles':tiles,'grouping_mode':g.HEMISPHERE,
                        'start':'2023-09-20','end':'2023-09-20','expected':{x['filename']:expected_checksum(x) for x in candidates}}
                    folder=logs/'test_grouped_run';stop=threading.Event()
                    def downloaded(state,tile,*args,**kwargs):
                        return engine.AutomationStageResult(state.run_id,tile,'download','success',engine.now_text(),engine.now_text())
                    real_execute=engine.execute_command_result
                    def stop_after_extract(state,tile,stage,*args,**kwargs):
                        result=real_execute(state,tile,stage,*args,**kwargs)
                        if stage=='extract':stop.set()
                        return result
                    with mock.patch.object(engine,'execute_download_result',side_effect=downloaded), \
                         mock.patch.object(engine,'execute_command_result',side_effect=stop_after_extract):
                        state=grouped.run_group_batch(project,batch,folder,False,stop,lambda _:None)
                    self.assertFalse(state.errors,state.errors);self.assertTrue(state.stopped)
                    stop.clear()
                    with mock.patch.object(engine,'execute_download_result',side_effect=AssertionError('Resume redownloaded')):
                        state=grouped.run_group_batch(project,batch,folder,False,stop,lambda _:None)
                    self.assertFalse(state.errors,state.errors)
                    store=VerificationStore(logs)
                    proofs=[p for p in store.artifacts().values() if p['stage']=='mosaic']
                    self.assertEqual(len(proofs),1)
                    proof=proofs[0];output=Path(proof['path'])
                    self.assertIn('_'+token+'_',output.name)
                    self.assertEqual(proof['sources'],batch['expected'])
                    check=check_sources(store,output)
                    self.assertTrue(check['passed'],check)
                    self.assertEqual(check['totals']['overlap_cells'],23)
                    raster=gdal.Open(str(output));self.assertEqual(raster.GetGeoTransform()[1],100)
                    self.assertEqual(raster.GetSpatialRef().GetAuthorityCode(None),str(epsg))
                    self.assertEqual(raster.GetRasterBand(1).ReadAsArray()[2,5],200)
                    self.assertEqual(raster.GetRasterBand(2).ReadAsArray()[2,5],1)
                    raster=None
                    before=output.read_bytes();c['lite']['cleanup_intermediates']=True
                    with mock.patch.object(engine,'execute_download_result',side_effect=AssertionError('Cleanup Resume redownloaded')):
                        state=grouped.run_group_batch(project,batch,folder,False,stop,lambda _:None)
                    self.assertFalse(state.errors,state.errors)
                    self.assertFalse(list(raw.glob('*.nc')))
                    self.assertFalse(list(Path(c['processing']['extracted_geotiffs']).glob('*.tif')))
                    self.assertEqual(output.read_bytes(),before)
                    with mock.patch.object(engine,'execute_download_result',side_effect=AssertionError('Cleaned Resume redownloaded')), \
                         mock.patch.object(engine,'execute_command_result',side_effect=AssertionError('Cleaned Resume reprocessed')):
                        state=grouped.run_group_batch(project,batch,folder,False,stop,lambda _:None)
                    self.assertFalse(state.errors,state.errors)


if __name__=='__main__':unittest.main()
