"""Four independent human/spectator seats, without widening packed legacy data."""
from native_map import A
import struct
from prototype import Assembler
import fresh_team_combat as core
import fresh_team_camera as camera
import spectator_switch as spec
import spectator_takeover as spectator
import guest_killfeed as feed
import team_participation as part
import team_start_gate as start
import lockon_queue as queue
import quad_controller as pads
import quad_viewports as views
import battle_mode_policy as modes

BASE,END=0x06C20000,0x06C30000
FRAME,TAKE,CONTROL=BASE,BASE+0x3000,BASE+0xF000
PROBE,FEEDBACK=BASE+0x8000,BASE+0xE000
F=dict(original=0x40,owned=0x50,held=0x60,buttons=0x70,watching=0x80,
       view_side=0x90,human_ports=0xA0,battle_mode=0xA4,takeovers=0xA8)
OPTIONS,TAKE_ENABLED=0xB0,0xB4


def frame(previous):
    a=Assembler(FRAME);spectator.save(a);pads.gate(a,'done');a.move(17,10)
    a.li(8,start.CONTROL);a.lw(8,8);a.branch(5,8,0,'done')
    a.li(8,A(0x3337B8));a.lw(8,8);a.i(12,8,8,0x3900);a.branch(5,8,0,'done')
    a.lw(8,28,-22364);a.lw(8,8,628);a.branch(5,8,0,'done')
    a.li(8,A(0x2FEB38));a.lw(14,8);spectator.pointer(a,14,0x108,'done')
    a.lw(8,14);a.addiu(9,0,3);a.branch(5,8,9,'done')
    a.move(18,0);a.li(16,CONTROL)
    a.label('seat');a.r(0,8,0,18,2);a.r(0x2D,19,16,8)
    a.lw(22,19,F['owned']);a.r(0x2B,8,22,17);a.branch(4,8,0,'next')
    import multiplayer_fusion as fusion
    a.li(8,fusion.CONTROL);a.lw(9,8);a.li(10,fusion.MAGIC);a.branch(5,9,10,'legacy_fusion')
    a.move(4,22);a.call(fusion.FOLLOW);a.addiu(8,0,-1);a.branch(4,2,8,'unfused')
    a.move(24,2);a.jump('publish');a.label('legacy_fusion')
    # Native pair 0/2 may fuse. Only their seats share the surviving body;
    # the other two humans keep their own view and controls.
    a.li(8,modes.CONTROL);a.lw(9,8);a.li(10,modes.MAGIC);a.branch(5,9,10,'unfused')
    a.lw(9,8,24);a.r(0x2B,10,9,17);a.branch(4,10,0,'unfused')
    a.lw(10,8,28);a.branch(4,22,9,'fused_view');a.branch(5,22,10,'unfused')
    a.label('fused_view');a.move(24,9);a.jump('publish')
    a.label('unfused');a.li(8,feed.CONTROL+spec.DEAD);a.r(0,9,0,22,2);a.r(0x2D,8,8,9);a.lw(8,8)
    a.branch(5,8,0,'watch');a.sw(0,19,F['held']);a.sw(0,19,F['watching'])
    a.move(24,22);a.jump('publish')
    a.label('watch');a.lw(23,19,F['watching']);a.addiu(8,0,1);a.sw(8,19,F['watching'])
    for seat in range(4):
        a.addiu(8,0,seat);a.branch(5,18,8,f'pad_next{seat}')
        a.li(8,pads.RECORDS+seat*pads.RECORD_STRIDE if seat<2 else pads.PADS+(seat-2)*pads.RECORD_STRIDE)
        a.jump('pad_ready');a.label(f'pad_next{seat}')
    a.label('pad_ready');a.lw(20,8,328);a.lw(21,19,F['buttons']);a.sw(20,19,F['buttons'])
    a.li(8,views.SUBJECTS);a.r(0,9,0,18,2);a.r(0x2D,8,8,9);a.lw(24,8)
    a.branch(4,23,0,'auto_scan')
    a.i(12,8,20,spectator.SQUARE);a.branch(4,8,0,'gesture')
    a.i(12,8,21,spectator.SQUARE);a.branch(5,8,0,'gesture')
    a.li(8,spec.lock.CONTROL);a.lw(9,8,spec.lock.FIELDS['button']);a.li(8,spectator.SQUARE)
    a.branch(5,9,8,'take_key');a.i(12,8,20,0x100);a.branch(4,8,0,'gesture')
    a.label('take_key');a.move(4,18);a.move(5,24);a.call(TAKE);a.branch(5,2,0,'next')
    a.label('gesture');a.li(8,spec.lock.CONTROL);a.lw(8,8,spec.lock.FIELDS['button']);a.r(0x24,9,20,8)
    a.addiu(25,0,spec.HOLD_UPDATES);a.li(8,queue.CONTROL);a.lw(10,8,queue.TIMING_MAGIC);a.li(11,queue.TIMING_TAG)
    a.branch(5,10,11,'timing');a.lw(25,8,queue.TIMING_UPDATES)
    a.addiu(10,25,-1);a.li(11,queue.MAX_HOLD_UPDATES);a.r(0x2B,10,10,11);a.branch(4,10,0,'next')
    a.label('timing');a.lw(11,19,F['held']);a.branch(4,9,0,'released')
    a.r(0x2B,8,11,25);a.branch(4,8,0,'next');a.addiu(11,11,1);a.sw(11,19,F['held']);a.jump('next')
    a.label('released');a.sw(0,19,F['held']);a.r(0x2B,8,11,25);a.branch(5,8,0,'next')
    a.move(26,0);a.jump('scan_start')
    a.label('auto_scan');a.addiu(26,0,1)
    a.label('scan_start');a.move(23,0);a.move(27,24)
    a.label('scan');a.addiu(23,23,1);a.r(0x2B,8,17,23);a.branch(5,8,0,'next')
    a.addiu(24,24,1);a.r(0x2B,8,24,17);a.branch(5,8,0,'candidate');a.move(24,0)
    a.label('candidate');a.move(4,24);a.call(spectator.LOOKUP);a.branch(4,3,0,'scan')
    a.branch(4,26,0,'publish')
    a.li(8,feed.CONTROL+spec.DEAD);a.r(0,9,0,24,2);a.r(0x2D,8,8,9);a.lw(8,8);a.branch(5,8,0,'scan')
    a.label('publish');a.li(8,views.SUBJECTS);a.r(0,9,0,18,2);a.r(0x2D,8,8,9);a.sw(24,8)
    a.label('next');a.addiu(18,18,1);a.addiu(8,0,4);a.branch(5,18,8,'seat')
    # Legacy camera/HUD helpers still consume the first two subjects.
    for seat in range(2):
        a.li(8,views.SUBJECTS);a.lw(9,8,4*seat);a.li(8,camera.SUCCESSOR_CONTROL);a.sw(9,8,8+4*seat)
    a.label('done');spectator.restore(a);a.jump(previous)
    data=a.finish();assert len(data)<TAKE-FRAME;return data


@modes.matching_install
def build_memory(ram,subjects,mode):
    installed=spectator.validate_memory(ram)
    if any(ram[BASE:END]):raise ValueError('Four-player seat reservation occupied')
    previous,extras=pads.chain_head(ram,A(0x1C2A28),BASE+0x7000,pads.NATIVE)
    data=bytearray(0xC0)
    struct.pack_into('<I',data,F['human_ports'],(1<<len(subjects))-1)
    struct.pack_into('<I',data,F['battle_mode'],modes.MODES[mode])
    struct.pack_into('<2I',data,OPTIONS,spectator.OPTION_MAGIC,struct.unpack_from('<I',ram,spec.CONTROL+spectator.TAKE_ENABLED)[0])
    padded=tuple(subjects)+(0xFFFFFFFF,)*(4-len(subjects))
    for key,values in (('original',padded),('owned',padded),('view_side',range(4))):struct.pack_into('<4I',data,F[key],*values)
    # Replace only the exact legacy update; its lookup and pad fallback remain
    # available. Legacy feedback is retired so it cannot publish wrong seats.
    parts=[(p,b) for p,b,*_ in extras]+[(FRAME,frame(previous)),(TAKE,spectator.take(base=TAKE,quad=True)),
        (CONTROL,bytes(data)),(spec.CODE,views.jump(installed['previous'])),(A(0x1C2A28),views.jump(FRAME))]
    import spectator_feedback
    feedback=bytearray(0x80)
    struct.pack_into('<2I',feedback,0,spectator_feedback.MAGIC,struct.unpack_from('<I',ram,core.ACTORS)[0])
    struct.pack_into('<4I',feedback,16,*padded)
    parts.extend(((spectator_feedback.DRAW,spectator_feedback.draw(quad=True)),
                  (PROBE,spectator.take(base=PROBE,commit=False,quad=True)),(FEEDBACK,bytes(feedback))))
    return dict(blocks=[dict(address=p,expected_hex=ram[p:p+len(b)].hex(),data_hex=b.hex()) for p,b in parts])
