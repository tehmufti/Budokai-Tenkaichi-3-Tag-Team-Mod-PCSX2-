"""Read-only validation of PCSX2 128 MiB states with save version 0x9A590000.

That save version covers the 2.8.x releases (2.8.0-2.8.2 tested) and the 2.7.x/2.9.x
nightlies that share it; pcsx2_versions.json names the accepted tags. Audited
SaveState.cpp, Counters.h/cpp, Memory.cpp, GS.cpp at release v2.8.0; those files are
unchanged at v2.8.2 (verified against a live 2.8.2 capture), and PCSX2 changes the save
version whenever the saved data changes. Only EE bytes are patched; internal structures
are preserved byte-for-byte. States are never converted between emulator versions.
"""
import math
import struct
import pcsx2_versions
import state128 as legacy

VERSION=0x9A590000
COUNTER_BYTES=4*32+2*24+4+8+40+4+1


def inspect_payload(version,internals,memory_size):
    require=legacy.require
    family=pcsx2_versions.state_family(version)
    require(family['layout']=='state28' and family['save_version']==VERSION,
            f"Save version 0x{family['save_version']:08X} does not use the 2.8 layout")
    require(memory_size==legacy.TOTAL_RAM,'Input must contain exactly 128 MiB EE RAM')
    bios,cpu,cycles,ee,iop=(legacy.unique_tag(internals,n) for n in ('BIOS','cpuRegs','Cycles','EE-Subsystems','IOP-Subsystems'))
    require(bios==0 and bios<cpu<cycles<ee<iop,'Unexpected 2.8 section order')
    require(ee==cycles+32+36,'Unexpected 2.8 cycle timer sizes')
    counters=ee+32;mem=counters+COUNTER_BYTES;flag=mem+legacy.MEMORY_DEVICE_BYTES;gs=flag+1
    require(gs+0x2000+4<iop<=len(internals)-32,'Inconsistent 2.8 subsystem boundaries')
    require(internals[cycles+44:cycles+56]==internals[counters+176:counters+188],
            'Duplicate 2.8 timer fields disagree')
    fps=struct.unpack_from('<d',internals,counters+188)[0]
    require(math.isfinite(fps) and 1<=fps<=240,'Invalid 2.8 counter frame rate')
    mode=struct.unpack_from('<I',internals,counters+228)[0]
    require(1<=mode<=11 and mode==struct.unpack_from('<I',internals,gs+0x2000)[0],'Duplicate 2.8 GS modes disagree')
    require(internals[counters+232] in (0,1) and all(internals[mem+i] in (0,1) for i in (1020,1021)),
            'Invalid 2.8 serialized Boolean')
    require(internals[flag]==1,'Input must be an ExtraMemory=true state')
    return dict(extra_memory_offset=flag,ee_subsystems_offset=ee,counter_bytes=COUNTER_BYTES,
                memory_device_bytes=legacy.MEMORY_DEVICE_BYTES,gs_offset=gs,video_mode=mode,
                framerate=fps,ee_memory_size=memory_size,emulator=family['emulator'])
