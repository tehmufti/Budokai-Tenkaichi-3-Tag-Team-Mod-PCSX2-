import json
import random
import struct
import unittest
import quad_viewports as q
from prototype import ROOT
from test_terrain_crossing_guard import ScalarMips

AI_READY=ROOT/'analysis/prepared-states/20260920-044905-2258fc22'
OT_TABLE,OT_TAGS,OT_ENTRIES=0x1000000,0x1100000,8196


class OrderingCpu(ScalarMips):
    """4 KiB pages (optionally over a RAM image), counted fetches, and SRL."""
    instruction_budget=400000
    hi=lo=0

    def __init__(self,image=b''):
        super().__init__({'segments':[]});self.image=image;self.pages={};self.fetched=0

    def original(self,key):return bytes(self.image[key<<12:(key+1)<<12]).ljust(4096,b'\0')

    def page(self,address):
        key=(address&0xFFFFFFFF)>>12
        if key not in self.pages:self.pages[key]=bytearray(self.original(key))
        return self.pages[key]

    def write(self,address,data):
        for i,value in enumerate(data):self.page(address+i)[(address+i)&4095]=value

    def read(self,address,length):
        start=address&4095
        if start+length<=4096:return bytes(self.page(address)[start:start+length])
        return bytes(self.page(address+i)[(address+i)&4095] for i in range(length))

    def u(self,address):
        self.fetched+=1;return int.from_bytes(self.read(address,4),'little')

    def extra_instruction(self,ins,pc):
        if ins>>26==0 and ins&63==2:
            self.r[(ins>>11)&31]=(self.r[(ins>>16)&31]&0xFFFFFFFF)>>((ins>>6)&31);return None
        return super().extra_instruction(ins,pc)

    def changed(self):
        return {key:bytes(p) for key,p in self.pages.items() if bytes(p)!=self.original(key)}


def ordering_blocks():
    starts={start for start,_,_ in q.OT_ROUTINES}
    return [(p,b) for p,b in q.pieces() if p in starts or p in (q.OT_RESET,q.OT_LINK)]


def ordering_run(image,writes,registers,entry,replaced):
    """Run native 102610/102688 or the installed replacement; return RAM, GPRs, fetches."""
    c=OrderingCpu(image)
    if not image:c.write(0x102600,q.NATIVE(0x102600,0x140))
    blocks=ordering_blocks() if replaced else []
    for p,b in blocks:c.write(p,b)
    for p,b in writes:c.write(p,b)
    c.r=list(registers);c.r[31]=0xFEED0000;c.fetched=0
    c.run(entry)
    fetched=c.fetched
    # Put the code back so only data writes are compared, over all of memory.
    for p,b in blocks:c.write(p,image[p:p+len(b)] if image else q.NATIVE(p,len(b)) if p<q.BASE else bytes(len(b)))
    return c.changed(),list(c.r),(c.hi,c.lo),fetched


def synthetic_table(rng,count,gp):
    """Heads/tails like the native DMA buckets, including zero heads and tails
    whose chain word aliases the table itself or the first/last globals."""
    words={}
    density=rng.choice((0,.001,.01,.1,.5,1.))
    for k in range(count):
        head=OT_TAGS+k*32;tail=head if rng.random()>=density else head+16
        roll=rng.random()
        if roll<.03:head=0
        elif roll<.05:tail=OT_TABLE+8*rng.randrange(count)-4
        elif roll<.07:tail=OT_TABLE+8*rng.randrange(count)
        elif roll<.08:tail=gp+q.OT_FIRST-4
        elif roll<.09:tail=gp+q.OT_LAST-4
        words[OT_TABLE+8*k]=head;words[OT_TABLE+8*k+4]=tail
    writes=[(p,struct.pack('<I',v&0xFFFFFFFF)) for p,v in words.items()]
    writes+=[(OT_TAGS+k*32,bytes(rng.getrandbits(8) for _ in range(32))) for k in range(min(count,48))]
    writes.append((gp+q.OT_FIRST,struct.pack('<2I',rng.getrandbits(32),rng.getrandbits(32))))
    return writes


def decoded_writes(word):
    """Registers an instruction of the OT copies can write, or None if foreign."""
    op,rt,rd,fn=word>>26,(word>>16)&31,(word>>11)&31,word&63
    if op==0:return set() if fn==8 else {rd}-{0} if fn in (0,2,0x21,0x2D) else None
    if op in (9,12,35):return {rt}-{0}
    if op in (1,4,5,6,43):return set()
    return None


class QuadViewportTests(unittest.TestCase):

    def test_fusion_views_copy_authored_camera_without_merging_viewports(self):
        import multiplayer_fusion as fusion
        for humans in (2,3,4):
            for view,rect in enumerate(q.rectangles(humans)):
                c=ScalarMips({'segments':[dict(address=q.PREPARE,data_hex=q.prepare().hex())]})
                c.w(q.CONTROL+q.VIEW_COUNT,humans);c.w(c.r[28]-22172,0x2400000)
                c.w(c.r[28]-22180,0x2500000);authored=bytes(range(128));c.write(0x2500000,authored)
                c.w(fusion.CONTROL,fusion.MAGIC)
                c.w(q.SUBJECTS+4*view,view);c.w(q.core.POINTERS+4*view,0x1900000+view*0x2000)
                c.w(0x1900000+view*0x2000,view)
                c.w(q.follow.SUCCESSOR_CONTROL+8,9)
                for addr in (0x23E040,0x207DD0,0x207E78,0x23E598):
                    c.callbacks[addr]=lambda m:m.r.__setitem__(2,0)
                seen=[]
                def participating(m):seen.append(m.r[4]);m.r[2]=1
                c.callbacks[fusion.CINEMATIC]=participating
                def wrong_path(m):raise AssertionError('Fusion camera was replaced by ordinary follow')
                c.callbacks[q.cinema.VIEW]=wrong_path;c.callbacks[0x23EAD0]=wrong_path
                c.r[4]=view;c.r[31]=0xFEED0000;c.run(q.PREPARE)
                at=q.CAMERAS+view*1024
                self.assertEqual(c.read(at,128),authored)
                self.assertEqual(struct.unpack('<4I',c.read(at+512,16)),rect)
                self.assertEqual(seen,[view]);self.assertEqual(c.u(q.follow.SUCCESSOR_CONTROL+8),9)


    def test_private_visibility_builders_ignore_pause_without_unpausing_game(self):
        for start,end,pause,dest in q.CACHE_ROUTINES:
            original=q.NATIVE(start,end-start);copy=dict(q.cache_builders())[dest]
            changed=[i for i in range(0,len(copy),4) if copy[i:i+4]!=original[i:i+4]]
            self.assertEqual(changed,[pause-start])
            for paused in (False,True):
                for entry,blob,bypass in ((start,original,False),(dest,copy,True)):
                    c=ScalarMips({'segments':[dict(address=entry,data_hex=blob.hex())]})
                    scene=0x331DC8;c.w(scene+0x19F0,0x8000|(0x100 if paused else 0))
                    c.r[31]=0xFEED0000
                    c.callbacks[0x248FC0]=lambda m:m.r.__setitem__(2,0x1800000)
                    c.callbacks[0x126EC8]=lambda m:m.r.__setitem__(2,scene)
                    # Stop just after the conditional pause exit. No render
                    # callbacks need to be faked to exercise the real gate.
                    body=entry+(pause-start)+12
                    result=c.run(entry,stops=(body,))
                    self.assertEqual(result==body,bypass or not paused)
                    self.assertEqual(c.u(scene+0x19F0),0x8000|(0x100 if paused else 0))

    def test_pair_staging_uses_private_builders_with_global_pause_unchanged(self):
        c=ScalarMips({'segments':[dict(address=q.STAGE,data_hex=q.stage().hex())]})
        cameras=0x2400000;pause=0x3337B8;c.w(c.r[28]-22172,cameras);c.w(pause,0x100)
        for view in range(4):c.write(q.CAMERAS+view*1024,bytes([view+1])*656)
        calls=[]
        for addr in (0x23EF98,0x23EFD0,q.CACHE_VIEW,q.CACHE_PAIR):
            c.callbacks[addr]=lambda m,addr=addr:calls.append((addr,m.r[4],m.u(pause)))
        c.r[31]=0xFEED0000
        for pair in range(2):
            c.r[4]=pair;c.run(q.STAGE)
            for side in range(2):
                self.assertEqual(c.read(cameras+1824+side*656,656),bytes([pair*2+side+1])*656)
        self.assertEqual([arg for addr,arg,_ in calls if addr==q.CACHE_VIEW],[0,1,0,1])
        self.assertEqual([arg for addr,arg,_ in calls if addr==q.CACHE_PAIR],[1,1])
        self.assertTrue(all(flags==0x100 for _,_,flags in calls))

    def test_intro_hides_stock_status_without_hiding_dialogue_or_clash_prompts(self):
        from test_viewport_hud import machine
        from test_display_settings import install
        import display_settings as display
        for phase in (1,2,3,6):
            for offset in range(0,28,4):
                c=install(machine())
                c.write(display.HUD_DRAW_FILTER,display.hud_draw_filter_code(quad_support=True))
                c.w(display.hud_subject.CONTROL+display.hud_subject.FIELDS['active'],1)
                c.w(0x2FEB38,0x1808000);c.w(0x1808000,phase)
                c.callbacks[q.hud.ACTIVE]=lambda m:m.r.__setitem__(2,0)
                c.callbacks[q.hud.POST]=lambda m:None
                manager=0x1952000;c.w(c.r[28]-22324,manager)
                for off in range(0,28,4):c.w(manager+off,0x1960000+off*64)
                c.r[4]=c.u(manager+offset);c.r[31]=0xFEED0000
                result=c.run(display.HUD_DRAW_FILTER,stops=(display.HUD_DRAW_ENTRY+8,))
                self.assertEqual(result==0xFEED0000,phase<3 and offset in (0,8),(phase,offset))

    def test_quad_hud_is_hidden_during_intros_and_results(self):
        from test_viewport_hud import machine
        for phase,result,want in ((0,0,0),(1,0,0),(2,0,0),(3,0,1),(3,1,0),(6,0,0)):
            c=machine();c.write(q.hud.ACTIVE,q.hud.active(quad_support=True))
            c.w(0x2FEB38,0x1808000);c.w(0x1808000,phase);c.w(0x333700,result)
            c.r[31]=0xFEED0000;c.run(q.hud.ACTIVE)
            self.assertEqual(c.r[2],want,(phase,result))

    def render(self,humans=4,phase=3,result=0):
        c=ScalarMips({'segments':[dict(address=q.DRAW,data_hex=q.draw().hex())]})
        manager,cameras=0x1900000,0x2400000
        c.w(q.core.ACTORS,manager);c.w(manager,2)
        c.write(q.core.MODE,struct.pack('<4I',1,4,manager,4))
        c.write(q.CONTROL,struct.pack('<4I',q.MAGIC,manager,4,1))
        c.w(q.CONTROL+q.VIEW_COUNT,humans)
        c.write(q.cinema.CONTROL,struct.pack('<4I',q.cinema.MAGIC,manager,4,0x2000000));c.w(0x2FEB38,0x2000000);c.w(0x2000000,phase)
        c.w(0x333700,result)
        c.w(c.r[28]-22172,cameras);c.w(cameras+3136,cameras+1824)
        c.w(c.r[28]-22176,cameras+2480)
        original=bytes(i%251 for i in range(1312));c.write(cameras+1824,original)
        calls=[]
        import teammate_revive as revive
        c.w(revive.CONTROL,revive.MAGIC)
        def callback(addr):
            def call(m):
                calls.append((addr,m.r[4],m.u(q.CONTROL+20)))
                if addr==q.STAGE:
                    m.w(q.CONTROL+20,m.r[4]);m.w(q.CONTROL+16,1)
                    m.write(cameras+1824,bytes([m.r[4]+1])*1312)
                if addr==0x2490F8:m.r[2]=1
            return call
        routines=(q.PREPARE,q.STAGE,0x23EF98,0x23EFD0,0x115950,0x115DE0,0x247578,
                  0x2490F8,0x102120,0x2493A0,0x10FB80,0x24B118,0x10FC50,0x10FD98,
                  0x111E50,0x1021D8,0x12CCD0,0x102708,0x247688,0x2129C8,0x23A2B8,
                  0x2476D8,0x23E6A0)
        for routine in routines+(revive.DRAW,q.MATTE,q.TAILS):c.callbacks[routine]=callback(routine)
        c.r[31]=0xFEED0000;c.run(q.DRAW)
        return c,calls,cameras,original

    def test_three_and_four_views_begin_at_ready_not_after_fight(self):
        import teammate_revive as revive
        for humans in (3,4):
            for phase,result in ((1,0),(2,0),(3,0),(3,1),(6,0)):
                c,calls,_,_=self.render(humans,phase,result)
                native=phase not in (2,3) or result
                self.assertEqual(any(addr==q.TAILS for addr,_,_ in calls),bool(native))
                self.assertEqual([arg for addr,arg,_ in calls if addr==q.PREPARE],[] if native else list(range(humans)))
                if native:continue
                for routine in (0x10FB80,0x10FC50,0x10FD98):
                    self.assertEqual([arg for addr,arg,_ in calls if addr==routine],[2,humans-2])
                self.assertEqual(sum(addr==revive.DRAW for addr,_,_ in calls),humans)
                self.assertEqual(sum(addr==q.MATTE for addr,_,_ in calls),1)

    def test_layer_order_postprocess_and_hud_once_and_camera_restore(self):
        import teammate_revive as revive
        c,calls,cameras,original=self.render()
        ids=[x[0] for x in calls]
        self.assertLess(max(i for i,x in enumerate(ids) if x==0x102708),ids.index(revive.DRAW))
        self.assertEqual([x[2] for x in calls if x[0]==revive.DRAW],[0,0,1,1])
        for routine in (0x24B118,0x247578,0x247688,0x2129C8,0x23A2B8,0x2476D8):
            self.assertEqual(ids.count(routine),1,hex(routine))
        self.assertEqual([x[2] for x in calls if x[0]==0x10FB80],[0,1])
        self.assertLess(max(i for i,x in enumerate(ids) if x==0x10FB80),ids.index(0x24B118))
        self.assertGreater(min(i for i,x in enumerate(ids) if x==0x10FD98),ids.index(0x24B118))
        self.assertLess(max(i for i,x in enumerate(ids) if x==0x12CCD0),
                        min(i for i,x in enumerate(ids) if x==revive.DRAW),
                        'font uploads must not overwrite another view\'s cached aura textures')
        self.assertLess(ids.index(0x247688),ids.index(q.MATTE))
        self.assertLess(ids.index(q.MATTE),ids.index(0x2129C8))
        self.assertEqual(c.read(cameras+1824,1312),original)
        self.assertEqual(c.u(q.CONTROL+16),0)
        self.assertEqual(c.u(q.CONTROL+24),1)

    def test_centered_lower_view_scissor_clamps_both_axes(self):
        for y0 in (0,225):
            c=ScalarMips({'segments':[dict(address=q.SCISSOR,data_hex=q.scissor().hex())]})
            manager=0x1900000;c.w(q.core.ACTORS,manager);c.w(manager,2)
            c.write(q.core.MODE,struct.pack('<4I',1,4,manager,4))
            c.write(q.CONTROL,struct.pack('<6I',q.MAGIC,manager,4,1,1,1))
            c.w(q.CONTROL+q.VIEW_COUNT,3);c.r[4:8]=[0,511,y0,447];c.r[31]=0xFEED0000
            c.run(q.SCISSOR,stops=(q.TAILS+0x60,))
            self.assertEqual(c.r[4:8],[128,382,225,447])

    def test_three_player_camera_templates_keep_size_and_center_bottom_view(self):
        for view,rect in enumerate(q.THREE_RECTS):
            c=ScalarMips({'segments':[dict(address=q.PREPARE,data_hex=q.prepare().hex())]})
            c.w(q.CONTROL+q.VIEW_COUNT,3);c.w(c.r[28]-22172,0x2400000)
            c.fw(0x2400000+568,2.0);c.fw(0x2400000+572,2.0)
            c.w(q.SUBJECTS+4*view,view);c.w(q.core.POINTERS+4*view,0x1900000+view*0x2000)
            for addr in (0x23E040,0x207DD0,0x207E78,q.cinema.VIEW,0x23EAD0):
                c.callbacks[addr]=lambda m:m.r.__setitem__(2,0)
            c.r[4]=view;c.r[31]=0xFEED0000;c.run(q.PREPARE)
            at=q.CAMERAS+view*1024
            self.assertEqual(struct.unpack('<4I',c.read(at+512,16)),rect)
            self.assertEqual((c.fr(at+568),c.fr(at+572)),(1.,1.))
            self.assertEqual(c.fr(at+576),2048. if view==2 else 1920.+256*view)

    def test_two_player_full_height_views_preserve_projection_aspect(self):
        for wide in (False,True):
            for humans in (2,3,4):
                c=ScalarMips({'segments':[dict(address=q.PREPARE,data_hex=q.prepare().hex())]})
                c.w(q.CONTROL+q.VIEW_COUNT,humans);c.w(c.r[28]-22172,0x2400000)
                x=(6/7)*(.75 if wide else 1.)
                c.fw(0x2400000+568,x);c.fw(0x2400000+572,1.)
                c.w(q.SUBJECTS,0);c.w(q.core.POINTERS,0x1900000)
                for addr in (0x23E040,0x207DD0,0x207E78,q.cinema.VIEW,0x23EAD0):
                    c.callbacks[addr]=lambda m:m.r.__setitem__(2,0)
                c.r[4]=0;c.r[31]=0xFEED0000;c.run(q.PREPARE)
                scale=1. if humans==2 else .5
                self.assertAlmostEqual(c.fr(q.CAMERAS+568),x*scale)
                self.assertAlmostEqual(c.fr(q.CAMERAS+572),scale)
                self.assertAlmostEqual(c.fr(q.CAMERAS+568)/c.fr(q.CAMERAS+572),x)

    def test_three_player_bottom_pair_builds_only_one_visibility_cache(self):
        c=ScalarMips({'segments':[dict(address=q.STAGE,data_hex=q.stage().hex())]})
        c.w(c.r[28]-22172,0x2400000);c.w(q.CONTROL+q.VIEW_COUNT,3);calls=[]
        for addr in (0x23EF98,0x23EFD0,q.CACHE_VIEW,q.CACHE_PAIR):
            c.callbacks[addr]=lambda m,addr=addr:calls.append((addr,m.r[4]))
        c.r[4]=1;c.r[31]=0xFEED0000;c.run(q.STAGE)
        self.assertEqual([arg for addr,arg in calls if addr==q.CACHE_VIEW],[0])
        self.assertEqual([arg for addr,arg in calls if addr==q.CACHE_PAIR],[0])


class OrderingTableTests(unittest.TestCase):
    """R2: exact unrolled copies of native 102610 (reset) and 102688 (link)."""

    def test_hooks_are_full_replacements_checked_against_native_bytes(self):
        data=dict(q.pieces())
        for start,end,entry in q.OT_ROUTINES:
            self.assertEqual(data[start],q.jump(entry))
            self.assertLess(start,q.BASE)
            self.assertEqual([p for p in data if start<p<end],[])
        self.assertEqual(data[q.OT_RESET],q.ot_reset());self.assertEqual(data[q.OT_LINK],q.ot_link())
        self.assertLessEqual(q.OT_RESET+len(q.ot_reset()),q.OT_LINK)
        self.assertLessEqual(q.OT_LINK+len(q.ot_link()),q.CONTROL)
        # Only the four relocated native heads use TAILS; nothing returns into 102610/102688.
        self.assertEqual(sorted(p for p in data if q.TAILS<=p<q.CAMERAS),[q.TAILS+32*i for i in range(4)])

    def test_copies_touch_only_native_registers_and_loop_at_least_seven_words(self):
        for code,base,allowed in ((q.ot_reset(),q.OT_RESET,{2,3,4,5}),(q.ot_link(),q.OT_LINK,{2,3,4,6})):
            words=struct.unpack(f'<{len(code)//4}I',code)
            for i,word in enumerate(words):
                written=decoded_writes(word)
                self.assertIsNotNone(written,hex(base+4*i))
                self.assertLessEqual(written,allowed,hex(base+4*i))
                if word>>26 in (35,43):self.assertIn((word>>21)&31,(2,4,28))
                if word>>26==0 and word&63==8:self.assertEqual((word>>21)&31,31)
                if word>>26 in (1,4,5,6):
                    target=i+1+struct.unpack('<h',struct.pack('<H',word&0xFFFF))[0]
                    self.assertTrue(0<=target<len(words))
                    # R5900 short loops: the native loop pads to seven words.
                    if target<=i:self.assertGreaterEqual(i+2-target,7,hex(base+4*i))

    def test_copies_match_native_memory_and_every_register_on_synthetic_tables(self):
        rng=random.Random(20260922);gp=OrderingCpu().r[28]
        counts=list(range(18))+[31,32,33,63,64,65,-1,-7,0x7FFFFFFF+1,OT_ENTRIES,OT_ENTRIES,OT_ENTRIES]
        counts+=[rng.choice((1,2,3,4,5,6,7,8,9,16,33,40,70,101)) for _ in range(400-len(counts))]
        for trial,count in enumerate(counts):
            size=count if 0<count<=OT_ENTRIES else 0
            writes=synthetic_table(rng,size,gp)
            registers=[0]+[rng.getrandbits(32) for _ in range(31)]
            registers[28],registers[29],registers[4],registers[5]=gp,0x1FFF000,OT_TABLE,count&0xFFFFFFFF
            for entry in (0x102610,0x102688):
                native=ordering_run(b'',writes,registers,entry,False)
                copy=ordering_run(b'',writes,registers,entry,True)
                self.assertEqual(copy[:3],native[:3],(trial,count,hex(entry)))
                if entry==0x102610:self.assertEqual(copy[1][2],1)
                if count==OT_ENTRIES:self.assertLessEqual(copy[3],native[3]+2)

    @unittest.skipUnless((AI_READY/'14-ai-ready.bin').exists(),'prepared fixture not retained')
    def test_copies_match_native_on_the_real_table_and_save_the_measured_work(self):
        image=(AI_READY/'14-ai-ready.bin').read_bytes()
        self.assertEqual(image[0x102600:0x102740],q.NATIVE(0x102600,0x140))
        u=lambda p:struct.unpack_from('<I',image,p)[0]
        gp=OrderingCpu().r[28];table=u(gp-22976)
        heads=struct.unpack_from(f'<{2*OT_ENTRIES}I',image,table)[0::2]
        rng=random.Random(8196)
        for filled in (0,1,12,300):
            # Real bucket heads; filled buckets end at another bucket's real tag.
            writes=[(table+8*k+4,struct.pack('<I',heads[rng.randrange(OT_ENTRIES)]+16)) for k in rng.sample(range(OT_ENTRIES),filled)]
            registers=[0]+[rng.getrandbits(32) for _ in range(31)]
            registers[28],registers[29],registers[4],registers[5]=gp,0x1FFF000,table,OT_ENTRIES
            for entry,limit in ((0x102688,.75),(0x102610,.42)):
                native=ordering_run(image,writes,registers,entry,False)
                copy=ordering_run(image,writes,registers,entry,True)
                self.assertEqual(copy[:3],native[:3],(filled,hex(entry)))
                if filled<=1:self.assertLess(copy[3],native[3]*limit,(filled,hex(entry),copy[3],native[3]))

    @unittest.skipUnless((AI_READY/'14-ai-ready.bin').exists(),'prepared fixture not retained')
    def test_build_refuses_changed_native_routines_and_leaves_presets_without_hooks_valid(self):
        import battle_mode_policy as policy
        import four_player_mode
        from test_battle_mode_pipeline import compose
        ram=bytearray((AI_READY/'14-ai-ready.bin').read_bytes())
        u=lambda p:struct.unpack_from('<I',ram,p)[0]
        manager,count=u(q.core.ACTORS),u(q.core.MODE+12)
        struct.pack_into('<4I',ram,q.core.MODE,1,count,manager,count)
        blocks={b['address']:b for b in q.build_memory(bytes(ram))['blocks']}
        for start,end,entry in q.OT_ROUTINES:
            self.assertEqual(blocks[start]['expected_hex'],q.NATIVE(start,8).hex())
            self.assertEqual(blocks[start]['data_hex'],q.jump(entry).hex())
            for at in (start,end-4):
                changed=bytearray(ram);changed[at]^=1
                with self.assertRaisesRegex(ValueError,'Native ordering-table routine changed'):q.build_memory(bytes(changed))
        # A preset prepared before R2 has the native entries and an empty copy
        # area. Nothing that validates a prepared four-player image reads them.
        source=(AI_READY/'14-ai-ready.bin').read_bytes()
        installation=json.loads((AI_READY/'ai-installation.json').read_text())
        support=json.loads((AI_READY/'support.json').read_text())
        with policy.building_for(5):
            ram,_,manifest=compose(source,installation,support,'coop',4,0x57,{'revive_enabled':True,'fusion_duration_enabled':True})
        self.assertTrue({start for start,_,_ in q.OT_ROUTINES}<={b['address'] for b in manifest['blocks']})
        older=bytearray(ram)
        for p,b in ordering_blocks():older[p:p+len(b)]=q.NATIVE(p,len(b)) if p<q.BASE else bytes(len(b))
        import teammate_revive as revive,cinematic_policy as cinema,fusion_duration,battle_modes,special_pause
        results=[]
        for image in (ram,older):
            with policy.building_for(5):
                results.append((four_player_mode.installed(image),four_player_mode.validate_pad(image),
                                revive.validate_memory(image),cinema.validate_memory(image),
                                fusion_duration.validate_memory(image),battle_modes.validate_memory(image),
                                special_pause.configure_memory(image,mode='none')['blocks'],
                                [four_player_mode.dependency_override(image,at,old) for at,old,_ in four_player_mode.variants(image)]))
        self.assertEqual(results[0],results[1]);self.assertTrue(results[1][0])


if __name__=='__main__':unittest.main()
