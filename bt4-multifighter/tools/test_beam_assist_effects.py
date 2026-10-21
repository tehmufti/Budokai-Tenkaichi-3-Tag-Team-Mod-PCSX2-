"""Execute helper beam geometry and ownership using native emitter setters."""
import struct
import unittest
from pathlib import Path as _TestPath
from native_map import elf_path as _test_elf_path
if not _test_elf_path(_TestPath(__file__).resolve().parents[1]).is_file():
    raise unittest.SkipTest('An extracted game executable is required for native assist tests')
import beam_assist_effects as fx
import beam_struggle as assist
import beam_clash as clash
import fresh_team_combat as core
from native_map import A
from test_tag_rush_effects import machine as emitter_machine, POOL, REGISTRY
from test_tag_rush_camera import run


def machine():
    c=emitter_machine()
    for p,code in ((fx.SPAWN,fx.spawn_code()),(fx.STOP,fx.stop_code()),(fx.TICK,fx.tick_code()),
                   (fx.OWNED,fx.owned_code()),(fx.GEOMETRY,fx.geometry_code()),(fx.IGNITE,fx.ignite_code())):
        c.write(p,code)
    c.write(fx.CONTROL,struct.pack('<5I',fx.MAGIC,c.u(core.ACTORS),4,1,POOL))
    c.w(fx.CONTROL+fx.C['init_status'],2)
    c.w(assist.CONTROL,assist.MAGIC);c.w(assist.CONTROL+assist.C['assist'],1)
    c.w(clash.CONTROL+16,1);c.w(clash.CONTROL+24,7)
    c.w(clash.INDICES,0);c.w(clash.INDICES+4,1)
    c.callbacks[fx.COLOR_APPLY]=lambda m:m.r.__setitem__(2,1)
    c.callbacks[assist.RUNNING]=lambda m:m.r.__setitem__(2,1)
    c.callbacks[fx.GET_POINT]=lambda m:m.write(m.r[4],struct.pack('<4f',12.,-18.,90.,1.))
    for i,model in enumerate(c.models):
        c.write(model+2416,struct.pack('<4f',30.*i,-20.,100.*i,1.))
        c.w(model+192+364*4,0x3A00000+i*0x100);c.w(0x3A00000+i*0x100,100)
        c.w(c.actors[i]+2376,304)
    for i in range(fx.COUNT):
        row=fx.ROWS+i*fx.STRIDE
        c.w(row+fx.R['prepared'],fx.PREPARED)
        c.w(row+fx.HEADER+36,row+fx.META);c.w(row+fx.DESC+796,row+fx.HEADER)
    return c


def admit(c,slot=0,actor=2):
    address=assist.CONTROL+assist.SLOTS+slot*assist.SLOT_STRIDE
    for key,value in (('state',assist.P_CONFIRMED),('serial',7),('actor',c.actors[actor]),('phys',actor),('k',slot%4)):
        c.w(address+assist.S[key],value)
    c.r[4:6]=[fx.ROWS+slot*fx.STRIDE,address]
    run(c,fx.SPAWN)
    return c.r[2]


class HelperEffectsTests(unittest.TestCase):
    def test_no_persistent_emitter_without_a_frame_owner(self):
        ram=bytearray(0x8000000)
        struct.pack_into('<I',ram,assist.CONTROL,assist.MAGIC)
        struct.pack_into('<I',ram,assist.CONTROL+assist.C['assist'],1)
        self.assertEqual(fx.build_memory(ram,iso='not-opened.iso')['blocks'],[])

    def test_builder_reinstall_accepts_native_relocations_but_rejects_asset_corruption(self):
        import texture_queue_guard as guard
        from tag_rush_install import selected_iso
        ram=bytearray(0x8000000)
        for p,data in guard.pieces():ram[p:p+len(data)]=data
        for key,value in (('magic',assist.MAGIC),('manager',0x1700000),('count',10),('assist',1),('frame_prev',0x07100000)):
            struct.pack_into('<I',ram,assist.CONTROL+(0 if key=='magic' else assist.C[key]),value)
        iso=selected_iso()
        if not iso.is_file():self.skipTest('The selected game disc is required')
        plan=fx.build_memory(ram,iso=iso)
        self.assertGreater(len(plan['blocks']),15)
        for block in plan['blocks']:
            p=block['address'];data=bytes.fromhex(block['data_hex'])
            self.assertEqual(ram[p:p+len(data)].hex(),block['expected_hex'])
            ram[p:p+len(data)]=data
        self.assertEqual(fx.build_memory(ram,iso=iso)['blocks'],[])
        path=iso.resolve();st=path.stat();asset=fx._assets(str(path),st.st_size,st.st_mtime_ns)
        for off,size in asset['mutable_ranges']:ram[fx.RESOURCE+off:fx.RESOURCE+off+size]=bytes([0x12])*size
        self.assertEqual(fx.build_memory(ram,iso=iso)['blocks'],[])
        ram[fx.METADATA]^=1
        with self.assertRaisesRegex(ValueError,'metadata changed'):fx.build_memory(ram,iso=iso)

    def test_all_eight_helpers_have_separate_owned_emitters(self):
        c=machine()
        for i,mid in zip(range(4,10),(2,3,5,6,8,9)):
            actor=c.actors[0]+i*0x2000;model=c.models[0]+i*0x2000
            c.write(actor,c.read(c.actors[2],0x1600));c.write(model,c.read(c.models[2],0x1700))
            c.w(actor,i);c.w(actor+12,mid);c.w(model+16,mid)
            c.w(core.POINTERS+4*i,actor);c.w(core.MODELS+4*mid,model)
            c.actors.append(actor);c.models.append(model)
        for address in (core.MODE+4,core.MODE+12,fx.CONTROL+fx.C['count'],assist.CONTROL+assist.C['count']):c.w(address,10)
        for slot,actor in enumerate((2,4,6,8,3,5,7,9)):
            self.assertEqual(admit(c,slot,actor),1)
        nodes=[c.u(fx.ROWS+i*fx.STRIDE+fx.R['node'])for i in range(8)]
        self.assertEqual(len(set(nodes)),8)
        c.callbacks[assist.RUNNING]=lambda m:m.r.__setitem__(2,0)
        run(c,fx.TICK)
        self.assertEqual(len([e for e in c.events if e[0]=='retire_children']),8)

    def test_eighth_parse_failure_restores_allocator_and_never_enables_partial_effects(self):
        c=machine();c.w(fx.CONTROL+fx.C['init_status'],0);c.w(fx.CONTROL+fx.C['ready'],0)
        beam=dict(reviewed=True,resource_address=fx.RESOURCE,metadata_address=fx.METADATA,
                  descriptor_counts=(1,6,0,1),descriptor_raw_bytes=2176)
        c.write(fx.INIT,fx.init_code(beam));old=c.read(REGISTRY,156);params=c.u(c.models[0]+2348)
        calls=[];c.callbacks[A(0x14B108)]=lambda m:None
        def parse(m):
            arena=m.u(REGISTRY+80);calls.append(arena)
            m.w(m.r[5]+796,m.r[4]);m.write(m.r[5]+780,struct.pack('<4I',1,6,0,1))
            for off,delta in ((764,0),(768,544),(776,2144)):m.w(m.r[5]+off,arena+delta)
            m.w(REGISTRY+92,fx.ARENA_SIZE+16 if len(calls)==8 else 2304)
        c.callbacks[A(0x14CEB0)]=parse;run(c,fx.INIT)
        self.assertEqual(calls,[fx.ARENAS+i*fx.ARENA_SIZE for i in range(8)])
        self.assertEqual(c.r[2],0);self.assertEqual(c.u(fx.CONTROL+fx.C['ready']),0)
        self.assertEqual(c.read(REGISTRY,156),old);self.assertEqual(c.u(c.models[0]+2348),params)

    def test_full_resource_does_not_overlap_color_tables(self):
        from tag_rush_install import selected_iso
        path=selected_iso().resolve()
        if not path.is_file():self.skipTest('The selected game disc is required')
        st=path.stat();asset=fx._assets(str(path),st.st_size,st.st_mtime_ns)
        spans=sorted((p,p+len(data))for p,data in fx.pieces(asset)+[(fx.RESOURCE,asset['resource']),(fx.METADATA,asset['metadata'])])
        self.assertTrue(all(b<=c for (_,b),(c,_)in zip(spans,spans[1:])))

    def test_both_sides_use_real_clash_point_and_visual_only_native_request(self):
        c=machine()
        for slot,actor in ((0,2),(4,3)):
            self.assertEqual(admit(c,slot,actor),1)
            row=fx.ROWS+slot*fx.STRIDE;body=c.u(row+fx.R['body'])
            self.assertEqual(c.read(body+1472,16),struct.pack('<4f',12.,-18.,90.,1.))
            self.assertEqual(c.u(row+fx.R['target_index']),1 if slot==0 else 0)
            self.assertEqual(c.u(body+1408)&0xC1,0xC1)  # native motion and collision disabled
            self.assertAlmostEqual(struct.unpack('<f',c.read(body+1420,4))[0],.25)
            self.assertEqual(c.requests[-1][9],0)  # lasts for the clash, not a ten-second projectile

    def test_invalid_clash_point_does_not_spawn(self):
        for point in ((float('nan'),0.,0.,1.),(1e9,0.,0.,1.)):
            c=machine();c.callbacks[fx.GET_POINT]=lambda m,p=point:m.write(m.r[4],struct.pack('<4f',*p))
            self.assertEqual(admit(c),0);self.assertEqual(c.requests,[])
        c=machine();c.callbacks[fx.GET_POINT]=lambda m:None
        self.assertEqual(admit(c),0);self.assertEqual(c.requests,[])

    def test_stale_serial_or_model_never_updates_beam(self):
        for change in ('serial','model','state','action','dead'):
            c=machine();self.assertEqual(admit(c),1)
            row=fx.ROWS;before=c.read(row+fx.SOURCE,48)
            if change=='serial':c.w(clash.CONTROL+24,8)
            elif change=='model':c.w(c.models[2]+12,999)
            elif change=='state':c.w(assist.CONTROL+assist.SLOTS+assist.S['state'],assist.P_FAILED)
            elif change=='action':c.w(c.actors[2]+2376,11)
            else:c.w(c.actors[2]+0x9E4,0)
            c.r[4]=row;run(c,fx.GEOMETRY)
            self.assertEqual(c.r[2],0);self.assertEqual(c.read(row+fx.SOURCE,48),before)

    def test_slot_eight_is_owned_and_outside_rows_are_rejected(self):
        c=machine();self.assertEqual(admit(c,7,3),1)
        c.r[4]=fx.ROWS+7*fx.STRIDE;run(c,fx.OWNED);self.assertNotEqual(c.r[2],0)
        for row in (fx.ROWS-4,fx.ROWS+4,fx.ROWS+8*fx.STRIDE):
            c.r[4]=row;run(c,fx.OWNED);self.assertEqual(c.r[2],0)

    def test_stop_cannot_retire_a_reused_native_node(self):
        c=machine();self.assertEqual(admit(c),1)
        row=fx.ROWS;node=c.u(row+fx.R['node']);body=c.u(row+fx.R['body'])
        c.w(body+48,0x100000);c.r[4]=row;before=len(c.events)
        run(c,fx.STOP)
        self.assertEqual(c.u(row+fx.R['node']),0)
        self.assertFalse(any(e[0]=='retire_children' for e in c.events[before:]))

    def test_tick_creates_once_then_stops_when_clash_ends(self):
        c=machine();slot=assist.CONTROL+assist.SLOTS
        for key,value in (('state',assist.P_CONFIRMED),('serial',7),('actor',c.actors[2]),('phys',2),('k',0)):
            c.w(slot+assist.S[key],value)
        run(c,fx.TICK);run(c,fx.TICK);self.assertEqual(len(c.requests),1)
        c.callbacks[assist.RUNNING]=lambda m:m.r.__setitem__(2,0)
        run(c,fx.TICK)
        self.assertTrue(any(e[0]=='retire_children' for e in c.events))


if __name__=='__main__':unittest.main()
