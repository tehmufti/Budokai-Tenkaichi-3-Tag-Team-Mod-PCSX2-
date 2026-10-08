"""An explicitly submitted, opaque layered bitmap for the owned loading HWND.

UpdateLayeredWindow supplies compositor pixels directly; window visibility and
hit-testing alone do not establish that a fullscreen game displays our cover.
No target-window style, size, focus or renderer setting is changed here.
"""
import ctypes


class LayeredBitmap:
    def __init__(self, api, gdi):
        self.api,self.gdi=api,gdi
        self.dc=self.bitmap=self.previous=None;self.size=None;self.submissions=0
        w,u,g=api.w,api.user,gdi
        class Blend(ctypes.Structure):
            _fields_=[('operation',ctypes.c_ubyte),('flags',ctypes.c_ubyte),
                      ('alpha',ctypes.c_ubyte),('format',ctypes.c_ubyte)]
        self.Blend=Blend
        u.GetDC.argtypes=[w.HWND];u.GetDC.restype=w.HDC
        u.ReleaseDC.argtypes=[w.HWND,w.HDC]
        u.UpdateLayeredWindow.argtypes=[w.HWND,w.HDC,ctypes.POINTER(w.POINT),ctypes.POINTER(w.SIZE),
            w.HDC,ctypes.POINTER(w.POINT),w.DWORD,ctypes.POINTER(Blend),w.DWORD]
        u.UpdateLayeredWindow.restype=w.BOOL
        g.CreateCompatibleDC.argtypes=[w.HDC];g.CreateCompatibleDC.restype=w.HDC
        g.CreateCompatibleBitmap.argtypes=[w.HDC,ctypes.c_int,ctypes.c_int];g.CreateCompatibleBitmap.restype=w.HBITMAP
        g.DeleteDC.argtypes=[w.HDC]

    def prepare(self,width,height):
        if not 1<=width<=16384 or not 1<=height<=16384:raise ValueError('Invalid loading bitmap dimensions')
        if self.size==(width,height):return self.dc
        self.close();screen=self.api.user.GetDC(None)
        if not screen:raise ctypes.WinError(ctypes.get_last_error())
        try:
            self.dc=self.gdi.CreateCompatibleDC(screen)
            if not self.dc:raise ctypes.WinError(ctypes.get_last_error())
            self.bitmap=self.gdi.CreateCompatibleBitmap(screen,width,height)
            if not self.bitmap:raise ctypes.WinError(ctypes.get_last_error())
            self.previous=self.gdi.SelectObject(self.dc,self.bitmap)
            if not self.previous or self.previous==ctypes.c_void_p(-1).value:
                raise ctypes.WinError(ctypes.get_last_error())
            self.size=(width,height)
            return self.dc
        except Exception:self.close();raise
        finally:self.api.user.ReleaseDC(None,screen)

    def submit(self,hwnd):
        if not self.size:raise RuntimeError('Loading bitmap has not been painted')
        w,u=self.api.w,self.api.user
        rect=w.RECT()
        if not u.GetWindowRect(hwnd,ctypes.byref(rect)):raise ctypes.WinError(ctypes.get_last_error())
        point=w.POINT(rect.left,rect.top);size=w.SIZE(*self.size);source=w.POINT()
        # Constant255, AlphaFormat0: every painted pixel is fully opaque. This
        # is explicit bitmap submission, not the previous alpha254 experiment.
        blend=self.Blend(0,0,255,0)
        if not u.UpdateLayeredWindow(hwnd,None,ctypes.byref(point),ctypes.byref(size),self.dc,
                ctypes.byref(source),0,ctypes.byref(blend),2):
            raise ctypes.WinError(ctypes.get_last_error())
        self.submissions+=1

    def close(self):
        if self.dc and self.previous:self.gdi.SelectObject(self.dc,self.previous)
        if self.bitmap:self.gdi.DeleteObject(self.bitmap)
        if self.dc:self.gdi.DeleteDC(self.dc)
        self.dc=self.bitmap=self.previous=None;self.size=None
