"""Native Qt voice browser/player. PCM lives in memory and stops when closed."""
from PySide6.QtCore import QThread, Signal, QBuffer, QByteArray, QIODevice
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QLineEdit,QPushButton,
    QLabel,QListWidget,QFileDialog,QDialogButtonBox,QComboBox,QSlider)
from PySide6.QtCore import Qt
from PySide6.QtMultimedia import QAudioFormat,QAudioSink,QAudio
import story_voice


class VoiceLoader(QThread):
    loaded=Signal(object)
    failed=Signal(str)
    def __init__(self,fn,args,parent):super().__init__(parent);self.fn=fn;self.args=args
    def run(self):
        try:self.loaded.emit(self.fn(*self.args))
        except Exception as e:self.failed.emit(str(e))


class VoicePicker(QDialog):
    def __init__(self,character,line=0,volume=100,parent=None):
        super().__init__(parent);self.setWindowTitle('Voice line preview');self.resize(730,570)
        self.line=line;self.worker=None;self.sink=None;self.buffer=None;self.rows=[];self.busy=False
        layout=QVBoxLayout(self);row=QHBoxLayout();layout.addLayout(row)
        self.iso=QLineEdit(story_voice.default_iso(parent));row.addWidget(self.iso,1)
        self.browse_button=QPushButton('Choose ISO');self.browse_button.clicked.connect(self.browse);row.addWidget(self.browse_button)
        row=QHBoxLayout();layout.addLayout(row)
        from story_editor import characters
        self.character=characters(character);row.addWidget(self.character,1)
        self.bank=QComboBox();self.bank.addItems(['Primary voice bank','Alternate voice bank']);row.addWidget(self.bank)
        self.reload=QPushButton('Load lines');self.reload.clicked.connect(self.scan);row.addWidget(self.reload)
        note=QLabel('Preview the actual disc audio. Bank names depend on the ISO: English/Spanish and Japanese. In a match, the game’s voice-language setting chooses the bank.');note.setWordWrap(True);layout.addWidget(note)
        self.list=QListWidget();self.list.currentRowChanged.connect(self.select);self.list.itemDoubleClicked.connect(lambda *_:self.play());layout.addWidget(self.list,1)
        row=QHBoxLayout();layout.addLayout(row)
        self.play_button=QPushButton('▶ Play');self.play_button.clicked.connect(self.play);row.addWidget(self.play_button)
        stop=QPushButton('■ Stop');stop.clicked.connect(self.stop);row.addWidget(stop)
        self.volume=QSlider(Qt.Horizontal);self.volume.setRange(0,100);self.volume.setValue(volume);row.addWidget(QLabel('Volume'));row.addWidget(self.volume)
        self.volume.valueChanged.connect(lambda v:self.sink.setVolume(v/100) if self.sink else None)
        self.status=QLabel('Choose a line and press Play, or double-click it.');self.status.setWordWrap(True);layout.addWidget(self.status)
        self.buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel);self.buttons.button(QDialogButtonBox.Ok).setText('Use this line')
        self.buttons.accepted.connect(self.accept);self.buttons.rejected.connect(self.reject);layout.addWidget(self.buttons)
        self.character.currentIndexChanged.connect(self.scan);self.bank.currentIndexChanged.connect(self.scan);self.iso.textEdited.connect(self.invalidate)
        self.select(-1)
        if self.iso.text():self.scan()
    def invalidate(self,*_):
        self.stop();self.rows=[];self.list.clear();self.select(-1)
    def browse(self):
        path,_=QFileDialog.getOpenFileName(self,'Game ISO',self.iso.text(),'ISO (*.iso)')
        if path:self.iso.setText(path);self.scan()
    def job(self,fn,args,callback):
        if self.busy:return
        self.busy=True
        for w in (self.character,self.bank,self.iso,self.reload,self.play_button,self.list,self.browse_button):w.setEnabled(False)
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(False)
        self.worker=VoiceLoader(fn,args,self);self.worker.loaded.connect(callback);self.worker.failed.connect(self.status.setText)
        self.worker.finished.connect(self.finished_job);self.worker.start()
    def finished_job(self):
        self.busy=False
        for w in (self.character,self.bank,self.iso,self.reload,self.list,self.browse_button):w.setEnabled(True)
        self.select(self.list.currentRow())
        self.worker.deleteLater();self.worker=None
    def scan(self,*_):
        if self.busy:return
        self.invalidate();self.status.setText('Reading character voice slots…')
        self.job(story_voice.inventory,(self.iso.text(),self.character.currentData(),self.bank.currentIndex()),self.loaded)
    def loaded(self,rows):
        self.rows=rows
        for line,seconds,error in rows:self.list.addItem(f'{line:02d}   '+(f'{seconds:.2f} s' if not error else 'Unavailable'))
        self.list.setCurrentRow(self.line);self.status.setText('Double-click a line to preview. Unavailable slots cannot be selected.')
    def select(self,index):
        valid=bool(0<=index<len(self.rows) and not self.rows[index][2])
        if valid:self.line=self.rows[index][0]
        self.play_button.setEnabled(valid and not self.busy);self.buttons.button(QDialogButtonBox.Ok).setEnabled(valid and not self.busy)
    def play(self):
        if self.busy or not 0<=self.list.currentRow()<len(self.rows):return
        self.stop();self.status.setText('Decoding voice line…')
        self.job(story_voice.load,(self.iso.text(),self.character.currentData(),self.line,self.bank.currentIndex()),self.play_pcm)
    def play_pcm(self,result):
        h,pcm=result;fmt=QAudioFormat();fmt.setSampleRate(h.rate);fmt.setChannelCount(h.channels);fmt.setSampleFormat(QAudioFormat.Int16)
        self.buffer=QBuffer(self);self.buffer.setData(QByteArray(pcm));self.buffer.open(QIODevice.ReadOnly)
        self.sink=QAudioSink(fmt,self);self.sink.setVolume(self.volume.value()/100)
        self.sink.stateChanged.connect(self.audio_state);self.sink.start(self.buffer)
        self.status.setText(f'Playing line {self.line} — {h.seconds:.2f} seconds')
        self.audio_state(self.sink.state())
    def audio_state(self,state):
        if self.sink and self.sink.error()!=QAudio.NoError:
            self.status.setText('Audio output failed: '+self.sink.error().name+'. Check your system’s playback device and try again.')
        elif state==QAudio.IdleState:self.status.setText(f'Finished line {self.line}. Play again or choose another line.')
    def stop(self):
        if self.sink:self.sink.stop();self.sink.deleteLater();self.sink=None
        if self.buffer:self.buffer.close();self.buffer.deleteLater();self.buffer=None
    def done(self,result):
        if self.worker and self.worker.isRunning():
            self.worker.loaded.disconnect();self.worker.wait()
        self.stop();super().done(result)
