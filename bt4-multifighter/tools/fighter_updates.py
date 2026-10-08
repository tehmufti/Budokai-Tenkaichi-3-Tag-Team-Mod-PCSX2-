"""Serialize body exchanges and extra form/costume reloads for one match.

An acknowledged extra form transaction must finish first. Once Body Change
captures its pair, no new extra resource IO starts until that pair is released.
The same extra worker survives a body exchange: it owns loaded resource receipts
and must not forget them while its native stage remains installed.
"""


def attach_body(p, progress=None, **options):
    """Attach the serial body worker; options are Worker keyword arguments
    (for example stuck_frames, or injected read_ram/apply/quiet/resume)."""
    import body_swap_worker
    worker = body_swap_worker.Worker(progress=progress, **options)
    if p.read_u32(body_swap_worker.body.CONTROL)==0:
        worker.attach(p)
        return worker
    native=body_swap_worker.native
    held=p.read_u32(native.CONTROL+16)==1 and p.read_u32(native.CONTROL+20)==1
    if not held:worker.quiet(p)
    _claim(worker,p,held)
    if not held:worker.resume(p)
    return worker


def _claim(worker, p, held):
    """worker.attach under the hold. A refusal (ValueError) is raised before any guest
    write, so the hold this call took is released and the match goes on. Any other
    failure is terminal: never release an uncertain installation or claim."""
    try:
        worker.attach(p)
    except ValueError:
        if not held:worker.resume(p)
        raise


def attach_fusion(p, progress=None, **options):
    """Claim the optional duration service under the native preparation hold."""
    import fusion_duration_worker as duration
    if p.read_u32(duration.timer.CONTROL)==0:
        return None
    worker=duration.Worker(progress=progress, **options)
    held=p.read_u32(duration.native.CONTROL+16)==1 and p.read_u32(duration.native.CONTROL+20)==1
    if not held:worker.quiet(p)
    _claim(worker,p,held)
    if not held:worker.resume(p)
    return worker


def switch_off(p, *, quiet=None, resume=None, apply=None):
    """Fighter updates are off for the rest of this match (an attach was refused).

    With no host worker, a guest service that asks for one would hold combat for
    good: an expired fusion timer (fusion_duration.tick) or a captured Body Change
    (body_swap_runner). Under an acknowledged hold, turn off each such service that
    is idle: the timed fusion claim (its guest code runs only while claimed; fused
    fighters then keep their fusion) and Body Change's enable word (the native move
    plays instead). Extra transformations need nothing: their rows only hold combat
    once a host staged them, so unclaimed requests just wait. Returns the services
    that were mid-transaction and could not be turned off (the hold this call took is
    then kept); the caller treats those, and any error raised here, as a failure."""
    import body_swap_worker as shared
    import extra_reload_requests as requests
    import extra_reload_worker as extra
    import fusion_duration as timer
    native=shared.native
    body=shared.body
    runner=extra.runner
    quiet=quiet or native.quiet;resume=resume or native.resume;apply=apply or native.apply
    held=p.read_u32(native.CONTROL+16)==1 and p.read_u32(native.CONTROL+20)==1
    if not held:quiet(p)
    busy=[];blocks=[]
    if p.read_u32(timer.CONTROL)==timer.MAGIC and p.read_u32(timer.CONTROL+12):
        count=min(p.read_u32(timer.CONTROL+8),64)
        # Expiry (3) waits for a host; a guest failure (100 and up) keeps its hold. Only an
        # empty, accepted, counting down or defused record (0, 1, 2, 5) is idle.
        if any(p.read_u32(timer.RECORDS+i*timer.STRIDE) not in (0,1,2,5) for i in range(count)):busy.append('fusion')
        else:blocks.append(shared.live_block(p,timer.CONTROL+12,0))
    if p.read_u32(body.CONTROL)==body.MAGIC and p.read_u32(body.CONTROL+20)==1:
        if p.read_u32(body.CONTROL+16):busy.append('body_change')
        else:blocks.append(shared.live_block(p,body.CONTROL+20,0))
    # A staged (3) or commit-requested (4) extra row holds combat until its host commits.
    rows=range(max(0,min(p.read_u32(requests.CONTROL+8),64)-2))
    if (p.read_u32(runner.CONTROL+4)!=p.read_u32(runner.CONTROL+8) or
            p.read_u32(runner.BG_CONTROL+4)!=p.read_u32(runner.BG_CONTROL+8) or
            any(p.read_u32(requests.RECORDS+i*requests.STRIDE+4) in (3,4) for i in rows)):busy.append('transformation')
    # One guarded transaction; a guest that rejects it wrote nothing. An error here
    # leaves the hold in place for the caller's failure path.
    if blocks:apply(p,dict(blocks=blocks))
    if not held and not busy:resume(p)
    return busy


def poll(p, extra, body, fusion=None):
    if extra.failure:
        raise RuntimeError(extra.failure)
    if body is not None and body.failure:
        raise RuntimeError(body.failure)
    if fusion is not None and fusion.failure:
        raise RuntimeError(fusion.failure)
    if extra.form_job is not None:
        extra.poll(p)
    else:
        if fusion is not None:
            fusion.poll(p,reload_worker=extra,body_worker=body)
            if fusion.failure:
                raise RuntimeError(fusion.failure)
            if fusion.busy:return
        if body is not None:
            body.poll(p, reload_worker=extra)
            if body.failure:
                raise RuntimeError(body.failure)
        if body is None or not body.busy:
            extra.poll(p)
    if extra.failure:
        raise RuntimeError(extra.failure)


def poll_delay(extra,body,fusion,ordinary):
    """Short sleeps only while a serial guest transaction needs acknowledgement.

    An extra's transformation disc read now runs unheld for well over a second
    with combat dispatching normally. Polling that at10ms would open ~170 PINE
    cycles, each with a full preflight, during live play; the acknowledgement
    that really needs a short sleep only begins once the row reaches3/4.
    """
    if extra is not None and getattr(extra,'form_phase',None)=='io':
        return min(ordinary,.05)
    busy=(extra is not None and extra.form_job is not None) or any(
        worker is not None and worker.busy for worker in (body,fusion))
    return min(ordinary,.01) if busy else ordinary
