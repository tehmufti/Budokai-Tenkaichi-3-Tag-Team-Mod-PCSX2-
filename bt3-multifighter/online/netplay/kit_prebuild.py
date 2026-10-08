"""Prepare a settled lobby choice in the background, without starting a match.

Only the host's private preparation copy is used. The cache remains keyed by
the complete match spec and test options; member names, Ready votes and seat
owners are never captured. Start still computes its current seats and commits
the match through FightMixin's existing guarded path.
"""
import json
import time

import kit_match
import kit_spec

SETTLE_SECONDS = 1.5
BUSY_JOBS = ('warm', 'prep', 'suspend', 'prebuild')
ALLOWED_SERVICES = ('cpu_transform',)


def choice_key(spec, options):
    """Exactly the existing prepared-cache identity, including human/CPU slots."""
    return (kit_spec.spec_sha(spec), json.dumps(options or None, sort_keys=True,
                                               separators=(',', ':'), ensure_ascii=True))


class PrebuildMixin:
    def init_prebuild(self):
        self.prebuild = None
        self.prebuild_choice = None
        self.prebuild_changed_at = None
        self.prebuild_generation = 0             # independent of committed prep_gen
        self.prebuild_failed_choice = None

    def _prebuild_lobby_choice(self):
        if self.role != 'host' or self.phase != 'lobby' or self.lobby is None or \
                self.lobby.phase != 'lobby' or self.prep is None or not self.local:
            return None
        try:
            spec = self.lobby.spec(self.local['catalog']['tables_sha256'],
                                   mod_build=(self.local.get('install') or {}).get('version'))
            # No random choices are resolved on speculation, and invalid picks
            # are left for the ordinary Start validation to explain.
            if spec is None or type(spec.get('stage')) is not int or type(spec.get('bgm')) is not int:
                return None
            kit_spec.validate(spec, self.local['view'], ALLOWED_SERVICES)
            options = dict(self.test_prep) if self.args.test_hooks and self.test_prep else None
            # Freeze the exact values before another lobby edit can mutate them.
            spec = json.loads(kit_spec.canonical(spec))
            options = json.loads(json.dumps(options))
            return dict(key=choice_key(spec, options), spec=spec, options=options,
                        title=kit_spec.title(spec, self.local['view']))
        except (KeyError, TypeError, ValueError):
            return None
        except Exception as error:
            from kit_codes import KitError
            if isinstance(error, KitError):
                return None
            raise

    def tick_prebuild(self, at=None):
        at = time.monotonic() if at is None else at
        choice = self._prebuild_lobby_choice()
        key = choice['key'] if choice is not None else None
        if key != self.prebuild_choice:
            self.prebuild_generation += 1
            self.prebuild_choice = key
            self.prebuild_changed_at = at if choice is not None else None
            self.prebuild_failed_choice = None
        if choice is None or self.prebuild_changed_at is None or \
                at - self.prebuild_changed_at < SETTLE_SECONDS or key == self.prebuild_failed_choice:
            return
        # Retain finished captures in the existing verified on-disk cache.
        # Publishing one is optional and must never commit/start its match.
        record = self.prebuild
        if record is not None and record['key'] == key and record['prep'] is self.prep:
            if record.get('meta') is not None:
                self._publish_prebuild(record)
                return
            if self.busy('prebuild'):
                return
        if any(self.busy(name) for name in BUSY_JOBS) or self.prep.state not in ('warm', 'suspended'):
            return
        cached = kit_match.made_match(key[0], choice['options'])
        record = dict(choice, generation=self.prebuild_generation, prep=self.prep,
                      meta=cached, adopted=None, started=False, running=False, published=False)
        self.prebuild = record
        if cached is not None:
            self._publish_prebuild(record)
            return
        folder = kit_match.made_folder(key[0])
        self.say('Preparing the settled lobby choice in the background.')
        self.job('prebuild', self._prebuild_job, record, folder,
                 then=lambda meta, r=record: self._prebuild_done(r, meta),
                 fail=lambda error, r=record: self._prebuild_failed(r, error))

    def _prebuild_job(self, record, folder):
        import kit_prepare_auto
        prep = record['prep']
        # A queued speculative job never jumps ahead of warm-up or another
        # owner. Once an actual build starts, let it finish into its own cache
        # even if the lobby edits change; canceling disc IO would waste more.
        with prep.lock:
            adopted = self._prebuild_adoption_current(record)
            wanted = self.role == 'host' and self.phase == 'lobby' and \
                self.prebuild_generation == record['generation'] and self.prebuild_choice == record['key']
            if self.prebuild is not record or self.prep is not prep or not (wanted or adopted):
                raise kit_prepare_auto.Cancelled()
            prep.cancel.clear()
            record['started'] = True
            record['running'] = True
            try:
                return self._prepare_locked(prep, record['spec'], folder, record['options'], record['title'])
            finally:
                record['running'] = False

    def _prebuild_adoption_current(self, record):
        return record.get('adopted') is not None and record['adopted'] == self.prep_gen and \
            self.role == 'host' and self.phase == 'preparing' and self.prep is record['prep'] and \
            bool(self.match) and self.match.get('spec_sha') == record['key'][0]

    def adopt_prebuild(self, spec, options, currentprep_gen):
        """Attach Start to an exact running/completed build; never copy old seats."""
        record = self.prebuild
        if record is None or record['prep'] is not self.prep or record['key'] != choice_key(spec, options) or \
                self.phase != 'preparing' or self.role != 'host' or currentprep_gen != self.prep_gen or \
                not self.match or self.match.get('spec_sha') != record['key'][0]:
            return False
        if record.get('meta') is None and not self.busy('prebuild'):
            return False
        if record.get('adopted') == currentprep_gen:
            return True
        record['adopted'] = currentprep_gen
        self.say('Using the background preparation for this exact match.')
        if record.get('meta') is not None:
            self.auto_prepared(record['meta'], currentprep_gen)
        return True

    def _prebuild_done(self, record, meta):
        if not isinstance(meta, dict) or meta.get('spec_sha') != record['key'][0] or (meta.get('options') or None) != \
                (record['options'] or None):
            self._prebuild_failed(record, ValueError('Background preparation returned another match'))
            return
        record['meta'] = meta
        if self.prebuild is not record or self.prep is not record['prep']:
            return                            # stale output remains only in the verified disk cache
        if self._prebuild_adoption_current(record):
            self.auto_prepared(meta, record['adopted'])
        else:
            self._publish_prebuild(record)

    def _publish_prebuild(self, record):
        if record.get('published') or record.get('meta') is None or self.phase != 'lobby' or \
                self.role != 'host' or self.prep is not record['prep']:
            return
        # Re-read the current lobby rather than relying on its last 1.5s tick.
        current = self._prebuild_lobby_choice()
        if current is None or current['key'] != record['key']:
            return
        publish = getattr(self, 'publish_prebuild', None)
        if publish is not None:
            # A previous immutable state may still be compressing. Retry on a
            # later tick rather than losing the latest settled roster.
            record['published'] = publish(record['meta']) is not False

    def _prebuild_failed(self, record, error):
        if self.prebuild is not record or self.prep is not record['prep']:
            return
        if self._prebuild_adoption_current(record):
            self.auto_failed(error, record['adopted'])
            return
        # Failure cannot alter Ready, commit a match or flood retries. Start
        # remains free to try the usual preparation path after an explanation.
        self.prebuild_failed_choice = record['key']
        lines = str(error).splitlines()
        detail = lines[0] if lines else type(error).__name__
        self.say(f'Background preparation stopped; Start can try again: {detail}')

    def cancel_prebuild(self, cancel_running=False):
        """Invalidate ownership; only cancel IO belonging to this exact record."""
        record = self.prebuild
        self.prebuild_generation += 1
        self.prebuild_choice = None
        self.prebuild_changed_at = None
        self.prebuild_failed_choice = None
        self.prebuild = None
        if record is not None:
            record['adopted'] = None
            if cancel_running and record['prep'] is self.prep and record.get('running') and self.busy('prebuild'):
                record['prep'].cancel.set()
