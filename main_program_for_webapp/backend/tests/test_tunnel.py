"""Tailscale remote access: only the station's own serve entry is ever touched (CLI mocked)."""
import json
import unittest
from unittest import mock

from app.services import tunnel_service as tun

DNS = "station.tail1234.ts.net"


class FakeTailscale:
    """Minimal stand-in for the tailscale CLI with a serve config held in memory."""

    def __init__(self, web=None, funnel=None, state="Running"):
        self.web = dict(web or {})
        self.funnel = dict(funnel or {})
        self.state = state
        self.calls = []

    def __call__(self, cmd, **kw):
        args = cmd[1:]
        self.calls.append(args)
        ok = lambda out="": mock.Mock(returncode=0, stdout=out, stderr="")  # noqa: E731
        if args[:2] == ["status", "--json"]:
            return ok(json.dumps({"BackendState": self.state, "Self": {"DNSName": DNS + ".", "TailscaleIPs": ["100.64.0.7"]}, "CertDomains": [DNS]}))
        if args[:3] == ["serve", "status", "--json"]:
            return ok(json.dumps({"Web": self.web, "AllowFunnel": self.funnel}))
        if args[0] in ("serve", "funnel") and "--bg" in args:
            port = next(a.split("=")[1] for a in args if a.startswith("--https="))
            key = f"{DNS}:{port}"
            self.web[key] = {"Handlers": {"/": {"Proxy": args[-1]}}}
            if args[0] == "funnel":
                self.funnel[key] = True
            return ok()
        if args[0] == "serve" and args[-1] == "off":
            port = args[1].split("=")[1]
            self.web.pop(f"{DNS}:{port}", None)
            self.funnel.pop(f"{DNS}:{port}", None)
            return ok()
        raise AssertionError(f"unexpected tailscale call {args}")


class TunnelTests(unittest.TestCase):
    def run_with(self, fake, fn, *a):
        with mock.patch.object(tun, "_binary", return_value="/usr/bin/tailscale"), mock.patch.object(tun.subprocess, "run", side_effect=fake):
            return fn(*a)

    def test_status_reports_other_entries_and_urls(self):
        fake = FakeTailscale(web={f"{DNS}:443": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:3000"}}}}, funnel={f"{DNS}:443": True})
        s = self.run_with(fake, tun.status)
        self.assertIsNone(s["serve"])
        self.assertEqual(s["others"], [{"port": 443, "target": "http://127.0.0.1:3000", "funnel": True}])
        self.assertEqual(s["direct_url"], "http://100.64.0.7:3001")
        self.assertNotIn("tailnet", s)  # the tailnet name is the owner's e-mail

    def test_enable_picks_a_free_port_and_leaves_others_alone(self):
        other = {"Handlers": {"/": {"Proxy": "http://127.0.0.1:3000"}}}
        fake = FakeTailscale(web={f"{DNS}:443": other}, funnel={f"{DNS}:443": True})
        s = self.run_with(fake, tun.enable, False)
        self.assertEqual(s["serve"], {"port": 8443, "funnel": False, "url": f"https://{DNS}:8443"})
        self.assertEqual(fake.web[f"{DNS}:443"], other)
        self.assertTrue(fake.funnel[f"{DNS}:443"])  # the user's funnel is untouched
        s = self.run_with(fake, tun.disable)
        self.assertIsNone(s["serve"])
        self.assertIn(f"{DNS}:443", fake.web)
        self.assertNotIn(["serve", "reset"], fake.calls)

    def test_funnel_on_then_back_to_tailnet_only(self):
        fake = FakeTailscale()
        s = self.run_with(fake, tun.enable, True)
        self.assertEqual(s["serve"], {"port": 443, "funnel": True, "url": f"https://{DNS}"})
        s = self.run_with(fake, tun.enable, False)
        self.assertEqual(s["serve"]["funnel"], False)

    def test_needs_running_tailscale(self):
        with self.assertRaises(tun.TunnelError):
            self.run_with(FakeTailscale(state="NeedsLogin"), tun.enable, False)

    def test_permission_error_explains_operator(self):
        res = mock.Mock(returncode=1, stdout="", stderr="Access denied: serve config denied")
        self.assertIn("--operator", tun._explain(res))

    def test_lan_urls_skip_loopback_and_tailscale(self):
        fam = mock.Mock()
        fam.name = "AF_INET"
        ifs = {"lo": [mock.Mock(family=fam, address="127.0.0.1")], "en0": [mock.Mock(family=fam, address="192.168.1.42")],
               "tailscale0": [mock.Mock(family=fam, address="100.98.73.72")], "docker0": [mock.Mock(family=fam, address="172.17.0.1")]}
        with mock.patch.object(tun.psutil, "net_if_addrs", return_value=ifs):
            self.assertEqual([u["url"] for u in tun.lan_urls()], ["http://192.168.1.42:3001"])


class FunnelPasscodeTests(unittest.TestCase):
    def test_funnel_refused_with_default_passcode(self):
        from fastapi.testclient import TestClient
        from app.config import settings
        from app.core.security import lease_manager
        from app.main import app

        client = TestClient(app)
        settings.operator_passcode = "rmutt-aoi"
        token = client.post("/api/auth/acquire", json={"operator_name": "t", "passcode": "rmutt-aoi", "force": True}).json()["operator_token"]
        try:
            with mock.patch.object(tun, "enable") as enable:
                res = client.post("/api/system/remote-access/serve", json={"funnel": True}, headers={"X-Operator-Token": token})
            self.assertEqual(res.status_code, 400)
            self.assertIn("รหัสผ่าน", res.json()["detail"])
            enable.assert_not_called()
        finally:
            lease_manager.release_lease(token)


if __name__ == "__main__":
    unittest.main()
