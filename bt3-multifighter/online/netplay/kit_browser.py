"""Opt-in LAN discovery and an optional shared directory; no central service is assumed.

The directory only advertises endpoints. Joining still performs password authentication,
disc/code checks, and the ordinary TCP/UDP handshake. Entries expire without heartbeats.
"""
import hashlib
import hmac
import ipaddress
import json
import secrets
import socket
import threading
import time
import urllib.parse
import urllib.request

DISCOVERY_PORT = 47401
MAGIC = 'TTM-BROWSER-1'
TTL = 90
ITERATIONS = 120000


def password_key(password, salt):
    return hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), bytes.fromhex(salt), ITERATIONS)


def proof(key, nonce):
    return hmac.new(key, ('TTM-room:' + nonce).encode('ascii'), hashlib.sha256).hexdigest()


def challenge(password):
    salt = secrets.token_hex(16)
    return salt, password_key(password, salt) if password else None


def auth_ok(key, nonce, response):
    return key is None or (isinstance(response, str) and hmac.compare_digest(proof(key, nonce), response))


def safe_room(row):
    if not isinstance(row, dict):
        raise ValueError('Invalid room advertisement')
    port = row.get('port')
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError('Invalid room port')
    return dict(name=str(row.get('name', 'Tag Team Mod'))[:64], port=port,
                adapter=str(row.get('adapter', ''))[:32], version=str(row.get('version', ''))[:32],
                players=max(0, min(16, int(row.get('players', 0)))),
                phase=str(row.get('phase', 'lobby'))[:24], password=bool(row.get('password')),
                protocol=int(row.get('protocol', 0)))


def directory_url(value):
    u = urllib.parse.urlsplit(value.strip())
    private = False
    try:
        private = ipaddress.ip_address(u.hostname).is_private
    except (ValueError, TypeError):
        private = u.hostname == 'localhost'
    if u.username or u.password or u.query or u.fragment or not u.hostname or \
            (u.scheme != 'https' and not (u.scheme == 'http' and private)):
        raise ValueError('Directory requires HTTPS (HTTP is allowed on private networks only)')
    return value.rstrip('/')


def request(url, path, data=None):
    target = directory_url(url) + path
    body = json.dumps(data).encode('utf-8') if data is not None else None
    req = urllib.request.Request(target, data=body, headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=4) as response:
        payload = response.read(131073)
        if len(payload) > 131072:
            raise ValueError('Directory response is too large')
        return json.loads(payload)


def discover(url='', timeout=1.5, address='255.255.255.255'):
    rooms, errors = {}, []
    nonce = secrets.token_hex(16)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.settimeout(0.1)
        sock.sendto(json.dumps(dict(magic=MAGIC, nonce=nonce)).encode(), (address, DISCOVERY_PORT))
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            try:
                data, peer = sock.recvfrom(4096)
                r = json.loads(data)
                if r.get('magic') != MAGIC or r.get('nonce') != nonce:
                    continue
                row = safe_room(r['room'])
                row['host'] = peer[0]
                row['source'] = 'LAN'
                rooms[(row['host'], row['port'])] = row
            except socket.timeout:
                pass
            except (OSError, ValueError, KeyError, TypeError, AttributeError):
                continue
    if url:
        try:
            for r in request(url, '/rooms').get('rooms', [])[:200]:
                row = safe_room(r)
                host = str(ipaddress.ip_address(r['host']))
                row.update(host=host, source='Directory')
                rooms[(host, row['port'])] = row
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
            errors.append('Directory: ' + str(error))
    return dict(rooms=list(rooms.values()), errors=errors)


class Advertiser:
    def __init__(self, room, directory=''):
        self.room, self.directory = room, directory
        self.stop = threading.Event()
        self.token = secrets.token_hex(32)
        self.error = None
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def close(self):
        self.stop.set()

    def run(self):
        last = 0
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind(('', DISCOVERY_PORT))
                sock.settimeout(0.2)
            except OSError as error:
                self.error = 'LAN discovery: ' + str(error)
                sock.settimeout(0.2)
            while not self.stop.is_set():
                try:
                    raw, peer = sock.recvfrom(4096)
                    q = json.loads(raw)
                    if q.get('magic') == MAGIC and isinstance(q.get('nonce'), str) and len(q['nonce']) == 32:
                        body = dict(magic=MAGIC, nonce=q['nonce'], room=safe_room(self.room()))
                        sock.sendto(json.dumps(body).encode(), peer)
                except socket.timeout:
                    pass
                except (OSError, ValueError, TypeError, AttributeError):
                    self.stop.wait(0.2)
                if self.directory and time.monotonic() - last > 25:
                    last = time.monotonic()
                    try:
                        request(self.directory, '/register', dict(token=self.token, room=safe_room(self.room())))
                    except (OSError, ValueError) as error:
                        self.error = str(error)
            if self.directory:
                try:
                    request(self.directory, '/remove', dict(token=self.token))
                except (OSError, ValueError):
                    pass
