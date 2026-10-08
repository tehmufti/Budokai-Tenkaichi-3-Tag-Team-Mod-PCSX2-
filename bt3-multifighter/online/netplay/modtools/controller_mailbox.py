"""Narrow, authenticated EE input mailbox transport for one PCSX2 process.

PINE authenticates the mapping once. The controller hub's thread then touches
only its owned mailboxes, avoiding contention with character-resource PINE
transactions. No emulator version offset is trusted.

Windows reads the emulator with Read/WriteProcessMemory. The EE base comes from
PCSX2's exported data symbol EEmem (a pointer to EE RAM, exported by every
PCSX2 runtime the mod supports): the main module's base plus the export's
address gives the pointer in microseconds. Builds without the export fall back
to a background VirtualQueryEx scan (BaseFinder; attach raises AttachPending
until it finishes). Linux maps PCSX2's own EE memory file through
/proc/<pid>/fd (see SharedMemoryMapping). Every route accepts a mapping only
after the PINE-written token (and the mailbox identity) is found in it.

One ProcessMemory per PCSX2 process is shared by every mailbox (shared_process)
and closed once, by the hub at watcher exit (release_process).
"""
import ctypes
import errno
import mmap
import os
import re
import secrets
import select
import stat
import struct
import threading
import time
from typing import NamedTuple
from ctypes import wintypes as w
import quad_controller as quad

TOKEN=quad.CONTROL+0x80
# The 128 MiB EE RAM starts at offset 0 of PCSX2's Linux memory file (PCSX2
# Memory.h: EEmemOffset=0). That file is larger (159 MiB in 2.6, 285 MiB in
# 2.8); only the EE part is mapped. Every mailbox address lies below 128 MiB.
EE_SIZE=0x8000000
# PCSX2 shm_open()s "pcsx2_<getpid()>" and unlinks it at once (LnxHostSys.cpp),
# so its descriptor reads "/dev/shm/pcsx2_<pid> (deleted)". Any directory is
# accepted because /dev/shm may be a symlink to /run/shm; memfd is future-proofing.
SHARED_MEMORY=re.compile(r'\A/(?:.*/|memfd:)?pcsx2_(\d+) \(deleted\)\Z',re.S)


# Group A's wording; player_errors translates it through its {play} template.
ACCESS_REFUSED=('Controllers 3 and 4 cannot be read: Windows refused access to PCSX2. Do not run PCSX2 or Play '
                'as administrator, then start {play} again.')


def launcher():
    """This installation's Play launcher (localization.entry, group A); plain 'Play' before it exists."""
    try:
        import localization
        return localization.entry('play') or 'Play'
    except Exception:  # noqa: BLE001 - a name inside a message only
        return 'Play'


class MappingLost(RuntimeError):pass


class AttachPending(RuntimeError):
    """The EE base is still being found in the background (builds without the EEmem export): try again on a later
    watcher tick. Silent: never reported to the player."""


class MailboxUnavailable(OSError):
    """This system cannot give 3-4 player input access to the emulator's EE memory."""


class Region(ctypes.Structure):
    _fields_=[('base',ctypes.c_void_p),('allocation',ctypes.c_void_p),
        ('allocation_protect',w.DWORD),('partition',w.WORD),('size',ctypes.c_size_t),
        ('state',w.DWORD),('protect',w.DWORD),('kind',w.DWORD)]


class WindowsProcessMemory:
    def __init__(self,pid):
        self.dll=ctypes.WinDLL('kernel32',use_last_error=True)
        signatures={
            'OpenProcess':([w.DWORD,w.BOOL,w.DWORD],w.HANDLE),
            'CloseHandle':([w.HANDLE],w.BOOL),
            'VirtualQueryEx':([w.HANDLE,ctypes.c_void_p,ctypes.POINTER(Region),ctypes.c_size_t],ctypes.c_size_t),
            'ReadProcessMemory':([w.HANDLE,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_size_t,ctypes.POINTER(ctypes.c_size_t)],w.BOOL),
            'WriteProcessMemory':([w.HANDLE,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_size_t,ctypes.POINTER(ctypes.c_size_t)],w.BOOL),
            'K32EnumProcessModulesEx':([w.HANDLE,ctypes.POINTER(ctypes.c_void_p),w.DWORD,ctypes.POINTER(w.DWORD),w.DWORD],w.BOOL),
            'K32GetModuleFileNameExW':([w.HANDLE,ctypes.c_void_p,ctypes.c_wchar_p,w.DWORD],w.DWORD)}
        for name,(args,result) in signatures.items():
            fn=getattr(self.dll,name);fn.argtypes=args;fn.restype=result
        self.handle=self.dll.OpenProcess(0x438,False,pid)
        # The Windows error goes in as winerror (5 = access denied), so its errno is EACCES and
        # player_errors classifies it as refused access (NO-ACCESS), not an unexpected error.
        if not self.handle:raise OSError(0,ACCESS_REFUSED.format(play=launcher()),None,ctypes.get_last_error())

    def read(self,address,size):
        buf=ctypes.create_string_buffer(size);count=ctypes.c_size_t()
        if not self.dll.ReadProcessMemory(self.handle,address,buf,size,ctypes.byref(count)) or count.value!=size:
            raise MappingLost('The emulator memory mapping is no longer readable')
        return buf.raw

    def write(self,address,data):
        buf=ctypes.create_string_buffer(data);count=ctypes.c_size_t()
        if not self.dll.WriteProcessMemory(self.handle,address,buf,len(data),ctypes.byref(count)) or count.value!=len(data):
            raise MappingLost('The emulator input mailbox is no longer writable')

    def main_module(self):
        """(base address, file path) of PCSX2's executable (module 0 of the process)."""
        modules=(ctypes.c_void_p*1)();needed=w.DWORD()
        if not self.dll.K32EnumProcessModulesEx(self.handle,modules,ctypes.sizeof(modules),ctypes.byref(needed),3) or not modules[0]:
            raise OSError(ctypes.get_last_error(),'The PCSX2 executable module could not be listed')
        buffer=ctypes.create_unicode_buffer(32768)
        if not self.dll.K32GetModuleFileNameExW(self.handle,modules[0],buffer,len(buffer)):
            raise OSError(ctypes.get_last_error(),'The PCSX2 executable path could not be read')
        return modules[0],buffer.value

    def ee_base(self):
        """The EE RAM address from PCSX2's exported EEmem pointer, or None when this build does not export it."""
        base,path=self.main_module()
        rva=export_rva(path,'EEmem')
        if rva is None:return None
        pointer=struct.unpack('<Q',self.read(base+rva,8))[0]
        return pointer or None

    def candidates(self):
        # PCSX2 maps EE pages individually into one allocation. Group by that
        # allocation, not individual VirtualQueryEx regions or heap snapshots.
        address=0;allocations=set()
        while address<0x7FFFFFFF0000:
            region=Region()
            if not self.dll.VirtualQueryEx(self.handle,address,ctypes.byref(region),ctypes.sizeof(region)):break
            end=(region.base or 0)+region.size
            if end<=address:break
            address=end
            if region.state==0x1000 and region.kind==0x40000 and region.protect&0xFF in (4,8,0x40,0x80):
                allocations.add(region.allocation)
        return sorted(a for a in allocations if a is not None)

    def close(self):
        if self.handle:self.dll.CloseHandle(self.handle);self.handle=None


_exports={}   # (path, size, mtime) -> {name: rva} of an executable's export table


def exports(path):
    """{name: rva} of a PE file's export table (parsed once per path, size and modification time)."""
    info=os.stat(path);key=(os.path.normcase(os.path.abspath(path)),info.st_size,info.st_mtime_ns)
    if key in _exports:return _exports[key]
    with open(path,'rb') as source:data=source.read()
    result={}
    pe=struct.unpack_from('<I',data,0x3C)[0]
    if data[pe:pe+4]!=b'PE'+bytes(2):raise ValueError(f'{path} is not a Windows executable')
    sections,optional=struct.unpack_from('<H',data,pe+6)[0],struct.unpack_from('<H',data,pe+20)[0]
    header=pe+24;magic=struct.unpack_from('<H',data,header)[0]
    directory,size=struct.unpack_from('<II',data,header+(112 if magic==0x20B else 96))
    table=[struct.unpack_from('<8sIIII',data,header+optional+40*i)[1:] for i in range(sections)]
    def offset(rva):
        for virtual_size,virtual,raw_size,raw in table:
            if virtual<=rva<virtual+max(virtual_size,raw_size):return rva-virtual+raw
        raise ValueError(f'{rva:#x} lies outside every section of {path}')
    if directory and size:
        start=offset(directory)
        functions,names,address_table,name_table,ordinals=struct.unpack_from('<IIIII',data,start+20)
        for i in range(names):
            text=offset(struct.unpack_from('<I',data,offset(name_table)+4*i)[0])
            name=data[text:data.index(bytes(1),text)].decode('ascii','replace')
            ordinal=struct.unpack_from('<H',data,offset(ordinals)+2*i)[0]
            result[name]=struct.unpack_from('<I',data,offset(address_table)+4*ordinal)[0]
    _exports[key]=result
    return result


def export_rva(path,name):
    try:return exports(path).get(name)
    except (OSError,ValueError,struct.error):return None


class Liveness:
    """Exit check for one Linux process, pinned by a pidfd.

    PCSX2's memory file stays mapped and readable after PCSX2 exits, so every
    mailbox access asks this first. Kernels without pidfd_open (before 5.3) or
    a seccomp filter fall back to the /proc/<pid>/stat start time and state.
    """
    def __init__(self,pid,*,proc='/proc',pidfd_open=getattr(os,'pidfd_open',None)):
        self.pid=pid;self.proc=proc;self.pidfd=None;self.start=None
        if pidfd_open is not None:
            try:self.pidfd=pidfd_open(pid)
            except ProcessLookupError:raise
            except OSError:self.pidfd=None
        if self.pidfd is None:
            self.start=self._identity()
            if self.start is not None:return
            if not os.path.exists(os.path.join(proc,'self','stat')):
                raise OSError(errno.ENOSYS,'3-4 player input needs Linux pidfd_open or /proc to watch PCSX2')
            raise ProcessLookupError(errno.ESRCH,f'Process {pid} has exited')

    def _identity(self):
        try:
            with open(os.path.join(self.proc,str(self.pid),'stat'),'rb') as source:text=source.read()
            fields=text[text.rindex(b')')+2:].split()
        except (OSError,ValueError):return None
        # Field 3 is the state (a zombie has exited), field 22 the start time.
        if len(fields)<20 or fields[0] in (b'Z',b'X',b'x'):return None
        return fields[19]

    def alive(self):
        if self.pidfd is not None:
            poller=select.poll();poller.register(self.pidfd,select.POLLIN)
            return not poller.poll(0)
        return self.start is not None and self._identity()==self.start

    def close(self):
        if self.pidfd is not None:os.close(self.pidfd);self.pidfd=None
        self.start=None


class ProcFS:
    """The descriptors of one process under /proc; tests substitute a fake tree."""
    def __init__(self,root='/proc'):self.root=root

    def folder(self,pid):return os.path.join(self.root,str(pid),'fd')

    def links(self,pid):
        folder=self.folder(pid);result=[]
        for name in sorted(os.listdir(folder),key=lambda name:(len(name),name)): # Descriptor order.
            path=os.path.join(folder,name)
            try:result.append((path,os.readlink(path)))
            except OSError:continue # Closed while listing.
        return result

    def identity(self,path):
        info=os.stat(path);return info.st_dev,info.st_ino

    def open(self,path):
        return os.open(path,os.O_RDWR|getattr(os,'O_CLOEXEC',0)|getattr(os,'O_BINARY',0))


class SharedMemoryMapping:
    """Linux: PCSX2's own EE memory file, opened through /proc/<pid>/fd and mmap'd.

    Following a /proc/<pid>/fd link needs only PTRACE_MODE_READ plus the
    file's 0600 owner, so Yama's ptrace_scope does not apply and the watcher
    may be PCSX2's sibling. process_vm_readv and /proc/<pid>/mem are not used:
    they need ptrace attach rights. The address is the file offset (EE RAM
    starts at offset 0); Mailbox still requires its PINE token in the mapping.
    Tested in WSL (no Yama) against a simulated PCSX2 process; Yama scopes 1-3
    with the real AppImage still need a check on a Linux desktop. Flatpak is
    unsupported (its PINE socket and PID namespace are sandboxed).
    """
    def __init__(self,pid,*,procfs=None,liveness=Liveness,size=EE_SIZE):
        self.view=self.liveness=self.source=None
        try:self.liveness=liveness(pid)
        except ProcessLookupError:raise MailboxUnavailable(f'PCSX2 (process {pid}) has closed') from None
        except OSError as error:raise MailboxUnavailable(error.strerror or str(error)) from None
        try:
            self.view=self._map(procfs or ProcFS(),pid,size)
            if not self.liveness.alive():raise MailboxUnavailable(f'PCSX2 (process {pid}) closed while its memory was mapped')
        except BaseException:self.close();raise

    def _closed(self,pid,error):
        """The message when `error` only means that PCSX2 is exiting, else None. While PCSX2 exits,
        /proc/<pid>/fd vanishes (ENOENT), answers ESRCH, or (exited, not yet reaped) EACCES:
        not a sandbox or permission problem."""
        if not self.liveness.alive() or isinstance(error,ProcessLookupError):return f'PCSX2 (process {pid}) has closed'
        if isinstance(error,FileNotFoundError):return f'PCSX2 (process {pid}) has closed, or /proc is not mounted'
        return None

    def _map(self,procfs,pid,size):
        folder=procfs.folder(pid)
        try:links=procfs.links(pid)
        except OSError as error:
            closed=self._closed(pid,error)
            if closed:raise MailboxUnavailable(closed) from None
            if isinstance(error,PermissionError):
                raise MailboxUnavailable(f'3-4 player input cannot read {folder}: PCSX2 must run as this user and '
                                         f'outside a sandbox such as Flatpak ({error.strerror or error})') from None
            raise MailboxUnavailable(f'3-4 player input cannot read {folder} ({error.strerror or error})') from None
        files={}
        for path,link in links:
            if not SHARED_MEMORY.match(link):continue
            try:files.setdefault(procfs.identity(path),(path,link))
            except OSError:continue
        if not files:
            raise MailboxUnavailable(f"3-4 player input cannot find PCSX2's memory file (/dev/shm/pcsx2_<pid> (deleted)) "
                                     f'in {folder}; it needs the official PCSX2 AppImage 2.6 or newer (not Flatpak)')
        if len(files)!=1:
            raise MailboxUnavailable(f'3-4 player input found {len(files)} PCSX2 memory files in {folder}; expected exactly one')
        (identity,(path,link)),=files.items()
        try:descriptor=procfs.open(path)
        except OSError as error:
            closed=self._closed(pid,error)
            if closed:raise MailboxUnavailable(closed) from None
            raise MailboxUnavailable(f"3-4 player input cannot open PCSX2's memory file {link} for reading and writing "
                                     f'({error.strerror or error})') from None
        try:
            info=os.fstat(descriptor)
            if (info.st_dev,info.st_ino)!=identity or not stat.S_ISREG(info.st_mode):
                raise MailboxUnavailable("PCSX2's memory file changed while it was being opened")
            if info.st_size<size:
                raise MailboxUnavailable(f"PCSX2's memory file {link} has {info.st_size:#x} bytes; "
                                         f'it should begin with the {size>>20} MiB EE RAM')
            view=mmap.mmap(descriptor,size,access=mmap.ACCESS_WRITE)
        finally:os.close(descriptor)
        self.source=f'{path} -> {link}'
        return view

    def _span(self,address,size):
        view=self.view
        if view is None or not self.liveness.alive():
            raise MappingLost('The emulator has closed; its memory mapping is no longer live')
        if address<0 or size<0 or address+size>len(view):
            raise MappingLost('The address is outside the emulator EE memory mapping')
        return view

    def read(self,address,size):
        return self._span(address,size)[address:address+size]

    def write(self,address,data):
        data=bytes(data);self._span(address,len(data))[address:address+len(data)]=data

    def candidates(self):return [0]

    def close(self):
        if self.view is not None:self.view.close();self.view=None
        if self.liveness is not None:self.liveness.close();self.liveness=None


ProcessMemory=WindowsProcessMemory if os.name=='nt' else SharedMemoryMapping
_shared={}        # (pid, factory) -> the one ProcessMemory of that PCSX2
_finders={}       # (pid, factory) -> BaseFinder
_shared_lock=threading.Lock()


def shared_process(pid,factory=None):
    """The ProcessMemory of PCSX2 process `pid`, opened once and shared by every mailbox (closed by release_process)."""
    factory=factory or ProcessMemory
    with _shared_lock:
        process=_shared.get((pid,factory))
        if process is None:process=_shared[(pid,factory)]=factory(pid)
        return process


def release_process(pid):
    """Close every shared handle of `pid` once (Hub.close at watcher exit)."""
    with _shared_lock:
        owned=[key for key in _shared if key[0]==pid]
        processes=[_shared.pop(key) for key in owned]
        for key in [k for k in _finders if k[0]==pid]:_finders.pop(key)
    for process in processes:
        try:process.close()
        except Exception:pass


class BaseFinder:
    """The VirtualQueryEx scan on a background thread, for PCSX2 builds without the EEmem export."""
    def __init__(self,process):
        self.process=process;self.result=None;self.error=None;self.done=threading.Event()
        self.thread=threading.Thread(target=self._run,name='TTM EE base finder',daemon=True);self.thread.start()

    def _run(self):
        try:self.result=self.process.candidates()
        except Exception as error:self.error=error
        finally:self.done.set()


def bases(process,pid,factory,*,wait=False):
    """Where EE RAM may start in `process`: the EEmem pointer (Windows), the mapping (Linux), or the scan."""
    base=getattr(process,'ee_base',None)
    if base is not None:
        try:found=base()
        except (OSError,MappingLost):found=None
        if found:return [found]
    if wait or base is None:return process.candidates()
    with _shared_lock:
        finder=_finders.get((pid,factory))
        if finder is None:finder=_finders[(pid,factory)]=BaseFinder(process)
    if not finder.done.is_set():raise AttachPending('The emulator memory is still being located')
    if finder.error is not None:
        with _shared_lock:_finders.pop((pid,factory),None)
        raise finder.error
    return finder.result


class Mailbox:
    TOKEN_ADDRESS=TOKEN
    CONTROL,MAILBOX=quad.CONTROL,quad.MAILBOX
    READS={quad.CONTROL:16,quad.CONTROL+16:8,quad.core.ACTORS:4,quad.core.MODE:16}
    WRITES={quad.MAILBOX:64,quad.CONTROL+16:4,quad.CONTROL+28:4}

    def __init__(self,process,base,token):self.process,self.base,self.token=process,base,token

    @classmethod
    def identity(cls,p):
        header=p.read(quad.CONTROL,16)
        magic,manager,count,enabled=struct.unpack('<4I',header)
        if magic!=quad.MAGIC or enabled!=1:raise ValueError('No owned four-player input installation')
        expected_mode=struct.pack('<4I',1,count,manager,count)
        if p.read(quad.core.MODE,16)!=expected_mode or p.read_u32(quad.core.ACTORS)!=manager:
            raise ValueError('Four-player input belongs to an inactive match')
        return {quad.CONTROL:header,quad.core.MODE:expected_mode,quad.core.ACTORS:struct.pack('<I',manager)}

    @classmethod
    def attach(cls,p,pid,process_factory=ProcessMemory,*,wait=False):
        """Authenticate this mailbox in the shared process memory of `pid`. wait=True scans in place (tools, tests);
        otherwise a build without EEmem raises AttachPending until its background scan is done."""
        identity=cls.identity(p)
        token=secrets.token_bytes(16);p.write(cls.TOKEN_ADDRESS,token)
        process=shared_process(pid,process_factory)
        matches=[]
        for base in bases(process,pid,process_factory,wait=wait):
            try:
                if (process.read(base+cls.TOKEN_ADDRESS,16)==token and
                        all(process.read(base+address,len(data))==data for address,data in identity.items())):
                    matches.append(base)
            except MappingLost:continue
        if len(matches)!=1:
            source=getattr(process,'source',None) # Linux names the memory file it searched.
            raise ValueError(f'Expected one authenticated EE mapping, found {len(matches)}'+(f' in {source}' if source else ''))
        return cls(process,matches[0],token)

    def require_owner(self):
        if self.process.read(self.base+self.TOKEN_ADDRESS,16)!=self.token:
            raise MappingLost('The match was replaced or restored; input ownership ended')

    def read(self,address,size):
        if self.READS.get(address)!=size:raise ValueError('Read is outside the controller mailbox contract')
        self.require_owner();return self.process.read(self.base+address,size)

    def read_u32(self,address):return struct.unpack('<I',self.read(address,4))[0]

    def write(self,address,data):
        if self.WRITES.get(address)!=len(data):raise ValueError('Write is outside the controller mailbox contract')
        self.require_owner();self.process.write(self.base+address,data)

    def write_u32(self,address,value):self.write(address,struct.pack('<I',value))
    def close(self):pass   # the process memory is shared (release_process closes it once)


class Capability(NamedTuple):
    available:object # True, False, or None when EE RAM gave no stable sample.
    reason:str=''
    lasting:bool=True # False: only a memory comparison said no; asked again later (PROBE_RETRY).


# Windows keeps its existing attach path. Elsewhere 3-4 player input first
# checks, once per emulator, that SDL and PCSX2's memory file both work.
PROBE_REQUIRED=os.name!='nt'
# Read-only samples of the game's ELF text in user RAM. A sample counts only when
# it is non-blank and did not change meanwhile. Not the kernel's first 512 KiB:
# PINE reads EE virtual addresses, and PCSX2 2.8.2 (the AppImage, checked live)
# answers zeros at 0x0 while the memory file holds the kernel there (only the
# kseg0 alias 0x80000000 shows it), so a kernel sample would always say no.
PROBE_RANGES=((0x100000,0x100),(0x200000,0x100))
# A range that differs from PINE is read again this many times (a short pause
# between) before the mapping is called wrong: the guest keeps running meanwhile.
PROBE_SAMPLES=3
# A memory-comparison "no" (not lasting) is remembered per emulator for the capture and
# controller devices it was asked for. The same capture and devices are asked again only
# after these pauses in seconds (the last one repeats); a new capture or devices at once.
PROBE_RETRY=(2.0,4.0,8.0,16.0,30.0)
_capabilities={}  # pid -> lasting verdict: True, or a lasting False
_provisional={}   # pid -> {key: (capture, devices), step, retry}: the last memory-comparison "no"
_pending=set()    # pids whose provisional "no" was reported and not yet followed by a recovery
_reported=set()   # pids whose lasting "no" was reported


def plain_reason(reason):
    """`reason` for a sentence that already names 3-4 player input and players 1 and 2:
    '3-4 player input cannot ...' reads 'it cannot ...' and a second P1/P2 note is dropped."""
    text=re.sub(r'\s*Players 1 and 2 are not affected\.?','',str(reason).strip())
    text=re.sub(r'^3-4 player input\s+','it ',text).strip().rstrip('.')
    return text or (type(reason).__name__ if isinstance(reason,BaseException) else 'no reason given')


def check_sdl(hub,timeout=5):
    """SDL's game-controller input runs: the controller hub's reader is ready (it starts the hub if needed)."""
    if hub is None:raise RuntimeError('The controller reader is not running')
    hub.require_ready(timeout)


def capability(p,pid,*,process_factory=None,sdl_check=None,ranges=PROBE_RANGES,samples=PROBE_SAMPLES,pause=.01):
    """Read-only 3-4 player input check: SDL loads and the mapping mirrors PINE.

    Nothing is written to the guest. PINE errors propagate; the caller owns
    that connection. Ownership is still proven later by the Mailbox token.
    A range that differs from PINE is sampled again; only a difference that
    persists (stable and non-blank every time) says no, and that verdict is
    not lasting, because the running guest may have raced every sample.
    """
    try:(sdl_check or (lambda:check_sdl(None)))()
    except Exception as error:
        reason=str(error) # input_binding already names SDL2 and the package to install.
        return Capability(False,reason if 'SDL' in reason else f'SDL2 controller input is unavailable ({reason})')
    try:process=(process_factory or ProcessMemory)(pid)
    except (OSError,ValueError,RuntimeError) as error:return Capability(False,str(error))
    try:
        bases=process.candidates()
        if len(bases)!=1:return Capability(None,'several candidate mappings; the input token decides')
        base,=bases;decided=False
        for address,size in ranges:
            for sample in range(max(1,samples)):
                if sample:time.sleep(pause)
                try:before=process.read(base+address,size)
                except MappingLost as error:return Capability(False,str(error))
                pine=p.read(address,size)
                try:after=process.read(base+address,size)
                except MappingLost as error:return Capability(False,str(error))
                if before!=after or len(set(before))<2:break # Changing or blank: this range cannot tell.
                if pine==before:decided=True;break
            else:
                return Capability(False,f'the emulator memory mapping does not match PINE at EE {address:#x}',lasting=False)
        return Capability(True) if decided else Capability(None,'EE RAM was blank or changing; the input token decides')
    finally:process.close()


class Owner:
    """Players 3 and 4 in a prepared match: one hub sink per captured world; a rewind always gets a new token.
    No thread starts or ends here: the controller hub publishes (controller_hub.BattleSink).

    `report` receives a problem (the watcher shows it as a warning), `notice` the
    recovery after a provisional "no" (defaults to `report`; both print when None).
    seats: 'private' (seats 3-4 of the check-in roster) or 'extras' (free controllers)."""
    def __init__(self,pid,*,report=None,notice=None,hub=None):
        self.mailbox_type=Mailbox
        self.pid=pid;self.service=None;self.capture=None;self.seats='private';self.attached_seats=None
        self.report=report;self.notice=notice;self.hub=hub

    def _tell(self,message,*,good=False):
        target=(self.notice or self.report) if good else self.report
        if target is not None:target(message)
        else:print(message,flush=True)

    def available(self,p,capture=None):
        """False when this system cannot run 3-4 player input, reported once.

        A lasting verdict holds for this emulator. A memory-comparison "no" is provisional:
        it holds for `capture` and the current devices until its PROBE_RETRY pause ends, so a
        watcher polling the same selection or match does not probe again each time."""
        if not PROBE_REQUIRED:return True
        result=_capabilities.get(self.pid)
        if result is None:
            key=(capture,self.seats);held=_provisional.get(self.pid)
            same=held is not None and held['key']==key
            if same and time.monotonic()<held['retry']:return False # Reported when first seen.
            result=capability(p,self.pid,sdl_check=lambda:check_sdl(self.hub))
            if result.available is False and not result.lasting:
                step=held['step']+1 if same else 0
                _provisional[self.pid]=dict(key=key,step=step,retry=time.monotonic()+PROBE_RETRY[min(step,len(PROBE_RETRY)-1)])
            else:
                _provisional.pop(self.pid,None)
                # Undecided is asked again on the next attach (a new capture); the token decides meanwhile.
                if result.available is not None:_capabilities[self.pid]=result
        if result.available is not False:
            # Only a probe that says yes ends a provisional "no". An undecided one allows this
            # attach silently (the input token decides) and keeps the "no" pending.
            if result.available is True and self.pid in _pending:
                _pending.discard(self.pid)
                self._tell('3-4 player input is available again after a retry: players 3 and 4, and allowing all '
                           'controllers during character selection, are back on.',good=True)
            return True
        if result.lasting:
            _pending.discard(self.pid)
            if self.pid not in _reported:
                _reported.add(self.pid)
                self._tell(f'3-4 player input is unavailable on this system: {plain_reason(result.reason)}. Players 3 and 4, '
                           'their Player Setup check-in, and allowing all controllers during character selection, are off; '
                           'P1 and P2 keep their PCSX2 controllers.')
        elif self.pid not in _pending:
            _pending.add(self.pid)
            self._tell(f'3-4 player input could not be confirmed yet; retrying ({plain_reason(result.reason)}). Until then '
                       'players 3 and 4, and allowing all controllers during character selection, stay off; '
                       'P1 and P2 keep their PCSX2 controllers.')
        return False

    def sink(self,mailbox,capture):
        import controller_hub
        return controller_hub.BattleSink(mailbox,capture)

    def attach(self,p,capture,*,rewound=False):
        if self.service is not None:
            if self.service.failure:raise RuntimeError(self.service.failure)
            if self.capture==capture and self.attached_seats==self.seats and not rewound and self.service.active:return
        self.close()
        if p.read_u32(quad.CONTROL)!=quad.MAGIC:return
        self.add(p,capture)

    def add(self,p,capture):
        if not self.available(p,capture):return
        if self.hub is None:raise RuntimeError('The controller reader is not running')
        if self.hub.state=='failed':raise MailboxUnavailable(self.hub.failure or 'SDL controller input is unavailable')
        self.hub.start()
        sink=self.sink(self.mailbox_type.attach(p,self.pid),capture)
        self.service=self.hub.add_sink(sink);self.capture=capture;self.attached_seats=self.seats

    def close(self):
        # A hub that does not answer is dropped once, never asked again (F8).
        try:
            if self.service is not None:self.service.close()
        finally:
            self.service=None;self.capture=None
