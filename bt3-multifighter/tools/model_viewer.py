"""Native OpenGL asset viewer. No emulator, web view, or game writes."""
import math
import time

import numpy as np
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QSurfaceFormat
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from OpenGL import GL as gl
from OpenGL.GLU import gluPerspective, gluLookAt


def quaternion_matrix(rotation):
    x, y, z, w = rotation
    length = math.sqrt(x*x+y*y+z*z+w*w)
    if not math.isfinite(length) or length < 1e-8: return np.eye(4, dtype=np.float32)
    x, y, z, w = (v/length for v in (x, y, z, w))
    return np.array([[1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w), 0],
                     [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w), 0],
                     [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y), 0],
                     [0, 0, 0, 1]], dtype=np.float32)


def pose_matrices(bones, transforms):
    world, remaining = {}, {b.native_id: b for b in bones}
    while remaining:
        progress = False
        for key, bone in list(remaining.items()):
            if bone.parent_id in remaining: continue
            transform = transforms.get(key)
            local = quaternion_matrix(transform.rotation) if transform else np.eye(4, dtype=np.float32)
            translation = transform.translation if transform and transform.translation is not None else bone.bind_translation
            local[:3, 3] = translation
            world[key] = world.get(bone.parent_id, np.eye(4, dtype=np.float32)) @ local
            del remaining[key]
            progress = True
        if not progress: raise ValueError('Skeleton contains a parent cycle')
    return world


def skin_positions(asset, world):
    positions = np.column_stack((asset.positions, np.ones(len(asset.positions), dtype=np.float32)))
    result = np.zeros((len(positions), 3), dtype=np.float32)
    for bone in asset.bones:
        transform = world[bone.native_id] @ np.linalg.inv(bone.bind_world)
        weight = np.sum(np.where(asset.bone_indices == bone.native_id, asset.bone_weights, 0), axis=1)
        mask = weight > 0
        if np.any(mask): result[mask] += (positions[mask] @ transform.T)[:, :3]*weight[mask, None]
    return np.ascontiguousarray(result)


class ModelViewport(QOpenGLWidget):
    frame_changed = Signal(float)
    failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        fmt = QSurfaceFormat()
        fmt.setVersion(2, 1)
        fmt.setProfile(QSurfaceFormat.CompatibilityProfile)
        fmt.setDepthBufferSize(24)
        fmt.setSamples(4)
        self.setFormat(fmt)
        self.setMinimumSize(420, 380)
        self.asset = self.clip = None
        self.positions = self.world = None
        self.textures = []
        self.dirty = False
        self.wireframe = self.skeleton = False
        self.show_grid = True
        self.follow_motion = True
        self.hidden_parts = set()
        self.playing = False
        self.loop = True
        self.speed = 1.0
        self.frame = 0.0
        self.last_clock = time.monotonic()
        self.yaw, self.pitch, self.distance = 0.0, 8.0, 50.0
        self.center = np.array([0., 10., 0.])
        self.pan = np.zeros(3)
        self.extent = 20.
        self.last_mouse = None
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.advance)
        self.timer.start(16)

    def set_asset(self, asset):
        self.asset, self.clip, self.playing = asset, None, False
        self.positions = np.ascontiguousarray(asset.positions, dtype=np.float32)
        self.world = {b.native_id: b.bind_world for b in asset.bones}
        self.hidden_parts.clear()
        display = self.positions*np.array([1, -1, -1])
        low, high = display.min(axis=0), display.max(axis=0)
        self.center = (low+high)/2
        self.extent = max(float(np.max(high-low)), 1.)
        self.floor = float(low[1])
        self.dirty = True
        self.reset_camera()

    def reset_camera(self):
        if self.positions is not None:
            display = self.positions*np.array([1, -1, -1])
            low, high = display.min(axis=0), display.max(axis=0)
            self.center = (low+high)/2
        self.yaw, self.pitch, self.distance = 0., 8., self.extent*2.1
        self.pan = np.zeros(3)
        self.update()

    def set_clip(self, clip):
        self.clip = clip
        self.set_frame(0)

    def set_frame(self, frame):
        if self.asset is None: return
        self.frame = float(frame)
        try:
            if self.clip:
                self.world = pose_matrices(self.asset.bones, self.clip.evaluate(frame))
                self.positions = skin_positions(self.asset, self.world)
            else:
                self.positions = np.ascontiguousarray(self.asset.positions, dtype=np.float32)
                self.world = {b.native_id: b.bind_world for b in self.asset.bones}
            if self.follow_motion:
                display = self.positions*np.array([1, -1, -1])
                self.center = (display.min(axis=0)+display.max(axis=0))/2
            self.frame_changed.emit(self.frame)
        except Exception as error:
            self.playing = False
            self.failed.emit(str(error))
        self.update()

    def advance(self):
        now = time.monotonic()
        dt, self.last_clock = min(now-self.last_clock, .1), now
        if self.playing and self.clip:
            fps = self.clip.frame_count / max(self.clip.duration_seconds, .001)
            frame = self.frame+dt*fps*self.speed
            # Native frame_count is the final key time, not an array length.
            end = max(1, self.clip.frame_count)
            if frame > end:
                if self.loop: frame %= end
                else: frame, self.playing = float(end), False
            self.set_frame(frame)

    def initializeGL(self):
        gl.glClearColor(5/255, 5/255, 5/255, 1)
        gl.glEnable(gl.GL_DEPTH_TEST)
        gl.glDisable(gl.GL_CULL_FACE)
        gl.glEnable(gl.GL_BLEND)
        gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA)
        gl.glEnable(gl.GL_ALPHA_TEST)
        gl.glAlphaFunc(gl.GL_GREATER, .12)

    def upload_textures(self):
        if self.textures: gl.glDeleteTextures(self.textures)
        self.textures = []
        for texture in self.asset.textures:
            index = int(gl.glGenTextures(1))
            self.textures.append(index)
            rgba = np.ascontiguousarray(texture.rgba, dtype=np.uint8)
            gl.glBindTexture(gl.GL_TEXTURE_2D, index)
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_LINEAR)
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_LINEAR)
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_S, gl.GL_REPEAT)
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_T, gl.GL_REPEAT)
            gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_RGBA, rgba.shape[1], rgba.shape[0], 0,
                            gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, rgba)
        self.dirty = False

    def paintGL(self):
        gl.glClear(gl.GL_COLOR_BUFFER_BIT | gl.GL_DEPTH_BUFFER_BIT)
        gl.glMatrixMode(gl.GL_PROJECTION)
        gl.glLoadIdentity()
        gluPerspective(35., self.width()/max(1, self.height()), .05, max(10000., self.distance*10))
        gl.glMatrixMode(gl.GL_MODELVIEW)
        gl.glLoadIdentity()
        target = self.center + getattr(self, 'pan', np.zeros(3))
        yaw, pitch = math.radians(self.yaw), math.radians(self.pitch)
        eye = target + self.distance*np.array([math.sin(yaw)*math.cos(pitch), math.sin(pitch), math.cos(yaw)*math.cos(pitch)])
        gluLookAt(*eye, *target, 0, 1, 0)
        if self.show_grid:
            gl.glDisable(gl.GL_TEXTURE_2D)
            step = max(1., self.extent/5)
            floor = getattr(self, 'floor', 0)-.03
            gl.glBegin(gl.GL_LINES)
            for i in range(-20, 21):
                gl.glColor4f(0, .65 if i % 5 else 1, .25, .22 if i % 5 else .5)
                gl.glVertex3f(i*step, floor, -20*step); gl.glVertex3f(i*step, floor, 20*step)
                gl.glVertex3f(-20*step, floor, i*step); gl.glVertex3f(20*step, floor, i*step)
            gl.glEnd()
        if self.asset is None: return
        if self.dirty: self.upload_textures()
        gl.glPushMatrix()
        gl.glScalef(1, -1, -1)
        gl.glEnableClientState(gl.GL_VERTEX_ARRAY)
        gl.glEnableClientState(gl.GL_TEXTURE_COORD_ARRAY)
        gl.glVertexPointer(3, gl.GL_FLOAT, 0, self.positions)
        uv = np.ascontiguousarray(self.asset.uv, dtype=np.float32)
        gl.glTexCoordPointer(2, gl.GL_FLOAT, 0, uv)
        gl.glColor4f(1, 1, 1, 1)
        gl.glPolygonMode(gl.GL_FRONT_AND_BACK, gl.GL_LINE if self.wireframe else gl.GL_FILL)
        for i, material in enumerate(self.asset.materials):
            mask = self.asset.triangle_materials == i
            if self.hidden_parts:
                mask &= ~np.isin(self.asset.triangle_bones, list(self.hidden_parts))
            triangles = np.ascontiguousarray(self.asset.triangles[mask], dtype=np.uint32)
            if not len(triangles): continue
            if not self.wireframe and 0 <= material.texture_index < len(self.textures):
                gl.glEnable(gl.GL_TEXTURE_2D)
                gl.glBindTexture(gl.GL_TEXTURE_2D, self.textures[material.texture_index])
            else: gl.glDisable(gl.GL_TEXTURE_2D)
            gl.glDrawElements(gl.GL_TRIANGLES, triangles.size, gl.GL_UNSIGNED_INT, triangles)
        gl.glPolygonMode(gl.GL_FRONT_AND_BACK, gl.GL_FILL)
        gl.glDisableClientState(gl.GL_TEXTURE_COORD_ARRAY)
        gl.glDisableClientState(gl.GL_VERTEX_ARRAY)
        gl.glDisable(gl.GL_TEXTURE_2D)
        if self.skeleton:
            gl.glDisable(gl.GL_DEPTH_TEST)
            gl.glColor4f(0, 1, .25, .8)
            gl.glBegin(gl.GL_LINES)
            for bone in self.asset.bones:
                if bone.parent_id in self.world:
                    gl.glVertex3fv(self.world[bone.native_id][:3, 3])
                    gl.glVertex3fv(self.world[bone.parent_id][:3, 3])
            gl.glEnd()
            gl.glEnable(gl.GL_DEPTH_TEST)
        gl.glPopMatrix()

    def mousePressEvent(self, event): self.last_mouse = event.position()
    def mouseReleaseEvent(self, event): self.last_mouse = None
    def mouseMoveEvent(self, event):
        if self.last_mouse is None: return
        delta = event.position()-self.last_mouse
        self.last_mouse = event.position()
        if event.buttons() & Qt.LeftButton:
            self.yaw += delta.x()*.4
            self.pitch = max(-85., min(85., self.pitch+delta.y()*.4))
        elif event.buttons() & (Qt.RightButton | Qt.MiddleButton):
            self.pan += np.array([-delta.x(), delta.y(), 0])*self.distance/1000
        self.update()
    def wheelEvent(self, event):
        self.distance = max(self.extent*.2, min(self.extent*20, self.distance*math.exp(-event.angleDelta().y()/1200)))
        self.update()
