"""Optional leader camera selection for the exposed multifighter experiment.

Keeps native per-leader camera calculation and split-screen renderer. Prevents
priority/cinematic selection from replacing the normal leader views.
"""
from native_map import A, CRC, SERIAL
import argparse,json,struct
from pathlib import Path
from prototype import Assembler
CODE,CONTROL,HOOK=0xFC000,0xFC400,A(0x23EFF0)
ORIGINAL=struct.pack('<2I',0x27BDFFF0,0xFFB00000)
POINTERS,MODELS,PARTICIPANT_OFFSET=0xD8040,A(0x31C640),0x300
PAIRED_STATES=((301,3),(313,3),(183,5))  # paired specials and throw execution ranges


def payload_cinematic():
 """Leader camera selection that presents the native cinematic camera only
 when the viewed leader takes part in the active cinematic.

 Rush/paired specials move both fighters to an off-stage staging area; the
 native single view switches to the cinematic camera there. Keeping the
 normal leader view during such a cinematic renders the empty staging area
 (a white screen). Cinematics of other pairs keep the normal leader views."""
 a=Assembler(CODE); helper=CODE+PARTICIPANT_OFFSET
 a.li(2,CONTROL); a.lw(2,2); a.branch(4,2,0,'fallback')
 a.li(2,0xB3088); a.lw(2,2); a.branch(4,2,0,'fallback')
 a.addiu(29,29,-0x30)
 for reg,off in ((16,0),(17,8),(18,16),(31,24)): a.i(63,reg,29,off)
 # Native cinematic timing advances exactly once per frame.
 a.call(A(0x23DBC0)); a.move(17,2)
 a.branch(4,17,0,'select'); a.call(A(0x23D510))
 a.label('select'); a.call(A(0x12AB10)); a.branch(4,2,0,'single')
 a.call(A(0x12A9E8)); a.branch(5,2,0,'single')
 a.branch(4,17,0,'split_normal')
 a.move(4,0); a.call(helper); a.branch(5,2,0,'split_side0')
 a.addiu(4,0,1); a.call(helper); a.branch(5,2,0,'split_side1')
 a.label('split_normal')
 # Two native passes, each following its own leader.
 a.move(4,0); a.call(A(0x23EF98))
 a.move(16,0); a.li(8,CONTROL); a.lw(9,8,8); a.addiu(9,9,1); a.sw(9,8,8)
 a.jump('done')
 a.label('split_side0'); a.move(18,0); a.jump('single_side')
 a.label('split_side1'); a.addiu(18,0,1); a.jump('single_side')
 a.label('single'); a.call(A(0x23EE08))
 a.i(11,8,2,2); a.branch(5,8,0,'valid'); a.move(2,0)
 a.label('valid'); a.move(18,2)
 a.label('single_side')
 a.move(4,18); a.li(8,CONTROL); a.sw(18,8,12)
 a.call(A(0x23EF98)); a.addiu(4,0,1); a.call(A(0x23EFD0))
 a.move(4,0); a.addiu(5,0,1); a.call(A(0x23EE78))
 a.addiu(16,0,1)
 a.branch(4,17,0,'done')
 a.move(4,18); a.call(helper); a.branch(4,2,0,'done')
 # The viewed leader takes part: restore the cinematic camera computed above.
 a.lw(8,28,-22180); a.sw(8,28,-22176)
 a.li(8,CONTROL); a.lw(9,8,16); a.addiu(9,9,1); a.sw(9,8,16)
 a.label('done'); a.li(8,CONTROL); a.lw(9,8,4); a.addiu(9,9,1); a.sw(9,8,4)
 a.move(2,16)
 for reg,off in ((16,0),(17,8),(18,16),(31,24)): a.i(55,reg,29,off)
 a.addiu(29,29,0x30); a.jr()
 a.label('fallback'); a.emit(0x27BDFFF0); a.emit(0xFFB00000); a.jump(HOOK+8)
 assert a.pc<=helper, 'Selection code overlaps the participant helper'
 while a.pc<helper: a.emit(0)
 # participant(a0=side) -> v0. Temporaries only; no stack.
 a.li(8,POINTERS); a.r(0,9,0,4,2); a.r(0x2D,8,8,9); a.lw(9,8); a.branch(4,9,0,'no')
 a.lw(10,9,0x948)
 for start,count in PAIRED_STATES:
  a.addiu(11,10,-start); a.i(11,11,11,count); a.branch(5,11,0,'yes')
 a.lw(12,28,-22180); a.branch(4,12,0,'no')
 a.lw(13,12,768); a.branch(5,13,0,'bound'); a.lw(13,12,772)
 a.label('bound'); a.branch(4,13,0,'no')
 a.lw(14,9,12); a.i(11,15,14,12); a.branch(4,15,0,'no')
 a.r(0,14,0,14,2); a.li(15,MODELS); a.r(0x2D,15,15,14); a.lw(14,15)
 a.branch(4,14,13,'yes')
 a.label('no'); a.move(2,0); a.jr()
 a.label('yes'); a.addiu(2,0,1); a.jr()
 b=a.finish(); assert len(b)<0xC00
 return b

def payload():
 a=Assembler(CODE)
 a.li(2,CONTROL); a.lw(2,2); a.branch(4,2,0,'fallback')
 a.li(2,0xB3088); a.lw(2,2); a.branch(4,2,0,'fallback')
 a.addiu(29,29,-0x20); a.i(63,16,29,0); a.i(63,31,29,8)
 # Maintain native camera-animation lifetime, then override selection last.
 a.call(A(0x23DBC0)); a.branch(4,2,0,'select'); a.call(A(0x23D510))
 a.label('select'); a.call(A(0x12AB10)); a.branch(4,2,0,'single')
 a.call(A(0x12A9E8)); a.branch(5,2,0,'single')
 # Intervening render preparation also receives a normal leader camera.
 a.move(4,0); a.call(A(0x23EF98))
 # Returning zero selects native two-pass renderer, each following its leader.
 a.move(16,0); a.li(8,CONTROL); a.lw(9,8,8); a.addiu(9,9,1); a.sw(9,8,8)
 a.jump('done')
 a.label('single'); a.call(A(0x23EE08))
 a.i(11,8,2,2); a.branch(5,8,0,'valid'); a.move(2,0)
 a.label('valid'); a.move(4,2); a.li(8,CONTROL); a.sw(2,8,12)
 a.call(A(0x23EF98)); a.addiu(4,0,1); a.call(A(0x23EFD0))
 a.move(4,0); a.addiu(5,0,1); a.call(A(0x23EE78))
 a.addiu(16,0,1)
 a.label('done'); a.li(8,CONTROL); a.lw(9,8,4); a.addiu(9,9,1); a.sw(9,8,4)
 a.move(2,16); a.i(55,16,29,0); a.i(55,31,29,8); a.addiu(29,29,0x20); a.jr()
 a.label('fallback'); a.emit(0x27BDFFF0); a.emit(0xFFB00000); a.jump(HOOK+8)
 b=a.finish(); assert len(b)<CONTROL-CODE
 return b

def build(source):
 r=Path(source).read_bytes()
 if len(r) not in (0x2000000,0x8000000): raise ValueError('Expected full EE RAM')
 if r[HOOK:HOOK+8]!=ORIGINAL: raise ValueError('Camera selection entry changed')
 blocks=[]
 for address,data,purpose in [(CODE,payload(),'Leader-only single/split camera selection'),(CONTROL,struct.pack('<4I',1,0,0,0),'Enable, frames, split frames, last single side')]:
  old=r[address:address+len(data)]
  if any(old): raise ValueError(f'Occupied camera cave {address:x}')
  blocks.append(dict(address=address,expected_hex=old.hex(),data_hex=data.hex(),purpose=purpose))
 blocks.append(dict(address=HOOK,expected_hex=ORIGINAL.hex(),data_hex=struct.pack('<2I',(2<<26)|(CODE>>2),0).hex(),purpose='Exposure-gated leader camera lock'))
 return dict(serial=SERIAL,crc=CRC,source=str(Path(source).resolve()),status='EXPERIMENTAL LEADER CAMERA SELECTION; LIVE VALIDATION REQUIRED',blocks=blocks,limitations=['Native leader camera eye/aim/collision calculations unchanged.','Cinematic timing is maintained but rendering stays on the leaders; special move presentation is reduced.','Live split-screen and CPU-versus-CPU modes need separate validation.'])

if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__); p.add_argument('--ram',required=True,type=Path); p.add_argument('--out',required=True,type=Path); x=p.parse_args(); x.out.write_text(json.dumps(build(x.ram),indent=2)+'\n'); print(x.out)
