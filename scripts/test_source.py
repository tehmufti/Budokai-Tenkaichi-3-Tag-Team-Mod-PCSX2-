"""Run portable tests without an emulator, BIOS, game ISO or private capture."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def run(arguments):
    result = subprocess.run([sys.executable,'-B',*arguments], cwd=ROOT)
    if result.returncode:
        raise SystemExit(result.returncode)

if __name__ == '__main__':
    run(['-m','unittest','discover','-s','bt3-multifighter/tools','-p','test_*.py'])
    run(['-m','unittest','discover','-s','player-installer','-p','test_*.py'])
    run(['-m','unittest','discover','-s','iso_compatibility','-t','.','-p','test_*.py'])
    for name in ('test_rooms.py','test_loading_policy.py','test_version_numbering.py','test_bot_intro_gates.py','test_scenario_queue_isolation.py'):
        run(['release_tools/online-next/'+name])
    run(['-m','unittest','discover','-s','release_tools/online-startup','-p','test_*.py'])
