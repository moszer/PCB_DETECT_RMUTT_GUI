"""Who is asking: someone at the station (LAN / tailnet / this machine) or a visitor from the
internet (Tailscale Funnel), and what an internet visitor may do without the station password.

The station is reached three ways, all through the web server (Next) on :3001:
  * LAN / tailnet IP / localhost: straight to Next.
  * https://<name>.ts.net from a tailnet device: Tailscale Serve proxies it and adds the
    user's identity (Tailscale-User-Login; it strips any copy the client sent).
  * the same name from the internet (Funnel): proxied too, but with no identity, the client's
    public address in X-Forwarded-For, and (newer Tailscale) Tailscale-Funnel-Request.

An internet visitor can look (status, history, camera) but not spend the station's resources
or take its data away unless they hold the control lease: the AI assistant (it uses the
station's API key), inspections (GPU, files written to disk), exports and downloads.
"""
from __future__ import annotations

import ipaddress
import re
from typing import Optional

from starlette.requests import Request
from starlette.responses import JSONResponse

from .security import lease_manager

# (method, path pattern) an internet visitor needs the lease for.
GUARDED = [
    (("POST", "PUT", "DELETE"), re.compile(r"^/api/chat(/.*)?$")),
    (("POST",), re.compile(r"^/api/inspection/.+")),
    (("GET",), re.compile(r"^/api/boards/[^/]+/export$")),
    (("GET",), re.compile(r"^/api/datasets/[^/]+/download$")),
    (("GET",), re.compile(r"^/api/history/(export/.+|performance/export\.(csv|json))$")),
    (("POST",), re.compile(r"^/api/system/libraries/check$")),
]

DENIED = ("เข้าจากอินเทอร์เน็ต: ส่วนนี้ (ผู้ช่วย AI · ตรวจภาพ · ดาวน์โหลดข้อมูล) ต้องกด “ขอสิทธิ์ควบคุม” "
          "และใส่รหัสสถานีก่อน")


def _is_public(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip.strip().strip("[]"))
    except ValueError:
        return False
    if addr.version == 6 and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    # Not private, loopback, link-local or the tailnet's 100.64/10 (CGNAT): reachable globally.
    return addr.is_global


def request_origin(request: Request) -> str:
    """'internet' for a Funnel (or otherwise public) visitor, else 'local'."""
    h = request.headers
    if h.get("tailscale-funnel-request"):
        return "internet"
    peer = request.client.host if request.client else ""
    hops = [p for p in (h.get("x-forwarded-for") or "").split(",") if p.strip()] + [peer]
    if any(_is_public(p) for p in hops if p):
        return "internet"
    host = (h.get("x-forwarded-host") or h.get("host") or "").split(":")[0].lower()
    if host.endswith(".ts.net") and not h.get("tailscale-user-login"):
        return "internet"  # through Serve without a tailnet identity: Funnel
    return "local"


def token_of(request: Request) -> Optional[str]:
    # Downloads are plain links (no headers), so they may carry the token in the query.
    return request.headers.get("x-operator-token") or request.headers.get("x-operator-id") or request.query_params.get("operator_token")


def needs_lease(method: str, path: str) -> bool:
    return any(method in methods and rx.match(path) for methods, rx in GUARDED)


async def internet_guard(request: Request, call_next):
    """Middleware: refuse the guarded actions to internet visitors without the lease."""
    if needs_lease(request.method, request.url.path) and request_origin(request) == "internet" \
            and not lease_manager.is_operator(token_of(request)):
        return JSONResponse({"detail": DENIED}, status_code=403)
    return await call_next(request)
