"""Avoid mistaking a Linux CPU Vulkan driver for hardware acceleration.

PCSX2's Automatic renderer already rejects CPU Vulkan devices. An explicit
Vulkan choice bypasses that check: Mesa lavapipe/llvmpipe can then draw broken
terrain/models as well as running slowly. Let PCSX2 choose again in that case.
Real Vulkan GPUs, Software mode, and Windows settings are left alone.
"""
from functools import lru_cache
import json
from pathlib import Path
import subprocess
import sys

SECTION = 'EmuCore/GS'
KEYS = frozenset({(SECTION, 'Renderer'), (SECTION, 'Adapter')})
MESSAGE = 'Vulkan selected a CPU graphics driver; using automatic hardware selection for this session.'


def _enumerate_vulkan():
    """Vulkan 1.0 device properties; run only in the disposable probe process.

    No device, window, graphics queue or surface is created. The fixed core
    VkPhysicalDeviceProperties structure fits in 824 bytes on Linux x86-64;
    reserve an aligned 4 KiB buffer and read only its documented prefix.
    """
    import ctypes as c
    class InstanceInfo(c.Structure):
        _fields_ = [('sType', c.c_uint32), ('pNext', c.c_void_p), ('flags', c.c_uint32),
                    ('pApplicationInfo', c.c_void_p), ('enabledLayerCount', c.c_uint32),
                    ('ppEnabledLayerNames', c.c_void_p), ('enabledExtensionCount', c.c_uint32),
                    ('ppEnabledExtensionNames', c.c_void_p)]
    class PropertiesPrefix(c.Structure):
        _fields_ = [(name, c.c_uint32) for name in
                    ('apiVersion', 'driverVersion', 'vendorID', 'deviceID', 'deviceType')]
        _fields_ += [('deviceName', c.c_char * 256)]
    vk = c.CDLL('libvulkan.so.1')
    vk.vkCreateInstance.argtypes = [c.POINTER(InstanceInfo), c.c_void_p, c.POINTER(c.c_void_p)]
    vk.vkCreateInstance.restype = c.c_int32
    vk.vkDestroyInstance.argtypes = [c.c_void_p, c.c_void_p]
    vk.vkDestroyInstance.restype = None
    vk.vkEnumeratePhysicalDevices.argtypes = [c.c_void_p, c.POINTER(c.c_uint32), c.POINTER(c.c_void_p)]
    vk.vkEnumeratePhysicalDevices.restype = c.c_int32
    vk.vkGetPhysicalDeviceProperties.argtypes = [c.c_void_p, c.c_void_p]
    vk.vkGetPhysicalDeviceProperties.restype = None
    instance = c.c_void_p()
    if vk.vkCreateInstance(c.byref(InstanceInfo(sType=1)), None, c.byref(instance)) != 0:
        raise RuntimeError('Vulkan instance unavailable')
    try:
        count = c.c_uint32()
        if vk.vkEnumeratePhysicalDevices(instance, c.byref(count), None) != 0 or not 0 < count.value <= 64:
            raise RuntimeError('Vulkan device inventory unavailable')
        devices = (c.c_void_p * count.value)()
        if vk.vkEnumeratePhysicalDevices(instance, c.byref(count), devices) != 0:
            raise RuntimeError('Vulkan device inventory changed')
        result = []
        for device in devices[:count.value]:
            storage = (c.c_uint64 * 512)()
            vk.vkGetPhysicalDeviceProperties(device, c.byref(storage))
            props = c.cast(storage, c.POINTER(PropertiesPrefix)).contents
            result.append(dict(type=props.deviceType, name=props.deviceName.decode('utf-8', 'replace')))
        return result
    finally:
        vk.vkDestroyInstance(instance, None)


def _valid_devices(value):
    return (isinstance(value, list) and 0 < len(value) <= 64 and
            all(isinstance(d, dict) and type(d.get('type')) is int and 0 <= d['type'] <= 4
                and isinstance(d.get('name'), str) and 0 < len(d['name']) <= 256 for d in value))


@lru_cache(maxsize=1)
def vulkan_devices():
    """A hung/crashing/missing driver must never prevent the mod from starting."""
    try:
        completed = subprocess.run([sys.executable, '-B', str(Path(__file__).resolve()), '--probe-vulkan'],
                                   capture_output=True, timeout=4, check=True)
        if len(completed.stdout) > 32768:
            return None
        value = json.loads(completed.stdout)
        return value if _valid_devices(value) else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def overrides(renderer, adapter='', *, platform=None, devices=None):
    """Return only session-local INI changes, and only for a confirmed CPU device.

    Enumeration order matches PCSX2's first-device default. If the player named
    an adapter, use that exact name; unknown/ambiguous names are not guessed.
    """
    if (sys.platform if platform is None else platform) != 'linux' or str(renderer).strip() != '14':
        return {}
    inventory = vulkan_devices() if devices is None else devices
    if not _valid_devices(inventory):
        return {}
    name = str(adapter or '').strip()
    selected = [d for d in inventory if d['name'] == name] if name else inventory[:1]
    # No hardware can be hidden behind an unfamiliar adapter name if every
    # enumerated device is CPU-only. Otherwise preserve an unknown selection.
    cpu_only = all(d['type'] == 4 for d in inventory)
    if not cpu_only and not (len(selected) == 1 and selected[0]['type'] == 4):
        return {}
    return {'Renderer': '-1', 'Adapter': ''}


def announce():
    try:
        import localization
        print(localization.tr(MESSAGE), flush=True)
    except ImportError:
        print(MESSAGE, flush=True)


if __name__ == '__main__':
    if sys.argv[1:] != ['--probe-vulkan'] or sys.platform != 'linux':
        raise SystemExit(2)
    try:
        print(json.dumps(_enumerate_vulkan()))
    except (OSError, RuntimeError, AttributeError):
        raise SystemExit(1)
