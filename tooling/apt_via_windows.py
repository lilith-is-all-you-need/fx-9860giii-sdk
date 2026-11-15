"""Temporary loopback-only download transport; no system network settings changed.

APT still verifies Ubuntu signatures and package hashes. The Windows helper
resolves the two official Ubuntu hosts and forwards HTTP requests over HTTPS.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import subprocess
import threading
import urllib.error
import urllib.parse
import urllib.request
import sys

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        url = urllib.parse.urlsplit(self.path)
        if url.hostname not in ('archive.ubuntu.com','security.ubuntu.com') or url.scheme != 'http':
            self.send_error(403)
            return
        request = urllib.request.Request(urllib.parse.urlunsplit(('https',url.netloc,url.path,url.query,'')))
        try:
            with urllib.request.urlopen(request,timeout=90) as data:
                self.send_response(data.status)
                for key in ('Content-Length','Content-Type','Last-Modified'):
                    if data.headers.get(key): self.send_header(key,data.headers[key])
                self.end_headers()
                while chunk := data.read(1024*1024): self.wfile.write(chunk)
        except urllib.error.HTTPError as error:
            self.send_error(error.code)
        except Exception as error:
            print('Transport:',error,flush=True)
            self.send_error(502)
    def log_message(self,*args): pass

def main():
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    cmd=['wsl.exe','-d','FxSDK-Dev-20261114','--exec','env','DEBIAN_FRONTEND=noninteractive',
         'apt-get','-o',f'Acquire::http::Proxy=http://127.0.0.1:{server.server_port}',
         '-o','Acquire::Retries=2',*sys.argv[1:]]
    print('Running APT with temporary Windows download transport',flush=True)
    try: return subprocess.call(cmd)
    finally: server.shutdown()

if __name__=='__main__': sys.exit(main())
