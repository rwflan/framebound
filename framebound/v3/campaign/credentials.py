"""One-use, loopback-only password form. Secrets never enter logs or argv."""
from __future__ import annotations

import argparse
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import threading
from urllib.parse import parse_qs


def key_file():
    path=Path(os.environ.get('FRAMEBOUND_MUSE_KEY_FILE',str(Path.home()/'.config/framebound/muse-api-key.json'))).expanduser().absolute()
    if path.resolve().is_relative_to(Path(__file__).resolve().parents[3]):
        raise ValueError('Credential files must remain outside the repository')
    return path


def load_key():
    value=os.environ.get('MODEL_API_KEY')
    if value:return value
    path=key_file()
    if not path.is_file():return None
    if path.is_symlink() or path.stat().st_mode & 0o077:raise ValueError('API key file must be private (0600) and not a symlink')
    return json.loads(path.read_text())['api_key']


def save_key(value):
    if not isinstance(value,str) or not 8<=len(value)<=4096 or any(c.isspace() for c in value):raise ValueError('Enter the complete API key without whitespace')
    path=key_file();path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    if path.is_symlink():raise ValueError('API key path cannot be a symlink')
    temporary=path.parent/('.key-'+secrets.token_hex(16))
    fd=os.open(temporary,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    try:
        with os.fdopen(fd,'w') as stream:
            json.dump({'api_key':value},stream);stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,path)
    finally:
        temporary.unlink(missing_ok=True)


def serve(port=8766):
    token=secrets.token_urlsafe(32)
    expected_path='/setup/'+token
    consumed=False
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def reply(self,status,body):
            raw=body.encode();self.send_response(status)
            self.send_header('Content-Type','text/html; charset=utf-8')
            self.send_header('Content-Length',str(len(raw)))
            self.send_header('Cache-Control','no-store')
            self.send_header('Referrer-Policy','no-referrer')
            self.send_header('Content-Security-Policy',"default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'")
            self.end_headers();self.wfile.write(raw)
        def authorized(self):
            return hmac.compare_digest(self.path,expected_path) and self.headers.get('Host')==f'127.0.0.1:{self.server.server_port}'
        def do_GET(self):
            if not self.authorized():self.reply(404,'Not found');return
            if consumed:self.reply(200,'<h2>Muse API key saved</h2><p>You can return to the chat.</p>');return
            self.reply(200,'''<!doctype html><html><head><meta name="viewport" content="width=device-width"><title>Connect Muse · Framebound</title>
<style>body{font:17px system-ui;background:#f6f4ee;color:#20312e;margin:0;padding:12vh 28px}main{max-width:480px;margin:auto}small{letter-spacing:.12em;color:#59736c}h1{font-size:36px;letter-spacing:-1px}p{line-height:1.6;color:#52635f}label{display:block;margin:28px 0 10px}input{box-sizing:border-box;width:100%;padding:15px;font:inherit;border:1px solid #a5b3ac;border-radius:8px;background:white}button{margin-top:20px;padding:14px 24px;font:inherit;color:white;background:#244e40;border:0;border-radius:8px;cursor:pointer}footer{font-size:13px;margin-top:28px;color:#6d7e77}</style></head>
<body><main><small>FRAMEBOUND · LOCAL SETUP</small><h1>Connect Muse</h1><p>Enter your Meta Model API key. Framebound stores it in a private local credential file and uses it for Muse requests.</p>
<form id="key-form" method="post" autocomplete="off"><label for="key">Muse API key</label><input id="key" name="api_key" type="password" autocomplete="new-password" required minlength="8" maxlength="4096" autofocus><button type="submit">Save API key</button></form>
<footer>This form is served on your computer. The key is never written to chat, repository files, or application logs. Saving it does not start a paid request.</footer><p id="status" role="status"></p></main>
<script>document.getElementById('key-form').addEventListener('submit',async function(event){event.preventDefault();const form=event.currentTarget;const status=document.getElementById('status');const button=form.querySelector('button');button.disabled=true;status.textContent='Saving locally…';try{const response=await fetch(location.href,{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:new URLSearchParams(new FormData(form)).toString()});if(!response.ok)throw new Error('save failed');form.reset();form.hidden=true;status.textContent='Muse API key saved. You can return to the chat. No paid request has started.';}catch(error){status.textContent='The key has not been saved. Please retry here or open this same address in Chrome.';button.disabled=false;}});</script></body></html>''')
        def do_POST(self):
            nonlocal consumed
            origin=self.headers.get('Origin')
            if not self.authorized() or origin not in (None,f'http://127.0.0.1:{self.server.server_port}') or consumed:
                self.reply(403,'Setup session unavailable');return
            try:
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=16384:raise ValueError('Invalid input size')
                form=parse_qs(self.rfile.read(length).decode(),strict_parsing=True)
                if set(form)!={'api_key'} or len(form['api_key'])!=1:raise ValueError('Enter one API key')
                save_key(form['api_key'][0]);consumed=True
            except (ValueError,OSError):
                self.reply(400,'<h2>Key could not be saved</h2><p>Check the complete key and local credential-file permissions, then go back and retry.</p>');return
            self.reply(200,'<title>Muse connected</title><h2>Muse API key saved</h2><p>You can return to the chat. No paid request has started.</p>')
    server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
    print(f'http://127.0.0.1:{server.server_port}'+expected_path,flush=True)
    server.serve_forever()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--port',type=int,default=8766)
    serve(parser.parse_args().port)
