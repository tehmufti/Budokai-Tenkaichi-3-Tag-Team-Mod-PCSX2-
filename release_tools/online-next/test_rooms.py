import json
from pathlib import Path
import socket
import sys
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'bt3-multifighter/online/netplay'), str(ROOT)]
import kit_browser as browser
import kit_controller as controller
import kit_directory
import kit_hub
import kit_ident
import kit_lobby
import kit_net
import kit_spec
import kit_verify


class Rooms(unittest.TestCase):
    def test_every_team_size_and_physical_seat(self):
        for a in range(1, 6):
            for b in range(1, 6):
                with self.subTest(a=a, b=b):
                    self.assertEqual(kit_spec.layout_problems('teams', [a, b]), [])
                    teams = [[(0, 0, 2*i+s) for i in range(n)] for s, n in enumerate((a, b))]
                    spec = kit_spec.make(tables_sha256='a'*64, teams=teams, stage=0)
                    self.assertEqual(kit_spec.human_problems(spec), [])
                    self.assertEqual(kit_spec.slot_mask(spec), sum(1<<(2*i+s) for s, n in enumerate((a,b)) for i in range(n)))
                    self.assertEqual(kit_verify.engine_count(spec), max(4, 2*max(a,b)))

    def test_invalid_sizes(self):
        for sizes in ([0,1], [6,1], [-1,2], ['1',2], [True,2]):
            self.assertTrue(kit_spec.layout_problems('teams', sizes))

    def handshake(self, entered):
        host = controller.Controller.__new__(controller.Controller)
        host.args = SimpleNamespace(timeout=3, ui='tk')
        host.role, host.cfg, host.profile, host.lang = 'host', {}, {'name':'Host'}, 'en'
        host.local = dict(identity={}, catalog=dict(family='bt3',disc='bt3-usa',tables_sha256='a'*64))
        host.lobby = kit_lobby.Lobby()
        host.room_salt, host.room_key = browser.challenge('secret')
        left, right = socket.socketpair()
        h, g = kit_net.Channel(left, 'local-host'), kit_net.Channel(right, 'local-guest')
        failures = []
        def work():
            try:
                host.host_handshake(h, ('127.0.0.1', 1))
            except Exception as error:
                failures.append(error)
            finally:
                h.close_soon()
        with patch.object(kit_ident, 'compare', return_value=[]):
            worker = threading.Thread(target=work)
            worker.start()
            g.send_preamble(kit_ident.PROTOCOL)
            self.assertEqual(g.read_preamble(3), kit_ident.PROTOCOL)
            hello = g.expect('HELLO', 3, 'host')
            auth = hello['auth']
            response = browser.proof(browser.password_key(entered, auth['salt']), auth['nonce'])
            g.send_json(type='HELLO', identity={}, lobby={'catalog':host.local['catalog']}, request={}, password_proof=response)
            kind, answer = g.receive(3)
            if answer['type'] == 'ACCEPT':
                g.send_json(type='RTT', rtt=dict(min=1, median=2, p95=3))
            worker.join(4)
        g.close_soon()
        self.assertFalse(worker.is_alive())
        return answer, failures

    def test_correct_room_password_real_socket(self):
        answer, failures = self.handshake('secret')
        self.assertEqual(answer['type'], 'ACCEPT')
        self.assertEqual(failures, [])

    def test_wrong_room_password_real_socket(self):
        answer, failures = self.handshake('wrong')
        self.assertEqual(answer['type'], 'REFUSE')
        self.assertEqual(len(failures), 1)

    def test_password_proof_cannot_be_replayed(self):
        salt, key = browser.challenge('secret')
        self.assertTrue(browser.auth_ok(key, 'a'*32, browser.proof(key,'a'*32)))
        self.assertFalse(browser.auth_ok(key, 'b'*32, browser.proof(key,'a'*32)))

    def test_directory_registration_expiration_and_removal(self):
        d = kit_directory.Directory()
        row = dict(name='Test', port=47400, players=2, adapter='bt3-pal', protocol=kit_ident.PROTOCOL)
        token = 'a'*64
        d.apply('/register','127.0.0.1',dict(token=token,room=row))
        self.assertEqual(d.apply('/rooms','127.0.0.1',{})['rooms'][0]['adapter'],'bt3-pal')
        d.rows[('127.0.0.1',token)]['seen'] -= browser.TTL+1
        self.assertEqual(d.apply('/rooms','127.0.0.1',{})['rooms'],[])
        d.apply('/register','127.0.0.1',dict(token=token,room=row))
        d.apply('/remove','127.0.0.1',dict(token=token))
        self.assertEqual(d.rows,{})

    def test_directory_http_and_browser(self):
        srv = kit_directory.server(port=0)
        worker = threading.Thread(target=srv.serve_forever,daemon=True)
        worker.start()
        url=f'http://127.0.0.1:{srv.server_port}'
        try:
            browser.request(url,'/register',dict(token='b'*64,room=dict(name='LAN',port=47400,players=2)))
            rooms=browser.discover(url,timeout=0.01,address='127.0.0.1')
            self.assertEqual(len(rooms['rooms']),1)
            self.assertEqual(rooms['errors'],[])
            browser.request(url,'/remove',dict(token='b'*64))
        finally:
            srv.shutdown(); srv.server_close(); worker.join(2)

    def test_lan_browser(self):
        ad=browser.Advertiser(lambda:dict(name='Local',port=47400,players=1))
        try:
            time.sleep(0.1)
            result=browser.discover(timeout=0.3,address='127.0.0.1')
            self.assertEqual([r['name'] for r in result['rooms']],['Local'])
        finally:
            ad.close();ad.thread.join(2)

    def test_public_directory_needs_https(self):
        for url in ('','file:///x','http://example.com','https://user:pass@example.com','https://example.com?q=x'):
            with self.assertRaises(ValueError):browser.directory_url(url)
        self.assertEqual(browser.directory_url('https://example.com/'),'https://example.com')

    def test_challenge_result_stays_in_selection(self):
        h=kit_hub.HubMixin()
        h.init_hub()
        h.hub_return=dict(scores={},ia=0,ib=1,match=dict(teams=[[dict(owner=10)],[dict(owner=11)]]))
        h.match=dict(spec=dict(type='versus'),seats={10:0,11:1})
        h.epoch=1;h.results=dict(how='ko',winner=1)
        self.assertFalse(h.hub_after_fight())
        self.assertIsNone(h.hub_return_at)
        self.assertEqual(h.hub_return['scores'][0]['duel_wins'],1)
        self.assertFalse(h.hub_after_fight())
        self.assertEqual(h.hub_return['scores'][0]['duel_wins'],1)
        h.epoch=2
        self.assertFalse(h.hub_after_fight())
        self.assertEqual(h.hub_return['scores'][0]['duel_wins'],2)

    def test_changed_challenge_teams_credit_actual_winner(self):
        h=kit_hub.HubMixin();h.init_hub()
        h.hub_return=dict(scores={},ia=0,ib=1,match=dict(teams=[[dict(owner=10)],[dict(owner=11)]]))
        h.match=dict(spec=dict(type='versus'),seats={10:1,11:0})
        h.epoch=1;h.results=dict(how='ko',winner=1)
        h.hub_after_fight()
        self.assertNotIn(0,h.hub_return['scores'])
        self.assertEqual(h.hub_return['scores'][1]['duel_wins'],1)

    def test_selected_runtime_and_wrong_disc(self):
        good=dict(kit_ident.GAME,version='PCSX2 v2.8.2')
        self.assertEqual(kit_ident.runtime_problems(good),[])
        self.assertEqual(kit_ident.runtime_problems(dict(good,serial='different'))[0][0],'TTM-NET-06')

    def test_lobby_snapshot_preserves_hub_back_action(self):
        lobby=kit_lobby.Lobby()
        lobby.return_to_hub=True
        guest=kit_lobby.Lobby.from_snapshot(lobby.snapshot())
        self.assertTrue(guest.return_to_hub)


if __name__ == '__main__':unittest.main()
