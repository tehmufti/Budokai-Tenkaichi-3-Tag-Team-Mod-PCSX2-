"""Synthetic UI/contract fixtures: no disc, BIOS, emulator or captured memory."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'bt3-multifighter/online/netplay'))
import kit_catalog


def ui_available():
    if os.name != 'nt' and not (os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY')):
        return False
    import tkinter as tk
    try:
        root = tk.Tk()
        root.withdraw()
        root.destroy()
        return True
    except tk.TclError:
        return False


def catalog():
    return kit_catalog.View(dict(dir='', tables_sha256='a'*64,
        characters=[dict(id=c, name='Test Fighter '+str(c), selectable=True, costumes=2,
                         portrait='', forms=[c]) for c in (0,54)],
        stages=[dict(id=0,name='Test Stage',thumb='',tested=True)],
        potaras=dict(slots=8,points=7,items=[
            dict(id=i,name=name,cost=cost,kind=kind,group=group,stats=stats,effects='00'*16)
            for i,name,cost,kind,group,stats in (
                (1,'Test attack small',2,0,0,[5,0,0,0]),
                (2,'Test attack large',4,0,0,[15,0,0,0]),
                (5,'Test defense',4,0,1,[0,15,0,0]),
                (124,'Test Training',3,1,34,[0,0,0,0]),
                (137,'Test CPU style',0,2,0,[0,0,0,0]),
                (138,'Another CPU style',0,2,0,[0,0,0,0]))])))
