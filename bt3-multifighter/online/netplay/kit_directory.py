"""Optional room directory. Use --cert and --key for direct public HTTPS.

python kit_directory.py --bind 127.0.0.1 --port 47402
Room endpoints use the actual client address. Forwarded headers are ignored;
do not place this service behind an unconfigured reverse proxy.
"""
import argparse
import ssl
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from kit_browser import TTL, safe_room


class Directory:
    def __init__(self):
        self.rows = {}
        self.lock = threading.Lock()

    def apply(self, path, host, data):
        with self.lock:
            now = time.monotonic()
            self.rows = {key: row for key, row in self.rows.items() if now - row['seen'] < TTL}
            if path == '/rooms':
                return dict(rooms=[dict(row['room'], host=row['host']) for row in self.rows.values()])
            token = data.get('token')
            if not isinstance(token, str) or len(token) != 64 or any(c not in '0123456789abcdef' for c in token):
                raise ValueError('Invalid registration token')
            key = (host, token)
            if path == '/register':
                if key not in self.rows and (len(self.rows) >= 200 or sum(k[0] == host for k in self.rows) >= 8):
                    raise ValueError('Directory is full for this address')
                self.rows[key] = dict(room=safe_room(data.get('room')), host=host, seen=now)
                return dict(ok=True)
            if path == '/remove':
                self.rows.pop(key, None)
                return dict(ok=True)
            raise ValueError('Unknown endpoint')


def server(bind='127.0.0.1', port=47402):
    directory = Directory()
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(5)

        def log_message(self, *args):
            pass  # no tokens or personal client data in access logs

        def handle_request(self):
            try:
                length = int(self.headers.get('Content-Length', 0))
                if not 0 <= length <= 4096:
                    raise ValueError('Request is too large')
                data = json.loads(self.rfile.read(length)) if length else {}
                if self.command == 'GET' and self.path != '/rooms' or self.command == 'POST' and self.path not in ('/register', '/remove'):
                    raise ValueError('Unknown endpoint')
                result = directory.apply(self.path, self.client_address[0], data)
                status = 200
            except (ValueError, TypeError, AttributeError):
                result, status = dict(error='Invalid directory request'), 400
            body = json.dumps(result).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        do_GET = do_POST = handle_request
    return ThreadingHTTPServer((bind, port), Handler)


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--bind', default='127.0.0.1')
    ap.add_argument('--port', type=int, default=47402)
    ap.add_argument('--cert', help='TLS certificate for a public directory')
    ap.add_argument('--key', help='TLS private key')
    args = ap.parse_args()
    if bool(args.cert) != bool(args.key):
        ap.error('--cert and --key must be supplied together')
    srv = server(args.bind, args.port)
    if args.cert:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(args.cert, args.key)
        srv.socket = context.wrap_socket(srv.socket, server_side=True)
    srv.serve_forever()
