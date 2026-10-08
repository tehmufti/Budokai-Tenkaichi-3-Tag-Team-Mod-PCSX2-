"""Host-side transaction ordering; no emulator or resource IO is opened."""
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import fighter_updates
from native_map import elf_path

HAS_NATIVE_REFERENCE = elf_path(Path(__file__).resolve().parents[1]).is_file()


class SchedulingTests(unittest.TestCase):
    def workers(self, *, busy=False, form=None):
        events = []
        extra = SimpleNamespace(failure=None, form_job=form)
        body = SimpleNamespace(failure=None, busy=busy)
        extra.poll = Mock(side_effect=lambda p: events.append('extra'))
        body.poll = Mock(side_effect=lambda p, reload_worker: events.append('body'))
        return extra, body, events

    def test_active_transactions_poll_quickly_without_busy_idle_spinning(self):
        extra,body,_=self.workers();fusion=SimpleNamespace(busy=False)
        self.assertEqual(fighter_updates.poll_delay(extra,body,fusion,.2),.2)
        for active in ('form','body','fusion'):
            extra.form_job=object() if active=='form' else None
            body.busy=active=='body';fusion.busy=active=='fusion'
            self.assertEqual(fighter_updates.poll_delay(extra,body,fusion,.2),.01)
            self.assertEqual(fighter_updates.poll_delay(extra,body,fusion,.005),.005)
        self.assertEqual(fighter_updates.poll_delay(None,None,None,.15),.15)

    def test_an_unheld_background_read_relaxes_the_cadence_and_keeps_the_routing(self):
        extra,body,events=self.workers(busy=True,form=object())
        extra.form_phase='io';fusion=Mock(failure=None,busy=True)
        self.assertEqual(fighter_updates.poll_delay(extra,body,fusion,.2),.05)
        self.assertEqual(fighter_updates.poll_delay(extra,body,fusion,.02),.02)
        fighter_updates.poll('guest',extra,body,fusion)
        self.assertEqual(events,['extra'])
        fusion.poll.assert_not_called();body.poll.assert_not_called()
        extra.form_phase='commit'
        self.assertEqual(fighter_updates.poll_delay(extra,body,fusion,.2),.01)

    def test_body_claim_prevents_new_extra_io(self):
        extra, body, events = self.workers()
        def claim(p, reload_worker):
            self.assertIs(reload_worker, extra)
            events.append('body'); body.busy = True
        body.poll.side_effect = claim
        fighter_updates.poll('guest', extra, body)
        self.assertEqual(events, ['body'])

    def test_acknowledged_extra_form_finishes_before_body_can_hold(self):
        extra, body, events = self.workers(busy=True, form=object())
        fighter_updates.poll('guest', extra, body)
        self.assertEqual(events, ['extra'])

    def test_released_body_allows_same_extra_owner_to_continue(self):
        extra, body, events = self.workers(busy=True)
        def release(p, reload_worker):
            self.assertIs(reload_worker, extra)
            events.append('body'); body.busy = False
        body.poll.side_effect = release
        fighter_updates.poll('guest', extra, body)
        self.assertEqual(events, ['body', 'extra'])

    def test_legacy_checkpoint_without_body_service_keeps_extra_updates(self):
        extra, _, events = self.workers()
        fighter_updates.poll('guest', extra, None)
        self.assertEqual(events, ['extra'])

    def test_defusion_does_not_interrupt_an_acknowledged_form_reload(self):
        extra,body,events=self.workers(form=object())
        fusion=Mock(failure=None,busy=True)
        fighter_updates.poll('guest',extra,body,fusion)
        self.assertEqual(events,['extra']);fusion.poll.assert_not_called()

    def test_defusion_claim_blocks_body_and_extra_until_complete(self):
        extra,body,events=self.workers()
        fusion=Mock(failure=None,busy=True)
        fighter_updates.poll('guest',extra,body,fusion)
        fusion.poll.assert_called_once_with('guest',reload_worker=extra,body_worker=body)
        self.assertEqual(events,[])
        fusion.busy=False
        fighter_updates.poll('guest',extra,body,fusion)
        self.assertEqual(events,['body','extra'])

    def test_failed_defusion_blocks_all_other_transactions(self):
        for prior in (True,False):
            extra,body,events=self.workers()
            fusion=Mock(failure='uncertain defusion' if prior else None,busy=False)
            fusion.poll.side_effect=lambda *a,**kw:setattr(fusion,'failure','uncertain defusion')
            with self.assertRaisesRegex(RuntimeError,'uncertain defusion'):
                fighter_updates.poll('guest',extra,body,fusion)
            self.assertEqual(events,[])

    @unittest.skipUnless(HAS_NATIVE_REFERENCE, 'Requires locally extracted native executable')
    def test_optional_defusion_attach_never_holds_a_disabled_match(self):
        client=Mock();client.read_u32.return_value=0
        self.assertIsNone(fighter_updates.attach_fusion(client))
        client.write.assert_not_called()

    def test_failed_body_cannot_allow_another_transaction(self):
        extra, body, events = self.workers()
        def fail(p, reload_worker):
            events.append('body'); body.failure = 'uncertain body commit'
        body.poll.side_effect = fail
        with self.assertRaisesRegex(RuntimeError, 'uncertain body commit'):
            fighter_updates.poll('guest', extra, body)
        self.assertEqual(events, ['body'])

    def test_any_prior_failure_stops_all_new_work(self):
        for owner in ('extra', 'body'):
            extra, body, events = self.workers()
            setattr(extra if owner == 'extra' else body, 'failure', 'previous transaction failed')
            with self.subTest(owner=owner), self.assertRaisesRegex(RuntimeError, 'previous transaction failed'):
                fighter_updates.poll('guest', extra, body)
            self.assertEqual(events, [])

    def test_failure_reported_by_extra_is_terminal(self):
        extra, body, _ = self.workers()
        extra.poll.side_effect = lambda p: setattr(extra, 'failure', 'extra commit failed')
        with self.assertRaisesRegex(RuntimeError, 'extra commit failed'):
            fighter_updates.poll('guest', extra, body)

    @unittest.skipUnless(HAS_NATIVE_REFERENCE, 'Requires locally extracted native executable')
    def test_real_worker_objects_idle_ordering_and_attach_options(self):
        """Real Worker instances (no SimpleNamespace) on a tiny fake client.

        The body worker reads status 0 (idle) and the extra worker sees the
        acknowledged hold, so both return without work; the order and the
        attach keyword pass-through are what this checks. The full exchange
        with real workers is test_body_swap_worker.
        """
        import struct
        import body_swap as bodymod
        import body_swap_worker
        import extra_reload_worker
        import native_preparation as native

        class Client:
            def __init__(self): self.ram = {}; self.reads = []
            def read_u32(self, p): self.reads.append(p); return self.ram.get(p, 0)
            def read(self, p, n): return bytes(n)
            def write_u32(self, p, v): self.ram[p] = v
            def write(self, p, d): pass
        p = Client(); p.ram[native.CONTROL+16] = 1
        body = body_swap_worker.Worker(read_ram=lambda c: b'', stuck_frames=7)
        self.assertEqual(body.stuck_frames, 7); self.assertFalse(body.attach(p))   # magic 0: legacy checkpoint
        extra = extra_reload_worker.Worker(read_ram=lambda c: b''); extra.active = True
        order = []
        real_body, real_extra = body.poll, extra.poll
        body.poll = lambda c, reload_worker=None: (order.append('body'), real_body(c, reload_worker=reload_worker))[1]
        extra.poll = lambda c: (order.append('extra'), real_extra(c))[1]
        fighter_updates.poll(p, extra, body)
        self.assertEqual(order, ['body', 'extra']); self.assertFalse(body.busy)
        with self.assertRaises(TypeError): fighter_updates.attach_body(p, unknown_option=1)
        p.ram[bodymod.CONTROL] = 0
        self.assertFalse(fighter_updates.attach_body(p, stuck_frames=9).active)


if __name__ == '__main__': unittest.main()
