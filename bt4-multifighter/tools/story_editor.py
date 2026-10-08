"""Native Qt mission creator. No PINE connection or save-state operations."""
import copy
import json
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QSlider, QCheckBox, QFormLayout,
    QTableWidget, QTableWidgetItem, QHeaderView, QFileDialog, QMessageBox, QDialog,
    QDialogButtonBox, QPlainTextEdit, QInputDialog, QListWidget, QTabWidget, QScrollArea)
import story_missions as missions
from character_names import character_table, character_name


def button(text, fn):
    b=QPushButton(text); b.clicked.connect(fn); return b


def spin(low,high,value):
    w=QSpinBox();w.setRange(low,high);w.setValue(value);return w


def combo(items, value=None):
    w=QComboBox()
    for label,data in items:w.addItem(label,data)
    if value is not None:w.setCurrentIndex(max(0,w.findData(value)))
    return w


def characters(value=0):
    ids=set(character_table());ids.add(value)
    return combo([(f'{cid} — {character_name(cid)}',cid) for cid in sorted(ids)],value)


def condition_label(condition):
    kind=condition['type'];fighter=condition.get('fighter','')
    if kind=='time':return f"After {condition['seconds']:g} seconds"
    if kind=='defeated':return fighter+' is defeated'
    if kind=='transformed':return fighter+' transforms'
    if kind=='form':return fighter+' becomes '+character_name(condition['character'])
    if kind=='health_below':return f"{fighter} has {condition['percent']:g}% HP or less"
    if kind=='event':return 'After '+condition['event']+(f" + {condition['delay_seconds']:g}s" if condition.get('delay_seconds') else '')
    if kind=='event_failed':return condition['event']+' failed'
    if kind=='not':return 'Not ('+condition_label(condition['condition'])+')'
    if kind=='health_above':return f"{fighter} has more than {condition['percent']:g}% HP"
    if kind in ('active','retired'):return fighter+' is '+kind
    if kind=='planet_destroyed':return f"After planet destruction #{condition.get('occurrence',1)}"
    return ('All: ' if kind=='all' else 'Any: ')+'; '.join(condition_label(c) for c in condition['conditions'])


class StatsWidget(QWidget):
    """Opt-in stat overrides; unchecked fields retain the character's native value."""
    def __init__(self,values=None,parent=None):
        super().__init__(parent);self.fields={};form=QFormLayout(self);values=values or {}
        names={'max_hp':'Maximum HP','health_percent':'Current HP (% of maximum)','damage':'Damage multiplier',
               'defense':'Defense multiplier','ki_percent':'Ki (%)','blast_stocks':'Blast stocks','difficulty':'CPU difficulty (0–4)',
               'invulnerable':'Invulnerable to attacks','cannot_be_defeated':'Attacks leave at least 1 HP'}
        for key,lo,hi,default,integer in [('max_hp',1,1000000,30000,True),('health_percent',1,100,100,False),
              ('damage',0,20,1,False),('defense',.05,20,1,False),('ki_percent',0,100,100,False),
              ('blast_stocks',0,99,3,True),('difficulty',0,4,2,True)]:
            enabled=QCheckBox(names[key]);enabled.setChecked(key in values)
            value=spin(lo,hi,values.get(key,default)) if integer else QDoubleSpinBox()
            if not integer:value.setDecimals(2);value.setRange(lo,hi);value.setValue(values.get(key,default))
            value.setEnabled(enabled.isChecked());enabled.toggled.connect(value.setEnabled);form.addRow(enabled,value);self.fields[key]=(enabled,value)
        for key in ('invulnerable','cannot_be_defeated'):
            enabled=QCheckBox('Override '+names[key].lower());enabled.setChecked(key in values)
            value=QCheckBox(names[key]);value.setChecked(values.get(key,False));value.setEnabled(enabled.isChecked())
            enabled.toggled.connect(value.setEnabled);form.addRow(enabled,value);self.fields[key]=(enabled,value)
    def value(self):
        return {key:(w.isChecked() if isinstance(w,QCheckBox) else w.value()) for key,(enabled,w) in self.fields.items() if enabled.isChecked()}


class ActionDialog(QDialog):
    def __init__(self,document,kind,parent=None,action=None):
        super().__init__(parent);self.document=document;self.kind=kind;self.setWindowTitle(kind.title())
        outer=QVBoxLayout(self);body=QWidget();layout=QFormLayout(body)
        self.scroll=QScrollArea();self.scroll.setWidgetResizable(True);self.scroll.setWidget(body);outer.addWidget(self.scroll,1)
        self.fighter=combo([(f['id']+' — '+character_name(f['character']),f['id']) for f in document['fighters']])
        self.form=characters();self.health=QDoubleSpinBox();self.health.setRange(1,100);self.health.setValue(100);self.health.setSuffix('%')
        self.text=QLineEdit();self.text.setMaxLength(120)
        self.seconds=QDoubleSpinBox();self.seconds.setRange(.5,30);self.seconds.setValue(4);self.seconds.setSuffix(' s')
        self.intro=QCheckBox('Play default entrance taunt (turn off when adding a cinematic)');self.intro.setChecked(True)
        self.freeze=QCheckBox('Freeze fighters and hold the preceding cinematic camera');self.freeze.setChecked(False)
        if kind=='message':layout.addRow('Text',self.text);layout.addRow('Display time',self.seconds)
        elif kind=='wait':
            self.seconds.setRange(.1,300);layout.addRow('Delay',self.seconds);layout.addRow(self.freeze)
            note=QLabel('Ordinary delays let the battle continue. Frozen pauses hold the last shot in this event and can last up to 30 seconds.');note.setWordWrap(True);layout.addRow(note)
        else:layout.addRow('Fighter',self.fighter)
        if kind=='set_stats':self.stats=StatsWidget(action.get('stats') if action else {},self);layout.addRow(self.stats)
        if kind=='take_control':self.player=spin(1,4,1);layout.addRow('Controller / player',self.player)
        if kind=='target':
            self.target=combo([(f['id'],f['id']) for f in document['fighters']]);layout.addRow('Enemy to target',self.target)
        if kind in ('enter','recover','heal'):layout.addRow('Health after action',self.health)
        if kind=='enter':layout.addRow(self.intro)
        if kind=='transform':layout.addRow('Destination form',self.form)
        if kind in ('voice','cinematic'):
            self.voice_character=characters();self.voice_line=spin(0,99,0);self.volume=spin(0,100,100)
            if kind=='cinematic':
                self.animated=QCheckBox('Play an animation (off = camera-only shot)');self.animated.setChecked(True);layout.addRow(self.animated)
                self.reset_positions=QCheckBox('Reset living fighters to the stage formation before this shot')
                self.reset_positions.setToolTip('Waits for bound attacks and reloads; resets position, facing and motion together. Fallen and retired fighters stay untouched.')
                layout.addRow(self.reset_positions)
                self.donor=characters();self.clip=spin(0,413,0);self.speed=QDoubleSpinBox();self.speed.setRange(.1,3);self.speed.setValue(1)
                self.seconds.setRange(.1,30)
                self.voice_enabled=QCheckBox('Play a voice line with this shot')
                layout.addRow('Animation donor',self.donor);layout.addRow('Animation ID',self.clip)
                layout.addRow(button('Preview / choose animation…',self.preview))
                layout.addRow('Shot duration',self.seconds);layout.addRow('Animation speed',self.speed)
                self.eye=QLineEdit('0, -16, 55');self.look=QLineEdit('0, -9, 0')
                self.end_eye=QLineEdit();self.end_look=QLineEdit()
                for title,w in [('Camera XYZ offset',self.eye),('Look-at XYZ offset',self.look),('End camera offset (optional)',self.end_eye),('End look-at offset (optional)',self.end_look)]:layout.addRow(title,w)
                self.easing=combo([('Smooth start and stop','smooth'),('Linear','linear'),('Ease in','ease_in'),('Ease out','ease_out')]);layout.addRow('Camera pan',self.easing)
                self.animated.toggled.connect(self.donor.setEnabled);self.animated.toggled.connect(self.clip.setEnabled)
                layout.addRow(self.voice_enabled)
            layout.addRow('Voice character',self.voice_character);layout.addRow('Voice line ID',self.voice_line);layout.addRow('Voice volume',self.volume)
            layout.addRow(button('Preview / choose voice line…',self.preview_voice))
            note=QLabel('Animation and voice are independent. Voice IDs use this disc’s native character bank (0–99). Camera offsets use world axes around the selected fighter.');note.setWordWrap(True);note.setMinimumHeight(54);layout.addRow(note)
        buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel);buttons.accepted.connect(self.checked_accept);buttons.rejected.connect(self.reject);outer.addWidget(buttons)
        self.resize(640,520)
        if action:self.load_action(action)
        if kind=='cinematic':self.resize(680,740)
    def load_action(self,action):
        def choose(w,v):w.setCurrentIndex(w.findData(v))
        if 'fighter' in action:choose(self.fighter,action['fighter'])
        self.health.setValue(action.get('health_percent',100));self.seconds.setValue(action.get('seconds',4))
        self.intro.setChecked(action.get('intro',True));self.text.setText(action.get('text',''))
        self.freeze.setChecked(action.get('freeze',False))
        if self.kind=='take_control':self.player.setValue(action['player'])
        if self.kind=='target':choose(self.target,action['target'])
        if self.kind=='transform':choose(self.form,action['character'])
        if self.kind in ('voice','cinematic'):
            voice=action if self.kind=='voice' else action.get('voice',{})
            choose(self.voice_character,voice.get('character',0));self.voice_line.setValue(voice.get('line',0));self.volume.setValue(voice.get('volume',100))
            if self.kind=='cinematic':
                self.reset_positions.setChecked(action.get('reset_positions',False))
                anim=action.get('animation');self.animated.setChecked(bool(anim))
                if anim:choose(self.donor,anim['character']);self.clip.setValue(anim['clip'])
                self.speed.setValue(action.get('speed',1))
                self.voice_enabled.setChecked(bool(voice));camera=action.get('camera',dict(eye=[0,-16,55],target=[0,-9,0]))
                for key,w in [('eye',self.eye),('target',self.look),('end_eye',self.end_eye),('end_target',self.end_look)]:
                    w.setText(', '.join(map(str,camera[key])) if key in camera else '')
                choose(self.easing,camera.get('easing','smooth'))
    def preview_voice(self):
        from story_voice_picker import VoicePicker
        dialog=VoicePicker(self.voice_character.currentData(),self.voice_line.value(),self.volume.value(),self)
        if dialog.exec()==QDialog.Accepted:
            self.voice_character.setCurrentIndex(self.voice_character.findData(dialog.character.currentData()))
            self.voice_line.setValue(dialog.line);self.volume.setValue(dialog.volume.value())
            if self.kind=='cinematic':self.voice_enabled.setChecked(True)
    def checked_accept(self):
        try:self.value();self.accept()
        except (ValueError,TypeError) as e:QMessageBox.warning(self,'Action',str(e))
    def preview(self):
        from story_preview import AnimationPicker
        f=next(f for f in self.document['fighters'] if f['id']==self.fighter.currentData())
        dialog=AnimationPicker(f['character'],f.get('costume',0),self.donor.currentData(),self.clip.value(),self)
        if dialog.exec()==QDialog.Accepted:
            self.clip.setValue(dialog.clip)
            if dialog.bank:
                self.seconds.setValue(min(30,dialog.bank.clip(dialog.clip).duration_seconds/self.speed.value()))

    def value(self):
        kind=self.kind
        if kind=='message':return dict(type=kind,text=self.text.text(),seconds=self.seconds.value())
        if kind=='wait':
            result=dict(type=kind,seconds=self.seconds.value())
            if self.freeze.isChecked():
                missions.number(result['seconds'],.1,30,'Frozen pause');result['freeze']=True
            return result
        result=dict(type=kind,fighter=self.fighter.currentData())
        if kind=='set_stats':result['stats']=self.stats.value();missions.validate_stats(result['stats'])
        if kind=='take_control':result['player']=self.player.value()
        if kind=='target':result['target']=self.target.currentData()
        if kind in ('enter','recover','heal'):result['health_percent']=self.health.value()
        if kind=='enter':result['intro']=self.intro.isChecked()
        if kind=='transform':result['character']=self.form.currentData()
        if kind in ('voice','cinematic'):
            voice=dict(character=self.voice_character.currentData(),line=self.voice_line.value(),volume=self.volume.value())
            if kind=='voice':result.update(voice)
            else:
                def vector(w):
                    values=[float(x.strip()) for x in w.text().split(',')]
                    if len(values)!=3:raise ValueError('Enter three camera coordinates separated by commas')
                    return values
                camera=dict(eye=vector(self.eye),target=vector(self.look))
                if self.end_eye.text().strip():camera['end_eye']=vector(self.end_eye)
                if self.end_look.text().strip():camera['end_target']=vector(self.end_look)
                if self.easing.currentData()!='smooth':camera['easing']=self.easing.currentData()
                result.update(camera=camera,seconds=self.seconds.value(),speed=self.speed.value())
                if self.reset_positions.isChecked():result['reset_positions']=True
                if self.animated.isChecked():result['animation']=dict(character=self.donor.currentData(),clip=self.clip.value())
                if self.voice_enabled.isChecked():result['voice']=voice
        return result


class FighterDialog(QDialog):
    def __init__(self,fighter,profile,parent=None):
        super().__init__(parent);self.setWindowTitle('Mission fighter');self.original=copy.deepcopy(fighter)
        self.original_profile=copy.deepcopy(profile)
        outer=QVBoxLayout(self);tabs=QTabWidget();outer.addWidget(tabs,1)
        main=QWidget();layout=QFormLayout(main);tabs.addTab(main,'Fighter and CPU')
        self.ident=QLineEdit(fighter['id']);self.team=spin(1,2,fighter['team']);self.slot=spin(1,32,fighter['slot'])
        self.character=characters(fighter['character']);self.costume=spin(0,255,fighter.get('costume',0))
        self.hp=spin(0,1000000,fighter.get('hp',0));self.hp.setSpecialValueText('Native character HP')
        self.difficulty=combo([('Native / copied difficulty',None)]+[(name,i) for i,name in enumerate(('Very weak','Weak','Normal','Strong','Very strong'))],fighter.get('difficulty'))
        t=fighter.get('transformations',{})
        self.forms_enabled=QCheckBox('Allow ordinary transformations');self.forms_enabled.setChecked(t.get('enabled',True))
        self.form_limit=spin(-1,1000,t.get('limit',-1));self.form_limit.setSpecialValueText('Unlimited')
        self.allowed_forms=QLineEdit(', '.join(map(str,t.get('allowed_forms',[]))))
        self.allowed_forms.setPlaceholderText('Any form, or comma-separated character/form IDs')
        self.reserve=QCheckBox('Wait offstage for an entrance event');self.reserve.setChecked(fighter.get('reserve',False))
        self.chance=QSlider(Qt.Horizontal);self.chance.setRange(0,100);self.chance.setValue(profile.get('transform_chance',100))
        self.percent=QLabel();self.chance.valueChanged.connect(self.update_chance);self.update_chance()
        for name,w in [('ID',self.ident),('Team',self.team),('Slot',self.slot),('Character / form',self.character),
                       ('Costume',self.costume),('',self.reserve),('CPU transformation likelihood',self.chance),('',self.percent)]:layout.addRow(name,w)
        for name,w in [('HP (10,000 = one bar)',self.hp),('CPU difficulty',self.difficulty),('',self.forms_enabled),('Maximum transformations',self.form_limit),('Allowed destination forms',self.allowed_forms)]:layout.addRow(name,w)
        self.stats=StatsWidget(fighter.get('stats'),self);tabs.addTab(self.stats,'Starting stat overrides')
        self.resize(680,620)
        info=QLabel('100% accepts ordinary native AI transformation attempts. It does not force constant transformations. Scripted forms use events.');info.setWordWrap(True);outer.addWidget(info)
        buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel);buttons.accepted.connect(self.checked_accept);buttons.rejected.connect(self.reject);outer.addWidget(buttons)
    def checked_accept(self):
        try:
            f,_,_=self.value();missions.identifier(f['id'],'Fighter ID')
            for value in f.get('transformations',{}).get('allowed_forms',[]):missions.integer(value,0,65535,'Allowed form')
            self.accept()
        except ValueError as e:QMessageBox.warning(self,'Fighter',str(e))
    def update_chance(self):self.percent.setText(f'{self.chance.value()}% of native attempts')
    def value(self):
        f=dict(self.original,id=self.ident.text().strip(),team=self.team.value(),slot=self.slot.value(),
            character=self.character.currentData(),costume=self.costume.value(),reserve=self.reserve.isChecked())
        for key in ('hp','difficulty','transformations'):f.pop(key,None)
        if self.hp.value():f['hp']=self.hp.value()
        if self.difficulty.currentData() is not None:f['difficulty']=self.difficulty.currentData()
        t=dict(enabled=self.forms_enabled.isChecked())
        if self.form_limit.value()>=0:t['limit']=self.form_limit.value()
        if self.allowed_forms.text().strip():t['allowed_forms']=[int(x.strip()) for x in self.allowed_forms.text().split(',')]
        f['transformations']=t
        f.pop('stats',None)
        if self.stats.value():f['stats']=self.stats.value()
        profile=missions.profile_id(f['id']);f['cpu_profile']=profile
        return f,profile,dict(self.original_profile,name=f['id']+' CPU',transform_chance=self.chance.value())


class ActionList(QWidget):
    """Ordered, editable actions with an optional JSON view for advanced authors."""
    def __init__(self,document,parent=None):
        super().__init__(parent);self.document=document;self.rows=[]
        layout=QVBoxLayout(self);layout.setContentsMargins(0,0,0,0)
        self.tabs=QTabWidget();layout.addWidget(self.tabs);self.list=QListWidget();self.list.itemDoubleClicked.connect(lambda *_:self.edit())
        self.raw=QPlainTextEdit();self.tabs.addTab(self.list,'Action sequence');self.tabs.addTab(self.raw,'Advanced JSON')
        self.tabs.currentChanged.connect(self.changed_tab)
        row=QHBoxLayout();layout.addLayout(row)
        for label,fn in [('Edit action',self.edit),('Duplicate',self.duplicate),('Move up',lambda:self.move(-1)),('Move down',lambda:self.move(1)),('Remove',self.remove)]:row.addWidget(button(label,fn))
    def duplicate(self):
        i=self.list.currentRow()
        if i>=0:self.rows.insert(i+1,copy.deepcopy(self.rows[i]));self.refresh();self.list.setCurrentRow(i+1)
    def toPlainText(self):
        return self.raw.toPlainText() if self.tabs.currentIndex()==1 else json.dumps(self.rows,indent=2)
    def setPlainText(self,text):
        rows=json.loads(text)
        if not isinstance(rows,list):raise ValueError('Actions must be a list')
        self.rows=rows;self.raw.setPlainText(json.dumps(rows,indent=2));self.refresh()
    def changed_tab(self,index):
        if index==1:self.raw.setPlainText(json.dumps(self.rows,indent=2))
        else:
            try:self.setPlainText(self.raw.toPlainText())
            except (ValueError,TypeError) as error:
                self.tabs.blockSignals(True);self.tabs.setCurrentIndex(1);self.tabs.blockSignals(False)
                QMessageBox.warning(self,'Actions',str(error))
    def refresh(self):
        from story_graph import action_label
        selected=self.list.currentRow();self.list.clear()
        for i,action in enumerate(self.rows):self.list.addItem(f'{i+1}. '+action_label(action))
        if self.rows:self.list.setCurrentRow(max(0,min(selected,len(self.rows)-1)))
    def edit(self):
        if self.tabs.currentIndex()!=0:return
        i=self.list.currentRow()
        if i<0:return
        dialog=ActionDialog(self.document,self.rows[i]['type'],self,action=self.rows[i])
        if dialog.exec()==QDialog.Accepted:self.rows[i]=dialog.value();self.refresh()
    def move(self,step):
        if self.tabs.currentIndex()!=0:return
        i=self.list.currentRow();j=i+step
        if 0<=i<len(self.rows) and 0<=j<len(self.rows):
            self.rows[i],self.rows[j]=self.rows[j],self.rows[i];self.refresh();self.list.setCurrentRow(j)
    def remove(self):
        if self.tabs.currentIndex()!=0:return
        i=self.list.currentRow()
        if i>=0:self.rows.pop(i);self.refresh()


class EventDialog(QDialog):
    def __init__(self,document,event=None,parent=None):
        super().__init__(parent);self.setWindowTitle('Story event');self.resize(680,530)
        self.document=document;self.original=event
        self.compound=copy.deepcopy(event['when']) if event else None
        layout=QVBoxLayout(self);form=QFormLayout();layout.addLayout(form)
        self.ident=QLineEdit(event['id'] if event else f'event-{len(document["events"])+1}')
        self.trigger=combo([('Elapsed time','time'),('Fighter defeated','defeated'),('Fighter has transformed','transformed'),
            ('Fighter is in a specific form','form'),('Health below percent','health_below'),('Previous event completed','event'),
            ('Health above percent','health_above'),('Fighter is active','active'),('Fighter has exited','retired'),
            ('Previous event failed','event_failed'),('Planet / arena destruction completed','planet_destroyed')])
        fighters=[(f['id'],f['id']) for f in document['fighters']]
        self.subject=combo(fighters);self.value=QDoubleSpinBox();self.value.setRange(0,86400);self.value.setDecimals(2)
        self.previous=combo([(e['id'],e['id']) for e in document['events'] if not event or e['id']!=event['id']])
        self.form=characters();self.timeout=spin(1,300,30)
        self.delay=QDoubleSpinBox();self.delay.setRange(0,86400);self.delay.setSuffix(' s');self.delay.setDecimals(2)
        self.failure=combo([('Release the event and continue','continue'),('Fail the scenario','fail_scenario')])
        self.occurrence=spin(1,1000,1)
        self.occurrence.setToolTip('1 means the first completed destruction in this battle. Starting on a destroyed arena does not count. Each event runs once.')
        for name,w in [('ID',self.ident),('When',self.trigger),('Trigger fighter',self.subject),('Seconds / HP percent',self.value),
                       ('Destination form',self.form),('Previous event',self.previous),('Delay after that event',self.delay),
                       ('Destruction occurrence',self.occurrence),('Event wait timeout (seconds)',self.timeout),('If this event fails',self.failure)]:form.addRow(name,w)
        self.trigger.currentIndexChanged.connect(self.update_fields)
        self.timeout.setToolTip('Total combat-time budget for the event, including KO fall/get-up and waiting for safe actions. Held cinematics stop this clock. Use at least 30 seconds for a second wind.')
        layout.addWidget(QLabel('Actions run from top to bottom. For a second wind: Recover (1% HP), Cinematic + voice, Heal, Transform.'))
        self.actions=ActionList(document,self);layout.addWidget(self.actions)
        self.timing_warning=QLabel();self.timing_warning.setWordWrap(True);self.timing_warning.setStyleSheet('color: #f6cb70');layout.addWidget(self.timing_warning)
        self.timeout.valueChanged.connect(lambda v:self.timing_warning.setText('Short timeout: a KO fall and get-up may take several seconds. The event will fail if it cannot finish in time.' if v<10 else ''))
        row=QHBoxLayout();layout.addLayout(row)
        self.action_kind=combo([(k.replace('_',' ').title(),k) for k in
            ('cinematic','voice','message','wait','enter','recover','transform','heal','set_stats','take_control','target','despawn','defeat','taunt')])
        row.addWidget(self.action_kind,1);row.addWidget(button('Add action',lambda:self.add_action(self.action_kind.currentData())))
        self.actions.setPlainText(json.dumps(event['actions'] if event else [],indent=2))
        self.condition_summary=QLabel();self.condition_summary.setWordWrap(True);layout.addWidget(self.condition_summary)
        row=QHBoxLayout();layout.addLayout(row)
        for text,join in [('Replace condition',None),('Add AND','all'),('Add OR','any'),('Invert condition','not')]:
            row.addWidget(button(text,lambda _=False,j=join:self.edit_condition(j)))
        if event:
            c=event['when']
            if c['type'] in ('all','any','not'):
                self.trigger.addItem('Advanced condition (preserved)','advanced');self.trigger.setCurrentIndex(self.trigger.count()-1)
            else:self.trigger.setCurrentIndex(self.trigger.findData(c['type']))
            if 'fighter' in c:self.subject.setCurrentIndex(self.subject.findData(c['fighter']))
            self.value.setValue(c.get('seconds',c.get('percent',0)))
            self.occurrence.setValue(c.get('occurrence',1))
            if 'character' in c:self.form.setCurrentIndex(self.form.findData(c['character']))
            if 'event' in c:self.previous.setCurrentIndex(self.previous.findData(c['event']))
            self.timeout.setValue(event.get('timeout_seconds',30))
            self.delay.setValue(c.get('delay_seconds',0));self.failure.setCurrentIndex(self.failure.findData(event.get('on_failure','continue')))
        self.update_fields()
        self.condition_summary.setText(condition_label(event['when']) if event else 'Combine conditions for branching, health gates and delayed scenes.')
        buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel);buttons.accepted.connect(self.checked_accept);buttons.rejected.connect(self.reject);layout.addWidget(buttons)
    def add_action(self,kind):
        try:
            actions=json.loads(self.actions.toPlainText())
            dialog=ActionDialog(self.document,kind,self)
            if dialog.exec()==QDialog.Accepted:
                actions.append(dialog.value());self.actions.setPlainText(json.dumps(actions,indent=2))
        except Exception as error:QMessageBox.warning(self,'Event',str(error))
    def update_fields(self):
        kind=self.trigger.currentData()
        self.subject.setEnabled(kind in ('defeated','transformed','form','health_below','health_above','active','retired'))
        self.value.setEnabled(kind in ('time','health_below','health_above'));self.value.setMaximum(100 if kind in ('health_below','health_above') else 86400)
        self.form.setEnabled(kind=='form');self.previous.setEnabled(kind in ('event','event_failed'));self.delay.setEnabled(kind=='event')
        self.occurrence.setEnabled(kind=='planet_destroyed')
    def edit_condition(self,join=None):
        old=self.value_event()['when']
        if join=='not':self.compound=dict(type='not',condition=old)
        else:
            candidate=copy.deepcopy(self.document)
            candidate['events']=[e for e in candidate['events'] if not self.original or e['id']!=self.original['id']]
            dialog=ConditionDialog(candidate,self)
            if dialog.exec()!=QDialog.Accepted:return
            new=dialog.value();self.compound=dict(type=join,conditions=[old,new]) if join else new
        index=self.trigger.findData('advanced')
        if index<0:self.trigger.addItem('Combined condition','advanced');index=self.trigger.count()-1
        self.trigger.setCurrentIndex(index);self.condition_summary.setText(condition_label(self.compound))
    def value_event(self):
        kind=self.trigger.currentData();c=dict(type=kind)
        if kind=='advanced':c=copy.deepcopy(self.compound)
        elif kind=='time':c['seconds']=self.value.value()
        elif kind in ('event','event_failed'):
            c['event']=self.previous.currentData()
            if kind=='event' and self.delay.value():c['delay_seconds']=self.delay.value()
        elif kind=='planet_destroyed':c['occurrence']=self.occurrence.value()
        else:
            c['fighter']=self.subject.currentData()
            if kind=='form':c['character']=self.form.currentData()
            if kind in ('health_below','health_above'):c['percent']=self.value.value()
        result=dict(id=self.ident.text().strip(),when=c,actions=json.loads(self.actions.toPlainText()),timeout_seconds=self.timeout.value())
        if self.failure.currentData()!='continue':result['on_failure']=self.failure.currentData()
        return result
    def checked_accept(self):
        try:
            event=self.value_event();candidate=copy.deepcopy(self.document)
            if self.original:
                index=next(i for i,e in enumerate(candidate['events']) if e['id']==self.original['id']);candidate['events'][index]=event
                def rename(c):
                    if c.get('type') in ('event','event_failed') and c.get('event')==self.original['id']:c['event']=event['id']
                    for child in c.get('conditions',[]):rename(child)
                    if c.get('condition'):rename(c['condition'])
                for e in candidate['events']:rename(e['when'])
                for key in ('win_when','fail_when'):
                    if candidate.get(key):rename(candidate[key])
            else:candidate['events'].append(event)
            missions.validate(candidate);self.accept()
        except Exception as error:QMessageBox.warning(self,'Event',str(error))


class ConditionDialog(QDialog):
    def __init__(self,document,parent=None):
        super().__init__(parent);self.setWindowTitle('Outcome condition');form=QFormLayout(self)
        self.kind=combo([('Time elapsed','time'),('Fighter defeated','defeated'),('Fighter transformed','transformed'),
            ('Fighter is in form','form'),('Health at/below percent','health_below'),('Event completed','event'),
            ('Health above percent','health_above'),('Fighter is active','active'),('Fighter has exited','retired'),
            ('Event failed','event_failed'),('Planet / arena destruction completed','planet_destroyed')])
        self.fighter=combo([(f['id'],f['id']) for f in document['fighters']]);self.form=characters()
        self.event=combo([(e['id'],e['id']) for e in document['events']]);self.amount=QDoubleSpinBox();self.amount.setRange(0,86400)
        self.occurrence=spin(1,1000,1)
        self.delay=QDoubleSpinBox();self.delay.setRange(0,86400);self.delay.setSuffix(' s')
        self.inverted=QCheckBox('Invert this condition (NOT)')
        for title,w in [('Condition',self.kind),('Fighter',self.fighter),('Form',self.form),('Event',self.event),('Seconds / percent',self.amount),('Destruction occurrence',self.occurrence)]:form.addRow(title,w)
        form.addRow('Delay after event completion',self.delay);form.addRow(self.inverted)
        self.kind.currentIndexChanged.connect(self.update_fields);self.update_fields()
        buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel);form.addRow(buttons)
        buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject)
    def update_fields(self):
        kind=self.kind.currentData();self.fighter.setEnabled(kind in ('defeated','transformed','form','health_below','health_above','active','retired'));self.form.setEnabled(kind=='form')
        self.event.setEnabled(kind in ('event','event_failed'));self.amount.setEnabled(kind in ('time','health_below','health_above'));self.delay.setEnabled(kind=='event')
        self.occurrence.setEnabled(kind=='planet_destroyed')
        self.amount.setMaximum(100 if kind in ('health_below','health_above') else 86400)
    def value(self):
        kind=self.kind.currentData();c=dict(type=kind)
        if kind=='time':c['seconds']=self.amount.value()
        elif kind in ('event','event_failed'):
            c['event']=self.event.currentData()
            if kind=='event' and self.delay.value():c['delay_seconds']=self.delay.value()
        elif kind=='planet_destroyed':c['occurrence']=self.occurrence.value()
        else:
            c['fighter']=self.fighter.currentData()
            if kind=='form':c['character']=self.form.currentData()
            if kind in ('health_below','health_above'):c['percent']=self.amount.value()
        return dict(type='not',condition=c) if self.inverted.isChecked() else c


class RulesDialog(QDialog):
    def __init__(self,document,parent=None):
        super().__init__(parent);self.document=document;self.setWindowTitle('Scenario outcomes and menus');self.resize(800,700)
        self.rules=copy.deepcopy(document.get('finish_rules',[]));self.conditions={k:copy.deepcopy(document.get(k)) for k in ('win_when','fail_when')}
        layout=QVBoxLayout(self);form=QFormLayout();layout.addLayout(form)
        self.team=spin(1,2,document.get('player_team',1));form.addRow('Player / success team',self.team)
        self.retry=QCheckBox('Allow Retry / Fight Again');self.retry.setChecked(document.get('menus',{}).get('retry',True));form.addRow(self.retry)
        self.selector=QCheckBox('Allow Return to Character Select');self.selector.setChecked(document.get('menus',{}).get('character_select',False));form.addRow(self.selector)
        info=QLabel('Preset scenarios hide character selection by default. Resume, Skill List and Main Menu stay available. Failure conditions take priority over success conditions.');info.setWordWrap(True);layout.addWidget(info)
        self.labels={}
        for key,title in (('win_when','Additional success condition'),('fail_when','Failure condition')):
            layout.addWidget(QLabel(title));self.labels[key]=QLabel();self.labels[key].setWordWrap(True);layout.addWidget(self.labels[key])
            row=QHBoxLayout();layout.addLayout(row)
            row.addWidget(button('Set / replace',lambda _=False,k=key:self.condition(k)))
            row.addWidget(button('Add AND',lambda _=False,k=key:self.condition(k,'all')))
            row.addWidget(button('Add OR',lambda _=False,k=key:self.condition(k,'any')))
            row.addWidget(button('Clear',lambda _=False,k=key:self.clear(k)))
        layout.addWidget(QLabel('Required finishing blows'))
        self.table=QTableWidget(0,4);self.table.setHorizontalHeaderLabels(['Victim','Attacker','Attack / form','Invalid finishing blow'])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch);self.table.setEditTriggers(QTableWidget.NoEditTriggers);layout.addWidget(self.table)
        row=QHBoxLayout();layout.addLayout(row);row.addWidget(button('Add finishing rule',self.add_finisher));row.addWidget(button('Remove selected',self.remove_finisher))
        buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel);layout.addWidget(buttons)
        buttons.accepted.connect(self.checked_accept);buttons.rejected.connect(self.reject);self.refresh()
    def refresh(self):
        for key,label in self.labels.items():label.setText(condition_label(self.conditions[key]) if self.conditions[key] else 'None — normal team defeat applies.')
        self.table.setRowCount(len(self.rules))
        for i,r in enumerate(self.rules):
            for j,text in enumerate((r['victim'],r['attacker'],r['attack']+(f" / form {r['form']}" if 'form' in r else ''),r['otherwise'])):self.table.setItem(i,j,QTableWidgetItem(text))
    def clear(self,key):self.conditions[key]=None;self.refresh()
    def condition(self,key,join=None):
        dialog=ConditionDialog(self.document,self)
        if dialog.exec()!=QDialog.Accepted:return
        c=dialog.value();old=self.conditions[key]
        self.conditions[key]=dict(type=join,conditions=[old,c]) if join and old else c;self.refresh()
    def add_finisher(self):
        dialog=QDialog(self);dialog.setWindowTitle('Required finishing blow');form=QFormLayout(dialog)
        names=[(f['id'],f['id']) for f in self.document['fighters']]
        victim=combo(names);attacker=combo(names);attack=combo([('Any attack','any'),('Ultimate','ultimate'),('Special or ultimate','special')])
        result=combo([('Keep opponent at 1 HP','hold_at_1_hp'),('Fail the scenario','fail')]);shape=spin(-1,65535,-1);shape.setSpecialValueText('Any form')
        for title,w in [('Victim',victim),('Required attacker',attacker),('Attack',attack),('Required form',shape),('Otherwise',result)]:form.addRow(title,w)
        buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel);form.addRow(buttons);buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject)
        if dialog.exec()==QDialog.Accepted:
            rule=dict(victim=victim.currentData(),attacker=attacker.currentData(),attack=attack.currentData(),otherwise=result.currentData())
            if shape.value()>=0:rule['form']=shape.value()
            self.rules.append(rule);self.refresh()
    def remove_finisher(self):
        i=self.table.currentRow()
        if i>=0:self.rules.pop(i);self.refresh()
    def value(self):return dict(**self.conditions,finish_rules=self.rules,player_team=self.team.value(),menus=dict(retry=self.retry.isChecked(),character_select=self.selector.isChecked()))
    def checked_accept(self):
        try:missions.validate(dict(self.document,**self.value()));self.accept()
        except ValueError as e:QMessageBox.warning(self,'Scenario rules',str(e))


class StoryEditor(QWidget):
    def __init__(self,parent=None):
        super().__init__(parent);self.document=missions.default_mission();self.path=None
        layout=QVBoxLayout(self);row=QHBoxLayout();layout.addLayout(row)
        for title,fn in [('New',self.new),('Open',self.open),('Save',self.save),('Save as',lambda:self.save(True)),
                         ('Import Mission 100 from ISO',self.import100),('Validate',self.validate),
                         ('Test this mission',self.test_mission),
                         ('Use for next battle',self.arm),('Cancel next battle',self.disarm)]:
            item=button(title,fn);row.addWidget(item)
            if title=='Test this mission':
                item.setToolTip('Save (when this mission has a file) and validate it, then start the game straight into it: '
                                'the Modded Scenarios launch runs by itself once the main menu appears.')
            if title=='Import Mission 100 from ISO' and self.document.get('game_family')=='bt4':
                item.setEnabled(False);item.setToolTip('Original BT3 rosters need a verified BT4 character mapping before conversion.')
        self.title=QLineEdit();layout.addWidget(self.title)
        self.description=QPlainTextEdit();self.description.setPlaceholderText('Battle description, objectives and author notes')
        self.description.setMaximumHeight(75);layout.addWidget(self.description)
        row=QHBoxLayout();layout.addLayout(row)
        self.library=QComboBox();self.library.setMinimumWidth(420)
        row.addWidget(QLabel('Saved missions'));row.addWidget(self.library,1)
        row.addWidget(button('Load selected preset',self.load_preset));row.addWidget(button('Refresh library',self.refresh_library))
        row=QHBoxLayout();layout.addLayout(row)
        self.stage=spin(-1,65535,-1);self.stage.setSpecialValueText('Any selected arena')
        self.stage_name=QLineEdit();self.stage_name.setPlaceholderText('Arena name (optional)')
        row.addWidget(QLabel('Arena ID'));row.addWidget(self.stage);row.addWidget(self.stage_name)
        self.music=spin(-1,65535,-1);self.music.setSpecialValueText('Random');row.addWidget(QLabel('Music ID'));row.addWidget(self.music)
        self.grace=QDoubleSpinBox();self.grace.setRange(1,300);self.grace.setSuffix(' s')
        self.grace.setToolTip('Maximum wait for a pending reinforcement or second wind after a whole side is defeated.')
        row.addWidget(QLabel('Reinforcement grace'));row.addWidget(self.grace)
        info=QLabel('Portable mission files • Play saved missions from Modded Scenarios. Definitions contain no emulator save state. Append Cinematic and Voice actions to any event to author a scene.');info.setWordWrap(True);layout.addWidget(info)
        self.fighters=QTableWidget(0,7);self.fighters.setHorizontalHeaderLabels(['ID','Team','Slot','Character','Costume','Arrival','CPU chance'])
        self.fighters.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch);self.fighters.setSelectionBehavior(QTableWidget.SelectRows);self.fighters.setEditTriggers(QTableWidget.NoEditTriggers)
        self.fighters.doubleClicked.connect(lambda *_:self.edit_fighter());layout.addWidget(self.fighters)
        row=QHBoxLayout();layout.addLayout(row)
        for title,fn in [('Add fighter',self.add_fighter),('Edit fighter',self.edit_fighter),('Remove fighter',self.remove_fighter),('Copy CPU settings…',self.copy_cpu)]:row.addWidget(button(title,fn))
        self.events=QTableWidget(0,3);self.events.setHorizontalHeaderLabels(['Event','When','Actions']);self.events.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.events.setSelectionBehavior(QTableWidget.SelectRows);self.events.setEditTriggers(QTableWidget.NoEditTriggers);self.events.doubleClicked.connect(lambda *_:self.edit_event())
        from story_graph import EventGraph
        self.graph=EventGraph(self);self.graph.selected.connect(lambda i,k:self.events.selectRow(i));self.graph.activated.connect(self.edit_node)
        self.event_tabs=QTabWidget();self.event_tabs.addTab(self.graph,'Event flow');self.event_tabs.addTab(self.events,'Event list');layout.addWidget(self.event_tabs,1)
        row=QHBoxLayout();layout.addLayout(row)
        for title,fn in [('Add event',self.add_event),('Add follow-up',self.followup_event),('Edit event',self.edit_event),('Remove event',self.remove_event),('Make enemy waves',self.waves)]:row.addWidget(button(title,fn))
        row.addWidget(button('Win / failure rules and menus…',self.rules))
        self.status=QLabel();self.status.setWordWrap(True);layout.addWidget(self.status)
        self.live_status=QLabel('Enable Runtime → Follow trainer for live event status.');self.live_status.setWordWrap(True);layout.addWidget(self.live_status)
        self.refresh();self.refresh_library()
    def show_status(self,state):
        self.graph.show_status(state)
        if not state:
            self.live_status.setText('No active custom scenario in the monitored match.');return
        if state.get('error'):self.live_status.setText(state['error']);return
        events=' · '.join(e['id']+': '+e['status']+(f" ({e['action']})" if e.get('action') else '') for e in state.get('events',[]))
        self.live_status.setText(f"{state['title']} — {state['seconds']:.1f}s — {state.get('outcome','running')}\n{events}")
    def refresh_library(self):
        self.library.clear()
        for path in sorted(missions.LIBRARY.rglob('*.json')):
            if missions.private(path):continue
            try:
                entry=missions.load(path);self.library.addItem(entry['title'],str(path))
            except (OSError,ValueError):continue
    def load_preset(self):
        path=self.library.currentData()
        if path:
            try:self.document=missions.load(path);self.path=None;self.refresh()
            except Exception as e:self.error(e)
    def error(self,e):QMessageBox.warning(self,'Custom Scenarios',str(e))
    def refresh(self):
        self.title.setText(self.document['title']);self.fighters.setRowCount(len(self.document['fighters']))
        self.description.setPlainText(self.document.get('description',''))
        stage=self.document.get('stage') or {};self.stage.setValue(stage.get('id',-1));self.stage_name.setText(stage.get('name',''))
        self.grace.setValue(self.document.get('defeat_grace_seconds',30));self.music.setValue(self.document.get('music') if self.document.get('music') is not None else -1)
        for i,f in enumerate(self.document['fighters']):
            p=self.document.get('cpu_profiles',{}).get(f.get('cpu_profile'),{})
            values=(f['id'],f['team'],f['slot'],character_name(f['character']),f.get('costume',0),'Reserve' if f.get('reserve') else 'At start',str(p.get('transform_chance',100))+'%')
            for j,v in enumerate(values):self.fighters.setItem(i,j,QTableWidgetItem(str(v)))
        self.events.setRowCount(len(self.document['events']))
        for i,e in enumerate(self.document['events']):
            for j,v in enumerate((e['id'],condition_label(e['when']),', '.join(a['type'] for a in e['actions']))):
                item=QTableWidgetItem(v);item.setToolTip(v);self.events.setItem(i,j,item)
        self.graph.set_document(self.document)
    def edit_node(self,event_index,action_index):
        self.events.selectRow(event_index)
        if action_index<0:self.event_dialog(event_index);return
        self.sync();action=self.document['events'][event_index]['actions'][action_index]
        dialog=ActionDialog(self.document,action['type'],self,action=action)
        if dialog.exec()==QDialog.Accepted:
            candidate=copy.deepcopy(self.document);candidate['events'][event_index]['actions'][action_index]=dialog.value()
            try:self.document=missions.validate(candidate);self.refresh()
            except ValueError as e:self.error(e)
    def sync(self):
        self.document['title']=self.title.text().strip()
        self.document['description']=self.description.toPlainText().strip()
        self.document['stage']=None if self.stage.value()<0 else dict(id=self.stage.value(),name=self.stage_name.text().strip())
        self.document['defeat_grace_seconds']=self.grace.value()
        self.document['music']=None if self.music.value()<0 else self.music.value()
    def rules(self):
        self.sync();dialog=RulesDialog(self.document,self)
        if dialog.exec()==QDialog.Accepted:self.document.update(dialog.value());self.refresh()
    def new(self):self.document=missions.default_mission();self.path=None;self.refresh()
    def open(self):
        path,_=QFileDialog.getOpenFileName(self,'Open mission',str(missions.LIBRARY),'Mission (*.json)')
        if path:
            try:self.document=missions.load(path);self.path=Path(path);self.refresh()
            except Exception as e:self.error(e)
    def save(self,save_as=False):
        self.sync();path=self.path
        if path and path.parent.name=='Mission 100':path=None
        if save_as or not path:
            value,_=QFileDialog.getSaveFileName(self,'Save mission',str(missions.LIBRARY/(self.document['id']+'.json')),'Mission (*.json)')
            if not value:return
            path=Path(value)
        try:self.document=missions.save(path,self.document);self.path=path;self.status.setText('Saved '+str(path));self.refresh_library()
        except Exception as e:self.error(e)
    def validate(self):
        self.sync()
        try:
            from story_runtime import validate_compilation
            validate_compilation(self.document);self.status.setText('Document, roster limits and guest code size passed. The game checks native form routes/resources when requested. Gameplay has not been tested by this check.')
            return True
        except Exception as e:self.error(e);return False
    def test_mission(self):
        """Quick launch: save/validate, queue this document and start (or reuse) this tree's game."""
        import story_quicklaunch as quick
        if not self.validate():return
        try:
            saved=''
            if self.path and self.path.parent.name!='Mission 100':
                self.document=missions.save(self.path,self.document);saved=f'Saved {self.path.name}. '
                self.refresh_library()
            quick.request(self.document)
            if quick.game_running():
                self.status.setText(saved+'Queued for the running game: return to the main menu and the mission '
                                    'starts by itself (the request expires after 15 minutes).')
            else:
                quick.start()
                self.status.setText(saved+f"Starting the game into “{self.document['title']}”. Press Start at the "
                                    'title screen; the mission starts by itself from the main menu.')
        except (OSError,ValueError) as e:self.error(e)
    def arm(self):
        if self.validate():
            try:
                missions.arm(self.document);self.status.setText('Armed. Start a fresh Modded Team Battle with exactly this roster and costumes. Ordinary modes are unchanged. A mismatch stops preparation with the expected slot.')
            except (OSError,ValueError) as e:self.error(e)
    def disarm(self):
        try:
            missions.disarm();self.status.setText('Next battle cleared. Saved mission files are unchanged.')
        except OSError as e:self.error(e)
    def add_fighter(self):
        self.sync();side=2;slot=1+sum(f['team']==side for f in self.document['fighters'])
        self.fighter_dialog(dict(id=f'fighter-{len(self.document["fighters"])+1}',team=side,slot=slot,character=0),None)
    def edit_fighter(self):
        self.sync();i=self.fighters.currentRow()
        if i>=0:self.fighter_dialog(self.document['fighters'][i],i)
    def fighter_dialog(self,f,i):
        dialog=FighterDialog(f,self.document.get('cpu_profiles',{}).get(f.get('cpu_profile'),{}),self)
        if dialog.exec()==QDialog.Accepted:
            row,key,profile=dialog.value();self.document.setdefault('cpu_profiles',{})[key]=profile
            if i is None:self.document['fighters'].append(row)
            else:
                # Renaming a fighter updates every reference atomically.
                old=f['id'];self.document['fighters'][i]=row
                if old!=row['id']:
                    def rename(obj):
                        if isinstance(obj,dict):
                            for k,v in obj.items():
                                if k in ('fighter','target','copy_cpu_from','victim','attacker') and v==old:obj[k]=row['id']
                                else:rename(v)
                        elif isinstance(obj,list):
                            for v in obj:rename(v)
                    rename(self.document)
            self.refresh()
    def remove_fighter(self):
        self.sync()
        i=self.fighters.currentRow()
        if i>=0:self.document['fighters'].pop(i);self.refresh()
    def copy_cpu(self):
        try:
            self.sync();i=self.fighters.currentRow()
            if i<0:raise ValueError('Select the destination fighter first')
            dest=self.document['fighters'][i]['id'];names=[f['id'] for f in self.document['fighters'] if f['id']!=dest]
            source,ok=QInputDialog.getItem(self,'Copy configured CPU','Source CPU',names,0,False)
            if ok:self.document=missions.copy_cpu_profile(self.document,source,dest);self.refresh()
        except Exception as e:self.error(e)
    def add_event(self):self.event_dialog(None)
    def followup_event(self):
        i=self.events.currentRow()
        if i<0:self.error('Select an event node first');return
        self.event_dialog(None,after=self.document['events'][i]['id'])
    def edit_event(self):
        i=self.events.currentRow()
        if i>=0:self.event_dialog(i)
    def event_dialog(self,i,after=None):
        self.sync();dialog=EventDialog(self.document,None if i is None else self.document['events'][i],self)
        if after:
            dialog.trigger.setCurrentIndex(dialog.trigger.findData('event'));dialog.previous.setCurrentIndex(dialog.previous.findData(after))
        if dialog.exec()==QDialog.Accepted:
            event=dialog.value_event()
            if i is None:self.document['events'].append(event)
            else:
                old=self.document['events'][i]['id'];self.document['events'][i]=event
                def rename(condition):
                    if condition.get('type') in ('event','event_failed') and condition.get('event')==old:condition['event']=event['id']
                    for child in condition.get('conditions',[]):rename(child)
                    if condition.get('condition'):rename(condition['condition'])
                if old!=event['id']:
                    for other in self.document['events']:rename(other['when'])
                    for key in ('win_when','fail_when'):
                        if self.document.get(key):rename(self.document[key])
            self.refresh()
    def remove_event(self):
        self.sync()
        i=self.events.currentRow()
        if i>=0:self.document['events'].pop(i);self.refresh()
    def waves(self):
        self.sync()
        if self.document['events']:
            self.error('Create waves on a copy with an empty event list so existing story events are preserved.');return
        enemies=sorted((f for f in self.document['fighters'] if f['team']==2),key=lambda f:f['slot'])
        for previous,f in zip(enemies,enemies[1:]):
            f['reserve']=True;self.document['events'].append(dict(id='arrival-'+f['id'],
                when=dict(type='defeated',fighter=previous['id']),
                actions=[dict(type='enter',fighter=f['id'],intro=True),dict(type='message',text=character_name(f['character'])+' enters!',seconds=4)]))
        self.refresh()
    def import100(self):
        path,_=QFileDialog.getOpenFileName(self,'USA BT3 ISO containing Mission 100','','ISO (*.iso)')
        if not path:return
        try:
            from mission100 import extract
            rows=extract(Path(path))
            for row in rows:missions.save(missions.LIBRARY/'Mission 100'/(row['id']+'.json'),row)
            self.refresh_library()
            self.status.setText('Imported all 100 original enemy rosters. Open a preset, choose your allies, then optionally add waves/events. Original stage/restriction metadata is retained but not yet enforced.')
        except Exception as e:self.error(e)
