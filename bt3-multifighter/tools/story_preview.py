"""Scenario animation picker using the Workbench's existing model renderer."""
from pathlib import Path
from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QLineEdit,QPushButton,
    QLabel,QListWidget,QFileDialog,QDialogButtonBox,QSplitter,QComboBox)
from model_viewer import ModelViewport
from character_names import character_table, character_name
from workbench_layout import fit_window


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
        self.loader=None;self.bank=None;self._request=None;self._closing=False
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
        row=QHBoxLayout();layout.addLayout(row)
        recipient=QLabel('Preview fighter: '+character_name(body));recipient.setWordWrap(True);row.addWidget(recipient,1)
        row.addWidget(QLabel('Animation donor'))
        self.donor_box=QComboBox()
        self.donor_box.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.donor_box.setMinimumContentsLength(20)
        for cid in sorted(set(character_table())|{donor}):self.donor_box.addItem(f'{cid} — {character_name(cid)}',cid)
        self.donor_box.setCurrentIndex(self.donor_box.findData(donor));row.addWidget(self.donor_box,1)
        self.status=QLabel('The recipient model plays the donor skeleton. Drag to orbit; scroll to zoom.');self.status.setWordWrap(True);layout.addWidget(self.status)
        split=QSplitter();layout.addWidget(split,1);self.list=QListWidget();split.addWidget(self.list)
        self.viewport=ModelViewport();self.viewport.setMinimumSize(240,200);split.addWidget(self.viewport);split.setSizes([260,740])
        split.setChildrenCollapsible(False)
        self.list.currentRowChanged.connect(self.select)
        self.buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.accept);self.buttons.rejected.connect(self.reject)
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(False);layout.addWidget(self.buttons)
        self.donor_box.currentIndexChanged.connect(self.load)
        self.iso.textChanged.connect(self.load)
        fit_window(self,1000,720)
        if initial:self.load()
    def browse(self):
        path,_=QFileDialog.getOpenFileName(self,'Game ISO',self.iso.text(),'ISO (*.iso)')
        if path:self.iso.setText(path)
    def load(self,*_):
        if self._closing:return
        self.donor=self.donor_box.currentData()
        self._request=(self.iso.text(),self.body,self.costume,self.donor)
        self.bank=None;self.list.clear();self.viewport.playing=False
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(False)
        self.status.setToolTip('')
        if not Path(self.iso.text()).is_file():self.status.setText('Choose the game ISO first.');return
        self.status.setText('Loading model and donor animation bank…')
        if self.loader is not None:return
        worker=Loader(*self._request,self);self.loader=worker
        worker.loaded.connect(lambda asset,bank:self.loaded(asset,bank,worker))
        worker.failed.connect(lambda message:self.load_failed(message,worker))
        worker.finished.connect(lambda:self.load_finished(worker));worker.start()
    def load_failed(self,message,worker):
        if not self._closing and worker.args==self._request:self.status.setText(message)
    def load_finished(self,worker):
        if self.loader is worker:self.loader=None
        if not self._closing and worker.args!=self._request:self.load()
        worker.deleteLater()
    def loaded(self,asset,bank,worker):
        # A quick second donor selection must never accept the first donor's bank.
        if self._closing or worker.args!=self._request:return
        self.bank=bank;self.viewport.set_asset(asset);self.list.clear()
        for c in bank.clips:
            label=' — Generic intro' if c.animation_id==384 else ''
            self.list.addItem(f'{c.animation_id} — {c.duration_seconds:.2f}s{label}')
        index=next((i for i,c in enumerate(bank.clips) if c.animation_id==self.clip),0)
        self.list.setCurrentRow(index);self.buttons.button(QDialogButtonBox.Ok).setEnabled(bool(bank.clips))
        self.status.setText('Select a clip, inspect it, then choose OK to use it. No game actions or effects run in this preview.')
        if worker.unsupported:
            self.status.setText(self.status.text()+' Unsupported clips: '+', '.join(str(i) for i,_ in worker.unsupported))
            self.status.setToolTip('\n'.join(f'{i}: {message}' for i,message in worker.unsupported))
    def select(self,index):
        if self.bank and 0<=index<len(self.bank.clips):
            clip=self.bank.clips[index];self.clip=clip.animation_id;self.viewport.set_clip(clip);self.viewport.playing=True
    def done(self,result):
        self._closing=True
        if self.loader and self.loader.isRunning():
            self.status.setText('Finishing the asset read before closing…');self.loader.wait()
        self.viewport.playing=False;super().done(result)
