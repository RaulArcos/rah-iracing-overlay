"""Isolated public Flask surface for capture: no SDK, SocketIO or desktop startup."""
import sys
from contextlib import contextmanager
from pathlib import Path
from threading import Thread

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'src'
sys.path.insert(0, str(SRC))


@contextmanager
def preview_server():
    from flask import Flask, send_from_directory
    from werkzeug.serving import make_server, WSGIRequestHandler
    from interface import interface_bp
    from overlays import overlays_bp

    app = Flask(__name__)
    app.register_blueprint(interface_bp)
    app.register_blueprint(overlays_bp, url_prefix='/overlay')

    @app.route('/common/js/<path:filename>')
    def serve_common_js(filename):
        return send_from_directory(SRC / 'common' / 'js', filename)

    # Fail closed if capture ever attempts a setting/launch action.
    @app.before_request
    def read_only():
        from flask import request, abort
        if request.method != 'GET':
            abort(405)

    class QuietHandler(WSGIRequestHandler):
        def log_request(self, *args, **kwargs):
            pass

    server = make_server('127.0.0.1', 0, app, request_handler=QuietHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}'
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
