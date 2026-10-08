"""Read-only USA BT3 skeletal animation bank decoder.

The formats below follow SLUS_216.78: PAK lookup 24FA20/24FA50,
byte-pair decompression 263278, channel evaluation 24BF58/24C1A8,
packed quaternion 256E00 and shortest-path SLERP 2568F8. No gameplay,
effect events, sound, root-motion application or actor aim overlays run here.
Matrices use column vectors, XYZW quaternions and parent @ T @ R; coordinates
remain in the game's negative-Y-up model space.
"""
from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass
import math
import struct

FPS = 30.0
ANIMATION_COUNT = 414
BONE_COUNT = 71
MAX_DECODED_SIZE = 0xC000  # Native per-animation scratch allocation.
IDENTITY = (0.0, 0.0, 0.0, 1.0)


class AnimationFormatError(ValueError):
    """Truncated, corrupt or unsupported native animation data."""


def _need(data: bytes, offset: int, size: int) -> None:
    if offset < 0 or size < 0 or offset + size > len(data):
        raise AnimationFormatError('Animation data extends beyond its resource')


def decompress_animation(data: bytes) -> bytes:
    """Decode the native byte-pair stream, with bounded dictionary expansion."""
    _need(data, 0, 8)
    expected, packed = struct.unpack_from('<II', data)
    if expected != 0 and not 148 <= expected <= MAX_DECODED_SIZE:
        raise AnimationFormatError(f'Unsupported animation unpacked size {expected}')
    _need(data, 8, packed)
    end, cursor = 8 + packed, 8
    output = bytearray()

    def byte() -> int:
        nonlocal cursor
        if cursor >= end:
            raise AnimationFormatError('Truncated byte-pair stream')
        value = data[cursor]
        cursor += 1
        return value

    while cursor < end:
        left, right, index = list(range(256)), [0] * 256, 0
        while index < 256:
            count = byte()
            if count >= 128:
                index += count - 127
                count = 0
            if index > 256:
                raise AnimationFormatError('Byte-pair dictionary skip overflow')
            if index == 256:
                break
            if index + count + 1 > 256:
                raise AnimationFormatError('Byte-pair dictionary run overflow')
            for _ in range(count + 1):
                left[index] = byte()
                if left[index] != index:
                    right[index] = byte()
                index += 1
        count = (byte() << 8) | byte()
        if count > 32767:
            raise AnimationFormatError('Native byte-pair token count exceeds signed 16 bits')
        for _ in range(count):
            stack = [byte()]
            # A valid binary tree producing N bytes visits at most 2*N-1 nodes.
            budget = 2 * (expected - len(output)) + 1
            while stack:
                token = stack.pop()
                budget -= 1
                if budget < 0:
                    raise AnimationFormatError('Cyclic or oversized byte-pair expansion')
                if left[token] == token:
                    if len(output) >= expected:
                        raise AnimationFormatError('Byte-pair output exceeds declared size')
                    output.append(token)
                else:
                    if len(stack) + 2 > 256:
                        raise AnimationFormatError('Cyclic or oversized byte-pair expansion')
                    stack.extend((right[token], left[token]))
    if len(output) != expected:
        raise AnimationFormatError('Byte-pair output size does not match its header')
    return bytes(output)


def _f32(value: float) -> float:
    return struct.unpack('<f', struct.pack('<f', value))[0]


def decode_quaternion(packed: int) -> tuple[float, float, float, float]:
    missing = packed >> 60
    if not 0 <= missing < 4:
        raise AnimationFormatError('Invalid compressed quaternion component index')
    scale, root2 = 9.536752259009518e-7, 1.4142135381698608
    values = [_f32(_f32(_f32(((packed >> (20*i)) & 0xFFFFF) * scale) - .5) * root2)
              for i in range(3)]
    total = _f32(_f32(_f32(values[0]*values[0]) + _f32(values[1]*values[1]))
                 + _f32(values[2]*values[2]))
    if total > 1.000001:
        raise AnimationFormatError('Compressed quaternion is not a unit rotation')
    values.insert(missing, _f32(math.sqrt(max(0.0, _f32(1.0-total)))))
    return tuple(values)


def slerp(a: tuple, b: tuple, fraction: float) -> tuple:
    dot = sum(x*y for x, y in zip(a, b))
    if dot < 0:
        b, dot = tuple(-v for v in b), -dot
    angle = math.acos(min(1.0, dot))
    sine = math.sin(angle)
    if sine < 1e-6:
        return a
    x, y = math.sin((1-fraction)*angle)/sine, math.sin(fraction*angle)/sine
    return tuple(x*u + y*v for u, v in zip(a, b))


@dataclass(frozen=True)
class BoneTransform:
    # None retains the mesh's bind local translation (rotation-only channels).
    translation: tuple[float, float, float] | None
    rotation: tuple[float, float, float, float]


@dataclass(frozen=True)
class AnimationTrack:
    bone_id: int
    times: tuple[int, ...]
    keys: tuple[BoneTransform, ...]

    def evaluate(self, frame: float) -> BoneTransform:
        if len(self.keys) == 1:
            return self.keys[0]
        exact = bisect_left(self.times, frame)
        if exact < len(self.times) and self.times[exact] == frame:
            return self.keys[exact]
        index = bisect_right(self.times, frame) - 1
        if index < 0 or index + 1 == len(self.keys):
            # This is also the native evaluator's out-of-channel-range result.
            return BoneTransform(None if self.keys[0].translation is None else (0., 0., 0.), IDENTITY)
        fraction = (frame-self.times[index]) / (self.times[index+1]-self.times[index])
        a, b = self.keys[index:index+2]
        translation = (None if a.translation is None else
                       tuple(x+(y-x)*fraction for x,y in zip(a.translation,b.translation)))
        return BoneTransform(translation, slerp(a.rotation, b.rotation, fraction))


@dataclass(frozen=True)
class AnimationClip:
    animation_id: int
    frame_count: int
    tracks: tuple[AnimationTrack, ...]
    flags: int

    @property
    def duration_seconds(self) -> float:
        return self.frame_count / FPS

    def evaluate(self, frame: float) -> dict[int, BoneTransform]:
        if not isinstance(frame, (float, int)) or not math.isfinite(frame):
            raise ValueError('Animation frame must be finite')
        frame = max(0.0, min(float(frame), self.frame_count))
        return {track.bone_id: track.evaluate(frame) for track in self.tracks}

    @classmethod
    def from_decoded(cls, animation_id: int, decoded: bytes) -> AnimationClip:
        _need(decoded, 0, 6 + 2*BONE_COUNT)
        flags, frames = struct.unpack_from('<HH', decoded)
        tracks = []
        for bone_id in range(BONE_COUNT):
            offset = struct.unpack_from('<H', decoded, 6 + 2*bone_id)[0] * 4
            if not offset:
                continue
            if offset < 148:
                raise AnimationFormatError('Bone channel overlaps animation header')
            _need(decoded, offset, 4)
            channel_flags, count = struct.unpack_from('<HH', decoded, offset)
            if not count:
                raise AnimationFormatError('Bone channel has no keys')
            start, keys, times = offset + 4, [], []
            if channel_flags & 1:
                _need(decoded, start, count*8 + (count*2 if count > 1 else 0))
                for i in range(count):
                    q = decode_quaternion(struct.unpack_from('<Q', decoded, start + i*8)[0])
                    keys.append(BoneTransform(None, q))
                    times.append(0 if count == 1 else struct.unpack_from('<H', decoded, start+count*8+i*2)[0])
            else:
                _need(decoded, start, count*24)
                for i in range(count):
                    x,y,z,time,packed = struct.unpack_from('<3fIQ', decoded, start + i*24)
                    if not all(math.isfinite(v) for v in (x,y,z)):
                        raise AnimationFormatError('Non-finite bone translation')
                    keys.append(BoneTransform((x,y,z), decode_quaternion(packed)))
                    times.append(time)
            if any(a > b for a,b in zip(times, times[1:])):
                raise AnimationFormatError('Bone key times must not decrease')
            tracks.append(AnimationTrack(bone_id, tuple(times), tuple(keys)))
        return cls(animation_id, frames, tuple(tracks), flags)


@dataclass(frozen=True)
class AnimationBank:
    clips: tuple[AnimationClip, ...]
    # Absent native sections are omitted, never replaced with invented clips.
    absent_ids: tuple[int, ...] = ()

    def clip(self, animation_id: int) -> AnimationClip:
        for clip in self.clips:
            if clip.animation_id == animation_id:
                return clip
        raise KeyError(animation_id)

    @classmethod
    def from_bytes(cls, data: bytes) -> AnimationBank:
        _need(data, 0, 4)
        count = struct.unpack_from('<I', data)[0]
        if not ANIMATION_COUNT <= count <= 4096:
            raise AnimationFormatError(f'Unsupported animation PAK entry count {count}')
        _need(data, 4, (count+1)*4)
        offsets = struct.unpack_from(f'<{count+1}I', data, 4)
        header_end = (count+2)*4
        if any((v & ~3) < header_end or (v & ~3) > len(data) for v in offsets):
            raise AnimationFormatError('Animation PAK offset outside resource data')
        if any((a & ~3) > (b & ~3) for a,b in zip(offsets, offsets[1:])):
            raise AnimationFormatError('Animation PAK offsets are not ordered')
        clips, absent = [], []
        for animation_id in range(ANIMATION_COUNT):
            start, end = offsets[animation_id] & ~3, offsets[animation_id+1] & ~3
            if start == end:
                absent.append(animation_id)
                continue
            try:
                decoded = decompress_animation(data[start:end])
                if not decoded:
                    absent.append(animation_id)
                else:
                    clips.append(AnimationClip.from_decoded(animation_id, decoded))
            except AnimationFormatError as exc:
                raise AnimationFormatError(f'Animation {animation_id}: {exc}') from exc
        return cls(tuple(clips), tuple(absent))
