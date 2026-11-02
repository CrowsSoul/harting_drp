"""Cancel a real solver phase in the dedicated verify_native_joule workspace."""
import argparse,json,time
from pathlib import Path
from verify_semantic_nx import client_for


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--data-dir',type=Path,required=True)
    parser.add_argument('--exe',type=Path)
    args=parser.parse_args()
    assert (args.data_dir/'native-joule-acceptance.json').is_file(), 'Use the isolated native-joule verification workspace'
    with client_for(args) as client:
        r=client.post('/api/auth/login',json={'username':'native_joule_verify','password':'Native-Joule-2026'})
        r.raise_for_status()
        r=client.post('/api/simulation/nastran/jobs',json={'current_a':10.})
        r.raise_for_status();key=r.json()['id']
        for _ in range(360):
            job=client.get('/api/simulation/nastran/jobs/'+key).json()
            if job['stage'].startswith('Siemens'):break
            assert job['state'] not in ('failed','completed','cancelled'),job
            time.sleep(.5)
        else:raise TimeoutError('native solver phase not reached')
        time.sleep(.5)
        started=time.monotonic()
        client.post('/api/simulation/nastran/jobs/'+key+'/cancel').raise_for_status()
        for _ in range(100):
            job=client.get('/api/simulation/nastran/jobs/'+key).json()
            if job['state'] in ('failed','completed','cancelled'):break
            time.sleep(.2)
        assert job['state']=='cancelled',job
        report={'ok':True,'state':job['state'],'cancel_elapsed_s':round(time.monotonic()-started,3),
                'job_id':key,'nx_job_id':job.get('nx_job_id'),'stage_before_cancel':'native Siemens solver',
                'logs':client.get('/api/simulation/nastran/jobs/'+key+'/logs').json()}
        (args.data_dir/'native-cancel-acceptance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({k:v for k,v in report.items() if k!='logs'},ensure_ascii=False))


if __name__=='__main__':main()
