"""Launch the modern interface alongside the untouched original GUI."""
import os
import socket
import threading
import time
import sys
from pathlib import Path
from runtime_paths import configure
configure()
import uvicorn
from desktop.server import create_app
from desktop.storage import ROOT
from desktop.instance import acquire

def main(start_page='studio'):
    os.chdir(ROOT)
    lock = acquire(ROOT / '.desktop/instance.lock')
    if lock is None:
        print('Flow AI Studio is already running. Use its existing window.\n'
              'After your jobs finish, close that window and launch again to load updates.', flush=True)
        return 2
    with lock:
        return run_app(start_page)

def run_app(start_page=''):
    app = create_app()
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
    config = uvicorn.Config(app, host='127.0.0.1', port=port, log_level='warning', access_log=False)
    server = uvicorn.Server(config)
    thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        if not thread.is_alive():
            raise RuntimeError('Local backend could not start')
        time.sleep(.05)
    if not server.started:
        raise RuntimeError('Local backend startup timed out')
    import webview
    class Bridge:
        def choose(self, kind='file'):
            dialog_type = webview.FileDialog.FOLDER if kind == 'folder' else webview.FileDialog.SAVE if kind == 'save' else webview.FileDialog.OPEN
            result = window.create_file_dialog(dialog_type, allow_multiple=kind=='references')
            return list(result) if result and kind=='references' else result[0] if result else None
    window = webview.create_window('Flow AI Studio', f'http://127.0.0.1:{port}/' + ('#'+start_page if start_page else ''), js_api=Bridge(),
                                  width=1440, height=920, min_size=(880, 600), background_color='#09090b')
    try:
        webview.start(gui='edgechromium', debug=False)
    finally:
        app.state.jobs.close()
        server.should_exit = True
        thread.join(timeout=3)
        sock.close()

if __name__ == '__main__':
    sys.exit(main() or 0)
