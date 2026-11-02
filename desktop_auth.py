"""Local accounts and isolated workspaces for the desktop edition."""
import hashlib
import hmac
import re
import secrets
import sqlite3
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from nxdrp.checkers.platform_web.backend._server import create_app
from nxdrp.checkers.platform_web.backend._service import MODULE


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=8, max_length=128)


class Profile(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    department: str = Field(default='', max_length=80)
    email: str = Field(default='', max_length=120)


class Registration(Credentials, Profile):
    pass


def create_desktop_app(directory: Path):
    directory.mkdir(parents=True, exist_ok=True)
    db_path = directory / 'accounts.sqlite3'
    def connect():
        db = sqlite3.connect(db_path, timeout=15)
        db.row_factory = sqlite3.Row
        return db
    with connect() as db:
        db.execute('CREATE TABLE IF NOT EXISTS users (id TEXT PRIMARY KEY, username TEXT UNIQUE COLLATE NOCASE, salt TEXT, password TEXT, name TEXT, department TEXT, email TEXT)')
        db.execute('CREATE TABLE IF NOT EXISTS sessions (token TEXT PRIMARY KEY, user_id TEXT, expires REAL)')
    apps = {}
    lock = threading.Lock()
    failures = []
    def public(row):
        return {k: row[k] for k in ('id', 'username', 'name', 'department', 'email')}
    def user(request):
        token = request.cookies.get('harting_session', '')
        with connect() as db:
            row = db.execute('SELECT users.* FROM users JOIN sessions ON users.id=sessions.user_id WHERE token=? AND expires>?', (hashlib.sha256(token.encode()).hexdigest(), time.time())).fetchone()
        if not row:
            raise HTTPException(401, '请登录个人工作空间')
        return row
    def digest(password, salt):
        return hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 600_000).hex()
    def login_response(row):
        token = secrets.token_urlsafe(32)
        with connect() as db:
            db.execute('DELETE FROM sessions WHERE expires<?', (time.time(),))
            db.execute('INSERT INTO sessions VALUES (?,?,?)', (hashlib.sha256(token.encode()).hexdigest(), row['id'], time.time()+8*3600))
        response = JSONResponse(public(row))
        response.set_cookie('harting_session', token, httponly=True, samesite='strict', max_age=8*3600)
        return response
    @asynccontextmanager
    async def lifespan(app):
        yield
        for workspace in apps.values():
            workspace.state.platform.stop()
    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None)
    @app.middleware('http')
    async def local_only(request, call_next):
        from urllib.parse import urlsplit
        host = request.headers.get('host', '')
        if host.split(':')[0] not in {'127.0.0.1', 'localhost'}:
            return JSONResponse({'detail':'仅允许本机访问'}, status_code=403)
        origin = request.headers.get('origin')
        if origin and urlsplit(origin).netloc != host:
            return JSONResponse({'detail':'拒绝跨站请求'}, status_code=403)
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response
    @app.post('/api/auth/register')
    def register(data: Registration):
        if not re.fullmatch(r'[a-zA-Z0-9_.-]{3,32}', data.username):
            raise HTTPException(422, '用户名限 3–32 位字母、数字、点、横线或下划线')
        if not data.name.strip():
            raise HTTPException(422, '请输入姓名')
        salt = secrets.token_hex(16)
        try:
            with connect() as db:
                db.execute('INSERT INTO users VALUES (?,?,?,?,?,?,?)', (secrets.token_hex(16), data.username, salt, digest(data.password, salt), data.name.strip(), data.department.strip(), data.email.strip()))
                row = db.execute('SELECT * FROM users WHERE username=?', (data.username,)).fetchone()
        except sqlite3.IntegrityError:
            raise HTTPException(409, '用户名已存在，请更换用户名')
        return login_response(row)
    @app.post('/api/auth/login')
    def login(data: Credentials):
        with lock:
            failures[:] = [t for t in failures if t > time.time()-60]
            if len(failures) >= 12:
                raise HTTPException(429, '尝试次数过多，请一分钟后重试')
            failures.append(time.time())
        with connect() as db:
            row = db.execute('SELECT * FROM users WHERE username=?', (data.username,)).fetchone()
        calculated = digest(data.password, row['salt'] if row else '00'*16)
        if not row or not hmac.compare_digest(calculated, row['password']):
            raise HTTPException(401, '用户名或密码不正确')
        return login_response(row)
    @app.get('/api/auth/me')
    def me(request: Request):
        return public(user(request))
    @app.put('/api/auth/me')
    def update(request: Request, data: Profile):
        row = user(request)
        if not data.name.strip():
            raise HTTPException(422, '姓名不能为空')
        with connect() as db:
            db.execute('UPDATE users SET name=?, department=?, email=? WHERE id=?', (data.name.strip(), data.department.strip(), data.email.strip(), row['id']))
        return me(request)
    @app.post('/api/auth/logout')
    def logout(request: Request):
        with connect() as db:
            db.execute('DELETE FROM sessions WHERE token=?', (hashlib.sha256(request.cookies.get('harting_session','').encode()).hexdigest(),))
        response = JSONResponse({'ok':True})
        response.delete_cookie('harting_session')
        return response
    static = StaticFiles(directory=MODULE / 'frontend/dist', html=True)
    class Dispatcher:
        async def __call__(self, scope, receive, send):
            if not scope['path'].startswith('/api'):
                return await static(scope, receive, send)
            try:
                row = user(Request(scope))
            except HTTPException as exc:
                return await JSONResponse({'detail':exc.detail}, status_code=exc.status_code)(scope, receive, send)
            with lock:
                if row['id'] not in apps:
                    workspace = create_app(directory / 'users' / row['id'], workers=2)
                    workspace.state.platform.start()
                    apps[row['id']] = workspace
                workspace = apps[row['id']]
            await workspace(scope, receive, send)
    app.mount('/', Dispatcher())
    return app
