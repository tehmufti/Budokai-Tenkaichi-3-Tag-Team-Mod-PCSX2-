"""Scenario animation picker using the Workbench's existing model renderer."""
from pathlib import Path
from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QLineEdit,QPushButton,
    QLabel,QListWidget,QFileDialog,QDialogButtonBox,QSplitter)
from model_viewer import ModelViewport


def preview_bank(data):
    """Keep a valid bank usable when an unrelated native channel is unsupported.

    The runtime still validates the selected clip strictly. Unsupported clips
    are reported here and never replaced with made-up animation data.
    """
    import struct
    import model_assets,model_animations
    if len(data)<4:raise ValueError('Truncated animation bank header')
    count=struct.unpack_from('<I',data)[0]
    if not 414<=count<=4096:raise ValueError('Invalid animation bank')
    clips=[];absent=[];unsupported=[]
    for index in range(414):
        raw=model_assets.package_entry(data,index+1)
        if not raw:absent.append(index);continue
        try:
            decoded=model_animations.decompress_animation(raw)
            if not decoded:absent.append(index);continue
            clips.append(model_animations.AnimationClip.from_decoded(index,decoded))
        except model_animations.AnimationFormatError as error:unsupported.append((index,str(error)))
    return model_animations.AnimationBank(tuple(clips),tuple(absent)),unsupported


class Loader(QThread):
    loaded=Signal(object,object)
    failed=Signal(str)
    def __init__(self,iso,body,costume,donor,parent):
        super().__init__(parent);self.args=iso,body,costume,donor
    def run(self):
        try:
            import model_assets,model_animations
            from dataclasses import replace
            iso,body,costume,donor=self.args
            asset=model_assets.load_character(iso,body,costume)
            bank,self.unsupported=preview_bank(model_assets.read_animation_bank(iso,donor))
            # Cinematic playback anchors bone-zero translation at the mark.
            # Preview the same pose, keeping the remaining skeleton untouched.
            bank=replace(bank,clips=tuple(replace(c,tracks=tuple(
                replace(t,keys=tuple(replace(k,translation=(0.,0.,0.)) if k.translation is not None else k for k in t.keys))
                if t.bone_id==0 else t for t in c.tracks)) for c in bank.clips))
            self.loaded.emit(asset,bank)
        except Exception as error:self.failed.emit(str(error))


class AnimationPicker(QDialog):
    def __init__(self,body,costume,donor,clip=0,parent=None):
        super().__init__(parent);self.setWindowTitle('Preview donor animation on scenario fighter');self.resize(1000,720)
        self.body,self.costume,self.donor,self.clip=body,costume,donor,clip
        self.loader=None;self.bank=None
        layout=QVBoxLayout(self);row=QHBoxLayout();layout.addLayout(row)
        import game_profile
        initial=game_profile.iso_path() or ''
        owner=parent
        while owner:
            if hasattr(owner,'iso') and hasattr(owner.iso,'text'):initial=owner.iso.text();break
            owner=owner.parent()
        self.iso=QLineEdit(str(initial));row.addWidget(self.iso,1)
        browse=QPushButton('Choose ISO');browse.clicked.connect(self.browse);row.addWidget(browse)
        load=QPushButton('Load preview');load.clicked.connect(self.load);row.addWidget(load)
        self.status=QLabel('The recipient model plays the donor skeleton. Drag to orbit; scroll to zoom.');layout.addWidget(self.status)
        split=QSplitter();layout.addWidget(split,1);self.list=QListWidget();split.addWidget(self.list)
        self.viewport=ModelViewport();split.addWidget(self.viewport);split.setSizes([260,740])
        self.list.currentRowChanged.connect(self.select)
        self.buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.accept);self.buttons.rejected.connect(self.reject)
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(False);layout.addWidget(self.buttons)
        if initial:self.load()
    def browse(self):
        path,_=QFileDialog.getOpenFileName(self,'Game ISO',self.iso.text(),'ISO (*.iso)')
        if path:self.iso.setText(path);self.load()
    def load(self):
        if self.loader and self.loader.isRunning():return
        if not Path(self.iso.text()).is_file():self.status.setText('Choose the game ISO first.');return
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(False)
        self.status.setText('Loading model and donor animation bank…')
        self.loader=Loader(self.iso.text(),self.body,self.costume,self.donor,self)
        self.loader.loaded.connect(self.loaded);self.loader.failed.connect(self.status.setText);self.loader.start()
    def loaded(self,asset,bank):
        self.bank=bank;self.viewport.set_asset(asset);self.list.clear()
        for c in bank.clips:
            label=' — Generic intro' if c.animation_id==384 else ''
            self.list.addItem(f'{c.animation_id} — {c.duration_seconds:.2f}s{label}')
        index=next((i for i,c in enumerate(bank.clips) if c.animation_id==self.clip),0)
        self.list.setCurrentRow(index);self.buttons.button(QDialogButtonBox.Ok).setEnabled(bool(bank.clips))
        self.status.setText('Select a clip, inspect it, then choose OK to use it. No game actions or effects run in this preview.')
        if self.loader and self.loader.unsupported:
            self.status.setText(self.status.text()+' Unsupported clips: '+', '.join(str(i) for i,_ in self.loader.unsupported))
            self.status.setToolTip('\n'.join(f'{i}: {message}' for i,message in self.loader.unsupported))
    def select(self,index):
        if self.bank and 0<=index<len(self.bank.clips):
            clip=self.bank.clips[index];self.clip=clip.animation_id;self.viewport.set_clip(clip);self.viewport.playing=True
    def done(self,result):
        if self.loader and self.loader.isRunning():
            self.status.setText('Finishing the asset read before closing…');self.loader.wait()
        self.viewport.playing=False;super().done(result)
