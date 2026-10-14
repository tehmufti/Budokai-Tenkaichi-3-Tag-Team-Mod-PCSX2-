"""Scrollable keyboard editor shared by desktop settings and the online lobby."""
import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path
import keyboard_bindings as kb

TEXT = {
    'title':('Keyboard bindings','Asignación de teclas'),
    'capture':('Set key','Asignar'), 'clear':('Clear','Borrar'),
    'save':('Save','Guardar'), 'cancel':('Cancel','Cancelar'),
    'defaults':('WASD preset','Perfil WASD'), 'test':('Test keys','Probar teclas'),
    'help':('Click Set key, then press the key you want. You can also choose from the list. Escape cancels capture.',
            'Pulsa Asignar y luego la tecla que quieras. También puedes elegirla en la lista. Esc cancela la captura.'),
    'waiting':('Press a key for {button}…','Pulsa una tecla para {button}…'),
    'unsupported':('That key is not supported. Choose another key or use the list.',
                   'Esa tecla no es compatible. Elige otra tecla o utiliza la lista.'),
    'reserved':('Pause, ScrollLock and F8 are reserved for online pause and screenshots.',
                'Pause, ScrollLock y F8 están reservadas para la pausa y las capturas en línea.'),
    'duplicate':('Shared keys: {keys}. These buttons will be pressed together.',
                 'Teclas compartidas: {keys}. Estos botones se pulsarán juntos.'),
    'testing':('Press your keys here to see which PS2 controls they activate. Escape stops the test.',
               'Pulsa tus teclas aquí para ver qué controles de PS2 activan. Esc termina la prueba.'),
    'down':('{key} → {buttons}','{key} → {buttons}'),
    'unbound':('Unbound','Sin asignar'),
    'offline':('Saved separately from other mod settings. Takes effect the next time you start Play. Controller bindings are kept; conflicting emulator shortcuts are temporarily disabled.',
                'Se guarda aparte de los otros ajustes. Se aplica al volver a iniciar Play. Se conservan los mandos y se desactivan temporalmente los atajos del emulador que entren en conflicto.'),
    'online':('These are your own controls. Other players can use different keys. Takes effect when you enter the next room.',
               'Son tus propios controles. Los demás pueden usar teclas diferentes. Se aplica al entrar en la siguiente sala.'),
    'player':('Player {n}','Jugador {n}'),
    'save_error':('Your keyboard bindings could not be saved.','No se ha podido guardar la asignación de teclas.'),
    'pending':('Bindings saved. Restart Play to use them.','Asignación guardada. Vuelve a iniciar Play para aplicarla.'),
}
LABELS = {
    'Up':('D-pad up','Cruceta arriba'),'Right':('D-pad right','Cruceta derecha'),
    'Down':('D-pad down','Cruceta abajo'),'Left':('D-pad left','Cruceta izquierda'),
    'Square':('Melee — Square','Cuerpo a cuerpo — Cuadrado'),
    'Triangle':('Ki blast — Triangle','Ráfaga de ki — Triángulo'),
    'Circle':('Guard — Circle','Guardia — Círculo'),'Cross':('Dash — Cross','Desplazamiento — Equis'),
    'Select':('Select / mod menu','Select / menú del mod'),'Start':('Start / pause menu','Start / pausa'),
    'L1':('L1','L1'),'L2':('Charge ki — L2','Cargar ki — L2'),'R1':('Ascend — R1','Ascender — R1'),
    'R2':('Descend — R2','Descender — R2'),'L3':('Left stick click — L3','Pulsar stick izquierdo — L3'),
    'R3':('Transform / right stick click — R3','Transformar / pulsar stick derecho — R3'),
    'LUp':('Move forward','Avanzar'),'LRight':('Move right','Moverse a la derecha'),
    'LDown':('Move backward','Retroceder'),'LLeft':('Move left','Moverse a la izquierda'),
    'RUp':('Right stick up','Stick derecho arriba'),'RRight':('Right stick right','Stick derecho a la derecha'),
    'RDown':('Right stick down','Stick derecho abajo'),'RLeft':('Right stick left','Stick derecho a la izquierda'),
}

def text(message,language='en',**values):
    return TEXT[message][1 if language=='es' else 0].format(**values)

class KeyboardEditor:
    def __init__(self,parent,mapping,*,language='en',online=False,on_save=None,pads=None):
        self.language=language;self.online=online;self.on_save=on_save;self.pads=pads
        self.pending=None;self.armed=False;self.testing=False;self.result=None
        self.window=tk.Toplevel(parent);self.window.title(text('title',language));self.window.transient(parent)
        self.window.geometry(f"{min(720,max(480,self.window.winfo_screenwidth()-80))}x{min(680,max(440,self.window.winfo_screenheight()-90))}")
        self.window.minsize(480,400)
        outer=ttk.Frame(self.window,padding=14);outer.pack(fill='both',expand=True)
        self.help=ttk.Label(outer,text=text('help',language),wraplength=660,justify='left');self.help.pack(fill='x',pady=(0,8))
        self.pad_name=tk.StringVar(master=self.window,value='Pad1')
        if pads is not None:
            names={text('player',language,n=i+1):name for i,name in enumerate(kb.PADS)}
            self.seat=tk.StringVar(master=self.window,value=next(iter(names)))
            selector=ttk.Combobox(outer,state='readonly',textvariable=self.seat,values=list(names),width=20)
            selector.pack(anchor='w',pady=(0,8))
            def select(_):
                self.save_draft();self.pad_name.set(names[self.seat.get()]);self.set_values(self.pads[self.pad_name.get()])
            selector.bind('<<ComboboxSelected>>',select)
        self.footer=ttk.Label(outer,text=text('online' if online else 'offline',language),wraplength=660,justify='left')
        buttons=ttk.Frame(outer);buttons.pack(side='bottom',fill='x',pady=(8,0))
        ttk.Button(buttons,text=text('defaults',language),command=lambda:self.set_values(kb.DEFAULT)).pack(side='left')
        ttk.Button(buttons,text=text('test',language),command=self.test_keys).pack(side='left',padx=6)
        ttk.Button(buttons,text=text('cancel',language),command=self.close).pack(side='right')
        ttk.Button(buttons,text=text('save',language),command=self.save).pack(side='right',padx=6)
        self.footer.pack(side='bottom',fill='x',pady=(8,0))
        self.status=tk.StringVar(master=self.window)
        self.status_label=ttk.Label(outer,textvariable=self.status,wraplength=660,justify='left')
        self.status_label.pack(side='bottom',fill='x',pady=(6,0))
        body=ttk.Frame(outer);body.pack(fill='both',expand=True)
        canvas=tk.Canvas(body,highlightthickness=0);scroll=ttk.Scrollbar(body,orient='vertical',command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set);scroll.pack(side='right',fill='y');canvas.pack(side='left',fill='both',expand=True)
        rows=ttk.Frame(canvas);item=canvas.create_window((0,0),window=rows,anchor='nw');rows.columnconfigure(0,weight=1)
        rows.bind('<Configure>',lambda _:canvas.configure(scrollregion=canvas.bbox('all')))
        self.labels=[];self.variables={};self.controls={}
        def resize(event):
            canvas.itemconfigure(item,width=event.width)
            for label in self.labels:label.configure(wraplength=max(100,event.width-280))
            for label in (self.help,self.footer,self.status_label):label.configure(wraplength=max(220,event.width-12))
        canvas.bind('<Configure>',resize)
        for row,button in enumerate(kb.BUTTONS):
            caption=LABELS[button][1 if language=='es' else 0]
            label=ttk.Label(rows,text=caption,wraplength=300);label.grid(row=row,column=0,sticky='w',pady=6,padx=(0,8));self.labels.append(label)
            variable=tk.StringVar(master=self.window,value=mapping.get(button,''));self.variables[button]=variable
            choice=ttk.Combobox(rows,textvariable=variable,state='readonly',values=('',)+tuple(k for k in kb.KEYS if not online or k not in kb.ONLINE_RESERVED),width=13)
            choice.grid(row=row,column=1,sticky='e',padx=4)
            choice.bind('<<ComboboxSelected>>',lambda _:self.refresh_status())
            capture=ttk.Button(rows,text=text('capture',language),command=lambda b=button:self.capture(b),width=9)
            capture.grid(row=row,column=2,padx=4)
            for key in ('Return','space'):
                capture.bind('<KeyPress-'+key+'>',lambda e,b=button:self.capture_from_key(b))
            ttk.Button(rows,text='×',width=2,command=lambda b=button:self.clear(b)).grid(row=row,column=3,padx=(4,0))
            self.controls[button]=capture
        self.window.bind('<KeyPress>',self.key_press);self.window.bind('<KeyRelease>',self.key_release)
        self.window.protocol('WM_DELETE_WINDOW',self.close)
        def wheel(event):
            canvas.yview_scroll(-1 if getattr(event,'num',0)==4 or getattr(event,'delta',0)>0 else 1,'units');return 'break'
        self.window.bind('<MouseWheel>',wheel);self.window.bind('<Button-4>',wheel);self.window.bind('<Button-5>',wheel)
        # X11 may not have mapped a new window yet. Use the existing bounded
        # modal-grab helper rather than failing the whole settings dialog.
        import input_binding
        self.refresh_status();input_binding.grab_dialog(self.window);self.window.focus_set()

    def values(self):return {button:variable.get() for button,variable in self.variables.items()}
    def set_values(self,mapping):
        self.pending=None;self.testing=False
        for button,variable in self.variables.items():variable.set(mapping.get(button,''))
        self.refresh_status()
    def clear(self,button):self.variables[button].set('');self.refresh_status()
    def save_draft(self):
        if self.pads is not None:self.pads[self.pad_name.get()]=self.values()
    def refresh_status(self):
        values=self.values()
        if self.pads is not None:
            values={f'{pad}/{button}':key for pad,mapping in self.pads.items()
                    for button,key in (self.values() if pad==self.pad_name.get() else mapping).items()}
        duplicate=kb.duplicates(values)
        self.status.set(text('duplicate',self.language,keys=', '.join(duplicate)) if duplicate else '')
    def capture(self,button):
        self.pending=button;self.armed=False;self.testing=False
        self.status.set(text('waiting',self.language,button=LABELS[button][1 if self.language=='es' else 0]))
        self.window.after_idle(self.arm)
    def arm(self):
        if self.pending:self.armed=True
    def capture_from_key(self,button):
        self.pending=button;self.armed=False;self.testing=False
        self.status.set(text('waiting',self.language,button=button));return 'break'
    def key_release(self,event):
        if self.pending and not self.armed:self.armed=True
    def key_press(self,event):
        if event.keysym=='Escape':
            if self.pending or self.testing:self.pending=None;self.testing=False;self.refresh_status()
            else:self.close()
            return 'break'
        if not self.pending and not self.testing:return None
        if self.pending and not self.armed:return 'break'
        key=kb.event_key(event)
        if key is None:self.status.set(text('unsupported',self.language));return 'break'
        if self.online and key in kb.ONLINE_RESERVED:self.status.set(text('reserved',self.language));return 'break'
        if self.testing:
            buttons=[button for button,value in self.values().items() if value==key]
            self.status.set(text('down',self.language,key=key,buttons=', '.join(buttons) or text('unbound',self.language)))
        else:
            self.variables[self.pending].set(key);self.pending=None;self.refresh_status()
        return 'break'
    def test_keys(self):
        self.pending=None;self.testing=True;self.status.set(text('testing',self.language));self.window.focus_set()
    def save(self):
        try:
            checked=kb.validate(self.values(),online=self.online)
            self.save_draft()
            result={pad:kb.validate(values) for pad,values in self.pads.items()} if self.pads is not None else checked
            if self.on_save:self.on_save(result)
        except (OSError,ValueError) as error:
            messagebox.showerror(text('title',self.language),text('save_error',self.language)+'\n\n'+str(error),parent=self.window);return
        self.result=result;self.close()
    def close(self):
        self.pending=None;self.testing=False
        self.window.destroy()

def show(parent,mapping,**options):
    editor=KeyboardEditor(parent,mapping,**options);parent.wait_window(editor.window);return editor.result

def show_offline(parent,*,language='en'):
    import runtime_profile
    try:record=kb.load_offline()
    except ValueError:record=dict(schema=1,pads={},hotkeys={})
    try:ini=Path(runtime_profile.CONFIG).read_text(encoding='utf-8-sig')
    except OSError:ini=''
    pads={pad:record['pads'].get(pad) or kb.keyboard_profile(ini,pad) for pad in kb.PADS}
    for pad,mapping in pads.items():
        if not any(mapping.values()):pads[pad]=dict(kb.DEFAULT) if pad=='Pad1' else kb.validate({})
    def save(values):
        kb.save_offline_profiles(values)
    return show(parent,pads['Pad1'],language=language,pads=pads,on_save=save)
