import sqlite3
import time
from fastapi.testclient import TestClient
from desktop_auth import create_desktop_app


def register(client, username):
    response = client.post('/api/auth/register', json={'username':username,'password':'Test-pass-2026','name':username,'department':'研发部','email':''})
    assert response.status_code == 200, response.text
    assert 'httponly' in response.headers['set-cookie'].lower()
    return response.json()


def test_accounts_and_task_isolation(tmp_path):
    with TestClient(create_desktop_app(tmp_path), base_url='http://127.0.0.1') as a:
        assert a.get('/').status_code == 200
        assert a.get('/api/tasks').status_code == 401
        alice = register(a, 'alice')
        assert a.post('/api/auth/register', json={'username':'ALICE','password':'Test-pass-2026','name':'重复'}).status_code == 409
        books = a.get('/api/rulebooks').json()
        samples = a.get('/api/samples').json()
        assert samples and books
        model = a.post('/api/samples/'+samples[0]).json()
        task = a.post('/api/tasks', json={'model_id':model['id'],'rulebook_id':books[0]['id'],'only':['DFM-02']}).json()
        for _ in range(100):
            detail = a.get('/api/tasks/'+task['id']).json()
            if detail['state'] in ('completed','failed'):
                break
            time.sleep(.05)
        assert detail['state'] == 'completed', detail
        assert a.get('/api/tasks/'+task['id']+'/result').status_code == 200
        assert a.get('/api/tasks/'+task['id']+'/reports/html').status_code == 200
        assert a.put('/api/auth/me', json={'name':'工程师 Alice','department':'机械部','email':'alice@example.com'}).json()['name'] == '工程师 Alice'
        assert a.post('/api/auth/logout').status_code == 200
        assert a.get('/api/tasks').status_code == 401
        bob = register(a, 'bob')
        assert bob['id'] != alice['id']
        assert a.get('/api/tasks').json() == []
        assert a.get('/api/tasks/'+task['id']).status_code == 404
        assert a.get('/api/tasks/'+task['id']+'/download').status_code == 404
        assert a.post('/api/tasks', json={'model_id':model['id'],'rulebook_id':books[0]['id'],'only':['DFM-02']}).status_code == 404
        a.post('/api/auth/logout')
        assert a.post('/api/auth/login', json={'username':'alice','password':'wrong-pass'}).status_code == 401
        assert a.post('/api/auth/login', json={'username':'alice','password':'Test-pass-2026'}).status_code == 200
        assert len(a.get('/api/tasks').json()) == 1
        assert a.get('/api/auth/me').json()['department'] == '机械部'
        assert a.post('/api/auth/logout', headers={'origin':'http://evil.example'}).status_code == 403
        cookie = a.cookies.get('harting_session')
        with sqlite3.connect(tmp_path/'accounts.sqlite3') as db:
            records = db.execute('SELECT password FROM users').fetchall()
            assert all('Test-pass-2026' not in record for record in records)
            db.execute('UPDATE sessions SET expires=0')
        assert a.get('/api/tasks').status_code == 401
    with TestClient(create_desktop_app(tmp_path), base_url='http://127.0.0.1') as a:
        assert a.post('/api/auth/login', json={'username':'alice','password':'Test-pass-2026'}).status_code == 200
        assert len(a.get('/api/tasks').json()) == 1
