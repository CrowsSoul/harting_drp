import io
import json
import time
import zipfile

from fastapi.testclient import TestClient
from desktop_auth import create_desktop_app


def register(client, name):
    response = client.post('/api/auth/register', json={'username': name, 'name': name, 'password': 'Bridge-Test-2026'})
    assert response.status_code == 200, response.text


def wait(client, key):
    for _ in range(300):
        record = client.get('/api/assistant/runs/' + key).json()
        if record['state'] in {'completed', 'failed', 'cancelled'}:
            assert record['state'] == 'completed', record
            return record
        time.sleep(.02)
    raise AssertionError('Semantic run timed out')


def test_semantic_result_is_same_snapshot_in_workbench_and_reports(tmp_path, monkeypatch):
    monkeypatch.setenv('DEEPSEEK_API_KEY', '')
    monkeypatch.setenv('NXDRP_REPORT_PROVIDER', 'nxdrp.checkers.report:generate_report')
    with TestClient(create_desktop_app(tmp_path), base_url='http://127.0.0.1') as client:
        register(client, 'bridge_alice')
        response = client.post('/api/assistant/auto', json={'instruction': 'board_a 跑一遍全部检查', 'offline': True})
        assert response.status_code == 202, response.text
        record = wait(client, response.json()['run']['run_id'])
        key = record['platform_task_id']
        task = client.get('/api/tasks/' + key).json()
        result = client.get('/api/tasks/' + key + '/result').json()
        assert task['state'] == 'completed' and task['origin'] == 'assistant'
        assert task['assistant_run_id'] == record['run_id']
        assert result['findings'] == record['result']['checks']['findings']
        assert result['assistant']['review'] == record['result']['review']
        assert task['summary']['findings'] == len(result['findings'])
        model = client.get('/api/tasks/' + key + '/model').json()
        assert model['model_id'] == record['result']['model']['model_id']
        rules = client.get('/api/tasks/' + key + '/rules').json()['rules']
        assert len([r for r in rules if r['check_item_id'].startswith('DFM-') and r.get('expression')]) == 38
        page = client.get('/api/tasks/' + key + '/reports/html')
        assert 'board_a 跑一遍全部检查' in page.text and '本次规则公式与出处' in page.text
        for fmt in ('pdf', 'docx'):
            created = client.post('/api/tasks/' + key + '/reports/' + fmt)
            assert created.status_code == 200, created.text
            exported = client.get(created.json()['download_url'])
            assert exported.status_code == 200
            if fmt == 'pdf':
                assert exported.content.startswith(b'%PDF-')
            else:
                with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
                    assert '语义任务评测报告' in archive.read('word/document.xml').decode('utf-8')
        client.post('/api/auth/logout')
        register(client, 'bridge_bob')
        assert client.get('/api/tasks/' + key).status_code == 404
        assert client.get('/api/tasks/' + key + '/result').status_code == 404
        assert client.get('/api/tasks/' + key + '/reports/html').status_code == 404
        assert client.get('/api/assistant/runs/' + record['run_id']).status_code == 404


def test_conditions_only_prediction_has_no_fabricated_geometry(tmp_path, monkeypatch):
    monkeypatch.setenv('DEEPSEEK_API_KEY', '')
    with TestClient(create_desktop_app(tmp_path), base_url='http://127.0.0.1') as client:
        register(client, 'bridge_conditions')
        response = client.post('/api/assistant/auto', json={
            'instruction': '给截面积 3.5 mm²、长度 12 mm、Cu，算 25 A 下的温升', 'offline': True})
        assert response.status_code == 202, response.text
        record = wait(client, response.json()['run']['run_id'])
        key = record['platform_task_id']
        task = client.get('/api/tasks/' + key).json()
        model = client.get('/api/tasks/' + key + '/model').json()
        assert task['analysis_only'] and task['total_items'] == 0 and model['parts'] == []
        result = client.get('/api/tasks/' + key + '/result').json()
        assert result['results'] == [] and result['findings'] == []
        assert result['assistant']['simulation'] == record['result']['simulation']
        page = client.get('/api/tasks/' + key + '/reports/html')
        assert '未执行几何检查' in page.text and '性能模型' in page.text
