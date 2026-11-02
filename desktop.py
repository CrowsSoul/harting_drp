"""Windows desktop entry point. Data always lives outside the application bundle."""
import argparse
import ctypes
import logging
import os
from pathlib import Path
import socket
import threading
import time
import urllib.request


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--serve', action='store_true', help='Run local web service for diagnostics')
    parser.add_argument('--port', type=int, default=0)
    parser.add_argument('--data-dir', type=Path)
    args = parser.parse_args()
    data = args.data_dir or Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'HartingDRP'
    data.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=data / 'desktop.log', level=logging.INFO, encoding='utf-8')
    # 桌面版默认启用报告模块：平台通过 provider 动态加载，生成 PDF / Word。
    os.environ.setdefault('NXDRP_REPORT_PROVIDER', 'nxdrp.checkers.report:generate_report')
    import uvicorn
    from desktop_auth import create_desktop_app
    app = create_desktop_app(data)
    sock = socket.socket()
    sock.bind(('127.0.0.1', args.port))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_config=None))
    if args.serve:
        server.run(sockets=[sock])
        return
    thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
    thread.start()
    try:
        for _ in range(200):
            if server.started:
                break
            if not thread.is_alive():
                raise RuntimeError('本地服务未能启动，请查看 desktop.log')
            time.sleep(.05)
        else:
            raise RuntimeError('本地服务启动超时')
        import webview
        webview.create_window('HARTING · 设计检查工作台', f'http://127.0.0.1:{port}', width=1500, height=940, min_size=(1100,720), background_color='#edf0f3')
        webview.settings['ALLOW_DOWNLOADS'] = True
        webview.start(gui='edgechromium', private_mode=True)
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        sock.close()


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        logging.exception('Desktop failed')
        ctypes.windll.user32.MessageBoxW(0, f'启动失败：{exc}\n\n请确认已安装 Microsoft Edge WebView2 Runtime。\n日志位于 %LOCALAPPDATA%\\HartingDRP\\desktop.log', 'HARTING', 0x10)
