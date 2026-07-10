"""Entry point: ensure a self-signed cert, then serve over HTTPS on localhost."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import ssl
import subprocess
import sys
import tempfile
import traceback
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
    with tempfile.NamedTemporaryFile("w", suffix=".cnf", delete=False) as fh:
        fh.write(_CERT_CNF)
        cnf_path = fh.name
    try:
        subprocess.run(
            [openssl, "req", "-x509", "-newkey", "rsa:2048", "-nodes",
             "-keyout", str(key), "-out", str(cert),
             "-days", "825", "-config", cnf_path],
            check=True, capture_output=True, text=True,
        )
    except subprocess.CalledProcessError as exc:
        raise SystemExit(f"openssl failed to create a certificate:\n{exc.stderr}")
    finally:
        os.unlink(cnf_path)
    try:
        key.chmod(0o600)
    except OSError:
        pass
    print(f"Generated self-signed certificate in {directory}/")
    return cert, key


def _confluence_targets(cfg) -> list:
    """(label, publish_all fn) for each enabled Confluence publisher (Lustre, EMF)."""
    from . import emf_publish, publish
    targets = []
    conf = getattr(cfg, "confluence", None) or {}
    if conf.get("enabled") and conf.get("auto_publish", True):
        targets.append(("lustre", publish.publish_all))
    emfc = getattr(cfg, "emf", None) or {}
    if emfc.get("enabled") and (emfc.get("confluence") or {}).get("enabled"):
        targets.append(("emf", emf_publish.publish_all))
    return targets


def _start_confluence_scheduler(cfg) -> None:
    """Background thread that publishes the Lustre + EMF pages at 00:00 & 12:00 Pacific."""
    targets = _confluence_targets(cfg)
    if not targets:
        return
    import threading
    import time
    from . import publish

    def loop() -> None:  # pragma: no cover - infinite background scheduler loop
        while True:
            now = publish.now_pt()
            time.sleep(max((publish.next_update_pt(now) - now).total_seconds(), 1))
            for label, fn in targets:
                try:
                    res = fn(cfg)
                    print(f"[confluence:{label}] auto-publish {publish.now_pt():%Y-%m-%d %H:%M %Z}: "
                          f"{'ok' if res.get('ok') else 'FAILED ' + str(res.get('error') or res.get('results'))}",
                          flush=True)
                except Exception:  # noqa: BLE001
                    traceback.print_exc()

    threading.Thread(target=loop, name="confluence-scheduler", daemon=True).start()
    labels = ", ".join(label for label, _ in targets)
    print(f"  Confluence auto-publish ON ({labels}) → next {publish.next_update_pt():%Y-%m-%d %H:%M} PT",
          flush=True)


def _start_slack_scheduler(cfg) -> None:
    """Background thread posting the daily build-health report at slack.hour Pacific."""
    from .sources import slack
    slack_cfg = getattr(cfg, "slack", None) or {}
    if not slack.configured(slack_cfg):
        return
    import threading
    import time
    from . import daily_report

    hour = int(slack_cfg.get("hour", 9))

    def loop() -> None:  # pragma: no cover - infinite background scheduler loop
        while True:
            now = daily_report.now_pt()
            time.sleep(max((daily_report.next_run_pt(hour, now) - now).total_seconds(), 1))
            try:
                res = daily_report.send_daily(cfg)
                print(f"[slack] daily report {daily_report.now_pt():%Y-%m-%d %H:%M %Z}: "
                      f"{'ok' if res.get('ok') else 'FAILED ' + str(res.get('error'))}", flush=True)
            except Exception:  # noqa: BLE001
                traceback.print_exc()

    threading.Thread(target=loop, name="slack-daily-report", daemon=True).start()
    print(f"  Slack daily report ON → next {daily_report.next_run_pt(hour):%Y-%m-%d %H:%M} PT",
          flush=True)


def main(argv: list[str] | None = None) -> int:
    cfg = load_config()
    parser = argparse.ArgumentParser(
        prog="exa-reporter",
        description="Local dashboard for ExaScaler Lustre branch health.",
    )
    parser.add_argument("--host", default=cfg.host, help="bind host (default: localhost)")
    parser.add_argument("--port", type=int, default=cfg.port,
                        help=f"bind port (default: {cfg.port})")
    parser.add_argument("--ttl", type=int, default=300,
                        help="cache TTL in seconds for heavy queries (default: 300)")
    parser.add_argument("--open", action="store_true",
                        help="open the dashboard in a browser on start")
    parser.add_argument("--publish-now", action="store_true",
                        help="publish the landed-patches changelog to Confluence once, then exit")
    parser.add_argument("--slack-now", action="store_true",
                        help="send the daily build-health report to Slack once, then exit")
    args = parser.parse_args(argv)

    cfg.host = args.host
    cfg.port = args.port

    if args.publish_now:
        from . import emf_publish, publish
        res = {"lustre": publish.publish_all(cfg), "emf": emf_publish.publish_all(cfg)}
        print(json.dumps(res, indent=2))
        return 0 if (res["lustre"].get("ok") or res["emf"].get("ok")) else 1

    if args.slack_now:
        from . import daily_report
        res = daily_report.send_daily(cfg)
        print(json.dumps(res, indent=2))
        return 0 if res.get("ok") else 1

    cert, key = ensure_cert(cfg.cert_dir)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certfile=str(cert), keyfile=str(key))

    try:
        httpd = make_server(cfg, cache_ttl=args.ttl)
    except OSError as exc:
        raise SystemExit(f"Could not bind {cfg.host}:{cfg.port} — {exc}")
    httpd.socket = context.wrap_socket(httpd.socket, server_side=True)

    url = f"https://{cfg.host}:{cfg.port}/"
    print(f"EXA Reporter → {url}", flush=True)
    print("  (self-signed TLS: accept the one-time browser warning)", flush=True)
    print("  Ctrl-C to stop.", flush=True)
    if args.open:
        import webbrowser
        webbrowser.open(url)
    _start_confluence_scheduler(cfg)
    _start_slack_scheduler(cfg)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down…")
        httpd.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
