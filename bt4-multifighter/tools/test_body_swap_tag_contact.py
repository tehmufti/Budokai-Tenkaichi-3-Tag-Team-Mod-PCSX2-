"""Body Change must attach after the final tag/scenario contact composition."""
# Native execution tests require the developer's extracted executable.
from pathlib import Path as _TestPath
import unittest as _TestUnit
from native_map import elf_path as _test_elf_path
_test_root = _TestPath(__file__).resolve().parents[1]
if not _test_elf_path(_test_root).is_file():
    raise _TestUnit.SkipTest('An extracted game executable is required for native tests')

import struct
import unittest

import battle_mode_policy as policy
import body_swap as body
import body_swap_capture as capture
import body_swap_runner as runner
import body_swap_worker as worker
import fusion_duration as timer
import native_preparation as native
import story_runtime as story
import tag_rush_safety as tag
import tag_rush_launch as launch
import tag_team_rush


class Client:
    def __init__(self,ram):self.ram=ram;self.writes=[]
    def read(self,at,size):return bytes(self.ram[at:at+size])
    def read_u32(self,at):return struct.unpack_from('<I',self.ram,at)[0]
    def write(self,at,data):self.ram[at:at+len(data)]=data;self.writes.append(at)


def machine(*,capacity=policy.TEAM_CAPACITY,count=8,scenario=False,timed=False):
    ram=bytearray(0x8000000)
    def put(at,data):ram[at:at+len(data)]=data
    def word(at,value):struct.pack_into('<I',ram,at,value)
    manager=0x1900000
    word(body.core.ACTORS,manager);word(manager,2)
    put(body.core.MODE,struct.pack('<4I',1,count,manager,count))
    put(body.participation.CONTROL,struct.pack('<5I',5,manager,count,(1<<count)-1,0))
    for index in range(count):
        actor=0x2200000+index*0x2000
        word(body.core.POINTERS+4*index,actor);word(actor,index)
    # Include one genuine Ginyu owner so successful attachment must publish it.
    actor=struct.unpack_from('<I',ram,body.core.POINTERS)[0]
    word(actor+0x998,1);word(actor+0x9A4,body.GINYU)
    put(body.CONTROL,struct.pack('<3I',body.MAGIC,manager,count))
    put(runner.CONTROL,struct.pack('<8I',body.MAGIC,0,0,0,manager,0,0,runner.fusion.CONTACT))
    word(native.CONTROL+16,1);word(native.CONTROL+20,1)
    with policy.building_for(capacity):
        put(runner.fusion.CONTACT,runner.fusion.contact_code())
        for at,data in runner.program(runner.fusion.CONTACT)+capture.program():put(at,data)
        if timed:
            for at,data in timer.program(runner.ENTRY,timer.feed.DRAW):put(at,data)
            put(timer.fusion.BEGIN,timer.fusion.begin_code(True))
            put(timer.fusion.COMMIT,timer.fusion.commit_code(True))
            put(timer.CONTROL,struct.pack('<11I',timer.MAGIC,manager,count,0,1200,1,0,0xffffffff,
                                         runner.ENTRY,timer.feed.DRAW,0))
            put(runner.HOOK,timer.JUMP(timer.FRAME))
        previous=timer.JUMP(runner.PROTECTED)
        if scenario:
            put(story.CONTROL,struct.pack('<3I',story.MAGIC,manager,count))
            put(story.CONTACT,story.protection_code(story.CONTACT,runner.PROTECTED,'contact'))
            previous=story.jump(story.CONTACT)
        put(tag.CONTROL,struct.pack('<4I',tag_team_rush.MAGIC,manager,count,1))
        put(tag.CONTACT,tag.contact_code());put(tag.TRAMPOLINE,tag.trampoline_code(previous))
        put(runner.contact.PROTECTED,timer.JUMP(tag.CONTACT))
    return Client(ram)


def attach(client):
    def apply(p,plan):
        assert (p.read_u32(native.CONTROL+16),p.read_u32(native.CONTROL+20))==(1,1)
        for block in plan['blocks']:
            at=block['address'];data=bytes.fromhex(block['data_hex'])
            assert p.read(at,len(data)).hex()==block['expected_hex']
            p.write(at,data)
    service=worker.Worker(apply=apply)
    service.attach(client)
    return service


class BodyTagContactTests(unittest.TestCase):
    def test_attach_and_full_validation_accept_exact_composed_chains(self):
        for capacity,count in ((policy.TEAM_CAPACITY,4),(policy.TEAM_CAPACITY,8),
                               (policy.TEAM_CAPACITY,10),(policy.LEGACY_TEAM_CAPACITY,6)):
            for scenario in (False,True):
                for timed in (False,True):
                    with self.subTest(capacity=capacity,count=count,scenario=scenario,timed=timed):
                        p=machine(capacity=capacity,count=count,scenario=scenario,timed=timed)
                        with policy.building_for(capacity):
                            self.assertEqual(runner.validate_memory.__wrapped__(p.ram),runner.fusion.CONTACT)
                        service=attach(p)
                        self.assertTrue(service.active);self.assertEqual(service.capacity,capacity)
                        self.assertEqual(p.read_u32(body.OWNERS),1)
                        self.assertEqual(p.read_u32(body.CONTROL+20),1)
                        self.assertTrue(service.installed(p))
                        self.assertEqual(p.writes,[body.OWNERS,body.CONTROL+20])

    def test_changed_wrapper_or_inner_program_is_rejected_before_any_write(self):
        changes={
            'tag magic':(tag.CONTROL,0), 'tag manager':(tag.CONTROL+4,0),
            'tag count':(tag.CONTROL+8,4), 'tag code':(tag.CONTACT+24,0),
            'continuation':(tag.TRAMPOLINE,struct.unpack_from('<I',story.jump(runner.JOB))[0]),
            'continuation delay':(tag.TRAMPOLINE+4,1),
            'story magic':(story.CONTROL,0), 'story manager':(story.CONTROL+4,0),
            'story code':(story.CONTACT+24,0), 'body code':(runner.PROTECTED+24,0),
            'capture code':(capture.CAPTURE+24,0), 'timer code':(timer.FRAME+24,0),
        }
        for name,(at,value) in changes.items():
            with self.subTest(change=name):
                p=machine(scenario=True,timed=True)
                original=p.read_u32(at)
                struct.pack_into('<I',p.ram,at,value if value!=original else value^1)
                with self.assertRaises(ValueError):attach(p)
                self.assertEqual(p.writes,[])
                self.assertEqual(p.read_u32(body.CONTROL+20),0)
                with self.assertRaises(ValueError):runner.validate_memory(p.ram)

    def test_uninstalled_tag_guard_does_not_override_existing_contact_checks(self):
        p=machine()
        original=timer.JUMP(runner.PROTECTED)
        p.ram[runner.contact.PROTECTED:runner.contact.PROTECTED+8]=original
        self.assertEqual(story.dependency_override(p.ram,runner.contact.PROTECTED,original),original)
        self.assertTrue(attach(p).active)

    def test_older_dependency_can_try_its_body_change_aware_fallback(self):
        p=machine(scenario=True)
        prior=timer.JUMP(runner.fusion.CONTACT)
        self.assertEqual(story.dependency_override(p.ram,runner.contact.PROTECTED,prior),prior)
        own=timer.JUMP(runner.PROTECTED)
        self.assertEqual(story.dependency_override(p.ram,runner.contact.PROTECTED,own),timer.JUMP(tag.CONTACT))

    def test_native_dispatcher_substitution_preserves_all_other_bytes(self):
        p=machine()
        at=launch.COMMIT_HOOK-8
        original=b'12345678'+launch.COMMIT_NATIVE+b'abcdefgh'
        patched=original[:8]+launch.COMMIT_PATCH+original[12:]
        p.ram[at:at+len(original)]=original
        self.assertEqual(launch.dependency_override(p.ram,at,original),original)
        p.ram[at:at+len(patched)]=patched
        code=launch.commit_code();p.ram[launch.COMMIT:launch.COMMIT+len(code)]=code
        self.assertEqual(launch.dependency_override(p.ram,at,original),patched)
        p.ram[at]^=1
        self.assertNotEqual(p.read(at,len(patched)),launch.dependency_override(p.ram,at,original))
        p.ram[launch.COMMIT+24]^=1
        with self.assertRaises(ValueError):launch.dependency_override(p.ram,at,original)

    def test_native_dispatcher_rejects_foreign_match_receipts(self):
        for at in (tag.CONTROL,tag.CONTROL+4,tag.CONTROL+8):
            with self.subTest(at=at):
                p=machine()
                p.ram[launch.COMMIT_HOOK:launch.COMMIT_HOOK+4]=launch.COMMIT_PATCH
                code=launch.commit_code();p.ram[launch.COMMIT:launch.COMMIT+len(code)]=code
                struct.pack_into('<I',p.ram,at,0)
                with self.assertRaises(ValueError):launch.dependency_override(p.ram,launch.COMMIT_HOOK,launch.COMMIT_NATIVE)


if __name__=='__main__':unittest.main()
