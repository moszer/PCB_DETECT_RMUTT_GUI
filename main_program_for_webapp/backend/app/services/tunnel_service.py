"""Remote access to the station: LAN addresses, and a Tailscale tunnel managed from the web.

Tailscale "serve" publishes the station's web page over HTTPS inside your tailnet (only your
own devices); "funnel" also publishes it on the public internet. Only the station's own entry
is ever added or removed: other serve/funnel entries on this machine are left alone.
"""
from __future__ import annotations

import ipaddress
import json
import os
import shutil
import subprocess
import time
from typing import Any, Dict, List, Optional

import psutil

MAC_APP = "/Applications/Tailscale.app/Contents/MacOS/Tailscale"
# Ports Tailscale allows for Funnel; the station uses the first one not taken by something else.
PORTS = (443, 8443, 10000)
TIMEOUT = 15


class TunnelError(RuntimeError):
    """Readable failure shown on the page."""


def frontend_port() -> int:
    try:
        return int(os.environ.get("PCB_FRONTEND_PORT", "3001"))
    except ValueError:
        return 3001


def lan_urls() -> List[Dict[str, str]]:
    """http://<ip>:<port> for each private IPv4 address of this machine."""
    port = frontend_port()
    urls = []
    for name, addrs in psutil.net_if_addrs().items():
        for a in addrs:
            if a.family.name != "AF_INET":
                continue
            ip = ipaddress.ip_address(a.address)
            if ip.is_loopback or not ip.is_private or ip in ipaddress.ip_network("100.64.0.0/10"):
                continue
            if name.startswith(("docker", "br-", "veth", "l4tbr", "virbr")):
                continue  # container bridges / Jetson USB-gadget network
            urls.append({"interface": name, "url": f"http://{a.address}:{port}"})
    return urls


def _binary() -> Optional[str]:
    found = shutil.which("tailscale")
    if found:
        return found
    return MAC_APP if os.path.isfile(MAC_APP) else None


def _run(*args: str, timeout: float = TIMEOUT) -> subprocess.CompletedProcess:
    exe = _binary()
    if not exe:
        raise TunnelError("ยังไม่ได้ติดตั้ง Tailscale บนเครื่องนี้")
    try:
        return subprocess.run([exe, *args], capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise TunnelError(f"tailscale {' '.join(args[:2])} ไม่ตอบภายใน {timeout:.0f} วินาที") from exc


def _explain(res: subprocess.CompletedProcess) -> str:
    out = (res.stderr or res.stdout or "").strip()
    low = out.lower()
    if "access denied" in low or "permission denied" in low or "operator" in low:
        return "Tailscale ไม่อนุญาตให้ผู้ใช้นี้ตั้งค่า — รันครั้งเดียวบนเครื่องนี้: sudo tailscale set --operator=$USER"
    if "https" in low and ("not enabled" in low or "certificates" in low):
        return "ต้องเปิด HTTPS ของ tailnet ก่อน: เปิด https://login.tailscale.com/admin/dns แล้วกด Enable HTTPS"
    if "funnel" in low and ("not enabled" in low or "attribute" in low or "policy" in low):
        return "tailnet ยังไม่อนุญาต Funnel: เปิดใน https://login.tailscale.com/admin/acls (nodeAttrs: funnel)"
    return out.splitlines()[-1] if out else f"tailscale ผิดพลาด (exit {res.returncode})"


def _station_targets() -> set:
    port = frontend_port()
    return {f"http://127.0.0.1:{port}", f"http://localhost:{port}", f"http://[::1]:{port}"}


def _serve_config() -> Dict[str, Any]:
    res = _run("serve", "status", "--json")
    if res.returncode != 0:
        return {}
    try:
        return json.loads(res.stdout or "{}") or {}
    except json.JSONDecodeError:
        return {}


def _entries(cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Every web serve entry: host, port, root proxy target, funnel flag, and whether it is ours."""
    out = []
    funnel = cfg.get("AllowFunnel") or {}
    targets = _station_targets()
    for hostport, web in (cfg.get("Web") or {}).items():
        host, _, port = hostport.rpartition(":")
        proxy = ((web.get("Handlers") or {}).get("/") or {}).get("Proxy", "")
        out.append({"host": host, "port": int(port or 443), "target": proxy, "funnel": bool(funnel.get(hostport)), "station": proxy.rstrip("/") in targets})
    return out


def status() -> Dict[str, Any]:
    data: Dict[str, Any] = {"lan": lan_urls(), "frontend_port": frontend_port(), "installed": bool(_binary()), "time": time.time()}
    if not data["installed"]:
        return data
    res = _run("status", "--json")
    try:
        st = json.loads(res.stdout or "{}")
    except json.JSONDecodeError:
        st = {}
    me = st.get("Self") or {}
    dns = (me.get("DNSName") or "").rstrip(".")
    ips = me.get("TailscaleIPs") or []
    data.update(
        state=st.get("BackendState") or ("Stopped" if res.returncode else "Unknown"),
        auth_url=st.get("AuthURL") or None,
        dns_name=dns or None,
        ipv4=next((ip for ip in ips if ":" not in ip), None),
        https=bool(st.get("CertDomains")),
        version=(st.get("Version") or "").split("-")[0] or None,
    )
    entries = _entries(_serve_config()) if data["state"] == "Running" else []
    mine = next((e for e in entries if e["station"]), None)
    data["serve"] = (
        {"port": mine["port"], "funnel": mine["funnel"], "url": f"https://{dns}" + ("" if mine["port"] == 443 else f":{mine['port']}")}
        if mine and dns
        else None
    )
    data["others"] = [{"port": e["port"], "target": e["target"], "funnel": e["funnel"]} for e in entries if not e["station"]]
    if data["ipv4"]:
        data["direct_url"] = f"http://{data['ipv4']}:{frontend_port()}"  # works inside the tailnet without serve
    return data


def login() -> Dict[str, Any]:
    """Start `tailscale up` without waiting; the login URL then shows up in status()."""
    exe = _binary()
    if not exe:
        raise TunnelError("ยังไม่ได้ติดตั้ง Tailscale บนเครื่องนี้")
    subprocess.Popen([exe, "up"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    for _ in range(20):  # the URL appears within a second or two
        time.sleep(0.5)
        s = status()
        if s.get("auth_url") or s.get("state") == "Running":
            return s
    s = status()
    if s.get("state") not in ("Running",) and not s.get("auth_url"):
        raise TunnelError("เริ่ม Tailscale ไม่สำเร็จ — บน Linux อาจต้องรันครั้งเดียว: sudo tailscale up (หรือ sudo tailscale set --operator=$USER)")
    return s


def enable(funnel: bool) -> Dict[str, Any]:
    s = status()
    if s.get("state") != "Running":
        raise TunnelError("Tailscale ยังไม่ได้เชื่อมต่อ — กด “เชื่อมต่อ Tailscale” ก่อน")
    taken = {o["port"] for o in s.get("others", [])}
    port = s["serve"]["port"] if s.get("serve") else next((p for p in PORTS if p not in taken), None)
    if port is None:
        raise TunnelError("พอร์ต 443, 8443 และ 10000 ของ Tailscale ถูกใช้หมดแล้ว")
    target = f"http://127.0.0.1:{frontend_port()}"
    if s.get("serve") and s["serve"]["funnel"] and not funnel:
        _off(port)  # funnel -> tailnet only: remove, then serve again
    res = _run("funnel" if funnel else "serve", "--bg", "--yes", f"--https={port}", target, timeout=30)
    if res.returncode != 0:
        raise TunnelError(_explain(res))
    return status()


def _off(port: int) -> None:
    res = _run("serve", f"--https={port}", "off")
    if res.returncode != 0:
        raise TunnelError(_explain(res))


def disable() -> Dict[str, Any]:
    s = status()
    if s.get("serve"):
        _off(s["serve"]["port"])
    return status()
