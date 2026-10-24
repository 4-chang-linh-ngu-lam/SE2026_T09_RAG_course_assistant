"""Private synthetic SMTPS sink. No published port, forwarding or token logging."""

import json
import socketserver
import ssl
import threading
from email.parser import BytesParser
from email.policy import default
from pathlib import Path

ROOT = Path('/fixture')
LOCK = threading.Lock()


class Handler(socketserver.StreamRequestHandler):
    def reply(self, value):
        self.wfile.write(value + b'\r\n')
        self.wfile.flush()

    def handle(self):
        self.request.settimeout(15)
        self.reply(b'220 synthetic SMTPS fixture')
        recipients = []
        while True:
            line = self.rfile.readline(8193)
            if not line or len(line) > 8192:
                return
            command, _, argument = line.decode('ascii', errors='replace').strip().partition(' ')
            command = command.upper()
            if command in ('EHLO', 'HELO'):
                self.reply(b'250 synthetic')
            elif command == 'MAIL':
                recipients = []
                self.reply(b'250 OK')
            elif command == 'RCPT':
                recipients.append(argument.partition(':')[2].strip().strip('<>'))
                self.reply(b'250 OK')
            elif command == 'DATA':
                self.reply(b'354 End with dot')
                chunks, size = [], 0
                while True:
                    chunk = self.rfile.readline(8193)
                    if chunk == b'.\r\n':
                        break
                    size += len(chunk)
                    if not chunk or len(chunk) > 8192 or size > 1048576:
                        return
                    chunks.append(chunk[1:] if chunk.startswith(b'..') else chunk)
                message = BytesParser(policy=default).parsebytes(b''.join(chunks))
                body = message.get_body(preferencelist=('plain',))
                record = {'recipients': recipients, 'message': body.get_content() if body else ''}
                with LOCK, (ROOT / 'messages.jsonl').open('a', encoding='utf-8') as target:
                    target.write(json.dumps(record) + '\n')
                self.reply(b'250 accepted')
            elif command == 'QUIT':
                self.reply(b'221 bye')
                return
            elif command in ('RSET', 'NOOP'):
                self.reply(b'250 OK')
            else:
                self.reply(b'502 unsupported')


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def get_request(self):
        connection, address = super().get_request()
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(ROOT / 'ca.crt', ROOT / 'mail.key')
        connection.settimeout(10)
        try:
            return context.wrap_socket(connection, server_side=True), address
        except Exception:
            connection.close()
            raise


if __name__ == '__main__':
    with Server(('0.0.0.0', 8465), Handler) as server:
        server.serve_forever()
