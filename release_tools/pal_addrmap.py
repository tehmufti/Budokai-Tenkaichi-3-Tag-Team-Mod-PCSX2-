"""USA (SLUS-21678) -> PAL (SLES-54945) address mapper for Budokai Tenkaichi 3.

Durable copy of the research mapper (scratchpad pal/addrmap/addrmap.py, VERSION 25) used by
release_tools/build_pal_map.py. It only reads: the two executables and DBZP.BIN overlays (paths or bytes)
and, optionally, the Hex-Rays export of the USA ELF (function starts). Its build cache lives in the
system temporary folder, never next to the tools or the game. The same mapper maps USA -> Japanese
(SLPS-25815) with two data rules switched (load(keep_equal_pairs=True, replay=False)): the Japanese
executable keeps USA's small-data and .bss addresses and its 60 Hz replay records. "PAL" below names the
target executable.

Memory model (verified, see research/address-map.md)
    ELF .text            USA 0x100000-0x2BF6B0      PAL 0x100000-0x2C0680
    ELF data/bss         USA 0x2BF6B0-0x334BF8      PAL 0x2C0680-0x331A38
    DBZP.BIN overlay     USA 0x334C00-0x3BE71C      PAL 0x331B00-0x3BC07C
        (menu / select-screen code, re-read before every menu session; crt0 zeroes _fbss.._end and
         SetupHeap(_end): _end = overlay base + DBZP.BIN size in both regions)
    heap                 above _end (USA 0x3BE71C, PAL 0x3BC07C)  -- not mappable statically

API
    m = load(usa, pal, hexrays)     # usa/pal = (elf, DBZP.BIN) paths or bytes; builds once (~2 min), then
                                    # reuses a pickle in the temp folder keyed by every input hash
    m.map_code(usa_addr)            -> (pal_addr | None, confidence)          ELF .text, .vutext, overlay code
    m.map_data(usa_addr)            -> (pal_addr | None, confidence)          ELF data/bss, overlay data
    m.map_addr(usa_addr)            -> (pal_addr | None, confidence, region)  dispatches by USA region
    m.explain(usa_addr)             -> dict with the evidence behind a mapping
    m.function_of(usa_addr)         -> USA function record (start, end, class, pal_start, ...)
    m.export_json(path)             -> runs, functions, data segments, evidence counts

Confidence vocabulary
    code:  'exact'   word inside a function classified identical (every word equal or relocation-verified)
           'high'    word matched by alignment and equivalent (equal, or relocation-verified)
           'medium'  word matched but it differs in a way not proven to be relocation only
           'low'     word not matched; position interpolated between matched neighbours with one delta
           'none'    no usable mapping
    data:  'exact'   the address itself is an evidence point, or lies in a content-aligned block
           'high'    inside a run of >=2 evidence points sharing one delta
           'medium'  between two runs with the same delta
           'ambiguous' between runs with different deltas (explain() lists every candidate)
           'low'     only the section base delta is known
           'none'    outside every known region
"""
from __future__ import annotations

import bisect
import collections
import difflib
import hashlib
import json
import pickle
import struct
import sys
import tempfile
from pathlib import Path

CACHE_DIR = Path(tempfile.gettempdir()) / 'tagteam-pal-addrmap'
VERSION = 25

# ------------------------------------------------------------------------------------------ images

class Image:
    """One region's executable plus its DBZP.BIN overlay, as the EE sees them after the menu loads."""

    def __init__(self, elf, overlay):
        self.path = '<bytes>' if isinstance(elf, (bytes, bytearray)) else str(Path(elf))
        self.blob = bytes(elf) if isinstance(elf, (bytes, bytearray)) else Path(elf).read_bytes()
        self.overlay = bytes(overlay) if isinstance(overlay, (bytes, bytearray)) else Path(overlay).read_bytes()
        self.sha256 = hashlib.sha256(self.blob).hexdigest()
        self.overlay_sha256 = hashlib.sha256(self.overlay).hexdigest()
        d = self.blob
        shoff = struct.unpack_from('<I', d, 32)[0]
        shnum, shstr = struct.unpack_from('<HH', d, 48)
        stroff = struct.unpack_from('<10I', d, shoff + 40 * shstr)[4]
        self.sections = {}
        for i in range(shnum):
            name, typ, fl, addr, off, size = struct.unpack_from('<6I', d, shoff + 40 * i)
            nm = d[stroff + name:d.index(b'\0', stroff + name)].decode()
            if addr and size:
                self.sections[nm] = dict(addr=addr, size=size, off=off, nobits=(typ == 8))
        self.gp = struct.unpack_from('<6I', d, self.sections['.reginfo']['off'])[5]
        t = self.sections['.text']
        self.text_base, self.text_end = t['addr'], t['addr'] + t['size']
        bss = self.sections['.bss']
        self.bss_end = bss['addr'] + bss['size']
        # the overlay is loaded at the first 0x100-aligned address after .bss (crt0/_end evidence below)
        self.ov_base = (self.bss_end + 0xFF) & ~0xFF
        self.ov_end = self.ov_base + len(self.overlay)
        self.end = self.ov_end
        self.sections['DBZP.BIN'] = dict(addr=self.ov_base, size=len(self.overlay), off=None, nobits=False)
        tw = list(struct.unpack_from('<%dI' % (t['size'] // 4), d, t['off']))
        ow = list(struct.unpack_from('<%dI' % (len(self.overlay) // 4), self.overlay))
        self.n_text = len(tw)
        self.words = tw + ow                          # one index space: ELF .text then the overlay
        self.n = len(self.words)
        self._ordered = sorted((s['addr'], s['addr'] + s['size'], n) for n, s in self.sections.items())

    # index <-> address over the combined code space
    def idx(self, addr):
        if self.text_base <= addr < self.text_end:
            return (addr - self.text_base) >> 2
        if self.ov_base <= addr < self.ov_end:
            return self.n_text + ((addr - self.ov_base) >> 2)
        return None

    def addr(self, idx):
        if idx < self.n_text:
            return self.text_base + 4 * idx
        return self.ov_base + 4 * (idx - self.n_text)

    def in_text(self, addr):
        return self.text_base <= addr < self.text_end

    def in_overlay(self, addr):
        return self.ov_base <= addr < self.ov_end

    def in_code_space(self, addr):
        return self.in_text(addr) or self.in_overlay(addr)

    def in_image(self, addr):
        return 0x100000 <= addr < self.end

    def section_of(self, addr):
        for lo, hi, n in self._ordered:
            if lo <= addr < hi:
                return n
        if self.bss_end <= addr < self.ov_base:
            return 'pad'
        return None

    def read(self, addr, n):
        if self.in_overlay(addr) and addr + n <= self.ov_end:
            o = addr - self.ov_base
            return self.overlay[o:o + n]
        for name, s in self.sections.items():
            if s['off'] is not None and s['addr'] <= addr and addr + n <= s['addr'] + s['size']:
                if s['nobits']:
                    return None
                o = s['off'] + addr - s['addr']
                return self.blob[o:o + n]
        return None

    def word(self, addr):
        b = self.read(addr, 4)
        return None if b is None else struct.unpack('<I', b)[0]


# ------------------------------------------------------------------------------------------ MIPS bits

MEM_LOAD_GPR = {0x20, 0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x37, 0x1A, 0x1B, 0x1E}
MEM_STORE_GPR = {0x28, 0x29, 0x2A, 0x2B, 0x2C, 0x2D, 0x2E, 0x3F, 0x1F}
MEM_COP = {0x31, 0x39, 0x36, 0x3E}
MEM_OTHER = {0x2F, 0x33}
MEM_OPS = MEM_LOAD_GPR | MEM_STORE_GPR | MEM_COP | MEM_OTHER
ALU_IMM = {0x08, 0x09, 0x0A, 0x0B, 0x0C, 0x0D, 0x0E, 0x18, 0x19}
BRANCH_OPS = {0x04, 0x05, 0x06, 0x07, 0x14, 0x15, 0x16, 0x17}
CALL_CLOBBER = set(range(1, 16)) | {24, 25, 31}
GP = 28


def sext16(v):
    return v - 0x10000 if v & 0x8000 else v


def fields(w):
    return w >> 26, (w >> 21) & 31, (w >> 16) & 31, (w >> 11) & 31, w & 0xFFFF


def is_branch(w):
    op, rs, rt = w >> 26, (w >> 21) & 31, (w >> 16) & 31
    if op in BRANCH_OPS:
        return True
    if op == 1 and rt in (0, 1, 2, 3, 0x10, 0x11, 0x12, 0x13):
        return True
    if op in (0x10, 0x11, 0x12) and rs == 8:
        return True
    return False


def branch_target(w, pc):
    return (pc + 4 + (sext16(w & 0xFFFF) << 2)) & 0xFFFFFFFF


def jump_target(w, pc):
    return ((pc + 4) & 0xF0000000) | ((w & 0x3FFFFFF) << 2)


def loose_mask(w):
    """Relocation- and layout-insensitive shape of an instruction, used for alignment."""
    op, rs = w >> 26, (w >> 21) & 31
    if op in (2, 3):
        return w & 0xFC000000
    if op == 0x0F:
        return w & 0xFFFF0000
    if is_branch(w):
        return w & 0xFFFF0000
    if op in ALU_IMM or op in MEM_OPS:
        if rs == 29 or (rs == 0 and op in (0x09, 0x0D, 0x19)):
            return w
        return w & 0xFFFF0000
    return w


def dest_gpr(w):
    op, rs, rt, rd, imm = fields(w)
    fn = w & 63
    if op == 0:
        if fn in (8, 0x0C, 0x0D, 0x0F):
            return ()
        if fn in (0x18, 0x19, 0x1A, 0x1B):          # mult/div write rd on the R5900 when rd != 0
            return (rd,) if rd else ()
        return (rd,)
    if op == 2:
        return ()
    if op == 3:
        return (31,)
    if op in ALU_IMM or op == 0x0F or op in MEM_LOAD_GPR:
        return (rt,)
    if op == 0x1C:
        return (rd,)
    if op in (0x10, 0x11, 0x12) and rs in (0, 1, 2):
        return (rt,)
    if op == 1 and rt in (0x10, 0x11, 0x12, 0x13):
        return (31,)
    return ()


def is_uncond_transfer(w):
    op, rs, rt = w >> 26, (w >> 21) & 31, (w >> 16) & 31
    return op == 2 or (op == 0 and (w & 63) == 8) or (op == 4 and rs == 0 and rt == 0)


def is_call(w):
    op = w >> 26
    return op == 3 or (op == 0 and (w & 63) == 9)


# ------------------------------------------------------------------------------------- code alignment

def lis(pairs):
    tails, tail_idx, prev = [], [], [-1] * len(pairs)
    for i, (_, b) in enumerate(pairs):
        j = bisect.bisect_left(tails, b)
        if j == len(tails):
            tails.append(b); tail_idx.append(i)
        else:
            tails[j] = b; tail_idx[j] = i
        prev[i] = tail_idx[j - 1] if j else -1
    out, k = [], tail_idx[-1] if tail_idx else -1
    while k >= 0:
        out.append(pairs[k]); k = prev[k]
    return out[::-1]


def align_words(uw, pw, K=12):
    um = [loose_mask(w) for w in uw]
    pm = [loose_mask(w) for w in pw]

    def grams(m):
        cnt, pos = collections.Counter(), {}
        for i in range(len(m) - K + 1):
            g = tuple(m[i:i + K]); cnt[g] += 1; pos[g] = i
        return cnt, pos
    uc, up = grams(um); pc, pp = grams(pm)
    anchors = sorted((up[g], pp[g]) for g, c in uc.items() if c == 1 and pc.get(g) == 1)
    chain = lis(anchors)
    nu, np_ = len(uw), len(pw)
    u2p, src = [-1] * nu, [0] * nu
    blocks = []
    for a, b in chain:
        if blocks and blocks[-1][2] == b - a and a <= blocks[-1][1]:
            blocks[-1][1] = max(blocks[-1][1], a + K)
        else:
            blocks.append([a, a + K, b - a])
    clean = []
    for a0, a1, d in blocks:
        if clean:
            pa0, pa1, pd = clean[-1]
            a0 = max(a0, pa1, pa1 + pd - d)
        if a1 > a0:
            clean.append([a0, a1, d])
    for a0, a1, d in clean:
        for i in range(a0, a1):
            u2p[i] = i + d; src[i] = 3
    edges = [(0, 0)] + [(a1, a1 + d) for a0, a1, d in clean]
    starts = [(a0, a0 + d) for a0, a1, d in clean] + [(nu, np_)]
    diff_words = 0
    for (ue, pe), (us, ps) in zip(edges, starts):
        if us <= ue or ps <= pe or (us - ue) * (ps - pe) > 60_000_000:
            continue
        sm = difflib.SequenceMatcher(None, um[ue:us], pm[pe:ps], autojunk=False)
        for i, j, n in sm.get_matching_blocks():
            for k in range(n):
                u2p[ue + i + k] = pe + j + k
                src[ue + i + k] = 2 if n >= 4 else 1
                diff_words += 1
    return dict(u2p=u2p, src=src, anchors=len(anchors), chain=len(chain), blocks=len(clean), diff_words=diff_words)


def align_code(U, P):
    """Align ELF .text with ELF .text and overlay with overlay (two independent alignments)."""
    t = align_words(U.words[:U.n_text], P.words[:P.n_text])
    o = align_words(U.words[U.n_text:], P.words[P.n_text:])
    u2p = t['u2p'] + [(j + P.n_text) if j >= 0 else -1 for j in o['u2p']]
    src = t['src'] + o['src']
    p2u = [-1] * P.n
    for i, j in enumerate(u2p):
        if j >= 0:
            p2u[j] = i
    return dict(u2p=u2p, p2u=p2u, src=src, text=t, overlay=o)


# --------------------------------------------------------------------------------- function discovery

def hexrays_starts(path=None):
    starts = set()
    if path is None:
        return starts
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            for line in f:
                if line.startswith('//----- ('):
                    starts.add(int(line[9:17], 16))
    except OSError:
        pass
    return starts


def call_targets(img):
    out = set()
    for i, w in enumerate(img.words):
        if w >> 26 == 3:
            t = jump_target(w, img.addr(i))
            if img.in_code_space(t):
                out.add(t)
    return out


def prologue_starts(img, lo_idx, hi_idx):
    """addiu sp,sp,-N right after a jr ra + delay slot (or after nop padding): overlay function starts."""
    out = set()
    for i in range(max(lo_idx, 2), hi_idx):
        w = img.words[i]
        if w >> 16 == 0x27BD and w & 0x8000:
            k = i - 1
            while k > lo_idx and img.words[k] == 0:
                k -= 1
            if img.words[k - 1] == 0x03E00008 or img.words[k] == 0x03E00008 or (img.words[k] >> 26) == 2:
                out.add(img.addr(i))
    return out


# ----------------------------------------------------------------------------------- address forming

CALLEE_SAVED = {16, 17, 18, 19, 20, 21, 22, 23, 30}


def _persistent_regs(img, a, b):
    """Callee-saved registers whose only writes in [a, b) build one address: lui r, then optional addiu/ori r, r."""
    writes = collections.defaultdict(list)
    for i in range(a, b):
        w = img.words[i]
        if w >> 26 in MEM_LOAD_GPR and ((w >> 21) & 31) == 29:
            continue                                    # epilogue restore from the stack frame
        for r in dest_gpr(w):
            if r in CALLEE_SAVED:
                writes[r].append(w)
    out = set()
    for r, ws in writes.items():
        if 1 <= len(ws) <= 2 and ws[0] >> 26 == 0x0F:
            if len(ws) == 1 or (ws[1] >> 26 in (0x09, 0x0D) and ((ws[1] >> 21) & 31) == r):
                out.add(r)
    return out


def formed_addresses(img, starts):
    """For every code-space index, the absolute address the instruction forms (or None).

    kind: 'g' gp-relative, 'h' lui+lo tracked, 'x' lui/gp base plus a register index (arrays),
          upper-case when the base register was set before a branch target (merged paths, lower weight).
    hisrc: index of the lui that produced the hi half (None for gp-relative).
    """
    btargets = set()
    for i, w in enumerate(img.words):
        if is_branch(w):
            k = img.idx(branch_target(w, img.addr(i)))
            if k is not None:
                btargets.add(k)
    start_idx = sorted(({img.idx(s) for s in starts} - {None}) | {0, img.n_text, img.n})
    formed = [None] * img.n
    kind = [None] * img.n
    hisrc = [None] * img.n
    gp = img.gp
    for fa, fb in zip(start_idx, start_idx[1:]):
        persist = _persistent_regs(img, fa, fb)
        state = {}                                      # reg -> (tag 'v'|'x', value, lui index)
        tainted = set()
        clear_after = call_after = False

        def clear(keep_callee):
            for r in list(state):
                if not (r in persist or (keep_callee and False)):
                    del state[r]
            tainted.intersection_update(state)
        for i in range(fa, fb):
            w = img.words[i]
            if i in btargets:
                tainted = set(state) - persist
            op, rs, rt, rd, imm = fields(w)
            s = sext16(imm)
            f = None
            base = state.get(rs)
            tk = rs in tainted
            if op in MEM_OPS:
                if rs == GP:
                    f = ((gp + s) & 0xFFFFFFFF, 'g', None)
                elif base:
                    f = ((base[1] + s) & 0xFFFFFFFF, ('h' if base[0] == 'v' else 'x'), base[2])
            elif op in (0x09, 0x19):
                if rs == GP:
                    f = ((gp + s) & 0xFFFFFFFF, 'g', None)
                elif base and rs != 29:
                    f = ((base[1] + s) & 0xFFFFFFFF, ('h' if base[0] == 'v' else 'x'), base[2])
            elif op == 0x0D and base and base[0] == 'v' and (base[1] & 0xFFFF) == 0:
                f = (base[1] | imm, 'h', base[2])
            if f:
                formed[i] = f[0]
                kind[i] = f[1].upper() if (tk and f[1] != 'g') else f[1]
                hisrc[i] = f[2]
            new = None
            if op == 0x0F and rt:
                new = (rt, ('v', (imm << 16) & 0xFFFFFFFF, i), False)
            elif op in (0x09, 0x19) and rt and f:
                new = (rt, ((base[0] if base else 'v'), f[0], f[2]), tk)
            elif op == 0x0D and rt and f:
                new = (rt, ('v', f[0], f[2]), tk)
            elif op == 0 and (w & 63) in (0x21, 0x2D, 0x25) and rd:
                x, y = state.get(rs), state.get(rt)
                if rt == 0 and rs != GP:
                    new = (rd, x, tk) if x else None
                elif rs == 0 and rt != GP:
                    new = (rd, y, rt in tainted) if y else None
                elif GP in (rs, rt):
                    other = rt if rs == GP else rs
                    if other not in state:
                        new = (rd, ('x', gp, None), False)
                elif x and not y and (w & 63) != 0x25:
                    new = (rd, ('x', x[1], x[2]), tk)
                elif y and not x and (w & 63) != 0x25:
                    new = (rd, ('x', y[1], y[2]), rt in tainted)
            for r in dest_gpr(w):
                state.pop(r, None); tainted.discard(r)
            if new and new[1]:
                state[new[0]] = new[1]
                if new[2]:
                    tainted.add(new[0])
            if clear_after:
                clear(False); clear_after = False
            if call_after:
                for r in CALL_CLOBBER:
                    state.pop(r, None); tainted.discard(r)
                call_after = False
            if is_uncond_transfer(w):
                clear_after = True
            elif is_call(w):
                call_after = True
    return formed, kind, hisrc


# ---------------------------------------------------------------------------------- data alignment

INIT_SECTIONS = ('.data', '.rodata', '.lit4', '.sdata')


def align_initialised(U, P, name):
    su, sp = U.sections[name], P.sections[name]

    def masked(img, s):
        ws = struct.unpack_from('<%dI' % (s['size'] // 4), img.blob, s['off'])
        return [('P' if img.in_image(v) else v) for v in ws]
    mu, mp = masked(U, su), masked(P, sp)
    sm = difflib.SequenceMatcher(None, mu, mp, autojunk=False)
    blocks = []
    for i, j, n in sm.get_matching_blocks():
        if n:
            informative = sum(1 for x in mu[i:i + n] if x not in (0, 'P'))
            blocks.append(dict(u=su['addr'] + 4 * i, p=sp['addr'] + 4 * j, n=4 * n, informative=informative, section=name))
    return blocks


# ------------------------------------------------------------------------------------ the mapper

# Replay input records (verified from 0x1D8330/0x1D8388/0x1D8470 and 0x12A940): two records, each a 2-byte
# array and a 4-byte array of one entry per frame for 150 s, then two header words.  USA sizes them for 60 Hz
# (9000 entries, stride 54008 = 0xD2F8), PAL for 50 Hz (7500 entries, stride 45008 = 0xAFD0).
REPLAY = dict(usa_base=0x301810, pal_base=0x302C90, usa_stride=54008, pal_stride=45008, count=2,
              usa_fields=((0, 0x4650, 2), (0x4650, 0xD2F0, 4), (0xD2F0, 0xD2F8, 1)),
              pal_fields=((0, 0x3A98, 2), (0x3A98, 0xAFC8, 4), (0xAFC8, 0xAFD0, 1)))


def in_replay(u):
    return REPLAY['usa_base'] <= u < REPLAY['usa_base'] + REPLAY['count'] * REPLAY['usa_stride']


def map_replay(u):
    r = REPLAY
    k, off = divmod(u - r['usa_base'], r['usa_stride'])
    for (a, b, sz), (pa, pb, psz) in zip(r['usa_fields'], r['pal_fields']):
        if a <= off < b:
            q = off - a
            if pa + q >= pb:
                return None, 'none', 'replay record %d entry %d does not exist in PAL (7500-frame buffer)' % (k, q // sz)
            return r['pal_base'] + k * r['pal_stride'] + pa + q, 'high', 'replay record %d field at +%X -> +%X' % (k, off, pa + q)
    return None, 'none', 'replay record: unknown field'


DATA_WEIGHT = {'h': 3, 'g': 3, 'x': 2, 'H': 1, 'X': 1, 'ptr': 2}


class Mapper:
    def __init__(self, U, P, data):
        self.U, self.P = U, P
        self.__dict__.update(data)
        self._build_indexes()

    def _build_indexes(self):
        self.fn_starts = sorted(self.functions)
        self.seg_u = [s['u0'] for s in self.data_segments]
        self.cblocks_u = [b['u'] for b in self.content_blocks]

    # ---- code
    def _pair_conf(self, i):
        if self.u2p[i] < 0:
            return None
        eq = self.equiv[i]
        good = eq in ('eq', 'reloc')
        fn = self.function_of(self.U.addr(i))
        if good and fn and fn['class'] in ('identical', 'same-shape'):
            return 'exact'
        if fn and fn['class'] == 'same-shape':
            return 'high'                                   # location certain (1:1 layout), the word itself differs
        if good and self.src[i] in (2, 3, 4):
            return 'high'
        return 'medium'

    def map_code(self, usa_addr):
        U, P = self.U, self.P
        vu, pv = U.sections['.vutext'], P.sections['.vutext']
        if vu['addr'] <= usa_addr < vu['addr'] + vu['size']:
            return usa_addr - vu['addr'] + pv['addr'], 'exact'
        i = U.idx(usa_addr)
        if i is None:
            return None, 'none'
        off = usa_addr & 3
        c = self._pair_conf(i)
        e = self.entries.get(usa_addr)
        if e and (self.u2p[i] < 0 or P.addr(self.u2p[i]) != e[0]):
            # call sites / code pointers disagree with the instruction alignment: the entry wins for entries
            return e[0], ('high' if e[1] >= 6 else 'medium')
        if c:
            return P.addr(self.u2p[i]) + off, c
        fn = self.function_of(usa_addr)
        lo = U.idx(fn['start']) if fn else i - 256
        hi = U.idx(fn['end'] - 4) + 1 if fn else i + 256
        a = i - 1
        while a >= lo and self.u2p[a] < 0:
            a -= 1
        b = i + 1
        while b < hi and b < U.n and self.u2p[b] < 0:
            b += 1
        da = self.u2p[a] - a if a >= lo and self.u2p[a] >= 0 else None
        db = self.u2p[b] - b if b < hi and b < U.n and self.u2p[b] >= 0 else None
        if da is not None and da == db:
            return P.addr(i + da) + off, 'low'
        return None, 'none'

    def map_range(self, usa_addr, length):
        """Map a byte range; for code, says whether PAL keeps the same word layout inside it.

        Returns dict(pal, pal_length, confidence, layout) where layout is 'same' (every word mapped with one
        delta), 'changed' (PAL inserts/drops words inside the range) or 'data'.
        """
        U, P = self.U, self.P
        region = self.region(usa_addr)
        if region in ('elf-code', 'overlay-code'):
            a, b = U.idx(usa_addr & ~3), U.idx((usa_addr + length - 1) & ~3)
            p0, c0 = self.map_code(usa_addr)
            p1, c1 = self.map_code(U.addr(b))
            js = [self.u2p[i] for i in range(a, b + 1)]
            same = all(j >= 0 for j in js) and len({j - i for i, j in zip(range(a, b + 1), js)}) == 1
            order = ['exact', 'high', 'medium', 'low', 'ambiguous', 'none']
            conf = max((c0, c1), key=order.index)
            plen = (p1 + 4 - p0) if (p0 is not None and p1 is not None) else None
            return dict(pal=p0, pal_length=plen, confidence=conf, layout='same' if same else 'changed')
        p0, c0 = self.map_data(usa_addr)
        p1, c1 = self.map_data(usa_addr + length - 1)
        plen = (p1 + 1 - p0) if (p0 is not None and p1 is not None) else None
        order = ['exact', 'high', 'medium', 'low', 'ambiguous', 'none']
        return dict(pal=p0, pal_length=plen, confidence=max((c0, c1), key=order.index),
                    layout='same' if plen == length else 'changed')

    def map_gp_offset(self, usa_offset):
        """A gp-relative immediate in USA code -> the PAL immediate reaching the mapped variable."""
        u = (self.U.gp + usa_offset) & 0xFFFFFFFF
        p, c = self.map_data(u)
        if p is None:
            return None, 'none'
        off = p - self.P.gp
        return (off, c) if -0x8000 <= off < 0x8000 else (None, 'none')

    def function_of(self, usa_addr):
        k = bisect.bisect_right(self.fn_starts, usa_addr) - 1
        if k < 0:
            return None
        f = self.functions[self.fn_starts[k]]
        return f if usa_addr < f['end'] else None

    # ---- data
    def map_data(self, usa_addr):
        r = self._data(usa_addr)
        return r['pal'], r['confidence']

    def _data(self, u):
        U, P = self.U, self.P
        sec = U.section_of(u)
        out = dict(usa=u, section=sec, pal=None, confidence='none')
        if sec is None or sec == '.text':
            return out
        if sec in ('.vutext', '.text_nop', '.ctors', '.dtors', '.reginfo', '.eh_frame'):
            d = P.sections[sec]['addr'] - U.sections[sec]['addr']
            out.update(pal=u + d, confidence='exact', delta=d, how='section identical in both ELFs')
            return out
        if sec == 'DBZP.BIN':
            return self._overlay_data(u, out)
        if u in self.data_pairs:
            p, n = self.data_pairs[u]
            out.update(pal=p, confidence='exact', delta=p - u, how='evidence point (weight %d)' % n)
            return out
        if getattr(self, 'replay', True) and in_replay(u):
            p, c, how = map_replay(u)
            out.update(pal=p, confidence=c, delta=(p - u) if p else None, how=how)
            return out
        content_guess = None
        k = bisect.bisect_right(self.cblocks_u, u) - 1
        if k >= 0:
            b = self.content_blocks[k]
            if u < b['u'] + b['n'] and b['informative'] >= 2:
                d = b['p'] - b['u']
                if not b.get('ev_disagree'):
                    out.update(pal=u + d, confidence='exact', delta=d, how='content block %X+%X' % (b['u'], b['n']))
                    return out
                content_guess = (u + d, b)
        k = bisect.bisect_right(self.seg_u, u) - 1
        prev = self.data_segments[k] if k >= 0 else None
        nxt = self.data_segments[k + 1] if k + 1 < len(self.data_segments) else None
        if prev and prev['section'] != sec:
            prev = None
        if nxt and nxt['section'] != sec:
            nxt = None
        if prev and u <= prev['u1'] and prev['n'] >= 2:
            out.update(pal=u + prev['delta'], confidence='high', delta=prev['delta'],
                       how='inside evidence run %X-%X (%d points)' % (prev['u0'], prev['u1'], prev['n']))
            if content_guess and content_guess[0] != u + prev['delta']:
                out['confidence'] = 'ambiguous'; out['candidates'] = [u + prev['delta'], content_guess[0]]
            return out
        if content_guess:
            out.update(pal=content_guess[0], confidence='medium', delta=content_guess[0] - u,
                       how='content block contradicted elsewhere by %d evidence points' % content_guess[1]['ev_disagree'])
            return out
        cands = [s['delta'] for s in (prev, nxt) if s]
        if not cands:
            if sec == 'pad':
                return out
            d = P.sections[sec]['addr'] - U.sections[sec]['addr']
            out.update(pal=u + d, confidence='low', delta=d, how='section base delta only')
            return out
        if len(set(cands)) == 1:
            out.update(pal=u + cands[0], confidence='medium', delta=cands[0],
                       how='between evidence with equal delta %+X' % cands[0])
            return out
        # different deltas: prefer the object that starts before the address (field access)
        out.update(pal=u + cands[0], confidence='ambiguous', delta=cands[0], candidates=[u + c for c in cands],
                   how='previous run %X..%X delta %+X, next run from %X delta %+X'
                       % (prev['u0'], prev['u1'], prev['delta'], nxt['u0'], nxt['delta']))
        return out

    def _overlay_data(self, u, out):
        """Overlay data: evidence point > unique-anchor word > evidence run > diff-matched word > neighbours."""
        U, P = self.U, self.P
        if u in self.data_pairs:
            p, n = self.data_pairs[u]
            out.update(pal=p, confidence='exact', delta=p - u, how='evidence point (weight %d)' % n)
            return out
        i = U.idx(u & ~3)
        j = self.u2p[i]
        if j >= 0 and self.src[i] >= 3 and U.words[i] != 0:
            out.update(pal=P.addr(j) + (u & 3), confidence='exact', delta=P.addr(j) - U.addr(i),
                       how='overlay unique-anchor word alignment')
            return out
        k = bisect.bisect_right(self.seg_u, u) - 1
        prev = self.data_segments[k] if k >= 0 and self.data_segments[k]['section'] == 'DBZP.BIN' else None
        nxt = self.data_segments[k + 1] if k + 1 < len(self.data_segments) and self.data_segments[k + 1]['section'] == 'DBZP.BIN' else None
        if prev and u <= prev['u1'] and prev['n'] >= 2:
            out.update(pal=u + prev['delta'], confidence='high', delta=prev['delta'],
                       how='inside overlay evidence run %X-%X (%d points)' % (prev['u0'], prev['u1'], prev['n']))
            return out
        if j >= 0 and self.src[i] >= 2:
            out.update(pal=P.addr(j) + (u & 3), confidence='high', delta=P.addr(j) - U.addr(i),
                       how='overlay diff word alignment')
            return out
        cands = sorted({s['delta'] for s in (prev, nxt) if s})
        if j >= 0:
            cands = sorted(set(cands) | {P.addr(j) - U.addr(i)})
        if len(cands) == 1:
            out.update(pal=u + cands[0], confidence='medium', delta=cands[0], how='overlay neighbours agree')
        elif cands:
            out.update(pal=u + cands[0], confidence='ambiguous', delta=cands[0], candidates=[u + c for c in cands],
                       how='overlay neighbours disagree')
        return out

    def region(self, usa_addr):
        U = self.U
        if U.in_text(usa_addr):
            return 'elf-code'
        if U.in_overlay(usa_addr):
            i = U.idx(usa_addr)
            return 'overlay-code' if i - U.n_text < self.overlay_code_words else 'overlay-data'
        s = U.section_of(usa_addr)
        if s == '.vutext':
            return 'vu-code'
        if s:
            return 'elf-data'
        return 'outside'

    def map_addr(self, usa_addr):
        r = self.region(usa_addr)
        if r in ('elf-code', 'overlay-code', 'vu-code'):
            p, c = self.map_code(usa_addr)
        else:
            p, c = self.map_data(usa_addr)
        return p, c, r

    def explain(self, usa_addr):
        U = self.U
        i = U.idx(usa_addr)
        if i is not None and self.region(usa_addr) != 'overlay-data':
            p, c = self.map_code(usa_addr)
            return dict(usa=usa_addr, pal=p, confidence=c, src=self.src[i], equiv=self.equiv[i],
                        usa_word=U.words[i], pal_word=(self.P.words[self.u2p[i]] if self.u2p[i] >= 0 else None),
                        function=self.function_of(usa_addr))
        return self._data(usa_addr)

    def export_json(self, path):
        U, P = self.U, self.P
        runs, cur = [], None
        for i, j in enumerate(self.u2p):
            d = (P.addr(j) - U.addr(i)) if j >= 0 else None
            if cur and d is not None and d == cur[2] and i == cur[1] + 1 and (i == U.n_text) == False:
                cur[1] = i
            elif d is not None:
                cur = [i, i, d]; runs.append(cur)
        doc = dict(
            note='USA SLUS-21678 -> PAL SLES-54945 address map; see research/address-map.md',
            usa=dict(elf=str(U.path), sha256=U.sha256, overlay_sha256=U.overlay_sha256, gp=U.gp,
                     overlay_base=U.ov_base, end=U.end,
                     sections={k: [v['addr'], v['size']] for k, v in U.sections.items()}),
            pal=dict(elf=str(P.path), sha256=P.sha256, overlay_sha256=P.overlay_sha256, gp=P.gp,
                     overlay_base=P.ov_base, end=P.end,
                     sections={k: [v['addr'], v['size']] for k, v in P.sections.items()}),
            code_runs=[dict(usa_start=U.addr(a), usa_end=U.addr(b) + 4, delta=d) for a, b, d in runs],
            functions=[v for k, v in sorted(self.functions.items())],
            data_segments=self.data_segments,
            content_blocks=self.content_blocks,
            data_evidence={('%X' % k): [v[0], v[1]] for k, v in sorted(self.data_pairs.items())},
            data_conflicts=self.data_conflicts,
            stats=self.stats,
        )
        Path(path).write_text(json.dumps(doc, indent=0, default=str))


# --------------------------------------------------------------------------------------- building

def pair_substitutions(U, P, u2p, src):
    """Where USA and PAL both have k unmatched words between the same matched neighbours, pair them
    positionally (a changed constant or operand in place): src 5."""
    n = 0
    i = 0
    N = len(u2p)
    while i < N:
        if u2p[i] >= 0:
            i += 1
            continue
        a = i
        while i < N and u2p[i] < 0:
            i += 1
        b = i                                             # [a, b) unmatched
        if a == 0 or b >= N or u2p[a - 1] < 0 or u2p[b] < 0:
            continue
        if (a - 1 < U.n_text) != (b < U.n_text):
            continue
        ja, jb = u2p[a - 1] + 1, u2p[b]
        if jb - ja == b - a and b - a <= 64:
            for k in range(b - a):
                u2p[a + k] = ja + k; src[a + k] = 5
                n += 1
    return n


def refine_entries(U, P, u2p, src, dpre, log, hexrays=None):
    """Vote PAL entry points for USA code addresses from call sites and code-pointer words, then realign
    every stretch between two consecutive accepted entries whose current mapping contradicts them."""
    votes = collections.defaultdict(collections.Counter)
    known_entries = hexrays_starts(hexrays) | call_targets(U)
    for i, j in enumerate(u2p):
        if j < 0:
            continue
        uw, pw = U.words[i], P.words[j]
        if uw >> 26 == 2 and pw >> 26 == 2:           # tail calls into known function entries
            ut, pt = jump_target(uw, U.addr(i)), jump_target(pw, P.addr(j))
            if ut in known_entries and P.in_code_space(pt) and U.in_text(ut) == P.in_text(pt):
                votes[ut][pt] += (3, 1, 2, 3, 3, 1)[src[i]]
            continue
        if uw >> 26 == 3 and pw >> 26 == 3:
            ut, pt = jump_target(uw, U.addr(i)), jump_target(pw, P.addr(j))
            if U.in_code_space(ut) and P.in_code_space(pt) and U.in_text(ut) == P.in_text(pt):
                votes[ut][pt] += (3, 1, 2, 3, 3, 1)[src[i]]
    ptr_votes = 0
    ptr_only = collections.defaultdict(collections.Counter)
    for name in INIT_SECTIONS:
        s = U.sections[name]
        for o in range(0, s['size'] - 3, 4):
            ua = s['addr'] + o
            uv = struct.unpack_from('<I', U.blob, s['off'] + o)[0]
            if not U.in_code_space(uv) or uv & 3:
                continue
            pa = dpre(ua)
            pv = P.word(pa) if pa is not None else None
            if pv is not None and P.in_code_space(pv) and U.in_text(uv) == P.in_text(pv):
                ptr_votes += 1
                ptr_only[uv][pv] += 2
    # a code-pointer word may only confirm the current map, or fill a hole the alignment left
    for t, c in ptr_only.items():
        i = U.idx(t)
        cur = P.addr(u2p[i]) if u2p[i] >= 0 else None
        for b, w in c.items():
            if b == cur or t in votes or cur is None or src[i] < 2:
                if b == t and cur is not None and cur != t:
                    continue                            # an equal constant, not a relocated pointer
                votes[t][b] += w
    accepted = []
    for t, c in votes.items():
        (b, w), *rest = c.most_common()
        tot = sum(c.values())
        if w >= 2 and w * 3 >= tot * 2:
            accepted.append((t, b, w, tot))
    accepted.sort()
    chain = lis([(t, b) for t, b, w, tot in accepted])
    keep = set(chain)
    acc = {t: (b, w, tot) for t, b, w, tot in accepted if (t, b) in keep}
    rejected = [(t, b, w, tot) for t, b, w, tot in accepted if (t, b) not in keep]
    # realign inconsistent stretches between consecutive entries (within one region)
    pts = sorted(acc)
    realigned = 0
    stretches = 0
    log_rows = []
    for k in range(len(pts)):
        a = pts[k]
        b = pts[k + 1] if k + 1 < len(pts) else None
        ia = U.idx(a); ja = P.idx(acc[a][0])
        if b is None or U.in_text(a) != U.in_text(b):
            ib = U.n_text if U.in_text(a) else U.n
            jb = P.n_text if U.in_text(a) else P.n
        else:
            ib = U.idx(b); jb = P.idx(acc[b][0])
        ok = u2p[ia] == ja and all(u2p[i] < 0 or ja <= u2p[i] < jb for i in range(ia, ib))
        if ok:
            continue
        if (ib - ia) * (jb - ja) > 4_000_000:
            continue
        old_in = sum(1 for i in range(ia, ib) if ja <= u2p[i] < jb)
        um = [loose_mask(w) for w in U.words[ia:ib]]
        pm = [loose_mask(w) for w in P.words[ja:jb]]
        sm = difflib.SequenceMatcher(None, um[1:], pm[1:], autojunk=False)
        blocks = [(x, y, n) for x, y, n in sm.get_matching_blocks() if n]
        new_in = 1 + sum(n for x, y, n in blocks)
        log_rows.append((U.addr(ia), U.addr(ib), P.addr(ja), P.addr(jb), old_in, new_in))
        if new_in < old_in:
            continue                                    # keep the body alignment; the entry stays in `acc`
        stretches += 1
        for i in range(ia, ib):
            u2p[i] = -1; src[i] = 0
        u2p[ia] = ja; src[ia] = 4
        for x, y, n in blocks:
            for q in range(n):
                u2p[ia + 1 + x + q] = ja + 1 + y + q
                src[ia + 1 + x + q] = 2 if n >= 4 else 1
                realigned += 1
    # drop any PAL word claimed twice (keep the stronger source)
    owner = {}
    for i, j in enumerate(u2p):
        if j < 0:
            continue
        if j in owner:
            o = owner[j]
            loser = i if src[o] >= src[i] else o
            u2p[loser] = -1; src[loser] = 0
            owner[j] = o if loser == i else i
        else:
            owner[j] = i
    log('entry votes: %d USA targets voted (%d from data pointer words), %d accepted, %d dropped as non-monotone; '
        '%d stretches realigned (%d words matched)' % (len(votes), ptr_votes, len(acc), len(rejected), stretches, realigned))
    return acc, dict(voted=len(votes), accepted=len(acc), rejected=rejected[:50], stretches=stretches, stretch_rows=log_rows,
                     realigned_words=realigned, votes={t: dict(c) for t, c in votes.items() if len(c) > 1})


def classify_pair(U, P, i, j, cmap):
    uw, pw = U.words[i], P.words[j]
    if uw == pw:
        return 'eq'
    uo, po = uw >> 26, pw >> 26
    if uo != po:
        return 'diff'
    if uo in (2, 3):
        return 'reloc' if cmap(jump_target(uw, U.addr(i))) == jump_target(pw, P.addr(j)) else 'reloc?'
    if is_branch(uw) and (uw & 0xFFFF0000) == (pw & 0xFFFF0000):
        return 'reloc' if cmap(branch_target(uw, U.addr(i))) == branch_target(pw, P.addr(j)) else 'reloc?'
    if (uw & 0xFFFF0000) == (pw & 0xFFFF0000) and (uo == 0x0F or uo in ALU_IMM or uo in MEM_OPS):
        return 'imm'
    return 'diff'


def build(U, P, hexrays=None, verbose=True, keep_equal_pairs=False, replay=True):
    """keep_equal_pairs: an address formed identically by aligned code (or an equal pointer word) is evidence when
    its ELF data section starts at the same address in both executables (the Japanese executable keeps .lit4,
    .sdata, .sbss, .scommon and .bss where USA has them; the European one moves all data, so the default drops
    them). replay: map the replay records with the European 50 Hz record rule (REPLAY); off for an executable
    that keeps the USA 60 Hz records."""
    log = print if verbose else (lambda *a, **k: None)
    log('USA overlay base %X end %X; PAL overlay base %X end %X' % (U.ov_base, U.end, P.ov_base, P.end))

    def same_base(a):
        sec = U.section_of(a)
        return (sec not in (None, 'pad', 'DBZP.BIN', '.text') and sec in P.sections
                and P.sections[sec]['addr'] == U.sections[sec]['addr'])
    al = align_code(U, P)
    ov_code_u = max(i for i in range(U.n_text, U.n) if U.words[i] == 0x03E00008) + 2
    ov_code_p = max(i for i in range(P.n_text, P.n) if P.words[i] == 0x03E00008) + 2
    u2p, p2u, src = al['u2p'], al['p2u'], al['src']
    for name, a, n in (('text', al['text'], U.n_text), ('overlay', al['overlay'], U.n - U.n_text)):
        mt = sum(1 for x in a['u2p'] if x >= 0)
        log('%s: anchors %d chain %d blocks %d; matched %d/%d USA words (%.2f%%), diff-filled %d (%d in blocks <4)'
            % (name, a['anchors'], a['chain'], a['blocks'], mt, n, 100 * mt / n, a['diff_words'],
               sum(1 for x in a['src'] if x == 1)))

    def cmap(a):
        i = U.idx(a)
        if i is None:
            return None
        j = u2p[i]
        return P.addr(j) if j >= 0 else None

    content_blocks = []
    for name in INIT_SECTIONS:
        bl = align_initialised(U, P, name)
        cov = sum(b['n'] for b in bl)
        log('content %-8s blocks %4d cover %6d / %6d bytes (%.1f%%)' % (name, len(bl), cov, U.sections[name]['size'],
                                                                         100 * cov / U.sections[name]['size']))
        content_blocks += bl
    content_blocks.sort(key=lambda b: b['u'])
    cbu = [b['u'] for b in content_blocks]

    def dpre(a):
        if U.in_overlay(a):
            return cmap(a & ~3)
        k = bisect.bisect_right(cbu, a) - 1
        if k >= 0:
            b = content_blocks[k]
            if a < b['u'] + b['n']:
                return a + b['p'] - b['u']
        return None

    entries, estats = refine_entries(U, P, u2p, src, dpre, log, hexrays)
    nsub = pair_substitutions(U, P, u2p, src)
    log('in-place substitutions paired: %d words' % nsub)
    p2u = [-1] * P.n
    for i, j in enumerate(u2p):
        if j >= 0:
            p2u[j] = i
    log('after entry refinement: text matched %d/%d, overlay matched %d/%d'
        % (sum(1 for x in u2p[:U.n_text] if x >= 0), U.n_text, sum(1 for x in u2p[U.n_text:] if x >= 0), U.n - U.n_text))

    # functions
    hx = hexrays_starts(hexrays)
    ucalls, pcalls = call_targets(U), call_targets(P)
    upro = prologue_starts(U, U.n_text, ov_code_u)
    ppro = prologue_starts(P, P.n_text, ov_code_p)
    ustarts = set(hx) | {a for a in ucalls if U.in_text(a)}
    ustarts |= {a for a in ucalls | upro if U.in_overlay(a) and U.idx(a) < ov_code_u}
    ustarts = sorted(ustarts)
    log('USA function starts: %d Hex-Rays headers, %d jal targets (%d not in Hex-Rays), overlay %d; total %d'
        % (len(hx), len(ucalls), len({a for a in ucalls if U.in_text(a)} - hx),
           sum(1 for a in ustarts if U.in_overlay(a)), len(ustarts)))
    mapped_starts = {cmap(s) for s in ustarts} - {None}
    mapped_starts |= {entries[a][0] for a in ustarts if a in entries}
    pstarts = sorted(pcalls | ppro | mapped_starts)
    log('PAL function starts: %d jal targets + %d overlay prologues + %d mapped USA starts = %d; PAL jal targets '
        'not hit by any mapped USA start: %d' % (len(pcalls), len(ppro), len(mapped_starts), len(pstarts),
                                                  len(pcalls - mapped_starts)))

    uf, uk, uh = formed_addresses(U, ustarts)
    pf, pk, ph = formed_addresses(P, pstarts)
    pairs = collections.defaultdict(collections.Counter)
    kinds = collections.Counter()
    outside = collections.Counter()
    for i, j in enumerate(u2p):
        if j < 0 or uf[i] is None or pf[j] is None:
            continue
        a, b = uf[i], pf[j]
        if not (U.in_image(a) and P.in_image(b)):
            outside[(a, b)] += 1
            continue
        if src[i] == 5:
            kinds['positional-skipped'] += 1           # in-place substituted words prove no address pair
            continue
        if a == b and not U.in_text(a) and not (keep_equal_pairs and same_base(a)):
            kinds['equal-constant-dropped'] += 1       # data never keeps its address between the regions
            continue
        kk = uk[i] if uk[i] == pk[j] else (uk[i] + pk[j])
        w = min(DATA_WEIGHT.get(uk[i], 1), DATA_WEIGHT.get(pk[j], 1)) if uk[i] and pk[j] else 1
        pairs[a][b] += w
        kinds[kk] += 1
    log('address-forming matched pairs by kind', dict(kinds))
    outside_diff = {k: v for k, v in outside.items() if k[0] != k[1]}
    log('address pairs outside the images: %d equal, %d different' % (sum(v for k, v in outside.items() if k[0] == k[1]),
                                                                     sum(outside_diff.values())))

    jal_ok = jal_bad = 0
    jal_bad_list = []
    for i, j in enumerate(u2p):
        if j < 0:
            continue
        uw, pw = U.words[i], P.words[j]
        if uw >> 26 == 3 and pw >> 26 == 3:
            ut, pt = jump_target(uw, U.addr(i)), jump_target(pw, P.addr(j))
            if cmap(ut) == pt:
                jal_ok += 1
            else:
                jal_bad += 1; jal_bad_list.append((U.addr(i), ut, pt, cmap(ut)))
    log('jal pairs: target maps through code map %d, disagree %d' % (jal_ok, jal_bad))

    # pointer words in initialised data (ELF sections and overlay data words at aligned places)
    uptr = {}
    for name in INIT_SECTIONS + ('.ctors', '.dtors'):
        s = U.sections.get(name)
        for o in range(0, s['size'] - 3, 4):
            v = struct.unpack_from('<I', U.blob, s['off'] + o)[0]
            if U.in_image(v):
                uptr[s['addr'] + o] = v
    ov_data_from = ov_code_u
    for i in range(ov_data_from, U.n):
        v = U.words[i]
        if U.in_image(v):
            uptr[U.addr(i)] = v
    ptr_code_ok = ptr_code_bad = 0
    ptr_bad_list = []
    for ua, uv in uptr.items():
        pa = dpre(ua)
        if pa is None:
            continue
        pv = P.word(pa)
        if pv is None or not P.in_image(pv):
            continue
        if U.in_code_space(uv) and (U.in_text(uv) or U.idx(uv) < ov_code_u):
            if cmap(uv) == pv:
                ptr_code_ok += 1
            else:
                ptr_code_bad += 1; ptr_bad_list.append((ua, uv, pa, pv, cmap(uv)))
        elif uv == pv and not U.in_text(uv) and not (keep_equal_pairs and same_base(uv)):
            kinds['ptr-equal-dropped'] += 1              # data never keeps its address; an equal word is a constant/ASCII
        else:
            pairs[uv][pv] += DATA_WEIGHT['ptr']
            kinds['ptr'] += 1
    log('pointer words in aligned data: code targets agree %d disagree %d; data pointer pairs %d'
        % (ptr_code_ok, ptr_code_bad, kinds['ptr']))

    data_pairs, conflicts = {}, []
    for a, c in pairs.items():
        (b, n), *rest = c.most_common()
        if rest:
            conflicts.append(dict(usa=a, candidates=[[x, y] for x, y in c.most_common()]))
        if rest and rest[0][1] * 2 > n:
            continue
        data_pairs[a] = (b, n)
    # piecewise constant-delta segments (ELF data, bss, pad only; overlay data uses the word alignment)
    segs = []
    for a in sorted(data_pairs):
        if U.in_text(a) or (U.in_overlay(a) and U.idx(a) < ov_code_u):
            continue
        if a == U.gp or (replay and in_replay(a)):
            continue                                    # _gp is a linker symbol; the replay records have their own rule
        b, n = data_pairs[a]
        d, sec = b - a, U.section_of(a)
        if segs and segs[-1]['delta'] == d and segs[-1]['section'] == sec:
            segs[-1]['u1'] = a; segs[-1]['n'] += 1; segs[-1]['weight'] += n
        else:
            segs.append(dict(u0=a, u1=a, delta=d, n=1, weight=n, section=sec))
    log('data evidence: %d USA addresses (%d outside code), %d with competing candidates (%d unresolved), %d segments'
        % (len(data_pairs), sum(1 for a in data_pairs if not U.in_code_space(a)), len(conflicts),
           sum(1 for c in conflicts if c['usa'] not in data_pairs), len(segs)))
    fp_ok = fp_bad = 0
    for a, (b, n) in data_pairs.items():
        if U.in_code_space(a):
            if cmap(a) == b:
                fp_ok += 1
            else:
                fp_bad += 1
    log('lui/addiu-formed code-space addresses: agree with code map %d, disagree %d' % (fp_ok, fp_bad))

    # content blocks contradicted by code evidence are demoted (duplicate floats / strings can misalign)
    for b in content_blocks:
        b['ev_agree'] = b['ev_disagree'] = 0
    for a, (b_, n) in data_pairs.items():
        k = bisect.bisect_right(cbu, a) - 1
        if k >= 0 and a < content_blocks[k]['u'] + content_blocks[k]['n']:
            blk = content_blocks[k]
            if a + blk['p'] - blk['u'] == b_:
                blk['ev_agree'] += 1
            else:
                blk['ev_disagree'] += 1
    log('content blocks contradicted by code evidence: %d of %d (%d evidence points disagree)'
        % (sum(1 for b in content_blocks if b['ev_disagree']), len(content_blocks),
           sum(b['ev_disagree'] for b in content_blocks)))
    data = dict(u2p=u2p, p2u=p2u, src=src, content_blocks=content_blocks, data_pairs=data_pairs,
                data_conflicts=conflicts, data_segments=segs, functions={}, equiv=[None] * U.n, stats={},
                overlay_code_words=ov_code_u - U.n_text, entries=entries, entry_stats=estats)
    if not replay:
        data['replay'] = False                          # (a European build keeps the pickled data unchanged)
    m = Mapper(U, P, data)

    def amap(a):
        if U.in_code_space(a) and not (U.in_overlay(a) and U.idx(a) >= ov_code_u):
            return cmap(a)
        return m.map_data(a)[0]

    equiv = [None] * U.n
    ec = collections.Counter()
    lo_pairs = {(x & 0xFFFF, y & 0xFFFF) for x, (y, n) in data_pairs.items()}
    hi_ok, hi_bad = collections.Counter(), collections.Counter()
    luis = []
    for i, j in enumerate(u2p):
        if j < 0:
            continue
        e = classify_pair(U, P, i, j, cmap)
        op = U.words[i] >> 26
        if op == 0x0F:
            luis.append((i, j, e)); continue
        if e in ('eq', 'imm'):
            a, b = uf[i], pf[j]
            same = U.words[i] == P.words[j]
            if a is not None and b is not None and U.in_image(a):
                good = amap(a) == b
                (hi_ok if good else hi_bad)[uh[i]] += 1
                e = ('eq' if same else 'reloc') if good else ('eq' if same else 'reloc?')
            elif a is not None and b is not None:
                (hi_ok if a == b else hi_bad)[uh[i]] += 1
                e = 'eq' if same else 'diff'
            elif e == 'imm':
                us, ps = U.words[i] & 0xFFFF, P.words[j] & 0xFFFF
                e = 'reloc~' if (us, ps) in lo_pairs else 'diff'
        equiv[i] = e
        ec[e] += 1
    for i, j, e in luis:
        if e != 'eq':
            ok, bad = hi_ok.get(i, 0), hi_bad.get(i, 0)
            e = 'reloc' if ok and not bad else 'reloc~' if ok else 'diff' if bad else 'reloc~'
        equiv[i] = e
        ec[e] += 1
    m.equiv = equiv
    log('matched-pair equivalence:', dict(ec))

    fns = {}
    ust = ustarts + [None]
    for k, s in enumerate(ustarts):
        e = ust[k + 1]
        if U.in_text(s):
            e = U.text_end if (e is None or not U.in_text(e)) else e
        else:
            e = U.addr(ov_code_u) if (e is None or not U.in_overlay(e)) else e
        a, b = U.idx(s), U.idx(e - 4) + 1
        n = b - a
        idxs = range(a, b)
        nm = sum(1 for i in idxs if u2p[i] >= 0)
        strong = sum(1 for i in idxs if u2p[i] >= 0 and src[i] >= 2)
        deltas = collections.Counter(u2p[i] - i for i in idxs if u2p[i] >= 0)
        bad = sum(1 for i in idxs if equiv[i] in ('diff', 'reloc?', 'eq!'))
        rec = dict(start=s, end=e, size=4 * n, words=n, matched=nm, strong=strong, bad=bad,
                   hexrays=(s in hx), region='elf' if U.in_text(s) else 'overlay')
        if s in entries:
            rec['entry_votes'] = [entries[s][1], entries[s][2]]
            rec['pal_entry'] = entries[s][0]
        if strong == 0 and s not in entries:
            rec['class'] = 'missing'
            if nm:
                ps = [u2p[i] for i in idxs if u2p[i] >= 0]
                rec['pal_start'], rec['pal_end'] = P.addr(min(ps)), P.addr(max(ps)) + 4
        else:
            d0 = deltas.most_common(1)[0][0]
            ps = u2p[a] if u2p[a] >= 0 else None
            pe = u2p[b - 1] if u2p[b - 1] >= 0 else None
            rec['pal_start'] = P.addr(ps) if ps is not None else None
            rec['pal_end'] = P.addr(pe) + 4 if pe is not None else None
            rec['delta'] = P.addr(a + d0) - U.addr(a)
            tail_insert = b < U.n and u2p[b] >= 0 and pe is not None and u2p[b] != pe + 1
            if s in entries and (u2p[a] < 0 or entries[s][0] != P.addr(u2p[a])):
                rec['entry_moved'] = True                   # callers enter PAL somewhere else than the first word maps
            if nm == n and len(deltas) == 1 and bad == 0 and not tail_insert and not rec.get('entry_moved'):
                rec['class'] = 'identical'
            elif nm == n and len(deltas) == 1 and not tail_insert and not rec.get('entry_moved'):
                rec['class'] = 'same-shape'                 # 1:1 word layout, some operands/constants differ
                rec['bad'] = bad
            else:
                rec['class'] = 'changed'
                rec['deltas'] = len(deltas)
                rec['pal_words'] = (pe - ps + 1) if (ps is not None and pe is not None) else None
                rec['unmatched'] = n - nm
                rec['tail_insert'] = tail_insert
        fns[s] = rec
    m.functions = fns
    m._build_indexes()
    cls = collections.Counter((f['region'], f['class']) for f in fns.values())
    cls_bytes = collections.Counter()
    for f in fns.values():
        cls_bytes[(f['region'], f['class'])] += f['size']
    log('functions:', {'/'.join(k): v for k, v in cls.items()}, 'bytes:', {'/'.join(k): v for k, v in cls_bytes.items()})
    m.stats = dict(text_words=U.n_text, overlay_words=U.n - U.n_text,
                   text_matched=sum(1 for x in u2p[:U.n_text] if x >= 0),
                   overlay_matched=sum(1 for x in u2p[U.n_text:] if x >= 0),
                   text_alignment={k: v for k, v in al['text'].items() if k not in ('u2p', 'src')},
                   overlay_alignment={k: v for k, v in al['overlay'].items() if k not in ('u2p', 'src')},
                   jal_ok=jal_ok, jal_bad=jal_bad, jal_bad_examples=jal_bad_list[:80],
                   ptr_code_ok=ptr_code_ok, ptr_code_bad=ptr_code_bad, ptr_bad_examples=ptr_bad_list[:200],
                   fp_ok=fp_ok, fp_bad=fp_bad, evidence_kinds=dict(kinds), equivalence=dict(ec),
                   outside_pairs_different={('%X' % a): ['%X' % b, n] for (a, b), n in outside_diff.items()},
                   function_classes={'/'.join(k): v for k, v in cls.items()},
                   function_class_bytes={'/'.join(k): v for k, v in cls_bytes.items()},
                   usa_function_starts=len(ustarts), pal_function_starts=len(pstarts),
                   data_evidence_addresses=len(data_pairs), data_conflicts=len(conflicts), data_segments=len(segs))
    m.pal_starts = pstarts
    m.uformed, m.pformed, m.ukind, m.pkind, m.uhisrc, m.phisrc = uf, pf, uk, pk, uh, ph
    return m


def hexrays_sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest() if path is not None else None


def cache_key(U, P, hexrays=None, keep_equal_pairs=False, replay=True):
    """The build cache key. The default (European) rules keep the key they always had."""
    key = (VERSION, U.sha256, P.sha256, U.overlay_sha256, P.overlay_sha256, hexrays_sha256(hexrays))
    options = tuple(k for k, on in (('keep_equal_pairs', keep_equal_pairs), ('no_replay', not replay)) if on)
    return key + (options,) if options else key


def load(usa, pal, hexrays=None, rebuild=False, verbose=False, cache_dir=CACHE_DIR, keep_equal_pairs=False,
         replay=True):
    """usa, pal: (executable, DBZP.BIN) as paths or bytes. hexrays: optional USA Hex-Rays export path.
    keep_equal_pairs / replay: the target executable's data rules (see build)."""
    U, P = Image(*usa), Image(*pal)
    key = cache_key(U, P, hexrays, keep_equal_pairs, replay)
    cache = Path(cache_dir) / ('addrmap-%s.pkl' % hashlib.sha256(repr(key).encode()).hexdigest()[:24])
    if not rebuild and cache.exists():
        try:
            with open(cache, 'rb') as f:
                k, data = pickle.load(f)
            if k == key:
                return Mapper(U, P, data)
        except Exception:
            pass
    m = build(U, P, hexrays, verbose=verbose, keep_equal_pairs=keep_equal_pairs, replay=replay)
    keep = {k: v for k, v in m.__dict__.items() if k not in ('U', 'P', 'fn_starts', 'seg_u', 'cblocks_u')}
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        tmp = cache.with_suffix('.tmp%d' % id(keep))
        with open(tmp, 'wb') as f:
            pickle.dump((key, keep), f)
        tmp.replace(cache)
    except OSError:
        pass                                            # a cache is only a speed-up
    return m


if __name__ == '__main__':
    # pal_addrmap.py USA.elf USA-DBZP.BIN PAL.elf PAL-DBZP.BIN [--hexrays FILE] [--rebuild] [0xADDR ...]
    args = [a for a in sys.argv[1:] if not a.startswith('-') and not a.startswith('0x')]
    hx = sys.argv[sys.argv.index('--hexrays') + 1] if '--hexrays' in sys.argv else None
    args = [a for a in args if a != hx]
    m = load(tuple(args[0:2]), tuple(args[2:4]), hx, rebuild='--rebuild' in sys.argv, verbose=True)
    for a in sys.argv[1:]:
        if a.startswith('0x'):
            print(json.dumps(m.explain(int(a, 16)), default=str))
