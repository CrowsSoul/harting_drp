"""Acceptance against the final executable using isolated accounts and actual NX."""
import argparse
import json
from pathlib import Path
import socket
import subprocess
import time
import httpx


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--exe', type=Path, required=True)
    parser.add_argument('--data-dir', type=Path, required=True)
    args = parser.parse_args()
    folder = args.data_dir.resolve()
    folder.mkdir(parents=True, exist_ok=True)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    report = {'ok': False, 'executable': str(args.exe.resolve()), 'jobs': []}
    process = subprocess.Popen([str(args.exe.resolve()), '--serve', '--port', str(port), '--data-dir', str(folder)],
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    try:
        with httpx.Client(base_url=f'http://127.0.0.1:{port}', timeout=20) as client:
            for _ in range(150):
                try:
                    if client.get('/').status_code == 200:
                        break
                except httpx.ConnectError:
                    if process.poll() is not None:
                        raise RuntimeError('EXE exited during startup')
                time.sleep(.2)
            account = client.post('/api/auth/register', json={
                'username': 'exe_nx_acceptance', 'name': 'EXE 联调验证', 'password': 'Exe-Test-2026'})
            account.raise_for_status()
            report['user_id'] = account.json()['id']
            assert client.get('/api/nx/settings').json()['batch_found']
            settings = client.get('/api/simulation/settings').json()
            assert settings['engine'] == 'simcenter' and not settings['external_solver_enabled'], settings
            assert not settings['native_solve_verified'] and 'calculix_exe' not in settings
            assert client.post('/api/simulation/jobs', json={}).status_code == 410
            assert client.put('/api/simulation/settings', json={'calculix_exe': 'ccx.exe'}).status_code == 410
            assert client.get('/api/simulation/simcenter/projects').json() == []
            assert client.get('/api/simulation/simcenter/jobs').json() == []
            report['simulation_settings'] = settings
            report['native_solve_acceptance'] = 'not_verified; requires a complete solver installation and a valid engineering project'

            def wait(key):
                for _ in range(240):
                    job = client.get('/api/nx/jobs/' + key).json()
                    if job['state'] in ('completed', 'failed', 'cancelled'):
                        report['jobs'].append(job)
                        if job['state'] != 'completed':
                            report['logs'] = client.get(f'/api/nx/jobs/{key}/logs').json()
                            raise AssertionError(job)
                        return job
                    time.sleep(.5)
                raise TimeoutError(key)

            created = client.post('/api/nx/jobs', json={'action': 'demo'})
            created.raise_for_status()
            key = created.json()['id']
            wait(key)
            original = client.get(f'/api/nx/jobs/{key}/download').content
            response = client.post('/api/nx/jobs', json={'action': 'apply', 'source_job_id': key, 'parameters': {'length': 40}})
            response.raise_for_status()
            modified = wait(response.json()['id'])
            values = {p['name']: p['value'] for p in modified['result']['parameters']}
            bbox = modified['result']['bodies'][0]['bbox']
            assert values['length'] == 40
            assert abs(bbox[3] - bbox[0] - 40) < 1e-5
            assert client.get(f'/api/nx/jobs/{key}/download').content == original
            report['checks'] = {'packed_journal_runs_in_real_nx': True, 'length_readback_40_mm': True,
                                'actual_geometry_40_mm': True, 'source_preserved': True,
                                'native_engine_selected': True, 'external_solver_disabled': True,
                                'retired_endpoints_rejected': True, 'native_project_endpoints_available': True}
            # Existing six-discipline flow still runs in the same executable.
            catalog = client.get('/api/catalog').json()['rows']
            assert len(catalog) == 44 and all(row['implemented'] for row in catalog)
            book = client.get('/api/rulebooks').json()[0]['id']
            report['categories'] = []
            for owner, sample in [('装配','board_a.model.json'),('注塑','thin_wall.model.json'),
                                  ('钣金','plate_holes.model.json'),('机加工','deep_slot.model.json'),
                                  ('电气安规','electrical_safety.model.json'),('性能预测','simulated_nx_terminal.model.json')]:
                scope = [row['check_item_id'] for row in catalog if row['owner_module'] == owner]
                assert scope
                model = client.post('/api/samples/' + sample).json()['id']
                task = client.post('/api/tasks', json={'model_id': model, 'rulebook_id': book, 'only': scope}).json()
                for _ in range(100):
                    detail = client.get('/api/tasks/' + task['id']).json()
                    if detail['state'] in ('completed', 'failed'):
                        break
                    time.sleep(.05)
                assert detail['state'] == 'completed', detail
                result = client.get('/api/tasks/' + task['id'] + '/result').json()
                assert not result['load_errors']
                assert not [row for row in result['results'] if row['status'] == 'error']
                assert client.get('/api/tasks/' + task['id'] + '/reports/html').status_code == 200
                report['categories'].append({'name': owner, 'items': len(scope), 'state': detail['state']})
            report['ok'] = True
            print(json.dumps({'ok': True, 'checks': report['checks'], 'categories': report['categories']}, ensure_ascii=False))
    except Exception as exc:
        report['error'] = str(exc)
        raise
    finally:
        (folder / 'acceptance.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        if process.poll() is None and hasattr(subprocess, 'CREATE_NO_WINDOW'):
            subprocess.run(['taskkill.exe', '/PID', str(process.pid), '/T', '/F'], capture_output=True,
                           creationflags=subprocess.CREATE_NO_WINDOW)
        elif process.poll() is None:
            process.terminate()
        process.wait(timeout=20)


if __name__ == '__main__':
    main()
