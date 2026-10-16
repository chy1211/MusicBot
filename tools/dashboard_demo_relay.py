"""Loopback-only relay for a credential-free --network none demo container.

Run on the Docker host. Docker exec stdio reaches the container's own loopback;
no bridge, production mounts, proxy changes or network access are required.
"""
import argparse
import re
import shutil
import socketserver
import subprocess
import threading

WORKER = """
import socket, sys, threading
sock = socket.create_connection(("127.0.0.1", 8080), timeout=10)
sock.settimeout(None)
def upload():
    try:
        while chunk := sys.stdin.buffer.read1(65536):
            sock.sendall(chunk)
    except OSError:
        pass
    finally:
        try:
            sock.shutdown(socket.SHUT_WR)
        except OSError:
            pass
threading.Thread(target=upload, daemon=True).start()
try:
    while chunk := sock.recv(65536):
        sys.stdout.buffer.write(chunk)
        sys.stdout.buffer.flush()
finally:
    sock.close()
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--container", default="musicbot-webtest-r4-demo")
    parser.add_argument("--port", type=int, default=18080)
    args = parser.parse_args()
    if not re.fullmatch(r"musicbot-webtest-[a-zA-Z0-9_.-]+", args.container):
        parser.error("Only a named musicbot-webtest- demo container is allowed")
    docker = shutil.which("docker")
    if not docker:
        parser.error("Docker CLI is required on the demo host")

    class Relay(socketserver.BaseRequestHandler):
        def handle(self):
            proc = subprocess.Popen(
                [docker, "exec", "-i", args.container, "python3", "-u", "-c", WORKER],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            def upload():
                try:
                    while chunk := self.request.recv(65536):
                        proc.stdin.write(chunk)
                        proc.stdin.flush()
                except (OSError, ValueError):
                    pass
                finally:
                    try:
                        proc.stdin.close()
                    except OSError:
                        pass
            threading.Thread(target=upload, daemon=True).start()
            try:
                while chunk := proc.stdout.read1(65536):
                    self.request.sendall(chunk)
            except OSError:
                pass
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
                proc.stdout.close()

    class Server(socketserver.ThreadingTCPServer):
        allow_reuse_address = True
        daemon_threads = True

    with Server(("127.0.0.1", args.port), Relay) as server:
        print(f"DEMO relay only: 127.0.0.1:{args.port}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
