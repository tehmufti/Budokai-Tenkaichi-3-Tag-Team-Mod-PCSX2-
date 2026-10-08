"""Read ISO9660 and BT3/BT4 volume indexes without local extracted references."""
from pathlib import Path
import hashlib
import io
import re
import struct
import pycdlib
from pycdlib.pycdlibexception import PyCdlibException


class FormatError(ValueError):
    """A disc that cannot be read. code: the installer's message code (TTM-ISO-..) when the cause is known; setup
    and check_installation show its translated text, and details fill its placeholders."""
    def __init__(self,message,code=None,**details):
        super().__init__(message);self.code=code;self.details=details


def require(ok,message):
    if not ok:raise FormatError(message)


# Image formats a player may select instead of a plain ISO (setup's preflight sniffs the same bytes:
# install_player.iso_problem and install-player.ps1 Get-IsoProblem; a test compares all three).
ARCHIVES=((b'7z\xbc\xaf\x27\x1c','7z'),(b'PK\x03\x04','ZIP'),(b'PK\x05\x06','ZIP'),(b'Rar!\x1a\x07','RAR'),(b'\x1f\x8b','gzip (.gz)'))
RAW_SYNC=b'\x00'+b'\xff'*10+b'\x00'
IMAGE_TEXT={
    'TTM-ISO-01':'The selected game image is still packed in an archive ({format}); extract it and select the .iso inside',
    'TTM-ISO-02':'The selected game image is a CHD file; convert it back to an ISO (chdman extractdvd)',
    'TTM-ISO-03':'The selected game image is a {format} file; decompress it to an ISO (maxcso --decompress)',
    'TTM-ISO-04':'The selected game image is a raw BIN/CUE image, not an ISO; convert it to an ISO',
    'TTM-ISO-05':'The selected file is not a PlayStation 2 disc image',
    'TTM-ISO-06':'The game ISO is incomplete: the file has {size} bytes, but the disc says {expected} bytes',
    'TTM-ISO-07':'The game ISO is damaged: its ISO 9660 file system cannot be read',
}


def image_problem(head,size):
    """(code, details) when the first 64 KiB and the size show something other than a complete 2048-byte-sector
    ISO 9660 image; None for a plausible ISO. The volume size check is size >= blocks*2048: BT4 REV2 carries 16 KiB
    of padding after its last block."""
    if head[:8]==b'MComprHD':return 'TTM-ISO-02',dict(format='CHD')
    if head[:4] in (b'CISO',b'ZISO'):
        kind=head[:4].decode('ascii')[0]+'SO';return 'TTM-ISO-03',dict(format=kind,extension=kind.lower())
    for magic,name in ARCHIVES:
        if head.startswith(magic):return 'TTM-ISO-01',dict(format=name)
    if head.startswith(RAW_SYNC):return 'TTM-ISO-04',{}
    if re.match(rb'(?:\xef\xbb\xbf)?\s*(?:FILE|REM|TRACK|CATALOG|PERFORMER|TITLE)\s',head[:64],re.I):return 'TTM-ISO-04',{}
    if size<0x8800 or len(head)<0x8058 or head[0x8000:0x8006]!=b'\x01CD001':return 'TTM-ISO-05',dict(size=size)
    expected=struct.unpack_from('<I',head,0x8050)[0]*2048
    if size<expected:return 'TTM-ISO-06',dict(size=size,expected=expected)
    return None


def image_error(code,details,cause=''):
    message=IMAGE_TEXT[code].format(**details)+(f' ({cause})' if cause else '')
    error=FormatError(message,code=code,**details);error.cause=cause
    return error


def preflight(path):
    """Refuse a compressed, archived, raw or incomplete image before hashing it (FormatError with a code)."""
    path=Path(path);size=path.stat().st_size
    with path.open('rb') as stream:head=stream.read(0x10000)
    problem=image_problem(head,size)
    if problem:raise image_error(*problem)


def unreadable(path,error):
    """A readable reason for a pycdlib or struct error raised while opening a disc image: the image problem the first
    64 KiB show, else a damaged file system (TTM-ISO-07) when the ISO 9660 volume descriptor is there, else not a disc
    image at all (TTM-ISO-05)."""
    head=b''
    try:
        size=Path(path).stat().st_size
        with Path(path).open('rb') as stream:head=stream.read(0x10000)
        problem=image_problem(head,size)
    except OSError:problem=None
    if problem:return image_error(*problem,cause=str(error))
    cause=f'{type(error).__name__}: {error}'
    if head[0x8000:0x8006]==b'\x01CD001':return image_error('TTM-ISO-07',{},cause=cause)
    return image_error('TTM-ISO-05',{},cause=cause)


def u32(data,at):
    require(0<=at<=len(data)-4,'Truncated uint32')
    return struct.unpack_from('<I',data,at)[0]


def package(data,allow_empty=True):
    count=u32(data,0)
    require(0<count<=4096 and 4*(count+2)<=len(data),'Invalid package count')
    offsets=[u32(data,4+i*4)&~3 for i in range(count+1)]
    require(4*(count+2)<=offsets[0] and offsets[-1]<=len(data),'Package offsets outside file')
    require(all(a<=b if allow_empty else a<b for a,b in zip(offsets,offsets[1:])),'Reversed package offsets')
    return [(a,b) for a,b in zip(offsets,offsets[1:])]


def entry(data,index):
    """Validate the selected native entry without trusting unused tail entries.

    Some shipped BT4 meshes retain stale offsets for unused final entries.
    Native extras consume collision/geometry entries, whose bounds must still
    be checked independently. Generic full-package audits remain strict.
    """
    count=u32(data,0)
    require(0<count<=4096 and 0<=index<count and 4*(count+2)<=len(data),'Invalid package entry')
    start,end=(u32(data,4*(index+n))&~3 for n in (1,2))
    require(4*(count+2)<=start<=end<=len(data),'Selected package entry outside file')
    return data[start:end]


def elf_reader(data):
    require(data[:7]==b'\x7fELF\x01\x01\x01','Expected 32-bit little-endian ELF')
    require(len(data)>=52 and struct.unpack_from('<H',data,18)[0]==8,'Expected MIPS executable')
    ph=u32(data,28);size,count=struct.unpack_from('<HH',data,42)
    require(size>=32 and 0<count<128 and ph+size*count<=len(data),'Invalid ELF segments')
    segments=[]
    for i in range(count):
        kind,off,va,_,length,mem,flags,align=struct.unpack_from('<8I',data,ph+i*size)
        if kind!=1:continue
        require(length<=mem and off+length<=len(data),'ELF segment outside file')
        segments.append((va,off,length))
    def read(at,n):
        for va,off,length in segments:
            if va<=at and at+n<=va+length:return data[off+at-va:off+at-va+n]
        raise FormatError(f'Unmapped executable address {at:08X}')
    return read


def executable_fingerprint(data):
    """Hash the loaded program and its layout, not ELF trailers/debug tables.

    Include entry point, flags, every segment's memory contract and contents.
    This permits repackaged executables without treating a few matching hook
    instructions as proof that the rest of the engine is compatible.
    """
    elf_reader(data)  # Bounds/type validation shared with native hook reads.
    digest=hashlib.sha256(b'TagTeam loaded ELF v1\0')
    digest.update(data[:28]);digest.update(data[36:42])
    ph=u32(data,28);size,count=struct.unpack_from('<HH',data,42)
    digest.update(struct.pack('<H',count))
    for i in range(count):
        kind,off,va,pa,length,mem,flags,align=struct.unpack_from('<8I',data,ph+i*size)
        require(off+length<=len(data),'ELF segment outside file')
        digest.update(struct.pack('<7I',kind,va,pa,length,mem,flags,align))
        digest.update(data[off:off+length])
    return digest.hexdigest()


def pcsx2_crc(data):
    """PCSX2 ElfObject::GetCRC: XOR full little-endian words, including trailer.

    This names cheats/savestates; it is NOT a compatibility or integrity hash.
    Reference: PCSX2 v2.8.2 pcsx2/Elfheader.cpp, GetCRC.
    """
    result=0
    for word, in struct.iter_unpack('<I',data[:len(data)//4*4]):result^=word
    return f'{result:08X}'


class Disc:
    def __init__(self,path):
        self.path=Path(path).resolve();self.iso=pycdlib.PyCdlib();self.closed=False;self.streams={}
        try:self.iso.open(str(self.path))
        except (PyCdlibException,struct.error,EOFError) as error:raise unreadable(self.path,error) from error
        try:
            self.members={}
            for directory,_,files in self.iso.walk(iso_path='/'):
                for name in files:
                    member=directory.rstrip('/')+'/'+name
                    self.members[member]=self.iso.get_record(iso_path=member).data_length
            config=self.member('/SYSTEM.CNF;1',max_size=65536)
            match=re.search(rb'(?im)^\s*BOOT2\s*=\s*cdrom0:\\([^\s;]+);1',config)
            require(match is not None,'SYSTEM.CNF has no supported PS2 boot executable')
            self.boot='/'+match[1].decode('ascii').replace('\\','/')+';1'
            self.elf=self.member(self.boot,max_size=16<<20);self.native=elf_reader(self.elf)
            self.serial=Path(self.boot).name.split(';')[0]
            self.member_hashes={p:hashlib.sha256(b).hexdigest() for p,b in (('/SYSTEM.CNF;1',config),(self.boot,self.elf))}
            if '/BIN/DBZP.BIN;1' in self.members:
                self.member_hashes['/BIN/DBZP.BIN;1']=hashlib.sha256(self.member('/BIN/DBZP.BIN;1')).hexdigest()
            self.tables={};self.volume_paths={};self.kind='unknown';self.region=None
            if '/BIN/DBZ4.BIN;1' in self.members and '/DATA/PZS4US1.AFS;1' in self.members:
                self.kind='bt4-indexed';self._bt4()
            elif '/DATA/PZS3US1.AFS;1' in self.members:
                self.region='US';self.kind='bt3-afs';self._afs()
            elif '/DATA/PZS3EU1.AFS;1' in self.members:
                # European SLES-54945: the same volumes named PZS3EU0-2 (the executable names pzs3eu*).
                self.region='EU';self.kind='bt3-afs';self._afs()
            elif '/DATA/PZS3JP1.AFS;1' in self.members:
                # Japanese SLPS-25815 (Sparking! Meteor): volumes PZS3JP0-2 (the executable names pzs3jp*).
                self.region='JP';self.kind='bt3-afs';self._afs()
        except (PyCdlibException,struct.error,EOFError) as error:
            self.close();raise unreadable(self.path,error) from error
        except BaseException:self.close();raise

    def member(self,path,max_size=32<<20):
        size=self.members.get(path)
        require(size is not None and 0<size<=max_size,f'Missing or excessive ISO member: {path}')
        out=io.BytesIO();self.iso.get_file_from_iso_fp(out,iso_path=path)
        data=out.getvalue();require(len(data)==size,'Truncated ISO member');return data

    def _afs(self):
        for volume in range(4):
            path=f'/DATA/PZS3{self.region}{volume}.AFS;1'
            if path not in self.members:continue
            with self.iso.open_file_from_iso(iso_path=path) as stream:
                head=stream.read(8);require(len(head)==8 and head[:4]==b'AFS\0','Changed AFS header')
                count=u32(head,4);require(0<count<=100000 and 8+count*8<=self.members[path],'Invalid AFS table length')
                raw=stream.read(count*8);require(len(raw)==count*8,'Truncated AFS table')
                entries=list(struct.iter_unpack('<II',raw))
                for off,size in entries:
                    require(size==0 or (off>=8+count*8 and off+size<=self.members[path]),'AFS file outside volume')
                ordered=sorted((off,off+size) for off,size in entries if size)
                require(all(b<=c for (_,b),(c,_) in zip(ordered,ordered[1:])),'Overlapping AFS files')
                self.tables[volume]=entries;self.volume_paths[volume]=path

    def _bt4(self):
        path='/BIN/DBZ4.BIN;1';data=self.member(path)
        self.member_hashes[path]=hashlib.sha256(data).hexdigest()
        for volume in range(4):
            name=f'pzs4us{volume}.afs'.encode();hits=[m.start() for m in re.finditer(re.escape(name),data)]
            require(len(hits)==1,'Missing or ambiguous BT4 volume index')
            base=hits[0]-16;require(base>=0,'Invalid BT4 volume header')
            _,size,count,duplicate=struct.unpack_from('<4I',data,base)
            require(count==duplicate and 0<count<=100000 and size==282+count*2 and base+size<=len(data),'Changed BT4 volume index')
            lengths=struct.unpack_from('<'+'H'*count,data,base+282)
            cursor=0;entries=[]
            for sectors in lengths:entries.append((cursor,sectors*2048));cursor+=sectors*2048
            target=f'/DATA/PZS4US{volume}.AFS;1'
            require(target in self.members and cursor<=self.members[target],'BT4 index exceeds volume')
            self.tables[volume]=entries;self.volume_paths[volume]=target
        if '/BIN/DBZP.BIN;1' in self.members:
            self.member_hashes['/BIN/DBZP.BIN;1']=hashlib.sha256(self.member('/BIN/DBZP.BIN;1')).hexdigest()

    def locate(self,file_id):
        require(type(file_id) is int and file_id>0,'Invalid global file ID')
        if self.kind=='bt4-indexed':
            if file_id>=0x20000:volume,index=3,file_id-0x20000
            elif file_id>=0x10CC0:volume,index=0,file_id-0x10CC0
            elif file_id>=0xD48:volume,index=2,file_id-0xD48
            else:volume,index=1,file_id-1
        elif self.kind=='bt3-afs':
            # Current BT3 character/stage mappings use volume1 only. Do not
            # invent global bases for other volumes on an unknown derivative.
            # Native global IDs number volumes 0,1,2 in one sequence: volume 0
            # has 1 entry on the USA and Japanese discs (volume1 index = ID-1)
            # and 2 on the European disc (index = ID-2), so count the disc's own
            # volume 0.
            require(0 in self.tables,'Missing AFS volume 0; global file IDs cannot be numbered')
            volume,index=1,file_id-len(self.tables[0])
        else:raise FormatError('No supported volume layout')
        require(volume in self.tables and 0<=index<len(self.tables[volume]),f'Unmapped file ID {file_id}')
        off,size=self.tables[volume][index]
        require(0<size<=32<<20,f'Empty or excessive resource {file_id}')
        return self.volume_paths[volume],off,size

    def read(self,file_id):
        path,off,size=self.locate(file_id)
        if path not in self.streams:
            stream=self.iso.open_file_from_iso(iso_path=path);stream.__enter__();self.streams[path]=stream
        stream=self.streams[path];stream.seek(off);data=stream.read(size)
        require(len(data)==size,f'Truncated resource {file_id}')
        return data

    def close(self):
        if self.closed:return
        self.closed=True
        for stream in self.streams.values():stream.close()
        self.iso.close()

    def __enter__(self):return self
    def __exit__(self,*_):self.close()
