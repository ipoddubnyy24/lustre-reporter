"""Entry point: ensure a self-signed cert, then serve over HTTPS on localhost."""

from __future__ import annotations

import argparse
import os
import shutil
import ssl
import subprocess
import sys
import tempfile
from pathlib import Path

from .config import load_config
from .server import make_server

# Minimal OpenSSL config with a SAN — required by modern browsers, and this
# form works on both OpenSSL and macOS's LibreSSL.
_CERT_CNF = """[req]
distinguished_name = dn
x509_extensions = v3
prompt = no
[dn]
CN = localhost
[v3]
subjectAltName = DNS:localhost,IP:127.0.0.1
basicConstraints = CA:FALSE
keyUsage = digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth
"""


def ensure_cert(cert_dir: str) -> tuple[Path, Path]:
    """Return (cert, key) paths, generating a self-signed pair if absent."""
    directory = Path(cert_dir)
    cert = directory / "cert.pem"
    key = directory / "key.pem"
    if cert.exists() and key.exists():
        return cert, key

    openssl = shutil.which("openssl")
    if not openssl:
        raise SystemExit(
            "openssl not found — cannot generate a TLS certificate.\n"
            f"Provide your own at {cert} and {key}, or install openssl."
        )
    directory.mkdir(parents=True, exist_ok=True)
    cnf_path = None
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".cnf", delete=False) as fh:
            fh.write(_CERT_CNF)
            cnf_path = fh.name
        subprocess.run(
            [openssl, "req", "-x509", "-newkey", "rsa:2048", "-nodes",
             "-keyout", str(key), "-out", str(cert),
             "-days", "825", "-config", cnf_path],
            check=True, capture_output=True, text=True,
        )
    except subprocess.CalledProcessError as exc:
        raise SystemExit(f"openssl failed to create a certificate:\n{exc.stderr}")
    finally:
        if cnf_path:
            os.unlink(cnf_path)
    try:
        key.chmod(0o600)
    except OSError:
        pass
    print(f"Generated self-signed certificate in {directory}/")
    return cert, key


def main(argv: list[str] | None = None) -> int:
    cfg = load_config()
    parser = argparse.ArgumentParser(
        prog="lustre-reporter",
        description="Local dashboard for ExaScaler Lustre branch health.",
    )
    parser.add_argument("--host", default=cfg.host, help="bind host (default: localhost)")
    parser.add_argument("--port", type=int, default=cfg.port,
                        help=f"bind port (default: {cfg.port})")
    parser.add_argument("--ttl", type=int, default=300,
                        help="cache TTL in seconds for heavy queries (default: 300)")
    parser.add_argument("--open", action="store_true",
                        help="open the dashboard in a browser on start")
    args = parser.parse_args(argv)

    cfg.host = args.host
    cfg.port = args.port

    cert, key = ensure_cert(cfg.cert_dir)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certfile=str(cert), keyfile=str(key))

    try:
        httpd = make_server(cfg, cache_ttl=args.ttl)
    except OSError as exc:
        raise SystemExit(f"Could not bind {cfg.host}:{cfg.port} — {exc}")
    httpd.socket = context.wrap_socket(httpd.socket, server_side=True)

    url = f"https://{cfg.host}:{cfg.port}/"
    print(f"Lustre Reporter → {url}", flush=True)
    print("  (self-signed TLS: accept the one-time browser warning)", flush=True)
    print("  Ctrl-C to stop.", flush=True)
    if args.open:
        import webbrowser
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down…")
        httpd.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
