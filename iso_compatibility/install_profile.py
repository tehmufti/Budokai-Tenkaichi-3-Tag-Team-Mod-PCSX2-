"""Prepare reviewed ISO references and artwork in a new trainer directory.

This is the automatic compatibility step for asset mods. It never invents
addresses for an unknown executable, edits an ISO, or connects to PCSX2.
"""
import json
import hashlib
from pathlib import Path
from .disc import Disc,require,package
from .scanner import scan,report,atomic_json
from .labels import unpack_bpe,english_label
from .adapters import BY_NAME


def prepare(iso,destination,cache,progress=print,tools=None):
    """Extract a disc's reference files into destination (a new game folder, or a Game disc staging folder).
    tools: the folder whose extract_loading_assets.py decodes the portraits (default: destination/tools)."""
    iso,destination,cache=Path(iso).resolve(),Path(destination).resolve(),Path(cache).resolve()
    require(not (destination/'game-profile.json').exists(),'Game profile already exists; use a new installation folder')
    profile=scan(iso,cache,progress=progress)
    audit=cache/(profile['identity']['iso_sha256']+'.md')
    audit.write_text(report(profile),encoding='utf-8')
    require(profile['capabilities']['runtime_hooks'],
            f'Executable/add-on is not supported by a reviewed runtime adapter. Resource report: {audit}')
    require(profile['summary']['base_fighters_valid']>0,'No valid base fighter resources were found')
    analysis=destination/'analysis';assets=destination/'assets'
    analysis.mkdir(parents=True,exist_ok=True);(assets/'portraits').mkdir(parents=True,exist_ok=True)
    adapter=BY_NAME[profile['identity']['adapter']]
    with Disc(iso) as disc:
        # The reference executable is the player's own, exactly as certified by the scan:
        # analysis/SLUS_216.78, or analysis/SLES_549.45 / SLPS_258.15 for the European / Japanese disc.
        require(disc.serial==adapter.serial and
                hashlib.sha256(disc.elf).hexdigest()==profile['identity']['members'].get(disc.boot),
                'Selected ISO changed during installation')
        (analysis/disc.serial).write_bytes(disc.elf)
        if disc.kind=='bt4-indexed':
            for name in ('DBZ4.BIN','DBZP.BIN'):(analysis/name).write_bytes(disc.member('/BIN/'+name+';1'))
            (analysis/'character-parameters.bin').write_bytes(disc.read(4))
        # English names, forms and portraits (the European disc holds five languages; 455 is English). The Japanese
        # disc's set names fighters in kanji/kana only: its English names ship with the tools (same roster order).
        raw=disc.read(adapter.ui_text_file)
        def parts(blob):return [blob[a:b]for a,b in package(blob)]
        ui=parts(unpack_bpe(parts(raw)[1]));names,forms,portraits=(parts(ui[i])for i in (29,30,31))
        english=None
        if adapter.text_language!='en':
            table=Path(tools or destination/'tools')/'bt3_english_names.json'
            require(table.is_file(),f'Missing English fighter names for this disc: {table}')
            english={row['character_id']:(row['base_name'],row['form'])
                     for row in json.loads(table.read_text(encoding='utf-8'))['characters']}
        # Reuse the reviewed GS swizzle decoder supplied in the player runtime.
        import importlib.util
        spec=importlib.util.spec_from_file_location('install_portraits',Path(tools or destination/'tools')/'extract_loading_assets.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        from PIL import Image
        rows=[]
        for cid in range(len(profile['layout']['costumes'])):
            if english is not None:
                base,form=english.get(cid,(f'Character {cid}',''))
            else:
                base=english_label(names[cid]) if cid<len(names) else f'Character {cid}'
                form=english_label(forms[cid]) if cid<len(forms) else ''
            row=dict(character_id=cid,name=base+(' - '+form if form else ''),base_name=base,form=form,
                     portrait=f'portraits/{cid:03d}.png',bitmap=f'portraits/{cid:03d}.bmp')
            if cid<len(portraits) and portraits[cid]:
                image=Image.frombytes('RGBA',(64,64),module.portrait_rgba(portraits[cid]))
                image.save(assets/row['portrait'])
                canvas=Image.new('RGB',image.size,(17,24,39));canvas.paste(image,mask=image.getchannel('A'))
                canvas.save(assets/row['bitmap'])
            rows.append(row)
        atomic_json(assets/'characters.json',dict(source=str(iso),source_sha256=hashlib.sha256(raw).hexdigest(),characters=rows))
    record=dict(schema=1,iso=str(iso),adapter=profile['identity']['adapter'],
                iso_sha256=profile['identity']['iso_sha256'],members=profile['identity']['members'],
                serial=profile['identity']['serial'],pcsx2_crc=profile['identity']['pcsx2_crc'],
                runtime_variant=profile['identity']['runtime_match']['variant'],audit=str(audit),gameplay_verified=False)
    atomic_json(destination/'game-profile.json',record)
    (destination/'COMPATIBILITY.md').write_text(report(profile),encoding='utf-8')
    progress(f"Prepared {len(rows)} character/form labels and portraits; compatibility report: {audit}")
    return record
