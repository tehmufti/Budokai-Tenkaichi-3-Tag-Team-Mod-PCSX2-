"""Native opaque Windows loading surface with one authoritative HWND/geometry.

No toolkit wrapper can replace the window handle or reapply an old geometry.
The host API supplies scoped placement; this class only paints its own window.
"""
import ctypes
import traceback
import time
from pathlib import Path
from loading_bitmap_surface import LayeredBitmap

COVER_EXT_STYLE = 0x08000000 | 0x80 | 0x80000  # NOACTIVATE | TOOLWINDOW | LAYERED


class BitmapHeader(ctypes.Structure):
    _fields_ = [('size', ctypes.c_uint32), ('width', ctypes.c_int32),
                ('height', ctypes.c_int32), ('planes', ctypes.c_uint16),
                ('bits', ctypes.c_uint16), ('compression', ctypes.c_uint32),
                ('bytes', ctypes.c_uint32), ('xppm', ctypes.c_int32),
                ('yppm', ctypes.c_int32), ('used', ctypes.c_uint32),
                ('important', ctypes.c_uint32)]


_pictures = {}          # (mode, humans, teams, message) -> (quantised composite, layers, progress rendered at)


def progress_overlay(picture, layers, progress):
    """The gauge fill and the percentage the guest draws per progress step, on the static composite."""
    lights = (layers or {}).get('lights') or {}
    gauge, atlas = lights.get('gauge'), (layers or {}).get('atlas_image')
    if not gauge or atlas is None: return picture
    from PIL import ImageDraw
    import loading_protocol as protocol
    import loading_art_v4 as art
    image = picture.copy(); d = ImageDraw.Draw(image)
    fill, _ = protocol.gauge_fill(progress)
    x0, x1, y0, y1 = gauge['x0'], gauge['x1'], gauge['y0'], gauge['y1']; end = x0+((x1-x0)*fill >> 8)
    c0, c1, c2 = gauge['colors']
    for x in range(x0, end):
        t = (x-x0)/max(1, x1-x0)
        d.line((x, y0, x, y1-1), fill=art.mix(c0, c1, t*2) if t < .5 else art.mix(c1, c2, (t-.5)*2))
    if end > x0: d.rectangle((max(x0, end-2), y0, end-1, y1-1), fill=gauge['tip'])
    for digit in art.gauge_digits(progress):
        glyph = atlas.crop((digit['u'], digit['v'], digit['u']+digit['w'], digit['v']+digit['h']))
        image.paste(glyph, (digit['x'], digit['y']), glyph)
    return image


def mode_bitmap(data):
    """The exact native loading artwork for the desktop fallback: the quantised composite is
    cached per picture and only the cheap progress overlay is redrawn per step."""
    from guest_loading_screen import render, is_v4
    mode, humans = data.get('mode', 'teams'), data.get('humans', 1)
    teams, message, progress = data.get('teams', ()), data.get('message', 'GETTING YOUR FIGHTERS READY'), data.get('progress', 0)
    error = tuple(data.get('error') or ()) or None   # the failure state: red text, no gauge (player_errors.cover_text)
    key = (mode, humans, repr(teams), message, error)
    entry = _pictures.get(key)
    if entry is None or (not is_v4(entry[1]) and entry[2] != progress):   # the fallback picture bakes its bar
        picture, layers, _ = render(teams, progress, message, mode=mode, humans=humans, **({'error': error} if error else {}))
        if len(_pictures) >= 4: _pictures.clear()
        _pictures[key] = entry = (picture, layers, progress)
    picture, layers, _ = entry
    return progress_overlay(picture, layers, progress).tobytes('raw', 'BGRX')


def presentation_layout(width, height):
    """Keep the same readable proportions in a window and at4K fullscreen."""
    scale = max(.5, min(width/1000, height/650))
    center = height/2
    return dict(title_pixels=max(16, round(34*scale)),
                message_pixels=max(11, round(20*scale)),
                hint_pixels=max(10, round(15*scale)),
                title_y=center-85*scale, message_y=center-17*scale,
                bar_y=center+45*scale, bar_height=max(3, round(5*scale)),
                hint_y=center+91*scale)


def team_layout(width,height,teams):
    """Parallel portrait/name rows with bounded text areas at all viewport sizes."""
    if width<440 or height<330 or not teams:return None
    scale=min(width/1000,height/650)
    rows=max(len(t.get('fighters',[]))for t in teams)
    row_height=min(height*.13,82*scale);gap=12*scale
    total=rows*row_height+(rows-1)*gap
    top=height*.45-total*.18
    return dict(scale=scale,title_y=height*.19,message_y=height*.28,
        team_y=top-22*scale,top=top,row_height=row_height,gap=gap,
        bar_y=max(height*.83,top+total+32*scale),hint_y=height*.92,
        lefts=(width*.1,width*.54),card_width=width*.36)


def activity_frame(now):
    return int(now*6)%12


class NativeLoadingWindow:
    def __init__(self, api):
        self.api = api; self.data = {}; self.closed = False; self.target_hwnd = 0
        self.bitmaps={}
        u, k, w = api.user, api.kernel, api.w
        self.gdi = ctypes.WinDLL('gdi32', use_last_error=True)
        self.proc_type = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, w.HWND, w.UINT, w.WPARAM, w.LPARAM)
        class WindowClass(ctypes.Structure):
            _fields_ = [('style', w.UINT), ('procedure', self.proc_type), ('class_extra', ctypes.c_int),
                        ('window_extra', ctypes.c_int), ('instance', w.HINSTANCE), ('icon', w.HANDLE),
                        ('cursor', w.HANDLE), ('background', w.HANDLE), ('menu', w.LPCWSTR), ('name', w.LPCWSTR)]
        class Paint(ctypes.Structure):
            _fields_ = [('dc', w.HANDLE), ('erase', w.BOOL), ('rect', w.RECT), ('restore', w.BOOL),
                        ('incremental', w.BOOL), ('reserved', ctypes.c_byte*32)]
        self.Paint = Paint
        k.GetModuleHandleW.argtypes = [w.LPCWSTR]; k.GetModuleHandleW.restype = w.HINSTANCE
        u.RegisterClassW.argtypes = [ctypes.POINTER(WindowClass)]; u.RegisterClassW.restype = w.WORD
        u.CreateWindowExW.argtypes = [w.DWORD, w.LPCWSTR, w.LPCWSTR, w.DWORD]+[ctypes.c_int]*4+[w.HWND, w.HMENU, w.HINSTANCE, ctypes.c_void_p]
        u.CreateWindowExW.restype = w.HWND
        u.DefWindowProcW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]; u.DefWindowProcW.restype = ctypes.c_ssize_t
        u.DestroyWindow.argtypes = [w.HWND]
        u.BeginPaint.argtypes = [w.HWND, ctypes.POINTER(Paint)]; u.BeginPaint.restype = w.HANDLE
        u.EndPaint.argtypes = [w.HWND, ctypes.POINTER(Paint)]
        u.FillRect.argtypes = [w.HANDLE, ctypes.POINTER(w.RECT), w.HANDLE]
        u.DrawTextW.argtypes = [w.HANDLE, w.LPCWSTR, ctypes.c_int, ctypes.POINTER(w.RECT), w.UINT]
        u.InvalidateRect.argtypes = [w.HWND, ctypes.POINTER(w.RECT), w.BOOL]
        u.UpdateWindow.argtypes = [w.HWND]
        u.PeekMessageW.argtypes = [ctypes.POINTER(w.MSG), w.HWND, w.UINT, w.UINT, w.UINT]
        u.TranslateMessage.argtypes = [ctypes.POINTER(w.MSG)]
        u.DispatchMessageW.argtypes = [ctypes.POINTER(w.MSG)]; u.DispatchMessageW.restype = ctypes.c_ssize_t
        g = self.gdi
        g.CreateSolidBrush.argtypes = [w.DWORD]; g.CreateSolidBrush.restype = w.HANDLE
        g.DeleteObject.argtypes = [w.HANDLE]
        g.SetBkMode.argtypes = [w.HANDLE, ctypes.c_int]
        g.SetTextColor.argtypes = [w.HANDLE, w.DWORD]
        g.CreateFontW.argtypes = [ctypes.c_int]*5+[w.DWORD]*8+[w.LPCWSTR]; g.CreateFontW.restype = w.HANDLE
        g.SelectObject.argtypes = [w.HANDLE, w.HANDLE]; g.SelectObject.restype = w.HANDLE
        g.StretchBlt.argtypes=[w.HDC]+[ctypes.c_int]*4+[w.HDC]+[ctypes.c_int]*4+[w.DWORD]
        g.SetStretchBltMode.argtypes=[w.HDC,ctypes.c_int]
        g.StretchDIBits.argtypes=[w.HDC]+[ctypes.c_int]*8+[
            ctypes.c_void_p,ctypes.POINTER(BitmapHeader),w.UINT,w.DWORD]
        g.StretchDIBits.restype=ctypes.c_int
        u.LoadImageW.argtypes=[w.HINSTANCE,w.LPCWSTR,w.UINT,ctypes.c_int,ctypes.c_int,w.UINT]
        u.LoadImageW.restype=w.HANDLE
        self.surface=LayeredBitmap(api,g)
        self.procedure = self.proc_type(self._procedure)
        instance = k.GetModuleHandleW(None)
        wc = WindowClass(0, self.procedure, 0, 0, instance, None, None, None, None, 'BT3LoadingPresentation')
        if not u.RegisterClassW(ctypes.byref(wc)):
            raise ctypes.WinError(ctypes.get_last_error())
        self.hwnd = u.CreateWindowExW(COVER_EXT_STYLE, wc.name, 'Preparing team match',
                                     0x80000000, 0, 0, 1, 1, None, None, instance, None)
        if not self.hwnd: raise ctypes.WinError(ctypes.get_last_error())
        self.event_type = ctypes.WINFUNCTYPE(None, w.HANDLE, w.DWORD, w.HWND, w.LONG, w.LONG, w.DWORD, w.DWORD)
        self.event_callback = self.event_type(self._foreground_changed)
        u.SetWinEventHook.argtypes = [w.DWORD, w.DWORD, w.HMODULE, self.event_type, w.DWORD, w.DWORD, w.DWORD]
        u.SetWinEventHook.restype = w.HANDLE; u.UnhookWinEvent.argtypes = [w.HANDLE]
        self.event_hook = u.SetWinEventHook(3, 3, None, self.event_callback, 0, 0, 2)

    def _foreground_changed(self, *_):
        if self.target_hwnd and self.api.foreground() != self.target_hwnd:
            self.api.conceal(self.hwnd)

    def _procedure(self, hwnd, message, wparam, lparam):
        try:
            if message == 0x21: return 3  # WM_MOUSEACTIVATE / MA_NOACTIVATE
            if message == 0x14: return 1  # WM_ERASEBKGND: paint is fully opaque.
            if message == 0x0F:
                paint = self.Paint(); dc = self.api.user.BeginPaint(hwnd, ctypes.byref(paint))
                # The actual pixels are supplied by UpdateLayeredWindow, not a
                # WM_PAINT rectangle that a fullscreen presentation may bypass.
                self.api.user.EndPaint(hwnd, ctypes.byref(paint))
                return 0
            if message == 2: self.closed = True; return 0
        except Exception: traceback.print_exc()
        return self.api.user.DefWindowProcW(hwnd, message, wparam, lparam)

    @staticmethod
    def rgb(value):
        value = value.lstrip('#'); return int(value[4:6]+value[2:4]+value[0:2], 16)

    def paint(self, hwnd, dc):
        w, u, g = self.api.w, self.api.user, self.gdi
        rect = w.RECT(); u.GetClientRect(hwnd, ctypes.byref(rect))
        width, height = rect.right, rect.bottom
        if self.data.get('mode') in ('teams', 'ffa', 'coop') and width >= 440 and height >= 330:
            self.paint_mode(dc, width, height)
            return
        def fill(x, y, right, bottom, color):
            brush = g.CreateSolidBrush(self.rgb(color)); area = w.RECT(int(x), int(y), int(right), int(bottom))
            try: u.FillRect(dc, ctypes.byref(area), brush)
            finally: g.DeleteObject(brush)
        def text(value, y, pixels, color, bold=False, bounds=None, align=1):
            font = g.CreateFontW(-pixels, 0, 0, 0, 700 if bold else 400, 0, 0, 0, 1, 0, 0, 5, 0, 'Segoe UI')
            previous = g.SelectObject(dc, font)
            try:
                g.SetBkMode(dc, 1); g.SetTextColor(dc, self.rgb(color))
                left,right=bounds or (width*.06,width*.94)
                area = w.RECT(int(left), int(y-pixels), int(right), int(y+pixels))
                u.DrawTextW(dc, str(value), -1, ctypes.byref(area), align | 4 | 0x20 | 0x8000)
            finally: g.SelectObject(dc, previous); g.DeleteObject(font)
        fill(0, 0, width, height, '#0d111c')
        layout = presentation_layout(width, height)
        teams=self.data.get('teams',[])
        cards=team_layout(width,height,teams)
        if cards:
            layout.update({key:cards[key]for key in ('title_y','message_y','bar_y','hint_y')})
            scale=cards['scale']
            for team in teams:
                side=team['side'];left=cards['lefts'][side];right=left+cards['card_width']
                color=('#65baff','#f2ad4d')[side]
                text(f'TEAM {side+1}',cards['team_y'],max(11,round(14*scale)),color,True,(left,right))
                for slot,fighter in enumerate(team['fighters']):
                    top=cards['top']+slot*(cards['row_height']+cards['gap']);bottom=top+cards['row_height']
                    fill(left,top,right,bottom,'#171f30');fill(left,top,left+3*scale,bottom,color)
                    size=cards['row_height']-12*scale;x=left+9*scale;y=top+6*scale
                    fill(x,y,x+size,y+size,'#111827')
                    self.portrait(dc,fighter.get('bitmap_path'),x,y,size)
                    name_left=x+size+12*scale;bounds=(name_left,right-10*scale)
                    base=fighter.get('base_name',fighter.get('name','Fighter'))
                    form=fighter.get('form','')
                    text(base,top+cards['row_height']*(.37 if form else .5),max(11,round(17*scale)),
                         '#eef3fb',True,bounds,0)
                    if form:text(form,top+cards['row_height']*.69,max(9,round(12*scale)),'#b5c3d9',False,bounds,0)
        error = self.data.get('error')
        if error:
            # The failure state looks like an error, never like loading: red title and lines, no bar, no hint.
            text(self.data.get('title', 'Match setup stopped'), layout['title_y'], layout['title_pixels'], '#ff6b6b', True)
            text(str(error[0]), layout['message_y'], layout['message_pixels'], '#ff8a80')
            if len(error) > 1:
                text(str(error[1]), layout['bar_y'], layout['hint_pixels'], '#f4b4ae')
            return
        text(self.data.get('title', 'Preparing your team match'), layout['title_y'],
             layout['title_pixels'], '#ffffff', True)
        text(self.data.get('message', 'Getting your fighters ready...'), layout['message_y'],
             layout['message_pixels'], '#b5c3d9')
        left, right, top = width*.25, width*.75, layout['bar_y']
        fill(left, top, right, top+layout['bar_height'], '#283346')
        progress = max(0, min(100, int(self.data.get('progress', 0))))
        fill(left, top, left+(right-left)*progress/100, top+layout['bar_height'], '#f2ad4d')
        text('Your match will begin when everyone is ready.', layout['hint_y'],
             layout['hint_pixels'], '#8fa0b8')

    def paint_mode(self, dc, width, height):
        # The helper owns this bitmap only. No emulator surface, memory or
        # transport field is touched; nearest scaling preserves the glyphs.
        key = (self.data.get('mode'), self.data.get('humans'),
               repr(self.data.get('teams')), self.data.get('progress'), self.data.get('message'),
               repr(self.data.get('error')))
        if getattr(self, 'mode_picture_key', None) != key:
            self.mode_picture_bytes = mode_bitmap(self.data)
            self.mode_picture_key = key
        header = BitmapHeader(40, 512, -448, 1, 32, 0, 512*448*4, 0, 0, 0, 0)
        g = self.gdi
        g.SetStretchBltMode(dc, 3)
        result = g.StretchDIBits(dc, 0, 0, width, height, 0, 0, 512, 448,
                                self.mode_picture_bytes, ctypes.byref(header), 0, 0x00CC0020)
        if result in (0, -1): raise ctypes.WinError(ctypes.get_last_error())
        # The guest animates its own bar; the helper paints the static picture only.

    def portrait(self,dc,path,x,y,size):
        if not path:return False
        path=Path(path)
        # The chosen game disc's portraits (character_names.assets_folder): the installed disc's assets, or the
        # folder of the disc chosen in Mod settings > Game disc.
        from character_names import assets_folder
        root=assets_folder()/'portraits'
        if path.suffix.lower()!='.bmp' or path.parent.resolve()!=root.resolve():return False
        key=str(path)
        if key not in self.bitmaps:
            self.bitmaps[key]=self.api.user.LoadImageW(None,key,0,0,0,0x10|0x2000)
        bitmap=self.bitmaps[key]
        if not bitmap:return False
        source=self.gdi.CreateCompatibleDC(dc)
        if not source:return False
        previous=self.gdi.SelectObject(source,bitmap)
        try:
            self.gdi.SetStretchBltMode(dc,3)
            return bool(self.gdi.StretchBlt(dc,int(x),int(y),int(size),int(size),source,0,0,64,64,0x00CC0020))
        finally:self.gdi.SelectObject(source,previous);self.gdi.DeleteDC(source)

    def redraw(self, data):
        self.data = data
        rect=self.api.w.RECT()
        if not self.api.user.GetClientRect(self.hwnd,ctypes.byref(rect)):
            raise ctypes.WinError(ctypes.get_last_error())
        dc=self.surface.prepare(rect.right,rect.bottom)
        self.paint(self.hwnd,dc)
        self.surface.submit(self.hwnd)

    def pump(self):
        message = self.api.w.MSG()
        while self.api.user.PeekMessageW(ctypes.byref(message), None, 0, 0, 1):
            if message.message == 0x12: self.closed = True; break
            self.api.user.TranslateMessage(ctypes.byref(message))
            self.api.user.DispatchMessageW(ctypes.byref(message))

    def close(self):
        self.api.conceal(self.hwnd)
        if self.event_hook: self.api.user.UnhookWinEvent(self.event_hook)
        self.api.user.DestroyWindow(self.hwnd)
        self.surface.close()
        for bitmap in self.bitmaps.values():
            if bitmap:self.gdi.DeleteObject(bitmap)
        self.bitmaps.clear()
