"""Expand preserved prepared presets, holding start until native initialization ends.

This is an offline copier stage. It never connects to PCSX2, changes the source
archive, or starts a watcher. The guest initializers run synchronously ahead of
the existing start gate; only that gate may restore the preset CPU assignments.
"""
from native_map import TRANSLATED, elf_path
import struct

from prototype import Assembler
import fresh_team_combat as core
import team_start_gate as start
import fresh_memory
import patch_state
from fresh_team_trainer import compose_manifests
from battle_mode_policy import ACTOR_COUNTS

CODE, TRAMPOLINE, CONTROL, END = 0x0777E000, 0x0777EC00, 0x0777EF00, 0x07780000
MAGIC = 0x50434631
# (Name, status/control, captured count offset). Manager is always at +4.
COMPONENTS = (
    ('ordinary aura', 0x0754F000, 12),
    ('giant and afterimage', 0x07584C00, 8),
    ('generic and tracked effects', 0x075DF000, 8),
    ('ground and auxiliary effects', 0x07703C00, 8),
    ('special effects', 0x0750F000, 8),
    ('spawn placement', 0x0745E000, 8),
    ('fighter participation', 0x077CF000, 8),
)


def code():
    a = Assembler(CODE); a.addiu(29, 29, -0x40)
    for i, r in enumerate(range(8, 16)): a.i(63, r, 29, i*8)
    a.li(14, CONTROL); a.li(15, start.CONTROL)
    # Never touch another match, or rearm an already released start gate.
    a.lw(8, 15); a.addiu(9, 0, 1); a.branch(5, 8, 9, 'done')
    a.lw(11, 14, 8); a.lw(8, 28, -22364); a.branch(5, 8, 11, 'done')
    a.lw(8, 15, 8); a.branch(5, 8, 11, 'done')
    a.lw(12, 14, 12); a.lw(8, 15, 12); a.branch(5, 8, 12, 'error')
    a.lw(8, 14); a.addiu(9, 0, 5); a.branch(4, 8, 9, 'ready_again')
    a.branch(5, 8, 0, 'held')
    core.gate(a, 'held'); a.branch(5, 10, 12, 'error')
    a.li(8, core.PAIR+4); a.lw(8, 8); a.branch(5, 8, 0, 'held')
    a.move(13, 0)
    a.label('actor'); a.r(0, 9, 0, 13, 4); a.r(0x21, 10, 14, 9)
    a.lw(9, 10, 0x40); a.r(0, 8, 0, 13, 2); a.li(11, core.POINTERS)
    a.r(0x21, 11, 11, 8); a.lw(8, 11); a.branch(5, 8, 9, 'error')
    a.lw(8, 9); a.branch(5, 8, 13, 'error')
    a.lw(8, 9, 12); a.lw(11, 10, 0x44); a.branch(5, 8, 11, 'error')
    a.r(0, 8, 0, 11, 2); a.li(9, core.MODELS); a.r(0x21, 9, 9, 8)
    a.lw(8, 9); a.lw(9, 10, 0x48); a.branch(5, 8, 9, 'error')
    a.lw(8, 9, 16); a.branch(5, 8, 11, 'error')
    a.addiu(13, 13, 1); a.branch(5, 13, 12, 'actor')
    a.lw(11, 14, 8); a.move(13, 0)
    for i, (_, address, count_offset) in enumerate(COMPONENTS):
        a.li(10, address); a.lw(8, 10, 4); a.branch(5, 8, 11, 'error')
        a.lw(8, 10, count_offset); a.branch(5, 8, 12, 'error')
        a.lw(8, 10); a.addiu(9, 0, 5); a.branch(4, 8, 9, f'component_{i}')
        # Pending initializers use 0 or 1. Any explicit error is terminal.
        a.i(11, 9, 8, 2); a.branch(4, 9, 0, 'error')
        a.addiu(13, 0, 1); a.label(f'component_{i}')
    a.branch(5, 13, 0, 'held')
    a.addiu(8, 0, 5); a.sw(8, 14)
    a.label('ready_again'); a.lw(8, 14, 16); a.sw(8, 15, 4); a.jump('done')
    a.label('error'); a.addiu(8, 0, 101); a.sw(8, 14)
    a.label('held'); a.sw(0, 15, 4)
    a.label('done')
    for i, r in enumerate(range(8, 16)): a.i(55, r, 29, i*8)
    a.addiu(29, 29, 0x40); a.jump(TRAMPOLINE)
    result = a.finish(); assert len(result) <= TRAMPOLINE-CODE; return result


def gate_memory(ram, source='<offline>'):
    require = lambda ok, text: None if ok else (_ for _ in ()).throw(ValueError(text))
    require(len(ram) == 0x8000000, 'Requires128MiB EE checkpoint')
    u = lambda p: struct.unpack_from('<I', ram, p)[0]
    manager, count = u(core.ACTORS), u(core.MODE+4)
    require(0x100000 <= manager <= len(ram)-16 and u(manager) == 2, 'Invalid captured native manager')
    require(count in ACTOR_COUNTS and (u(core.MODE), u(core.MODE+8), u(core.MODE+12)) == (1, manager, count)
            and u(core.PAIR+4) == 0, 'Requires captured active team without aliases')
    require(tuple(u(start.CONTROL+o) for o in (0, 4, 8, 12)) == (1, 1, manager, count)
            and u(fresh_memory.CONTROL+80) == 1, 'Preserved preset must still be held with start requested')
    require(not any(ram[CODE:END]), 'Preset readiness reservation occupied')
    native_size = len(start.code(0)); tail = u(start.CODE+native_size-8)
    require(tail >> 26 == 2, 'Changed prepared start continuation')
    previous = (tail & 0x3FFFFFF) << 2
    original = start.code(previous)
    require(ram[start.CODE:start.CODE+len(original)] == original, 'Changed prepared start gate')
    control = bytearray(0x100); struct.pack_into('<6I', control, 0, 0, MAGIC, manager, count, 1, previous)
    for i in range(count):
        actor = u(core.POINTERS+4*i)
        require(0x100000 <= actor <= len(ram)-0x1600 and u(actor) == i, 'Changed actor identity')
        mid = u(actor+12); require(mid < 12, 'Unregistered actual model')
        model = u(core.MODELS+4*mid)
        require(0x100000 <= model <= len(ram)-0x1670 and u(model+16) == mid, 'Changed model identity')
        require(u(actor+0x948) == 11 and not any(u(actor+o) for o in (0x1278, 0x127C, 0x1280, 0x1284)),
                'Preserved preset actors must remain held idle')
        cpu = u(start.CONTROL+0x40+4*i)
        require(cpu in (0, 1) and u(start.CONTROL+0x80+4*i) == actor, 'Changed saved CPU/actor assignment')
        struct.pack_into('<4I', control, 0x40+i*16, actor, mid, model, cpu)
    for name, address, offset in COMPONENTS:
        require((u(address+4), u(address+offset)) == (manager, count) and u(address) in (0, 1, 5),
                f'{name} initializer is missing, failed, or belongs to another team')
    pieces = [(CODE, code()), (TRAMPOLINE, original[:8]+struct.pack('<2I', (2<<26)|((start.CODE+8)>>2), 0)),
              (CONTROL, bytes(control)), (start.REQUEST, bytes(4)),
              (start.CODE, struct.pack('<2I', (2<<26)|(CODE>>2), 0))]
    return dict(serial=patch_state.SERIAL, crc=patch_state.CRC, source=str(source), control=CONTROL,
                components=[dict(name=name, control=p) for name,p,_ in COMPONENTS],
                blocks=[dict(address=p, expected_hex=ram[p:p+len(b)].hex(), data_hex=b.hex()) for p,b in pieces])


def transport_memory(ram, source='<offline>'):
    """Retain the reviewed late-frame service, with the loading cover disabled."""
    import guest_loading_screen as loading
    import native_preparation as native
    import mode_menu
    import select_duplicates
    import native_mode_menu
    import native_menu_services
    from prototype import ROOT, elf_reader
    original = elf_reader(elf_path(ROOT))[2]
    pieces = loading.code_pieces()
    import json
    previous_menus=[{row['address']:bytes.fromhex(row['data_hex']) for row in json.loads(
        (ROOT/'analysis/sept22-before-ffa-slot-labels.json').read_text())},
        {row['address']:bytes.fromhex(row['data_hex']) for row in json.loads(
        (ROOT/'analysis/sept22-before-selection-control-menu-code.json').read_text())},
        {row['address']:bytes.fromhex(row['data_hex']) for row in json.loads(
        (ROOT/'analysis/sept20-evening-before-menu-texture.json').read_text())},{row['address']:bytes.fromhex(row['data_hex']) for row in json.loads(
        (ROOT/'analysis/sept20-before-ui-repair-menu-code.json').read_text())},{int(p):bytes.fromhex(b) for p,b in json.loads(
        (ROOT/'analysis/sept19-native-menu-v2-code.json').read_text()).items()},
        {row['address']:bytes.fromhex(row['data_hex']) for row in json.loads(
            (ROOT/'analysis/sept19-before-training-menu-code.json').read_text())},
        # Exact training-three-row release, independently matched to the real
        # Sept20 01:10 held capture. Choice11 extends these helpers; accepting
        # only older pre-training code would strand recently prepared presets.
        {row['address']:bytes.fromhex(row['data_hex']) for row in json.loads(
            (ROOT/'analysis/sept20-before-coop-training-menu-code.json').read_text())},
        {row['address']:bytes.fromhex(row['data_hex']) for row in json.loads(
            (ROOT/'assets/native-menu-pre-settings.json').read_text())}]
    if TRANSLATED:previous_menus=[]  # USA-only prior menu images (native USA hook addresses)
    # Three-player selection grew into the old prompt entry at 07699800;
    # that dormant prompt now starts at 07699900. Validate the complete owned
    # code interval as one image, including zeros between/after its helpers.
    # Comparing just the former selector plus padding would mistake its old
    # adjacent prompt for foreign bytes. Accept only a complete known layout.
    import coop_character_select as selection
    def selection_image(parts):
        image=bytearray(selection.DATA-selection.CODE)
        found=[]
        for p,data in parts:
            if selection.CODE<=p<selection.DATA:
                if p+len(data)>selection.DATA:
                    raise ValueError('Prepared native transport selector exceeds code reservation')
                found.append((p,data))
        spans=sorted((p,p+len(data)) for p,data in found)
        if any(end>start for (_,end),(start,_) in zip(spans,spans[1:])):
            raise ValueError('Prepared native transport selector helpers overlap')
        for p,data in found:image[p-selection.CODE:p-selection.CODE+len(data)]=data
        return found,bytes(image)
    selected,combined=selection_image(pieces)
    if selected:
        pieces=[(p,data) for p,data in pieces if not selection.CODE<=p<selection.DATA]+[(selection.CODE,combined)]
        for previous in previous_menus:
            prior,image=selection_image(previous.items())
            if prior:
                for p,_ in prior:del previous[p]
                previous[selection.CODE]=image
    # The first native-menu build occupied part of the transport packet arena.
    # Retire only its exact dormant code image, with every other packet byte
    # zero. Never clear a pending packet or accept an unknown legacy mutation.
    legacy_address=0x07A00000
    legacy=(ROOT/'analysis/sept19-native-menu-v1-payload.bin').read_bytes()
    legacy_packet=bytes(ram[native.PACKET:native.PACKET+native.CAPACITY])
    old_packet=bytearray(native.CAPACITY)
    offset=legacy_address-native.PACKET;old_packet[offset:offset+len(legacy)]=legacy
    retire_legacy=legacy_packet==bytes(old_packet)
    if retire_legacy:pieces=pieces+[(legacy_address,bytes(len(legacy)))]
    # Pieces that overwrite ELF code start out holding the ELF's own bytes, not
    # the zeros of a mod reservation. The select-screen unlock is one of them.
    elf_pieces = (native.HOOK, loading.HOOK, mode_menu.HOOK, select_duplicates.CONFLICT, *native_menu_services.HOOKS)
    for p in (native.HOOK,loading.HOOK):
        if ram[p+4:p+8] != original(p+4,4):
            raise ValueError(f'Prepared native transport delay slot changed:{p+4:08X}')
    # Loading code pieces are compared and rewritten over their WHOLE reservation
    # (start: (end, legacy images)), so a captured legacy image may be longer than
    # the current one (v3 payload > v4 payload) and its stale tail is zeroed on
    # upgrade, while a foreign byte anywhere in the span still rejects. The KS
    # pieces have no legacy: zero or current. The retired v3 buffers at
    # 0x07480000 and the v4 BUFFERS hold pictures in held captures and are
    # deliberately outside every zero requirement below.
    import loading_lights_a
    import loading_lights_b
    loading_spans={loading.CODE:(loading.CONTROL,loading.legacy_payloads()),
                   loading.SUBS:(loading.SUBS_END,loading.legacy_subs()),
                   loading_lights_a.CODE:(loading_lights_a.END,()),
                   loading_lights_b.CODE:(loading_lights_b.END,())}
    for p,data in pieces:
        if p in loading_spans and len(data)>loading_spans[p][0]-p:raise ValueError('Loading code piece exceeds its reservation')
    pieces=[(p,data+bytes(loading_spans[p][0]-p-len(data))) if p in loading_spans else (p,data) for p,data in pieces]
    # A helper can shrink between releases. Validate its old tail and a guard
    # word too, otherwise a foreign instruction just past the new end escapes
    # validation. Never extend into an adjacent helper/control reservation.
    menu_starts=sorted(p for p,_ in pieces if native_mode_menu.CODE<=p<native_mode_menu.CONTROL)
    menu_ends={p:min([q for q in menu_starts if q>p]+[native_mode_menu.CONTROL]) for p in menu_starts}
    expanded=[]
    for p,data in pieces:
        if p in menu_ends:
            span=max([len(data)]+[len(prior.get(p,b'')) for prior in previous_menus])
            if p+span>menu_ends[p]:raise ValueError('Prepared native transport menu span overlaps next helper')
            span+=min(4,menu_ends[p]-p-span)
            data+=bytes(span-len(data))
        expanded.append((p,data))
    pieces=expanded
    for p,data in pieces:
        expected = original(p,len(data)) if p in elf_pieces else bytes(len(data))
        allowed=(expected,data)
        if p==mode_menu.CODE:
            for version in (1,2):
                previous=(ROOT/f'analysis/sept19-duel-route-v{version}-payload.bin').read_bytes()
                if len(previous)>len(data):raise ValueError('Prior Duel router exceeds new span')
                allowed+=(previous+bytes(len(data)-len(previous)),)
        for previous_menu in previous_menus:
            previous=previous_menu.get(p)
            if previous is not None:
                if len(previous)>len(data):raise ValueError('Prior native menu payload exceeds new span')
                allowed+=(previous+bytes(len(data)-len(previous)),)
        if p==native.GATE:
            # The dispatch gate grew two magic-gated background-reload call
            # sites. A preset captured before that change carries the previous
            # emission followed by reservation zeros; accept and rewrite it
            # exactly as the previous native menu payloads are accepted.
            previous=(ROOT/'analysis/sept20-before-background-io-gate.bin').read_bytes()
            if len(previous)>len(data):raise ValueError('Prior native dispatch gate exceeds new span')
            allowed+=(previous+bytes(len(data)-len(previous)),)
            # beta.35/36 captures: the same gate with the phase-1 rewrite limited to substates below 4.
            for previous in native.previous_gate_images():
                if len(previous)>len(data):raise ValueError('Prior native dispatch gate exceeds new span')
                allowed+=(previous+bytes(len(data)-len(previous)),)
        if p==native.CODE:
            for previous in native.previous_service_images():
                if len(previous)>len(data):raise ValueError('Prior native preparation service exceeds new span')
                allowed+=(previous+bytes(len(data)-len(previous)),)
        if p==mode_menu.HOOK:
            allowed+=(dict(mode_menu.code_pieces())[mode_menu.HOOK],struct.pack('<2I',(2<<26)|(legacy_address>>2),0))
        if p==legacy_address and retire_legacy:allowed+=(legacy,)
        if p in loading_spans:
            # Earlier prepared presets carry the September16 or v3 emissions;
            # all are dormant data here and are replaced by the current image.
            allowed+=tuple(previous+bytes(len(data)-len(previous)) for previous in loading_spans[p][1])
        if ram[p:p+len(data)] not in allowed:
            raise ValueError(f'Prepared native transport reservation or hook changed:{p:08X}')
    for p,size in ((native.CONTROL,256),(loading.CONTROL,64),(native.PACKET,native.CAPACITY),
                   (mode_menu.CONTROL,64)):
        if any(ram[p:p+size]) and not(p==native.PACKET and retire_legacy):
            raise ValueError('Prepared native transport control/packet storage must be unused')
    control=bytearray(256);struct.pack_into('<I',control,0,native.MAGIC)
    pieces=pieces+[(native.CONTROL,bytes(control)),(loading.CONTROL,bytes(64))]
    return dict(serial=patch_state.SERIAL,crc=patch_state.CRC,source=str(source),
                blocks=[dict(address=p,expected_hex=ram[p:p+len(data)].hex(),data_hex=data.hex())
                        for p,data in pieces])


def build_memory(ram, source='<offline>'):
    import multi_contact
    return multi_contact.prior_manifest(ram,lambda view:_build_memory(view,source=source))


def _build_memory(ram, source='<offline>'):
    # Import lazily: this is an optional prepared-preset stage, not a launcher
    # process. All four builders require a pristine held source or exact v1.
    import extra_charge_aura as ordinary
    import extra_extended_auras as extended
    import extra_generic_effects as generic
    import extra_ground_effects as ground
    import extra_reload_worker as reload_worker
    import extra_throws
    import extra_positional_audio
    import camera_continuity
    import team_participation
    import fusion_partner_lifecycle
    import initial_targets
    import special_camera_arbitration
    import special_concurrency
    import ordinary_form_admission
    import finished_camera_cleanup
    import beam_clash
    import dash_clash
    import spawn_placement
    import spectator_switch
    # Validate and upgrade the exact preserved frame chain before adding any
    # new outer wrappers. Original preset archives remain untouched.
    builders = [lambda r: spawn_placement.upgrade_memory(r, source=source)]
    builders += [lambda r, module=m: module.build_memory(r, source=source)
                 for m in (extra_throws, ordinary, extended, generic, ground, extra_positional_audio)]
    builders.append(lambda r: camera_continuity.build_memory(r, source=source))
    builders.append(lambda r: transport_memory(r, source=source))
    # Request capture is live, but native form admission remains dormant until
    # the owned host worker validates and attaches after the preset starts.
    builders.append(lambda r: reload_worker.install_memory(r, source=source, enabled=True, forms=True))
    builders.append(lambda r: spectator_switch.build_memory(r, source=source))
    builders.append(lambda r: team_participation.build_memory(r, source=source))
    builders.append(lambda r: fusion_partner_lifecycle.build_memory(r, source=source))
    builders.append(lambda r: initial_targets.build_memory(r, source=source))
    builders.append(lambda r: special_camera_arbitration.build_memory(r, source=source))
    builders.append(lambda r: special_concurrency.build_memory(r, source=source))
    builders.append(lambda r: ordinary_form_admission.build_memory(r, source=source))
    builders.append(lambda r: finished_camera_cleanup.build_memory(r, source=source))
    builders.append(lambda r: beam_clash.build_memory(r, source=source))
    builders.append(lambda r: dash_clash.build_memory(r, source=source))
    builders.append(lambda r: gate_memory(r, source=source))
    result = compose_manifests(ram, builders)
    result.update(source=str(source), control=CONTROL,
                  forms=True, common_positional_audio=True,
                  status='Pending native effect initialization; guest start is held until every component is ready')
    return result
