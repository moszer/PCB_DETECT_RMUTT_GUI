import asyncio, importlib, io, json, pathlib, sys, tempfile, threading, time, traceback
from unittest.mock import patch
import cv2, numpy as np
from fastapi import UploadFile
from fastapi.testclient import TestClient
import app.config as config
# All persistence is isolated from the working project and baseline test database.
audit_data=pathlib.Path(tempfile.mkdtemp(prefix='pcb-web-probes-'))
for attr, suffix in [('STORAGE_DIR',''),('UPLOADS_DIR','uploads'),('RUNS_DIR','runs'),('REFERENCES_DIR','references')]:
    p=audit_data/suffix;p.mkdir(exist_ok=True);setattr(config,attr,p)
config.DB_PATH=audit_data/'inspection.db'
from app.main import app
from app.core.schemas import AOIRunReport, ScanPlanRequest, ReferenceProfile, ReferencePoint, InspectionSummary
from app.core.security import lease_manager
from app.services.aoi_scan_service import AOIScanService, aoi_scan_service
from app.services.camera_service import CameraService
from app.services.machine_service import MachineService, machine_service
from app.services.storage_service import storage_service
from app.routers.aoi import _require_operator_lease
from app.routers.system import update_settings, SettingsUpdateRequest
from app.routers.inspection import inspect_uploaded_image
inference_module=importlib.import_module('app.services.inference_service')
results=[]
def finding(name, confirmed, evidence):
    results.append(dict(name=name,confirmed=bool(confirmed),evidence=evidence))
    print(json.dumps(results[-1],ensure_ascii=False),flush=True)
# Absolutely prohibit hardware I/O in this harness.
with patch('serial.Serial', side_effect=AssertionError('Hardware access forbidden')):
    with patch('cv2.VideoCapture', side_effect=AssertionError('Real camera access forbidden')):
        service=AOIScanService()
        finished=threading.Event()
        def start():
            try: service.start_scan(ScanPlanRequest())
            except Exception: pass
            finally: finished.set()
        worker=threading.Thread(target=start,daemon=True);worker.start();worker.join(.15)
        stack=traceback.extract_stack(sys._current_frames()[worker.ident]) if worker.is_alive() else []
        finding('AOI start deadlocks on nested non-reentrant lock',worker.is_alive() and any(s.name=='is_running' for s in stack),[(s.name,s.lineno) for s in stack[-3:]])
        # Avoid lifespan: do not load a real model or initialize station hardware.
        client=TestClient(app,raise_server_exceptions=False)
        aoi_scan_service._current_run=AOIRunReport(id='probe',plan=ScanPlanRequest(),total_points=4)
        response=client.get('/api/system/status')
        finding('Status endpoint crashes with a run present',response.status_code==500,{'http':response.status_code,'schema_has_total_points':'total_points' in AOIRunReport.model_fields})
        aoi_scan_service._current_run=None
        profile=ReferenceProfile(id='probe_ref',name='Probe',points=[ReferencePoint(x=1,y=2,label='resistor')])
        storage_service.save_reference(profile)
        listed=client.get('/api/references').json()[0]
        finding('Reference list omits points consumed by frontend', 'points' not in listed, {'returned_keys':list(listed),'detail_points':len(client.get('/api/references/probe_ref').json()['points'])})
        response=client.post('/api/auth/acquire',json={'operator_name':'Audit operator'})
        op=response.json()['operator_id']
        leaked=client.get('/api/auth/lease').json().get('active_operator_id')==op
        secret=client.get('/api/system/settings').json().get('operator_passcode')==config.settings.operator_passcode
        finding('Lease authentication bypass and credential exposure',response.json()['success'] and leaked and secret,{'no_passcode_accepted':response.json()['success'],'operator_token_public':leaked,'configured_passcode_public':secret})
        takeover=client.post('/api/auth/acquire',json={'operator_name':'Audit second operator','force':True}).json()
        finding('Unauthenticated force takeover accepted',takeover['success'],{'success':takeover['success']})
        lease_manager.release_lease(takeover['operator_id'])
        _require_operator_lease(None)
        finding('Unreserved station accepts commands without operator',True,'_require_operator_lease(None) returned normally')
        # Simulated machine only; no HOME/MOVE sent to hardware.
        machine_service.connect(mode='simulation')
        before=machine_service._client.soft_limits
        update_settings(SettingsUpdateRequest(soft_limit_x_mm=1,soft_limit_y_mm=1))
        after=machine_service._client.soft_limits
        planned=AOIScanService().plan_scan(ScanPlanRequest(origin_x_mm=39,columns=1,rows=1))
        finding('Soft limit display diverges from enforced limits and planner', before==after and planned[0].x_mm==39,{'display_mm':machine_service.get_state().soft_limits_mm,'enforced_steps':after,'accepted_plan_mm':planned[0].x_mm})
        machine_service.disconnect()
        class FakeCapture:
            def __init__(self,opened):self.opened=opened;self.props={}
            def isOpened(self):return self.opened
            def set(self,k,v):self.props[k]=v
            def get(self,k):return self.props.get(k,0)
            def release(self):self.opened=False
        with patch('threading.Thread.start',return_value=None):
            with patch('cv2.VideoCapture',return_value=FakeCapture(False)):
                camera=CameraService();camera.start()
                finding('Camera open failure reports active success via implicit mock',camera.is_active and camera._is_mock,{'active':camera.is_active,'mock':camera._is_mock})
                camera.stop()
            with patch('cv2.VideoCapture',return_value=FakeCapture(True)):
                camera=CameraService();camera.start(width=1920,height=1080);camera.start(width=3840,height=2160)
                finding('Changing resolution on same camera is ignored',camera.resolution==(1920,1080),{'requested':[3840,2160],'actual':camera.resolution})
                camera.stop()
        # Prove reference file escape only inside the temporary audit directory.
        escaped=ReferenceProfile(id='../audit_escape',name='Harmless audit marker')
        response=client.post('/api/references',json=escaped.model_dump())
        finding('Reference ID allows writing JSON outside references directory',response.status_code==200 and (audit_data/'audit_escape.json').is_file(),{'http':response.status_code,'escaped_one_directory':(audit_data/'audit_escape.json').is_file()})
        storage_service.save_single_inspection('PASS',None,'fake','cpu','fake.png',None,[],InspectionSummary(),{})
        listed_runs=client.get('/api/history/runs').json()
        finding('Single inspections are invisible in history',listed_runs['total']==0,{'saved_single_inspections':1,'history_total':listed_runs['total']})
        report=AOIRunReport(id='sim_stats',status='complete',is_simulation=True,plan=ScanPlanRequest(),overall_verdict='PASS')
        storage_service.create_run(report)
        stats=client.get('/api/history/statistics').json()
        finding('Simulation contaminates production yield statistics',stats['total_runs']==1 and stats['pass_runs']==1,stats)
        # Verify event-loop blockage using mocked inference, no model or hardware.
        class SlowInference:
            is_loaded=True
            model_path='fake'
            class device_info: label='fake'
            def predict(self,*args,**kwargs):time.sleep(.25);return [],{}
        inspection_module=importlib.import_module('app.routers.inspection')
        async def event_loop_probe():
            samples=[];done=False
            async def heartbeat():
                while not done:
                    samples.append(time.monotonic());await asyncio.sleep(.01)
            task=asyncio.create_task(heartbeat());await asyncio.sleep(.03)
            _, encoded=cv2.imencode('.png',np.zeros((10,10,3),dtype=np.uint8))
            upload=UploadFile(io.BytesIO(encoded.tobytes()),filename='probe.png')
            await inspect_uploaded_image(upload,conf=.25,match_dist=50,fail_on_extra=True,reference_id=None)
            await asyncio.sleep(.03);done=True;await task
            return max(b-a for a,b in zip(samples,samples[1:]))
        with patch.object(inspection_module,'inference_service',SlowInference()):
            gap=asyncio.run(event_loop_probe())
        finding('Upload inference blocks HTTP/WebSocket event loop',gap>.2,{'heartbeat_max_gap_seconds':round(gap,3),'stub_inference_seconds':.25})
        # Waiting MOVE falsely succeeds when client is disconnected.
        move_issued=threading.Event()
        class FakeClient:
            homed=True;closed=False;position=(0,0);ready=True;pending=None;limits=(21167,20446)
            def command(self,*args):move_issued.set();return 1
            def close(self):self.closed=True
        motion=MachineService();motion._client=FakeClient();outcome={}
        def move():
            try:outcome['returned']=motion.move_to_steps(100,100,timeout_sec=1)
            except Exception as e:outcome['error']=str(e)
        mover=threading.Thread(target=move);mover.start();move_issued.wait(1);motion.disconnect();mover.join(1)
        finding('Disconnect while MOVE waits falsely returns success',outcome.get('returned') is True,outcome)
pathlib.Path('/tmp/pcb-web-probe-results.json').write_text(json.dumps(results,indent=2,ensure_ascii=False))
print('Confirmed:',sum(r['confirmed'] for r in results),'/',len(results))
