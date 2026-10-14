"""Keyboard editing, capture cancellation, tester and small-window layout."""
import tkinter as tk
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import keyboard_bindings as k
import keyboard_controls_ui as ui

class EditorTests(unittest.TestCase):
    def setUp(self):
        try:self.root=tk.Tk()
        except tk.TclError:self.skipTest('Tk display unavailable')
        self.root.geometry('180x80');self.errors=[];self.root.report_callback_exception=lambda *error:self.errors.append(error)
        self.editor=ui.KeyboardEditor(self.root,k.DEFAULT,online=True)
        self.editor.window.update()
        self.addCleanup(self.cleanup)
    def cleanup(self):
        try:self.root.destroy()
        except tk.TclError:pass
        self.assertFalse(self.errors)
    def event(self,key):return SimpleNamespace(keysym=key,keycode=0)
    def test_capture_save_and_cancel_leave_other_controls_intact(self):
        self.editor.capture('Square');self.editor.window.update()
        self.editor.key_press(self.event('z'))
        self.assertEqual(self.editor.values()['Square'],'Z');self.assertEqual(self.editor.values()['Cross'],'Space')
        self.editor.capture('Cross');self.editor.window.update();self.editor.key_press(self.event('Escape'))
        self.assertEqual(self.editor.values()['Cross'],'Space');self.assertTrue(self.editor.window.winfo_exists())
        self.editor.save();self.assertEqual(self.editor.result['Square'],'Z')
    def test_keyboard_activation_waits_for_release(self):
        self.editor.capture_from_key('Square')
        self.editor.key_press(self.event('Return'));self.assertEqual(self.editor.values()['Square'],'J')
        self.editor.key_release(self.event('Return'));self.editor.key_press(self.event('x'))
        self.assertEqual(self.editor.values()['Square'],'X')
    def test_reserved_online_keys_are_rejected_and_capture_continues(self):
        self.editor.capture('Cross');self.editor.window.update();self.editor.key_press(self.event('Pause'))
        self.assertEqual(self.editor.values()['Cross'],'Space');self.assertEqual(self.editor.pending,'Cross')
        self.editor.key_press(self.event('c'));self.assertEqual(self.editor.values()['Cross'],'C')
    def test_tester_does_not_rebind(self):
        before=self.editor.values();self.editor.test_keys();self.editor.key_press(self.event('w'))
        self.assertIn('LUp',self.editor.status.get());self.assertEqual(self.editor.values(),before)
        self.editor.key_press(self.event('Escape'));self.assertFalse(self.editor.testing)
    def test_small_window_keeps_actions_and_scrollbar_accessible(self):
        self.editor.window.geometry('480x400');self.editor.window.update()
        widgets=[]
        def children(widget):
            for child in widget.winfo_children():widgets.append(child);children(child)
        children(self.editor.window)
        save=next(w for w in widgets if isinstance(w,ui.ttk.Button) and w.cget('text')=='Save')
        self.assertTrue(save.winfo_ismapped())
        self.assertLessEqual(save.winfo_rooty()+save.winfo_height(),self.editor.window.winfo_rooty()+self.editor.window.winfo_height())
        self.assertTrue(any(isinstance(w,ui.ttk.Scrollbar) and w.winfo_ismapped() for w in widgets))
    def test_spanish_labels_and_cancel(self):
        self.editor.close();self.editor=ui.KeyboardEditor(self.root,k.DEFAULT,language='es',online=True)
        self.assertEqual(self.editor.window.title(),'Asignación de teclas')
        self.editor.variables['Cross'].set('C');self.editor.close();self.assertIsNone(self.editor.result)
    def test_failed_save_keeps_draft(self):
        self.editor.on_save=lambda _:(_ for _ in ()).throw(OSError('read-only test'))
        with patch.object(ui.messagebox,'showerror') as message:self.editor.save()
        message.assert_called_once();self.assertTrue(self.editor.window.winfo_exists());self.assertIsNone(self.editor.result)

if __name__=='__main__':unittest.main()
