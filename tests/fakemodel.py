"""A scriptable stand-in for llama-server.

The stages that matter most -- which rows freqfix targets, which candidates it
accepts -- are model-calling scripts, so they are exactly the code a model-free
test suite tends to skip. It does not need a real model: it needs a server that
returns chosen answers, so the decision logic can be driven deterministically.

Speaks the sliver of the OpenAI chat-completions API that common.chat uses.
"""
import json, re, threading
from http.server import BaseHTTPRequestHandler, HTTPServer


class FakeModel:
    """Serves scripted replies and records every request.

    reply(system, user) -> str decides what comes back, so a test can answer
    differently for the gloss prompt and the judge prompt.
    """

    def __init__(self, reply):
        self.reply = reply
        self.calls = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                n = int(self.headers.get('Content-Length', 0))
                body = json.loads(self.rfile.read(n) or b'{}')
                msgs = {m['role']: m['content'] for m in body.get('messages', [])}
                system, user = msgs.get('system', ''), msgs.get('user', '')
                outer.calls.append({'system': system, 'user': user,
                                    'max_tokens': body.get('max_tokens'),
                                    'temperature': body.get('temperature'),
                                    'chat_template_kwargs': body.get('chat_template_kwargs')})
                try:
                    content = outer.reply(system, user)
                except Exception as ex:                     # surface, don't hang
                    content = f'FAKEMODEL ERROR {ex}'
                payload = json.dumps(
                    {'choices': [{'message': {'role': 'assistant', 'content': content}}]}
                ).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        self.server = HTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def url(self):
        return f'http://127.0.0.1:{self.server.server_port}/v1/chat/completions'

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *a):
        self.server.shutdown()
        self.server.server_close()

    # -- helpers for reading back what the code under test actually asked ----
    def judge_calls(self):
        """Requests that look like a judging prompt (they carry a gloss)."""
        return [c for c in self.calls if 'Gloss:' in c['user']]

    def gloss_of(self, call):
        m = re.search(r'Gloss:\s*(.*)', call['user'])
        return m.group(1).strip() if m else None

    def entry_of(self, call):
        m = re.search(r'Entry:\s*(.*?)(?:\nGloss:|$)', call['user'], re.S)
        return m.group(1).strip() if m else None
