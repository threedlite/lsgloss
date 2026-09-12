"""common.chat is the single HTTP call every stage shares.

It replaced nine hand-rolled urllib blocks, two of which crashed on the one
case this project actually hits -- a model returning no content under
--reasoning-budget 0. That behaviour is pinned here.
"""
import unittest
from tests.util import ROOT
from tests.fakemodel import FakeModel
from common import chat


class TestChat(unittest.TestCase):
    def test_returns_the_assistant_text(self):
        with FakeModel(lambda s, u: '  little star  ') as m:
            self.assertEqual(chat(m.url, 'sys', 'usr'), 'little star')

    def test_empty_content_is_a_value_not_a_crash(self):
        # llama.cpp returns content-free replies when the reasoning budget runs
        # out; callers screen for '' themselves
        with FakeModel(lambda s, u: '') as m:
            self.assertEqual(chat(m.url, 'sys', 'usr'), '')

    def test_missing_content_key_is_a_value_not_a_crash(self):
        # the KeyError that used to take down refine.py and score.py
        import json, threading
        from http.server import BaseHTTPRequestHandler, HTTPServer

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a): pass
            def do_POST(self):
                p = json.dumps({'choices': [{'message': {'role': 'assistant'}}]}).encode()
                self.send_response(200)
                self.send_header('Content-Length', str(len(p)))
                self.end_headers(); self.wfile.write(p)

        srv = HTTPServer(('127.0.0.1', 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            url = f'http://127.0.0.1:{srv.server_port}/v1/chat/completions'
            self.assertEqual(chat(url, 'sys', 'usr'), '')
        finally:
            srv.shutdown(); srv.server_close()

    def test_sends_system_and_user_roles(self):
        with FakeModel(lambda s, u: f'{s}|{u}') as m:
            self.assertEqual(chat(m.url, 'SYS', 'USR'), 'SYS|USR')

    def test_passes_max_tokens_and_temperature(self):
        with FakeModel(lambda s, u: 'x') as m:
            chat(m.url, 's', 'u', max_tokens=17, temperature=0.5)
            self.assertEqual(m.calls[0]['max_tokens'], 17)
            self.assertEqual(m.calls[0]['temperature'], 0.5)

    def test_reasoning_effort_is_sent_only_when_asked(self):
        with FakeModel(lambda s, u: 'x') as m:
            chat(m.url, 's', 'u')
            chat(m.url, 's', 'u', effort='medium')
        # effort rides in chat_template_kwargs: the first call must not carry
        # it (llama-server would otherwise apply a reasoning budget), the
        # second must
        self.assertEqual(len(m.calls), 2)
        self.assertIsNone(m.calls[0]['chat_template_kwargs'])
        self.assertEqual(m.calls[1]['chat_template_kwargs'], {'reasoning_effort': 'medium'})


if __name__ == '__main__':
    unittest.main()
