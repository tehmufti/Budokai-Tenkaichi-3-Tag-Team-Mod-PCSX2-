"""Native BT3 modder workbench: assets, animations, settings and trainer telemetry.

The GUI never creates a PINE connection. Live edits are short-lived requests to
the already running trainer; model browsing reads the original local ISO only.
"""
import argparse
import ast
import json
import os
import sys
import time
import uuid
from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt, QThread, Signal, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QFormLayout, QLabel, QPushButton, QLineEdit, QComboBox, QCheckBox, QSpinBox,
    QDoubleSpinBox, QSlider, QTabWidget, QSplitter, QFileDialog, QMessageBox,
    QPlainTextEdit, QTableWidget, QTableWidgetItem, QHeaderView, QListWidget, QScrollArea, QDialog)

import atomic_files
import mod_settings
import trainer_bridge as bridge
from character_names import character_table, character_name
from model_viewer import ModelViewport

ROOT = Path(__file__).resolve().parents[1]
VIEWER = ROOT/'analysis'/'model-viewer'
STYLE = '''
QWidget { background:#050505; color:#b8d9bd; font-family:Consolas; font-size:12px; }
QMainWindow, QTabWidget::pane { border:1px solid #174426; }
QLabel#title { color:#00ff41; font-size:22px; font-weight:600; }
QLabel#muted { color:#719a7d; }
QPushButton { color:#00ff41; border:1px solid #26673a; padding:7px 12px; background:#09140c; }
QPushButton:hover { background:#163721; border-color:#00ff41; }
QPushButton:disabled { color:#4a5b4d; border-color:#27372b; }
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit { padding:5px; border:1px solid #245a34; background:#09100b; }
QTabBar::tab { padding:10px 17px; color:#7ba187; background:#080e0a; border-bottom:2px solid #162a1c; }
QTabBar::tab:selected { color:#00ff41; border-bottom:2px solid #00ff41; }
QListWidget, QTableWidget { background:#080d09; alternate-background-color:#0c1710; border:1px solid #174426; }
QListWidget::item:selected, QTableWidget::item:selected { background:#17482a; color:#d9ffe4; }
QHeaderView::section { color:#00ff41; background:#0d2013; border:0; padding:7px; }
QSlider::groove:horizontal { height:4px; background:#20442b; }
QSlider::handle:horizontal { background:#00ff41; width:10px; margin:-5px 0; }
QCheckBox { spacing:8px; padding:3px; }
QCheckBox::indicator { width:16px; height:16px; border:1px solid #80b98d; border-radius:2px; background:#09100b; }
QCheckBox::indicator:hover { border:2px solid #00ff41; }
QCheckBox::indicator:checked { background:#00b936; border:2px solid #b8ffca; }
QCheckBox::indicator:disabled { border:1px solid #4a5b4d; background:#17231a; }
QToolTip { color:#d9ffe4; background:#0d2013; border:1px solid #00ff41; }
'''


def button(text, callback):
    result = QPushButton(text)
    result.clicked.connect(callback)
    return result


def line(*widgets):
    row = QHBoxLayout()
    for widget in widgets: row.addWidget(widget)
    return row


def open_path(path):
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).resolve())))


class AssetLoader(QThread):
    loaded = Signal(object, object, str)
    failed = Signal(str)
    def __init__(self, iso, character, costume, damaged, parent):
        super().__init__(parent)
        self.args = (iso, character, costume, damaged)
    def run(self):
        try:
            import model_assets
            import model_animations
            iso, character, costume, damaged = self.args
            asset = model_assets.load_character(iso, character, costume, damaged)
            bank, warning = None, ''
            try: bank = model_animations.AnimationBank.from_bytes(model_assets.read_animation_bank(iso, character))
            except Exception as error: warning = f'Animation bank unavailable: {error}'
            self.loaded.emit(asset, bank, warning)
        except Exception as error: self.failed.emit(str(error))


class Workbench(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('BT3 Workbench')
        self.resize(1440, 900)
        self.loader = None
        self.asset = self.bank = None
        self.loaded_character = None
        self.telemetry = None
        self.pending = {}
        self.closing = False
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        heading = QLabel('BT3 Workbench')
        heading.setObjectName('title')
        layout.addWidget(heading)
        subtitle = QLabel('ASSETS  /  ANIMATION BANK  /  RUNTIME  /  PREFERENCES')
        subtitle.setObjectName('muted')
        layout.addWidget(subtitle)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        self.build_models()
        self.build_runtime()
        from story_editor import StoryEditor
        self.story_editor=StoryEditor(self)
        self.tabs.addTab(self.story_editor, 'Custom Scenarios')
        self.build_settings()
        self.build_tools()
        self.statusBar().showMessage('Offline asset browsing is ready. Live trainer monitoring is opt-in.')
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh_runtime)
        self.timer.start(750)

    def error(self, message):
        self.statusBar().showMessage(str(message))
        QMessageBox.warning(self, 'BT3 Workbench', str(message))

    def build_models(self):
        page = QWidget(); outer = QVBoxLayout(page)
        default = ROOT.parent/'games'/'SLUS_219.78.DBZBT4B14REV2ENG.iso'
        self.iso = QLineEdit(str(default))
        outer.addLayout(line(QLabel('SOURCE ISO'), self.iso, button('Browse…', self.browse_iso)))
        controls = QWidget(); column = QVBoxLayout(controls)
        controls.setMaximumWidth(355)
        self.search = QLineEdit(); self.search.setPlaceholderText('Find fighter or form…')
        self.characters = QComboBox()
        self.character_rows = sorted(character_table())
        self.populate_characters()
        self.search.textChanged.connect(self.populate_characters)
        self.costume = QSpinBox(); self.costume.setRange(0, 3)
        self.damaged = QCheckBox('Battle-damaged costume')
        column.addWidget(QLabel('CHARACTER / FORM'))
        column.addWidget(self.search); column.addWidget(self.characters)
        column.addLayout(line(QLabel('Costume index'), self.costume))
        column.addWidget(self.damaged)
        self.load_button = button('Load fighter', self.load_asset)
        column.addWidget(self.load_button)
        self.model_info = QLabel('Select a fighter to read its model from the ISO.')
        self.model_info.setWordWrap(True); column.addWidget(self.model_info)
        column.addWidget(QLabel('ANIMATION BANK'))
        self.animation_search = QLineEdit(); self.animation_search.setPlaceholderText('Filter animation ID…')
        self.animation_search.textChanged.connect(self.filter_animations)
        column.addWidget(self.animation_search)
        self.animations = QListWidget(); self.animations.currentRowChanged.connect(self.select_clip)
        column.addWidget(self.animations, 1)
        self.bookmark_name = QLineEdit(); self.bookmark_name.setPlaceholderText('Note, e.g. revival candidate')
        column.addWidget(self.bookmark_name)
        column.addWidget(button('Save animation bookmark', self.bookmark))
        column.addWidget(button('Export current pose (OBJ)', self.export_pose))
        column.addWidget(button('Show / hide model parts…', self.model_parts))
        self.halo = QCheckBox('Show halo')
        self.halo.setChecked(True); self.halo.setEnabled(False)
        self.halo.setToolTip('Viewer and exported pose only. Other parts can be toggled in Show / hide model parts.')
        self.halo.toggled.connect(self.halo_changed)
        column.addWidget(self.halo)
        column.addWidget(button('Save viewport image', self.save_image))
        display = QWidget(); view_layout = QVBoxLayout(display)
        view_layout.setContentsMargins(0, 0, 0, 0)
        self.viewport = ModelViewport()
        self.viewport.failed.connect(self.animation_error)
        self.viewport.frame_changed.connect(self.frame_changed)
        view_layout.addWidget(self.viewport, 1)
        tip = QLabel('LEFT DRAG orbit  ·  WHEEL zoom  ·  RIGHT DRAG pan')
        tip.setObjectName('muted'); view_layout.addWidget(tip)
        grid = QCheckBox('Grid'); grid.setChecked(True)
        grid.toggled.connect(lambda value: self.view_option('show_grid', value))
        skeleton = QCheckBox('Skeleton'); skeleton.toggled.connect(lambda value: self.view_option('skeleton', value))
        wire = QCheckBox('Wireframe'); wire.toggled.connect(lambda value: self.view_option('wireframe', value))
        follow = QCheckBox('Follow motion'); follow.setChecked(True)
        follow.toggled.connect(lambda value: self.view_option('follow_motion', value))
        view_layout.addLayout(line(grid, skeleton, wire, follow, button('Reset view', self.viewport.reset_camera)))
        self.play = button('Play / pause', self.toggle_play)
        self.loop = QCheckBox('Loop'); self.loop.setChecked(True)
        self.loop.toggled.connect(lambda value: setattr(self.viewport, 'loop', value))
        self.speed = QDoubleSpinBox(); self.speed.setRange(.05, 4); self.speed.setSingleStep(.25); self.speed.setValue(1); self.speed.setSuffix('×')
        self.speed.valueChanged.connect(lambda value: setattr(self.viewport, 'speed', value))
        self.frame_label = QLabel('Bind pose')
        view_layout.addLayout(line(self.play, self.loop, QLabel('Speed'), self.speed, self.frame_label))
        self.scrub = QSlider(Qt.Horizontal)
        self.scrub.setRange(0, 0)
        self.scrub.sliderPressed.connect(lambda: setattr(self.viewport, 'playing', False))
        self.scrub.valueChanged.connect(lambda value: self.viewport.set_frame(value/100))
        view_layout.addWidget(self.scrub)
        split = QSplitter(); split.addWidget(controls); split.addWidget(display); split.setStretchFactor(1, 1)
        outer.addWidget(split, 1)
        self.tabs.addTab(page, 'Model / animation')

    def view_option(self, name, value):
        setattr(self.viewport, name, value); self.viewport.update()

    def populate_characters(self, *_):
        chosen = self.characters.currentData()
        self.characters.clear()
        query = self.search.text().lower()
        for cid in self.character_rows:
            name = f'{cid:03d}  {character_name(cid)}'
            if query in name.lower(): self.characters.addItem(name, cid)
        found = self.characters.findData(chosen)
        if found >= 0: self.characters.setCurrentIndex(found)

    def browse_iso(self):
        path, _ = QFileDialog.getOpenFileName(self, 'BT4 ISO', self.iso.text(), 'PlayStation 2 ISO (*.iso)')
        if path: self.iso.setText(path)

    def load_asset(self):
        if self.loader is not None or self.characters.currentData() is None: return
        self.load_button.setEnabled(False)
        self.model_info.setText('Reading native model and animation data…')
        self.loading_character = self.characters.currentData()
        self.loading_costume = self.costume.value()
        self.loading_damaged = self.damaged.isChecked()
        self.loading_iso = self.iso.text()
        self.loader = AssetLoader(self.loading_iso, self.loading_character, self.loading_costume, self.loading_damaged, self)
        self.loader.loaded.connect(self.asset_loaded)
        self.loader.failed.connect(self.load_failed)
        self.loader.finished.connect(self.load_finished)
        self.loader.start()

    def asset_loaded(self, asset, bank, warning):
        self.asset, self.bank = asset, bank
        self.loaded_character = self.loading_character
        self.loaded_costume, self.loaded_damaged, self.loaded_iso = self.loading_costume, self.loading_damaged, self.loading_iso
        self.viewport.set_asset(asset)
        from model_assets import part_names
        self.halo.setEnabled(111 in part_names(asset))
        self.halo_changed(self.halo.isChecked())
        self.animations.clear(); self.animations.addItem('Bind pose')
        if bank:
            for clip in bank.clips:
                self.animations.addItem(f'{clip.animation_id:03d}  /  {clip.frame_count} frames  /  {clip.duration_seconds:.2f}s')
        self.animations.setCurrentRow(0)
        self.filter_animations()
        self.model_info.setText(f'{character_name(self.loaded_character)}\n{len(asset.positions):,} vertices · {len(asset.triangles):,} triangles\n'
            f'{len(asset.bones)} bones · {len(asset.textures)} textures\n{len(bank.clips) if bank else 0} animation clips')
        self.statusBar().showMessage(warning or 'Loaded real game assets. Animation numbers are native bank IDs.')

    def load_failed(self, message):
        self.model_info.setText('Load failed. The previous model, if any, is unchanged.')
        self.error(message)

    def load_finished(self):
        old, self.loader = self.loader, None
        if old: old.deleteLater()
        self.load_button.setEnabled(True)

    def filter_animations(self, *_):
        query = self.animation_search.text().lower()
        for index in range(self.animations.count()):
            item = self.animations.item(index); item.setHidden(query not in item.text().lower())

    def select_clip(self, row):
        clip = self.bank.clips[row-1] if self.bank and 0 < row <= len(self.bank.clips) else None
        self.viewport.playing = False
        self.scrub.blockSignals(True); self.scrub.setRange(0, max(0, clip.frame_count)*100 if clip else 0); self.scrub.setValue(0); self.scrub.blockSignals(False)
        self.viewport.set_clip(clip)
        self.frame_label.setText(f'Frame 0 / {clip.frame_count}' if clip else 'Bind pose')

    def animation_error(self, error): self.statusBar().showMessage(f'Animation stopped: {error}')
    def toggle_play(self):
        if self.viewport.clip: self.viewport.playing = not self.viewport.playing
    def frame_changed(self, frame):
        self.scrub.blockSignals(True); self.scrub.setValue(round(frame*100)); self.scrub.blockSignals(False)
        if self.viewport.clip: self.frame_label.setText(f'Frame {frame:.1f} / {self.viewport.clip.frame_count}')

    def bookmark(self):
        clip = self.viewport.clip
        if clip is None: return self.error('Choose an animation first.')
        path = VIEWER/'animation-bookmarks.json'
        try:
            try: rows = atomic_files.read_json(path)
            except FileNotFoundError: rows = []
            if not isinstance(rows, list): raise ValueError('Bookmark file must contain a list')
            rows.append(dict(character=self.loaded_character, character_name=character_name(self.loaded_character),
                costume=self.loaded_costume, damaged=self.loaded_damaged, animation_id=clip.animation_id,
                frame=self.viewport.frame, note=self.bookmark_name.text(), created=time.time()))
            atomic_files.write_json(path, rows)
            self.statusBar().showMessage('Animation bookmark saved. This does not change in-game revival actions.')
        except (OSError, ValueError) as error: self.error(error)

    def save_image(self):
        if self.asset is None: return
        path, _ = QFileDialog.getSaveFileName(self, 'Save viewport', str(VIEWER/'viewport.png'), 'PNG (*.png)')
        if path and not self.viewport.grabFramebuffer().save(path): self.error('Could not save viewport image')

    def model_parts(self):
        if self.asset is None: return
        dialog = QDialog(self); dialog.setWindowTitle('Native model parts'); dialog.resize(400, 560)
        layout = QVBoxLayout(dialog)
        label = QLabel('All authored parts are shown initially, including optional accessories. Toggle individual native bone parts here.')
        label.setWordWrap(True); layout.addWidget(label)
        parts = QListWidget(); layout.addWidget(parts)
        from model_assets import part_names
        names = part_names(self.asset)
        ids, counts = np.unique(self.asset.triangle_bones, return_counts=True)
        for bone, count in zip(ids, counts):
            name = names.get(int(bone), 'Part')
            parts.addItem(f'{name} {bone:03d}  /  {count} triangles')
            item = parts.item(parts.count()-1); item.setData(Qt.UserRole, int(bone))
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked if bone in self.viewport.hidden_parts else Qt.Checked)
        def changed(item):
            bone = item.data(Qt.UserRole)
            if item.checkState() == Qt.Checked: self.viewport.hidden_parts.discard(bone)
            else: self.viewport.hidden_parts.add(bone)
            if bone == 111 and bone in names:
                self.halo.blockSignals(True)
                self.halo.setChecked(bone not in self.viewport.hidden_parts)
                self.halo.blockSignals(False)
            self.viewport.update()
        parts.itemChanged.connect(changed)
        layout.addWidget(button('Done', dialog.accept)); dialog.exec()

    def halo_changed(self, visible):
        if self.asset is None: return
        from model_assets import part_names
        if 111 not in part_names(self.asset): return
        if visible: self.viewport.hidden_parts.discard(111)
        else: self.viewport.hidden_parts.add(111)
        self.viewport.update()

    def export_pose(self):
        if self.asset is None: return
        path, _ = QFileDialog.getSaveFileName(self, 'Export current pose in native coordinates', str(VIEWER/f'fighter-{self.loaded_character}.obj'), 'Wavefront OBJ (*.obj)')
        if not path: return
        try:
            export_obj(Path(path), self.asset, self.viewport.positions, self.viewport.hidden_parts)
            self.statusBar().showMessage('Pose, materials and textures exported in native model coordinates.')
        except (OSError, ValueError) as error: self.error(error)

    def build_runtime(self):
        page = QWidget(); layout = QVBoxLayout(page)
        self.follow = QCheckBox('Follow running trainer')
        self.follow.toggled.connect(self.follow_changed)
        layout.addLayout(line(self.follow, button('Open offline RAM / save state…', self.open_snapshot)))
        self.runtime_status = QLabel('Monitoring off. Asset browsing and settings do not need the emulator.')
        self.runtime_status.setWordWrap(True); layout.addWidget(self.runtime_status)
        self.fighters = QTableWidget(0, 10)
        self.fighters.setHorizontalHeaderLabels(['Slot', 'Team', 'Fighter', 'HP', 'Ki', 'Stocks', 'Action', 'Target', 'Actor', 'Model'])
        self.fighters.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.fighters.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.fighters.setSelectionBehavior(QTableWidget.SelectRows)
        self.fighters.setSelectionMode(QTableWidget.SingleSelection)
        self.fighters.setEditTriggers(QTableWidget.NoEditTriggers)
        self.fighters.itemSelectionChanged.connect(self.select_fighter)
        self.fighters.cellDoubleClicked.connect(self.inspect_fighter)
        layout.addWidget(self.fighters, 1)
        self.gauge = QComboBox(); self.gauge.addItems(['hp', 'ki', 'stocks'])
        self.gauge.currentTextChanged.connect(self.select_fighter)
        self.value = QSpinBox(); self.value.setRange(0, 0x1000000)
        self.apply_gauge = button('Apply gauge edit', self.queue_edit); self.apply_gauge.setEnabled(False)
        layout.addLayout(line(QLabel('Selected fighter'), self.gauge, self.value, self.apply_gauge))
        self.gauge_note = QLabel('HP: 10,000 = one health bar. Stocks: 100,000 = one blast stock. Edits apply once.')
        layout.addWidget(self.gauge_note)
        self.runtime_details = QPlainTextEdit(); self.runtime_details.setReadOnly(True); self.runtime_details.setMaximumHeight(165)
        layout.addWidget(self.runtime_details)
        self.tabs.addTab(page, 'Live trainer')

    def follow_changed(self, enabled):
        if not enabled:
            self.apply_gauge.setEnabled(False)
            self.runtime_status.setText('Monitoring off. Any unprocessed edit expires within five seconds.')
        self.refresh_runtime()

    def refresh_runtime(self):
        if not self.follow.isChecked(): return
        try:
            atomic_files.write_json(bridge.DIRECTORY/'lease.json', {'created': time.time()}, timeout=.1)
            try: state = atomic_files.read_json(bridge.DIRECTORY/'snapshot.json')
            except FileNotFoundError: state = None
            if state is None or not 0 <= time.time()-state.get('created', 0) <= 3:
                self.runtime_status.setText('Waiting for the automatic trainer. Start Play and enter a prepared match.')
                self.apply_gauge.setEnabled(False)
            else: self.show_snapshot(state)
            for token, created in list(self.pending.items()):
                path = bridge.DIRECTORY/'results'/(token+'.json')
                try: result = atomic_files.read_json(path)
                except FileNotFoundError:
                    if time.time()-created > 8:
                        self.statusBar().showMessage('Edit expired or the trainer is busy; refresh before trying again.')
                        self.pending.pop(token)
                    continue
                self.pending.pop(token)
                self.statusBar().showMessage(result.get('message') or 'Edit did not finish')
        except (OSError, ValueError, KeyError, TypeError) as error:
            self.runtime_status.setText(f'Telemetry unavailable: {error}')
            self.apply_gauge.setEnabled(False)

    def show_snapshot(self, state):
        previous = self.selected_fighter()
        self.telemetry = state
        rows = state.get('fighters', [])
        self.fighters.blockSignals(True); self.fighters.setRowCount(len(rows))
        for index, fighter in enumerate(rows):
            values = [fighter['physical'], fighter['team'], fighter['name'],
                f"{fighter['hp']} / {fighter['hp_max']}", f"{fighter['ki']} / {fighter['ki_max']}",
                f"{fighter['stocks']/100000:.2f} / {fighter['stocks_max']/100000:g}",
                fighter['action'], fighter['target'], f"{fighter['actor']:08X}", f"{fighter['model']:08X}"]
            for column, value in enumerate(values): self.fighters.setItem(index, column, QTableWidgetItem(str(value)))
            if previous and previous['physical'] == fighter['physical']: self.fighters.selectRow(index)
        self.fighters.blockSignals(False)
        self.runtime_status.setText(('OFFLINE SNAPSHOT · ' if state.get('offline') else 'LIVE · ')+
            (f"{state.get('mode', '').upper()} · {len(rows)} fighters · battle phase {state.get('phase')}" if state.get('active') else state.get('reason', 'Waiting')))
        self.runtime_details.setPlainText(json.dumps({key: value for key, value in state.items() if key != 'fighters'}, indent=2))
        self.story_editor.show_status(state.get('story'))
        self.select_fighter(update_value=False)

    def selected_fighter(self):
        index = self.fighters.currentRow()
        rows = self.telemetry.get('fighters', []) if self.telemetry else []
        return rows[index] if 0 <= index < len(rows) else None

    def select_fighter(self, *_, update_value=True):
        fighter = self.selected_fighter()
        enabled = bool(fighter and self.follow.isChecked() and self.telemetry.get('editable')
            and not self.telemetry.get('offline') and fighter['alive']
            and 0 <= time.time()-self.telemetry.get('created', 0) <= 3)
        self.apply_gauge.setEnabled(enabled)
        if fighter:
            field = self.gauge.currentText()
            self.value.setRange(1 if field == 'hp' else 0, min(0x1000000, max(1, fighter[field+'_max'])))
            if update_value: self.value.setValue(fighter[field])

    def queue_edit(self):
        self.select_fighter(update_value=False)
        fighter = self.selected_fighter()
        if fighter is None or not self.apply_gauge.isEnabled(): return
        token = uuid.uuid4().hex
        request = {key: fighter[key] for key in ('physical', 'actor', 'model', 'character', 'slot', 'row')}
        request.update(epoch=self.telemetry['epoch'], created=time.time(), field=self.gauge.currentText(), value=self.value.value())
        try:
            atomic_files.write_json(bridge.DIRECTORY/'requests'/(token+'.json'), request, timeout=.2)
            self.pending[token] = time.time()
            self.statusBar().showMessage('Edit queued for the trainer’s next safe combat boundary.')
        except OSError as error: self.error(error)

    def inspect_fighter(self, row, _):
        fighter = self.selected_fighter()
        if fighter:
            self.search.clear(); self.characters.setCurrentIndex(self.characters.findData(fighter['character']))
            self.tabs.setCurrentIndex(0); self.load_asset()

    def open_snapshot(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Inspect offline RAM', str(ROOT/'analysis'), 'EE RAM or save state (*.bin *.p2s);;All files (*)')
        if not path: return
        try:
            from camera_snapshot import read_ram
            state = bridge.snapshot(bridge.RamReader(read_ram(path)))
            state.update(offline=True, editable=False, source=path)
            self.follow.setChecked(False); self.show_snapshot(state)
        except Exception as error: self.error(error)

    def build_settings(self):
        page = QWidget(); layout = QVBoxLayout(page)
        layout.addWidget(QLabel('Preferences use the same settings file as the game launcher. Save changes for the next match / launch.'))
        pages = QTabWidget(); layout.addWidget(pages, 1)
        self.setting_widgets = {}; self.setting_base = mod_settings.load_settings(); forms = {}
        for key, (default, kind, low, high, group, label) in mod_settings.ui_fields().items():
            if group not in forms:
                body = QWidget(); form = QFormLayout(body); form.setVerticalSpacing(14)
                scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setWidget(body)
                pages.addTab(scroll, group); forms[group] = form
            value = self.setting_base[key]
            if kind == 'bool': widget = QCheckBox(); widget.setChecked(value)
            elif kind in ('choice', 'button'):
                widget = QComboBox(); widget.addItems(low); widget.setCurrentText(value)
            else:
                widget = QSpinBox() if kind == 'int' else QDoubleSpinBox()
                widget.setRange(low, high); widget.setValue(value)
                if kind != 'int': widget.setDecimals(2); widget.setSingleStep(.25)
            self.setting_widgets[key] = (widget, kind)
            forms[group].addRow(label, widget)
        layout.addLayout(line(button('Save changed preferences', self.save_settings),
            button('Controller rebind / per-character rules…', lambda: open_path(ROOT/'Mod settings.cmd')),
            button('Open settings file', lambda: open_path(mod_settings.SETTINGS_PATH))))
        self.tabs.addTab(page, 'Mod settings')

    def save_settings(self):
        patch = {}
        for key, (widget, kind) in self.setting_widgets.items():
            value = widget.isChecked() if kind == 'bool' else widget.currentText() if kind in ('choice', 'button') else widget.value()
            if value != self.setting_base[key]: patch[key] = value
        try:
            mod_settings.save_settings(patch)
            # Keep the baseline aligned with visible widgets, not unrelated
            # concurrent edits from another settings window.
            self.setting_base.update(patch)
            self.statusBar().showMessage(f'Saved {len(patch)} changed preferences. Start a new match to apply them.')
        except (OSError, ValueError) as error: self.error(error)

    def build_tools(self):
        page = QWidget(); layout = QVBoxLayout(page)
        layout.addLayout(line(button('Runtime logs', lambda: open_path(ROOT/'analysis'/'autopilot')),
            button('Asset exports / bookmarks', lambda: open_path(VIEWER)),
            button('Refresh latest log', self.refresh_log)))
        self.log = QPlainTextEdit(); self.log.setReadOnly(True); layout.addWidget(self.log, 1)
        layout.addWidget(QLabel('TOOL SOURCE INDEX · inspect local tools without executing them'))
        search = QLineEdit(); search.setPlaceholderText('Find a tool…'); layout.addWidget(search)
        self.tools_list = QListWidget(); layout.addWidget(self.tools_list, 1)
        self.tool_descriptions = {}
        for path in sorted((ROOT/'tools').glob('*.py')):
            if path.name.startswith('test_'): continue
            try:
                module = ast.parse(path.read_text(encoding='utf-8-sig'))
                description = ast.get_docstring(module) or '(No module description)'
            except (OSError, SyntaxError): description = '(Unable to read source)'
            self.tool_descriptions[path.name] = (path, description)
            self.tools_list.addItem(path.name)
        search.textChanged.connect(lambda query: [self.tools_list.item(i).setHidden(query.lower() not in self.tools_list.item(i).text().lower()) for i in range(self.tools_list.count())])
        self.tool_description = QLabel('Choose a tool to read its purpose; double-click to open its source.')
        self.tool_description.setWordWrap(True); layout.addWidget(self.tool_description)
        self.tools_list.currentTextChanged.connect(lambda name: self.tool_description.setText(self.tool_descriptions[name][1][:700]) if name else None)
        self.tools_list.itemDoubleClicked.connect(lambda item: self.open_source(item.text()))
        self.tabs.addTab(page, 'Logs / tools')
        self.refresh_log()

    def open_source(self, name):
        path = self.tool_descriptions[name][0]
        try: source = path.read_text(encoding='utf-8-sig')
        except OSError as error: return self.error(error)
        # Opening .py through the Windows file association can execute it.
        # Keep source inspection inside a read-only native text window.
        dialog = QDialog(self); dialog.setWindowTitle(str(path)); dialog.resize(1000, 760)
        layout = QVBoxLayout(dialog); text = QPlainTextEdit(); text.setReadOnly(True)
        text.setPlainText(source); layout.addWidget(text)
        layout.addWidget(button('Close', dialog.accept)); dialog.exec()

    def refresh_log(self):
        folder = ROOT/'analysis'/'autopilot'
        candidates = list(folder.glob('*/*.log'))+list(folder.glob('*/*.txt'))
        if not candidates:
            self.log.setPlainText('No automatic-trainer logs found yet.'); return
        path = max(candidates, key=lambda p: p.stat().st_mtime)
        try:
            with path.open('rb') as stream:
                stream.seek(max(0, path.stat().st_size-24000)); tail = stream.read().decode('utf-8', errors='replace')
            self.log.setPlainText(str(path)+'\n\n'+tail)
        except OSError as error: self.log.setPlainText(str(error))

    def closeEvent(self, event):
        if self.loader is not None and self.loader.isRunning():
            self.statusBar().showMessage('Finishing the asset read before closing…')
            if not self.closing:
                self.closing = True; self.loader.finished.connect(self.close)
            event.ignore(); return
        self.viewport.playing = False; self.timer.stop(); event.accept()


def export_obj(path, asset, positions, hidden_parts=()):
    from PIL import Image
    path.parent.mkdir(parents=True, exist_ok=True)
    material_path = path.with_suffix('.mtl')
    material_lines = []
    for index, material in enumerate(asset.materials):
        material_lines.extend([f'newmtl material_{index}', 'Kd 1 1 1', 'd 1'])
        if 0 <= material.texture_index < len(asset.textures):
            texture_path = path.with_name(path.stem+f'-texture-{material.texture_index}.png')
            Image.fromarray(asset.textures[material.texture_index].rgba).save(texture_path)
            material_lines.append(f'map_Kd {texture_path.name}')
    lines = ['# BT3 native coordinates; static current pose', f'mtllib {material_path.name}']
    lines.extend('v '+' '.join(f'{v:.8g}' for v in row) for row in positions)
    lines.extend(f'vt {u:.8g} {1-v:.8g}' for u, v in asset.uv)
    last = None
    visible = ~np.isin(asset.triangle_bones, list(hidden_parts))
    for triangle, material in zip(asset.triangles[visible], asset.triangle_materials[visible]):
        if material != last: lines.append(f'usemtl material_{material}'); last = material
        lines.append('f '+' '.join(f'{int(index)+1}/{int(index)+1}' for index in triangle))
    material_path.write_text('\n'.join(material_lines)+'\n', encoding='utf-8')
    path.write_text('\n'.join(lines)+'\n', encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Validate dependencies without a window or emulator')
    parser.add_argument('--smoke', type=Path, help='Load character 0, capture GUI and exit (no emulator connection)')
    parser.add_argument('--character', type=int, default=0)
    parser.add_argument('--animation', type=int, help='Native animation ID for an offline smoke capture')
    parser.add_argument('--frame', type=float, default=0, help='Frame for the offline smoke capture')
    args = parser.parse_args()
    if args.check:
        import model_assets, model_animations, pycdlib, PIL, zstandard
        print('Native GUI, asset parser and animation dependencies are ready.'); return 0
    app = QApplication(sys.argv[:1]); app.setStyle('Fusion'); app.setStyleSheet(STYLE)
    app.setFont(QFont('Consolas', 10))
    window = Workbench(); window.show()
    if args.smoke:
        result = {'code': 1}
        def capture():
            if window.asset is None: return
            args.smoke.parent.mkdir(parents=True, exist_ok=True)
            window.viewport.grabFramebuffer().save(str(args.smoke.with_name(args.smoke.stem+'-viewport.png')))
            window.grab().save(str(args.smoke))
            result['code'] = 0; window.close()
        def loaded(*_):
            if args.animation is not None and window.bank:
                index = next((i for i, clip in enumerate(window.bank.clips) if clip.animation_id == args.animation), None)
                if index is None:
                    print('Animation ID is absent from this character bank', file=sys.stderr); app.exit(1); return
                window.animations.setCurrentRow(index+1)
                window.viewport.set_frame(min(args.frame, window.viewport.clip.frame_count))
            QTimer.singleShot(800, capture)
        window.characters.setCurrentIndex(window.characters.findData(args.character))
        window.load_asset()
        window.loader.loaded.connect(loaded)
        window.loader.failed.connect(lambda message: (print(message, file=sys.stderr), app.exit(1)))
        QTimer.singleShot(60000, lambda: app.exit(2))
        app.exec(); return result['code']
    return app.exec()


if __name__ == '__main__': raise SystemExit(main())
