"""Optional immutable ISO-reference representation of an authoritative state.

The original archive is always available. Dependency/adapter/codec differences
disable this transport optimization without changing gameplay compatibility.
"""
import hashlib
from dataclasses import dataclass
import json
import os
from pathlib import Path
import threading
import zlib

CODEC = 'iso-ref-v1'
MAX_WIRE = 64 << 20
MAX_ARCHIVE = 512 << 20
_FRESH_TOKEN = object()


@dataclass(frozen=True, init=False)
class FreshArchiveProof:
    """Ephemeral receipt from our trusted fresh converter, never disk/wire input."""
    archive_sha256: str
    archive_size: int
    zlib_version: str
    _word_json: str

    def __init__(self, archive_sha256, archive_size, words, token):
        if token is not _FRESH_TOKEN:
            raise ValueError('Fresh archive proofs must come from the converter receipt')
        object.__setattr__(self, 'archive_sha256', archive_sha256)
        object.__setattr__(self, 'archive_size', archive_size)
        object.__setattr__(self, 'zlib_version', zlib.ZLIB_RUNTIME_VERSION)
        object.__setattr__(self, '_word_json', json.dumps(words, sort_keys=True, separators=(',', ':')))

    def matches(self, archive_sha256, archive_size):
        return self.archive_sha256 == archive_sha256 and self.archive_size == archive_size and \
            self.zlib_version == zlib.ZLIB_RUNTIME_VERSION

    def words(self):
        return json.loads(self._word_json)


def fresh_preparation_proof(path, report):
    """Only the fresh prepare return calls this; editable match.json is excluded.

    build_netplay emitted this receipt AFTER the audited level-1 writer had
    reopened, CRC-read and compared every native entry with guarded final RAM.
    The trusted local/subprocess converter then checked the full lobby spec.
    """
    import kit_verify
    built = report.get('netplay') or {}
    proof = built.get('archive_proof')
    expected = report.get('netplay_sha256')
    words = report.get('words')
    size = Path(path).stat().st_size
    if not isinstance(words, dict) or len(kit_verify.canonical(words)) > 1 << 20 or \
            not valid_sha(expected) or built.get('sha256') != expected or \
            report.get('verify_sha') != kit_verify.sha(words) or type(proof) is not dict or \
            type(proof.get('schema')) is not int or \
            proof != dict(schema=1, writer='python-zipfile-deflate-1', zlib=zlib.ZLIB_RUNTIME_VERSION,
                          sha256=expected, size=size) or not 0 < size <= MAX_ARCHIVE or sha(path) != expected:
        raise ValueError('The fresh converter receipt does not match its fully verified archive')
    return FreshArchiveProof(expected, size, words, _FRESH_TOKEN)


def sha(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b''):
            result.update(chunk)
    return result.hexdigest()


class Manager:
    def __init__(self, iso_path, expected_iso_sha, adapter, cache, say=lambda _: None):
        self.lock = threading.RLock()
        self.iso = None
        self.codec = None
        self.cache = Path(cache) / 'wire'
        self.say = say
        self.fresh_proofs = {}
        self.decoded_memory = None
        if adapter != 'bt3-usa' or not valid_sha(expected_iso_sha):
            return
        try:
            import kit_wire_codec
            self.codec = kit_wire_codec
            self.iso = kit_wire_codec.VerifiedIso(iso_path, expected_iso_sha, adapter=adapter)
        except Exception as error:
            self.say(f'Compact transfer unavailable; ordinary snapshots remain enabled ({type(error).__name__}).')

    def capability(self):
        if self.iso is None:
            return None
        return dict(codec=CODEC, schema=self.codec.SCHEMA, iso_sha256=self.iso.sha256,
                    adapter=self.iso.adapter.name, zlib=zlib.ZLIB_RUNTIME_VERSION, max_wire=MAX_WIRE)

    def compatible(self, capability):
        local = self.capability()
        return local is not None and isinstance(capability, dict) and capability == local

    def artifact(self, path, expected_sha, expected_size):
        original = dict(codec='archive', path=str(path), sha256=expected_sha, size=expected_size)
        with self.lock:
            if Path(path).stat().st_size != expected_size or sha(path) != expected_sha:
                raise ValueError('Authoritative source changed')
            if self.iso is None or not valid_sha(expected_sha):
                return original
            try:
                self.cache.mkdir(parents=True, exist_ok=True)
                key = hashlib.sha256((expected_sha + self.iso.sha256 + self.codec.SCHEMA
                                      + zlib.ZLIB_RUNTIME_VERSION).encode()).hexdigest()
                target = self.cache / (key + '.wire')
                receipt = self.cache / (key + '.json')
                # Cache files are disposable. Recheck their embedded identity and
                # hash rather than trusting a separately editable receipt.
                if target.is_file():
                    try:
                        if not 0 < target.stat().st_size <= MAX_WIRE or not receipt.is_file() or receipt.stat().st_size > 4096:
                            raise ValueError('Invalid wire cache bounds/receipt')
                        known = json.loads(receipt.read_text())
                        if known.get('archive_sha256') != expected_sha or known.get('archive_size') != expected_size \
                                or known.get('iso_sha256') != self.iso.sha256 or known.get('schema') != self.codec.SCHEMA:
                            raise ValueError('Wire cache identity differs')
                        data = target.read_bytes()
                        actual = hashlib.sha256(data).hexdigest()
                        if known.get('sha256') != actual or known.get('size') != len(data):
                            raise ValueError('Wire cache content changed')
                        header, _ = self.codec.header_of(data)
                        if header['archive_sha256'] != expected_sha or header['archive_length'] != expected_size \
                                or header['iso_sha256'] != self.iso.sha256 or header['schema'] != self.codec.SCHEMA:
                            raise ValueError('Wire cache metadata differs')
                        return dict(codec=CODEC, path=str(target), sha256=actual,
                                    size=len(data), iso_sha256=self.iso.sha256)
                    except Exception:
                        target.unlink(missing_ok=True); receipt.unlink(missing_ok=True)
                proof = getattr(self, 'fresh_proofs', {}).get(expected_sha)
                encoded = self.codec.encode_state(path, self.iso, fresh_proof=proof) if proof is not None else \
                    self.codec.encode_state(path, self.iso)
                if encoded.archive_sha256 != expected_sha:
                    raise ValueError('Authoritative archive identity changed')
                part = target.with_name(target.name + f'.{os.getpid()}.part')
                try:
                    part.write_bytes(encoded.wire)
                    part.replace(target)
                    known = dict(archive_sha256=expected_sha, archive_size=expected_size,
                                 iso_sha256=self.iso.sha256, schema=self.codec.SCHEMA,
                                 sha256=hashlib.sha256(encoded.wire).hexdigest(), size=len(encoded.wire))
                    receipt_part = receipt.with_name(receipt.name + f'.{os.getpid()}.part')
                    try:
                        receipt_part.write_text(json.dumps(known, sort_keys=True))
                        receipt_part.replace(receipt)
                    finally:
                        receipt_part.unlink(missing_ok=True)
                finally:
                    part.unlink(missing_ok=True)
                self.say(f'Compact snapshot: {expected_size / 1e6:.1f} -> {len(encoded.wire) / 1e6:.1f} MB '
                         f'({encoded.seconds:.2f} s encoding).')
                return dict(codec=CODEC, path=str(target), sha256=hashlib.sha256(encoded.wire).hexdigest(),
                            size=len(encoded.wire), iso_sha256=self.iso.sha256)
            except Exception as error:
                self.say(f'Using ordinary snapshot transfer ({type(error).__name__}).')
                return original

    def register_fresh(self, proof):
        """Cache only bounded immutable proof objects, not decoded game RAM."""
        if type(proof) is not FreshArchiveProof or not proof.matches(proof.archive_sha256, proof.archive_size):
            return False
        with self.lock:
            if not hasattr(self, 'fresh_proofs'):
                self.fresh_proofs = {}
            self.fresh_proofs.pop(proof.archive_sha256, None)
            self.fresh_proofs[proof.archive_sha256] = proof
            while len(self.fresh_proofs) > 8:
                self.fresh_proofs.pop(next(iter(self.fresh_proofs)))
        return True

    def restore(self, descriptor, part, target, *, current=lambda: True):
        """Verify, reconstruct, and atomically publish one owned transfer."""
        if descriptor['codec'] == 'archive':
            if Path(part).stat().st_size != descriptor['archive_size'] or sha(part) != descriptor['archive_sha256']:
                raise ValueError('Ordinary snapshot identity differs')
            Path(part).replace(target)
            return str(target)
        with self.lock:
            if self.iso is None or self.codec is None or descriptor.get('iso_sha256') != self.iso.sha256:
                raise ValueError('Compact snapshot ISO is unavailable')
            if Path(part).stat().st_size != descriptor['size'] or descriptor['size'] > MAX_WIRE:
                raise ValueError('Compact representation size differs')
            with Path(part).open('rb') as stream:
                wire = stream.read(MAX_WIRE + 1)
            if len(wire) != descriptor['size'] or hashlib.sha256(wire).hexdigest() != descriptor['sha256']:
                raise ValueError('Compact representation identity differs')
            # One transient EE image, never an editable receipt or a disk cache.
            # Older/alternate codecs retain the conventional verification path.
            decoded = self.codec.decode_state_with_memory(wire, self.iso, descriptor['archive_sha256']) \
                if hasattr(self.codec, 'decode_state_with_memory') else None
            data = decoded.archive if decoded is not None else \
                self.codec.decode_state(wire, self.iso, descriptor['archive_sha256'])
            if len(data) != descriptor['archive_size']:
                raise ValueError('Reconstructed archive size differs')
            output = Path(part).with_name(Path(part).name + '.decoded')
            try:
                output.write_bytes(data)
                if sha(output) != descriptor['archive_sha256']:
                    raise ValueError('Reconstructed archive identity differs')
                output.replace(target)
                if decoded is not None and current():
                    import kit_state
                    self.decoded_memory = kit_state.decoded_memory(target, decoded)
            finally:
                output.unlink(missing_ok=True)
        return str(target)

    def snapshot_for(self, path, expected_sha, expected_size):
        """Return only the current opaque proof after a complete disk identity check."""
        with self.lock:
            value = self.decoded_memory
            if value is None or not valid_sha(expected_sha) or type(expected_size) is not int or expected_size <= 0:
                return None
            try:
                value.read(path, expected_sha, expected_size)
            except (OSError, ValueError):
                self.decoded_memory = None
                return None
            return value

    def discard_snapshot(self):
        with self.lock:
            self.decoded_memory = None

    def close(self):
        with self.lock:
            self.decoded_memory = None
            getattr(self, 'fresh_proofs', {}).clear()
            if self.iso is not None:
                self.iso.close()
                self.iso = None


def valid_sha(value):
    return isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value)
