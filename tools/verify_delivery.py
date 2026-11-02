"""Standard-library smoke check of the single desktop delivery after relocation."""
import argparse
import hashlib
import http.cookiejar
import json
from pathlib import Path
import re
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path)
    parser.add_argument('--exe', type=Path,
                        default=Path(__file__).resolve().parents[1] / 'release/HartingDRP_NX.exe')
    args = parser.parse_args()
    exe = args.exe.resolve()
    if not exe.is_file():
        parser.error('Desktop EXE is missing; run build_desktop.ps1 or supply --exe.')
    report = {'ok': False, 'executable': exe.name,
              'executable_sha256': hashlib.sha256(exe.read_bytes()).hexdigest(), 'checks': {}}
    with tempfile.TemporaryDirectory(prefix='harting-delivery-check-') as data:
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        process = subprocess.Popen([str(exe), '--serve', '--port', str(port), '--data-dir', data],
                                  creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

        def request(path, method='GET', payload=None):
            body = None if payload is None else json.dumps(payload).encode('utf-8')
            req = urllib.request.Request(f'http://127.0.0.1:{port}' + path, data=body,
                    method=method, headers={'Content-Type': 'application/json'})
            try:
                with opener.open(req, timeout=15) as response:
                    return response.status, response.read()
            except urllib.error.HTTPError as error:
                return error.code, error.read()

        try:
            for _ in range(150):
                try:
                    status, index = request('/')
                    if status == 200:
                        break
                except urllib.error.URLError:
                    if process.poll() is not None:
                        raise RuntimeError('Desktop EXE exited during startup')
                time.sleep(.2)
            else:
                raise TimeoutError('Desktop startup timed out')
            assert request('/api/nx/settings')[0] == 401
            assert request('/api/auth/register', 'POST', {'username': 'delivery_check',
                'name': 'Delivery smoke check', 'password': 'Temporary-Check-2026'})[0] == 200
            settings = json.loads(request('/api/simulation/settings')[1])
            assert settings['engine'] == 'simcenter' and not settings['external_solver_enabled']
            assert settings['native_solve_verified'] is False
            assert settings['native_solve_verification_scope'] == 'imported_simcenter_project'
            assert request('/api/simulation/jobs', 'POST', {})[0] == 410
            assert request('/api/simulation/simcenter/projects')[0] == 200
            assert request('/api/nx/jobs')[0] == 200
            catalog = json.loads(request('/api/catalog')[1])['rows']
            assert len(catalog) == 44
            assets = re.findall(r'(?:src|href)="([^\"]+\.(?:js|css))"', index.decode('utf-8'))
            assert assets and all(request(asset if asset.startswith('/') else '/' + asset)[0] == 200 for asset in assets)
            report['checks'] = {'relocated_exe_starts': True, 'authentication_enforced': True,
                'frontend_assets_available': True, 'nx_endpoints_available': True,
                'native_engine_selected': True, 'retired_solver_disabled': True,
                'native_project_endpoint_available': True, 'original_44_checks_available': True}
            report['imported_simcenter_project_solve_verified'] = False
            report['native_joule_demo_available'] = 'native_joule_demo' in settings
            report['personal_account_data_touched'] = False
            report['ok'] = True
        except Exception as exc:
            report['error'] = str(exc)
            raise
        finally:
            if process.poll() is None:
                if hasattr(subprocess, 'CREATE_NO_WINDOW'):
                    subprocess.run(['taskkill.exe', '/PID', str(process.pid), '/T', '/F'],
                        capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
                else:
                    process.terminate()
            process.wait(timeout=20)
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
