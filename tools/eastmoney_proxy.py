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
import os
import select
import socket
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

# Clear any system proxy env vars so raw sockets bypass VPN/Clash TUN
for _k in list(os.environ.keys()):
    if 'proxy' in _k.lower():
        os.environ.pop(_k, None)

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
        """Handle plain HTTP GET — uses raw sockets to bypass system proxy."""
        parsed = urlparse(self.path)
        hostname = parsed.hostname or self.headers.get("Host", "").split(":")[0]
        port = parsed.port or 80

        if not host_allowed(hostname):
            logger.warning("BLOCKED GET: %s", hostname)
            self.send_error(403, f"Access denied: {hostname}")
            return

        try:
            # Rebuild the path for the target server
            if parsed.path:
                request_path = parsed.path
                if parsed.query:
                    request_path += "?" + parsed.query
            else:
                request_path = self.path.split(hostname, 1)[-1] if hostname in self.path else "/"

            # Use raw socket to bypass system HTTP_PROXY (Clash/V2Ray etc.)
            remote = socket.create_connection((hostname, port), timeout=15)

            # Build the HTTP request
            req_lines = [f"GET {request_path} HTTP/1.1",
                         f"Host: {hostname}"]
            for k, v in self.headers.items():
                if k.lower() not in ("host", "proxy-connection", "proxy-authorization"):
                    req_lines.append(f"{k}: {v}")
            req_lines.append("Connection: close")
            req_lines.append("")
            http_request = "\r\n".join(req_lines).encode("utf-8")

            remote.sendall(http_request)

            # Read response
            response_data = b""
            while True:
                chunk = remote.recv(65536)
                if not chunk:
                    break
                response_data += chunk
            remote.close()

            # Split headers and body
            header_end = response_data.find(b"\r\n\r\n")
            if header_end == -1:
                self.send_error(502, "Invalid response from upstream")
                return

            headers_raw = response_data[:header_end].decode("utf-8", errors="replace")
            body = response_data[header_end + 4:]

            # Parse status line
            status_line = headers_raw.split("\r\n")[0]
            try:
                status_code = int(status_line.split(" ")[1])
            except (IndexError, ValueError):
                status_code = 200

            # Forward headers (skip Transfer-Encoding/Connection)
            self.send_response(status_code)
            for line in headers_raw.split("\r\n")[1:]:
                if ":" in line:
                    k, v = line.split(":", 1)
                    if k.strip().lower() not in ("transfer-encoding", "connection"):
                        self.send_header(k.strip(), v.strip())
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
