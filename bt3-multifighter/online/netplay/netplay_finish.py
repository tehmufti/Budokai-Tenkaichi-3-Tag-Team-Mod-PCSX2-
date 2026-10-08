"""Finish padded online matches before native two-leader victory rendering.

The native winner remains authoritative. An unequal roster can enter director
states 3–5 and submit a stalled VIF1 chain during a fatal cinematic or victory presentation.
Park fatal rendering while native updates determine the winner.
Commit one final deterministic hash after the winning update, then park the
render path for the online result/vote screen. Combat and offline code are unchanged.
"""
import struct
import netplay_core as nc
import netplay_view as nv
from native_map import A
from prototype import Assembler
import team_participation as participation

CODE, CONTROL, END = 0x07B2E000, 0x07B2F800, 0x07B2F900
MAGIC = 0x31464E4F
SAVED = tuple(range(1, 26)) + (30, 31)


def code():
    a = Assembler(CODE)
    a.addiu(29, 29, -0xE0)
    for i, r in enumerate(SAVED): a.i(63, r, 29, i * 8)
    a.li(16, CONTROL); a.lw(8, 16); a.li(9, MAGIC); a.branch(5, 8, 9, 'render')
    a.lw(8, 16, 4); a.branch(5, 8, 0, 'done')
    a.li(17, nc.CONTROL); a.lw(8, 17); a.li(9, nc.MAGIC); a.branch(5, 8, 9, 'render')
    a.lw(8, 17, nc.F['state']); a.addiu(9, 0, nc.RUNNING); a.branch(5, 8, 9, 'render')
    a.li(8, A(0x2FEB38)); a.lw(18, 8); nc._valid(a, 18, 'render')
    a.lw(19, 18); a.addiu(8, 0, 3); a.branch(4, 19, 8, 'preoutro')
    a.addiu(8, 19, -4); a.i(11, 8, 8, 2); a.branch(4, 8, 0, 'render')
    a.li(8, A(0x333700)); a.lw(20, 8); a.i(12, 8, 20, 0x1F)
    a.addiu(8, 8, -1); a.i(11, 8, 8, 2); a.branch(4, 8, 0, 'preoutro')
    a.lw(21, 17, nc.F['frame']); a.addiu(21, 21, 1)
    a.sw(21, 17, nc.F['frame'])
    a.move(4, 21); a.call(nc.HASH_CODE)
    a.sw(21, 17, nc.F['decided_frame']); a.sw(19, 17, nc.F['decided_state'])
    a.sw(20, 17, nc.F['decided_result']); a.sw(0, 17, nc.F['waiting'])
    a.addiu(8, 0, 1); a.sw(8, 16, 4)
    # Publish the terminal state after all result/hash fields are committed.
    a.addiu(8, 0, nc.DECIDED); a.sw(8, 17, nc.F['state']); a.jump('done')
    a.label('preoutro')
    # A fatal cinematic can submit the broken padded-roster VIF chain one update
    # BEFORE the director publishes the winner. Park only rendering while the
    # native battle updates finish; never fabricate a winner from the HP check.
    a.lw(8, 16, 12); a.branch(4, 8, 0, 'render')
    a.li(8, participation.CONTROL); a.lw(9, 8); a.addiu(10, 0, 5); a.branch(5, 9, 10, 'render')
    a.lw(22, 8, 12); a.lw(10, 8, 16); a.r(0x27, 10, 10, 0); a.r(0x24, 22, 22, 10)
    a.lw(9, 16, 8); a.r(0x24, 22, 22, 9); a.branch(4, 22, 0, 'render')
    a.move(21, 0)
    for i in range(10):
        tag = f'next{i}'
        a.i(12, 8, 22, 1 << i); a.branch(4, 8, 0, tag)
        a.li(8, 0xD8040 + 4*i); a.lw(14, 8); nc._valid(a, 14, 'render')
        a.lw(8, 14); a.addiu(9, 0, i); a.branch(5, 8, 9, 'render')
        a.lw(8, 14, 0x994); a.i(11, 9, 8, 5); a.branch(4, 9, 0, 'render')
        a.r(0, 10, 0, 8, 7); a.r(0, 11, 0, 8, 5); a.r(0x21, 10, 10, 11)
        a.r(0, 11, 0, 8, 2); a.r(0x21, 10, 10, 11); a.r(0x21, 14, 14, 10)
        a.lw(12, 14, 0x9E4); a.r(0x2A, 8, 0, 12); a.branch(4, 8, 0, tag)
        a.i(13, 21, 21, 1 << (i & 1)); a.addiu(8, 0, 3); a.branch(4, 21, 8, 'render')
        a.label(tag)
    a.jump('done')
    a.label('render'); a.call(nv.SWAP)
    a.label('done')
    for i, r in enumerate(SAVED): a.i(55, r, 29, i * 8)
    a.addiu(29, 29, 0xE0); a.jr()
    out = a.finish()
    assert CODE + len(out) <= CONTROL
    return out


def blocks(ram, spec, view_blocks):
    if len(spec['teams'][0]) == len(spec['teams'][1]): return []
    if not nv.MARKER_GATE + 0x100 <= CODE < END <= nc.VIEW_AREA_END:
        raise ValueError('Online finish reservation overlaps another allocation')
    if any(ram[CODE:END]): raise ValueError('Online finish reservation is occupied')
    # Replace the planned view hook, never a foreign or already installed hook.
    site = nv.natives().render_site
    row = next(b for b in view_blocks if b['address'] == site)
    if row['data_hex'] != struct.pack('<I', nv.jal(nv.SWAP)).hex():
        raise ValueError('Online view hook changed')
    row['data_hex'] = struct.pack('<I', nv.jal(CODE)).hex()
    roster_mask = sum(1 << (2*j+t) for t,team in enumerate(spec['teams']) for j in range(len(team)))
    terminal_teams = int(spec.get('mode') == 'teams' and spec.get('type', 'versus') == 'versus')
    return [dict(address=p, expected_hex=bytes(ram[p:p+len(d)]).hex(), data_hex=d.hex(),
                 purpose='Park unequal online matches after the final winner hash')
            for p, d in [(CODE, code()), (CONTROL, struct.pack('<4I', MAGIC, 0, roster_mask, terminal_teams))]]
