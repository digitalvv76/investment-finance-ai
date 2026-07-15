#!/usr/bin/env python3
"""East Money HTTP/HTTPS forward proxy — runs on your local Windows.

Usage:
    python eastmoney_proxy.py              # default port 1080
    python eastmoney_proxy.py --port 8888  # custom port

What it does:
    你的电脑 (住宅IP) → 访问东方财富 API → 返回结果
    ECS 通过 SSH 反向隧道连到这个代理 → 绕过 IP 封禁

Security: only forwards to *.eastmoney.com domains, rejects everything else.
"""

import argparse
import logging
import select
import socket
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("em-proxy")

# Only allow East Money domains — block everything else for safety
ALLOWED_HOSTS = {
    "push2his.eastmoney.com",
    "push2.eastmoney.com",
    "ff.eastmoney.com",
    "searchapi.eastmoney.com",
    "data.eastmoney.com",
    "quote.eastmoney.com",
    "emdatah5.eastmoney.com",
}


def host_allowed(hostname: str) -> bool:
    """Check if hostname matches an East Money domain."""
    hostname = hostname.lower().rstrip(".")
    if hostname in ALLOWED_HOSTS:
        return True
    # Also allow subdomains like *.eastmoney.com
    if hostname.endswith(".eastmoney.com"):
        return True
    return False


class ForwardProxyHandler(BaseHTTPRequestHandler):
    """HTTP handler that forwards requests to the target server."""

    timeout = 30

    def log_message(self, format, *args):
        logger.info("%s — %s", self.client_address[0], format % args)

    def do_CONNECT(self):
        """Handle HTTPS CONNECT tunnel (for push2his.eastmoney.com etc)."""
        hostname = self.path.split(":")[0]
        if not host_allowed(hostname):
            logger.warning("BLOCKED CONNECT: %s", hostname)
            self.send_error(403, f"Access denied: {hostname}")
            return

        try:
            # Connect to the target server from THIS machine (your PC)
            port = int(self.path.split(":")[1]) if ":" in self.path else 443
            remote = socket.create_connection((hostname, port), timeout=15)
            self.send_response(200, "Connection Established")
            self.end_headers()

            # Bidirectional pipe: client ↔ remote
            self._tunnel(self.connection, remote)
        except Exception as e:
            logger.error("CONNECT %s failed: %s", hostname, e)
            try:
                self.send_error(502, str(e))
            except Exception:
                pass

    def do_GET(self):
        """Handle plain HTTP GET (for ff.eastmoney.com HTTP fallback)."""
        parsed = urlparse(self.path)
        hostname = parsed.hostname or self.headers.get("Host", "").split(":")[0]

        if not host_allowed(hostname):
            logger.warning("BLOCKED GET: %s", hostname)
            self.send_error(403, f"Access denied: {hostname}")
            return

        try:
            # Build the target URL
            if parsed.scheme:
                target_url = self.path
            else:
                target_url = f"http://{self.headers['Host']}{self.path}"

            import urllib.request
            req = urllib.request.Request(
                target_url,
                headers={k: v for k, v in self.headers.items()
                        if k.lower() not in ("host", "proxy-connection")},
                method="GET",
            )
            resp = urllib.request.urlopen(req, timeout=15)
            body = resp.read()

            self.send_response(resp.status)
            for k, v in resp.headers.items():
                if k.lower() not in ("transfer-encoding",):
                    self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:
            logger.error("GET %s failed: %s", hostname, e)
            try:
                self.send_error(502, str(e))
            except Exception:
                pass

    def do_POST(self):
        """Handle POST requests (same logic as GET)."""
        self.do_GET()

    @staticmethod
    def _tunnel(client, remote):
        """Bidirectional copy between client and remote sockets."""
        try:
            sockets = [client, remote]
            while True:
                readable, _, errored = select.select(sockets, [], sockets, 30)
                if errored:
                    break
                if not readable:
                    break
                for sock in readable:
                    data = sock.recv(65536)
                    if not data:
                        return
                    if sock is client:
                        remote.sendall(data)
                    else:
                        client.sendall(data)
        except Exception:
            pass
        finally:
            try:
                client.close()
            except Exception:
                pass
            try:
                remote.close()
            except Exception:
                pass


def main():
    parser = argparse.ArgumentParser(description="East Money forward proxy")
    parser.add_argument("--port", type=int, default=1080, help="Listen port (default: 1080)")
    parser.add_argument("--bind", default="127.0.0.1", help="Bind address (default: 127.0.0.1)")
    args = parser.parse_args()

    server = HTTPServer((args.bind, args.port), ForwardProxyHandler)
    logger.info("East Money proxy listening on %s:%d", args.bind, args.port)
    logger.info("Allowed domains: %s", ", ".join(sorted(ALLOWED_HOSTS)))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        server.shutdown()


if __name__ == "__main__":
    main()
