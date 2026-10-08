"""Bounded generated-file retention, only in an installer-owned player profile.

Never touches user states/cards or a developer folder. Prior checkpoint archives
referenced by trainer slot receipts are retained so slot ownership remains provable.
"""
import json
import re
import runtime_profile
import shutil
import stat
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def remove_run(run,marker):
    """Delete one generated run, its marker file last: a run that is only partly deleted (a
    file locked by antivirus or OneDrive) keeps its marker and is tried again next launch."""
    for path in sorted(run.rglob('*'),key=lambda p:len(p.parts),reverse=True):
        if path==run/marker:continue
        if path.is_dir() and not path.is_symlink():path.rmdir()
        else:path.unlink()
    (run/marker).unlink();run.rmdir()


def prune(root=ROOT,keep=3,failed=None):
    """Delete all but the newest `keep` generated runs; return the removed folders.

    Housekeeping only: a run that cannot be deleted (a locked file) is skipped and, when
    `failed` is a list, recorded there as {'path','error'}; it never stops Play (L8)."""
    if type(keep)is not int or keep<1:raise ValueError('Keep at least one generated session')
    root=Path(root).resolve()
    marker=root/'player-install.json'
    if not marker.is_file() or json.loads(marker.read_text()).get('storage_policy')!=1:return []
    protected=set()
    for runtime in ('runtime128','runtime28'):
        # PCSX2's data folder: the runtime folder on Windows, runtime/PCSX2 for the Linux AppImage.
        for claim in (runtime_profile.data_directory(root/runtime)/'sstates').glob('*.trainer-claim.json'):
            try:
                item=json.loads(claim.read_text())
                if 'archive' not in item:continue  # a claim without a receipt protects no run
                protected.add(Path(item['archive']).resolve().parent)
            except (OSError,ValueError,KeyError,TypeError,AttributeError):return [] # uncertain ownership: keep all
    removed=[]
    for relative,required in (('analysis/prepared-states','session.json'),('analysis/autopilot','status.json')):
        parent=(root/relative).resolve()
        if not parent.is_relative_to(root) or not parent.exists():continue
        runs=sorted((p for p in parent.iterdir() if re.fullmatch(r'\d{8}-\d{6}-[0-9a-f]{8}',p.name)
                     and p.is_dir() and not p.is_symlink() and (p/required).is_file()),
                    key=lambda p:p.stat().st_mtime,reverse=True)
        for run in runs[keep:]:
            actual=run.resolve()
            if actual.parent!=parent or actual in protected:continue
            # Do not traverse junctions introduced into a generated run.
            def reparse(path):
                return path.is_symlink() or bool(getattr(path.lstat(),'st_file_attributes',0)&stat.FILE_ATTRIBUTE_REPARSE_POINT)
            if reparse(run) or any(reparse(p) for p in run.rglob('*')):continue
            try:remove_run(actual,required)
            except OSError as error:
                if failed is not None:failed.append(dict(path=str(actual),error=str(error)))
                continue
            removed.append(str(actual))
    return removed


KEPT=('Kept {count} old generated folder(s) that could not be deleted now (a file is in use); they are tried again '
      'at the next launch.')


def main():
    """Always exit 0: retention is housekeeping and never blocks Play (L8)."""
    failed=[]
    try:removed=prune(failed=failed)
    except Exception as error:  # noqa: BLE001 - a damaged marker or claim folder: keep everything
        removed=[];failed.append(dict(path=str(ROOT),error=str(error) or type(error).__name__))
    print(json.dumps(dict(removed=removed,failed=failed)))
    if failed:
        try:
            import localization
            print(localization.tr(KEPT,count=len(failed)))
        except Exception:  # noqa: BLE001 - never blocks Play: English then
            print(KEPT.format(count=len(failed)))
    return 0


if __name__=='__main__':raise SystemExit(main())
