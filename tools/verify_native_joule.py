"""Real platform -> NX parameter readback -> Siemens SOL 153 -> result acceptance."""
import argparse
import hashlib
import json
from pathlib import Path
import time
from verify_semantic_nx import client_for


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--data-dir',type=Path,required=True)
    parser.add_argument('--exe',type=Path)
    parser.add_argument('--launch',action='store_true')
    args=parser.parse_args()
    args.data_dir.mkdir(parents=True,exist_ok=True)
    report={'ok':False,'mode':'executable' if args.exe else 'source','scope':'fixed_1d_joule_demo',
            'simcenter_project_solve_verified':False,'jobs':[]}
    if args.exe:report['exe_sha256']=hashlib.sha256(args.exe.read_bytes()).hexdigest()
    try:
        with client_for(args) as client:
            response=client.post('/api/auth/register',json={'username':'native_joule_verify','name':'native thermal acceptance','password':'Native-Joule-2026'})
            response.raise_for_status()
            assert client.get('/api/simulation/settings').json()['native_joule_demo']['solver_found']
            original=None
            for current,expected in [(20,26.346875),(40,30.3875)]:
                response=client.post('/api/simulation/nastran/jobs',json={'current_a':current})
                response.raise_for_status();key=response.json()['id']
                for _ in range(600):
                    job=client.get('/api/simulation/nastran/jobs/'+key).json()
                    if job['state'] in ('completed','failed','cancelled'):break
                    time.sleep(.5)
                report['jobs'].append(job)
                if job['state']!='completed':
                    report['logs']=client.get('/api/simulation/nastran/jobs/'+key+'/logs').json()
                    raise AssertionError(job)
                result=job['result']
                assert result['engine']=='Siemens Simcenter Nastran' and result['solution']=='SOL 153'
                assert abs(result['maximum_c']-expected)<1e-4,result
                assert result['analytic_check_passed'] and result['op2_bytes']>0
                assert abs(result['geometry']['length_mm']-100)<1e-6
                assert abs(result['geometry']['area_mm2']-4)<1e-6
                nx=client.get('/api/nx/jobs/'+job['nx_job_id']).json()
                values={p['name']:p['value'] for p in nx['result']['parameters']}
                assert abs(values['current_A']-current)<1e-6 and values['length']==100
                assert client.get(f'/api/simulation/nastran/jobs/{key}/files/joule.op2').content
                assert 'FATAL' not in client.get(f'/api/simulation/nastran/jobs/{key}/files/joule.f06').text.upper()
                if current==20:
                    original=client.get('/api/nx/jobs/'+job['nx_job_id']+'/download').content
            first,second=report['jobs']
            assert abs(second['result']['rise_c']/first['result']['rise_c']-4)<2e-5
            assert client.get('/api/nx/jobs/'+first['nx_job_id']+'/download').content==original
            if args.launch:
                launched=client.post('/api/nx/launch',json={'job_id':second['nx_job_id']})
                launched.raise_for_status();report['gui_launch']=launched.json()
                for _ in range(160):
                    gui=client.get('/api/nx/jobs/'+second['nx_job_id']).json()
                    if gui.get('gui_state') in ('ready','failed','exited'):break
                    time.sleep(.5)
                assert gui.get('gui_state')=='ready',gui
                report['gui_model_loaded']=True
            assert client.get('/api/simulation/simcenter/projects').status_code==200
            assert client.post('/api/simulation/jobs',json={}).status_code==410
            report.update(ok=True,checks={'actual_NX_geometry_and_parameters':True,
                'actual_Siemens_SOL153_two_currents':True,'native_F06_and_OP2_available':True,
                'I_squared_temperature_rise':True,'source_model_preserved':True})
    except Exception as error:
        report['error']=str(error)
        raise
    finally:
        (args.data_dir/'native-joule-acceptance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'ok':True,'mode':report['mode'],'checks':report['checks']},ensure_ascii=False))


if __name__=='__main__':main()
