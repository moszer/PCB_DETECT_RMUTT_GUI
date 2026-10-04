"""Live performance readings, and Jetson power / clock / fan control.

Readings need no privileges (sysfs, /proc, nvpmodel -q). Changes go through the root helper
/usr/local/sbin/aoi-jetson-power via `sudo -n`, which scripts/jetson/install-power-control.sh
allows for the station user; without it the page is read-only and says how to enable it.
"""
from __future__ import annotations

import glob
import logging
import os
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import psutil

logger = logging.getLogger(__name__)

HELPER = "/usr/local/sbin/aoi-jetson-power"
# The version in this checkout; when it differs from the installed one, the setup must be re-run.
HELPER_SOURCE = Path(__file__).resolve().parents[3] / "scripts" / "jetson" / "aoi-jetson-power"
STATE_DIR = Path("/var/lib/rmutt-aoi")
NVPMODEL_CONF = Path("/etc/nvpmodel.conf")
FAN_CONF = Path("/etc/nvfancontrol.conf")
# With the fan fixed below 100 %, run it at 100 % (still fixed) above this temperature.
FAN_SAFETY_C = 85.0


class HardwareError(RuntimeError):
    """A change that could not be applied (message shown to the user)."""


def _read(path: str | Path, default: Optional[str] = None) -> Optional[str]:
    try:
        return Path(path).read_text().strip()
    except (OSError, ValueError):
        return default


def _num(path: str | Path) -> Optional[float]:
    raw = _read(path)
    try:
        return float(raw) if raw is not None else None
    except ValueError:
        return None


def _hwmon(name: str) -> Optional[Path]:
    for h in glob.glob("/sys/class/hwmon/hwmon*"):
        if _read(f"{h}/name") == name:
            return Path(h)
    return None


def _crit(milliamps: Optional[float]) -> Optional[float]:
    """Over-current limit of a rail; INA3221 reports 32.76 A when none is set."""
    return round(milliamps / 1000, 2) if milliamps and milliamps < 30000 else None


def is_jetson() -> bool:
    return Path("/etc/nv_tegra_release").is_file()


class HardwareService:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._mode_cache: tuple[float, Optional[Dict[str, Any]]] = (0.0, None)
        self._control_cache: tuple[float, bool] = (0.0, False)
        self._watchdog: Optional[threading.Thread] = None
        psutil.cpu_percent(percpu=True)  # prime: the next call returns usage since now

    # ── readings ──────────────────────────────────────────────────────────────
    def snapshot(self) -> Dict[str, Any]:
        jetson = is_jetson()
        data: Dict[str, Any] = {
            "time": time.time(),
            "platform": "jetson" if jetson else ("linux" if os.name == "posix" and Path("/proc").is_dir() else "other"),
            "model": self._board_model(),
            "cpu": self._cpu(),
            "memory": self._memory(),
            "temperatures": self._temperatures(),
        }
        if jetson:
            data.update(
                gpu=self._gpu(),
                emc=self._devfreq("bwmgr"),
                power_rails=self._rails(),
                fan=self._fan(),
                power_mode=self._power_mode(),
                clocks_max=self._clocks_max(),
                over_current=self._over_current(),
                control_available=self.control_available(),
                helper_outdated=self.helper_outdated(),
            )
        return data

    @staticmethod
    def _board_model() -> Optional[str]:
        model = _read("/proc/device-tree/model")
        return model.replace("\x00", "") if model else None

    @staticmethod
    def _cpu() -> Dict[str, Any]:
        usage = psutil.cpu_percent(percpu=True)
        cores: List[Dict[str, Any]] = []
        for i, pct in enumerate(usage):
            base = f"/sys/devices/system/cpu/cpu{i}/cpufreq"
            cur = _num(f"{base}/scaling_cur_freq")
            cores.append(
                {
                    "id": i,
                    "usage": round(pct, 1),
                    "mhz": round(cur / 1000) if cur else None,
                    "max_mhz": round((_num(f"{base}/cpuinfo_max_freq") or 0) / 1000) or None,
                    "governor": _read(f"{base}/scaling_governor"),
                }
            )
        if cores and cores[0]["mhz"] is None:  # macOS/others: one frequency for all cores
            try:
                f = psutil.cpu_freq()
            except Exception:  # noqa: BLE001 - Apple Silicon has no readable CPU frequency
                f = None
            for c in cores:
                c["mhz"] = round(f.current) if f and f.current else None
                c["max_mhz"] = round(f.max) if f and f.max else None
        load = os.getloadavg() if hasattr(os, "getloadavg") else (0.0, 0.0, 0.0)
        return {"cores": cores, "usage": round(sum(usage) / len(usage), 1) if usage else 0.0, "load": [round(x, 2) for x in load]}

    @staticmethod
    def _memory() -> Dict[str, Any]:
        vm, sw = psutil.virtual_memory(), psutil.swap_memory()
        mb = 1024 * 1024
        return {"total_mb": vm.total // mb, "used_mb": (vm.total - vm.available) // mb, "swap_total_mb": sw.total // mb, "swap_used_mb": sw.used // mb}

    @staticmethod
    def _temperatures() -> List[Dict[str, Any]]:
        temps = []
        for z in sorted(glob.glob("/sys/class/thermal/thermal_zone*")):
            name, value = _read(f"{z}/type"), _num(f"{z}/temp")
            if name and value is not None and -40000 < value < 150000:
                temps.append({"name": name.replace("-thermal", ""), "c": round(value / 1000, 1)})
        if not temps:
            try:
                for name, entries in (psutil.sensors_temperatures() or {}).items():
                    for e in entries[:1]:
                        temps.append({"name": name, "c": round(e.current, 1)})
            except (AttributeError, OSError):
                pass
        return temps

    @staticmethod
    def _devfreq(name: str) -> Optional[Dict[str, Any]]:
        d = f"/sys/class/devfreq/{name}"
        cur = _num(f"{d}/cur_freq")
        if cur is None:
            return None
        return {"mhz": round(cur / 1e6), "max_mhz": round((_num(f"{d}/max_freq") or 0) / 1e6), "min_mhz": round((_num(f"{d}/min_freq") or 0) / 1e6)}

    def _gpu(self) -> Optional[Dict[str, Any]]:
        gpu_dev = next(iter(glob.glob("/sys/class/devfreq/*.gpu")), None)
        if not gpu_dev:
            return None
        info = self._devfreq(os.path.basename(gpu_dev)) or {}
        load = _num(f"{gpu_dev}/device/load")  # the GPU platform device (devfreq links to it)
        info["usage"] = round(load / 10, 1) if load is not None else None  # per mille
        return info

    @staticmethod
    def _rails() -> List[Dict[str, Any]]:
        h = _hwmon("ina3221")
        rails = []
        if h:
            for i in range(1, 9):
                label, mv, ma = _read(h / f"in{i}_label"), _num(h / f"in{i}_input"), _num(h / f"curr{i}_input")
                if label and mv is not None and ma is not None:
                    rails.append({"name": label, "watts": round(mv * ma / 1e6, 2), "volts": round(mv / 1000, 2), "amps": round(ma / 1000, 2), "crit_amps": _crit(_num(h / f"curr{i}_crit"))})
        return rails

    @staticmethod
    def _fan() -> Dict[str, Any]:
        pwm_dir, tach = _hwmon("pwmfan"), _hwmon("pwm_tach")
        pwm = _num(pwm_dir / "pwm1") if pwm_dir else None
        manual = _read(STATE_DIR / "fan-manual")
        profile = None
        if FAN_CONF.is_file():
            m = re.search(r"^\s*FAN_DEFAULT_PROFILE\s+(\w+)", FAN_CONF.read_text(errors="ignore"), re.M)
            profile = m.group(1) if m else None
        profiles = re.findall(r"FAN_PROFILE\s+(\w+)\s*\{", FAN_CONF.read_text(errors="ignore")) if FAN_CONF.is_file() else []
        active = subprocess.run(["systemctl", "is-active", "--quiet", "nvfancontrol"], check=False).returncode == 0
        return {
            "percent": round(pwm * 100 / 255) if pwm is not None else None,
            "rpm": _num(tach / "rpm") if tach else None,
            "mode": "manual" if manual else "auto",
            "auto_service": active,
            "manual_percent": int(manual) if manual and manual.isdigit() else None,
            "profile": profile,
            "profiles": profiles,
        }

    def _power_mode(self) -> Optional[Dict[str, Any]]:
        now = time.monotonic()
        if now - self._mode_cache[0] < 5 and self._mode_cache[1]:
            return self._mode_cache[1]
        modes = []
        if NVPMODEL_CONF.is_file():
            modes = [{"id": int(i), "name": n} for i, n in re.findall(r"^< POWER_MODEL ID=(\d+) NAME=(\S+) >", NVPMODEL_CONF.read_text(errors="ignore"), re.M)]
        current = None
        try:
            out = subprocess.run(["nvpmodel", "-q"], capture_output=True, text=True, timeout=5, check=False).stdout
            lines = [line.strip() for line in out.splitlines() if line.strip()]
            current = int(lines[-1]) if lines and lines[-1].isdigit() else None
        except (OSError, subprocess.SubprocessError):
            pass
        info = {"current": current, "modes": modes}
        self._mode_cache = (now, info)
        return info

    @staticmethod
    def _clocks_max() -> bool:
        if (STATE_DIR / "clocks-max").exists():
            return True
        cores = glob.glob("/sys/devices/system/cpu/cpu[0-9]*/cpufreq")
        return bool(cores) and all(_read(f"{c}/scaling_min_freq") == _read(f"{c}/scaling_max_freq") for c in cores)

    @staticmethod
    def _over_current() -> Optional[Dict[str, int]]:
        h = _hwmon("soctherm_oc")
        if not h:
            return None
        return {f.name.split("_")[0]: int(_num(f) or 0) for f in sorted(h.glob("oc*_event_cnt"))}

    # ── control ───────────────────────────────────────────────────────────────
    def control_available(self) -> bool:
        now = time.monotonic()
        if now - self._control_cache[0] < 30:
            return self._control_cache[1]
        ok = False
        if is_jetson() and Path(HELPER).is_file():
            try:
                ok = subprocess.run(["sudo", "-n", HELPER, "check"], capture_output=True, timeout=5, check=False).returncode == 0
            except (OSError, subprocess.SubprocessError):
                ok = False
        self._control_cache = (now, ok)
        return ok

    @staticmethod
    def helper_outdated() -> bool:
        installed, source = _read(HELPER), _read(HELPER_SOURCE)
        return bool(installed and source and installed != source)

    def _helper(self, *args: str) -> str:
        if not is_jetson():
            raise HardwareError("ใช้ได้เฉพาะบน NVIDIA Jetson")
        if not self.control_available():
            raise HardwareError("ยังไม่ได้เปิดสิทธิ์ควบคุมพลังงาน — รันบน Jetson: sudo ./scripts/jetson/install-power-control.sh")
        with self._lock:
            res = subprocess.run(["sudo", "-n", HELPER, *args], capture_output=True, text=True, timeout=60, check=False)
        self._mode_cache = (0.0, None)
        out = (res.stdout + res.stderr).strip()
        if res.returncode != 0:
            raise HardwareError(out.splitlines()[-1] if out else f"คำสั่งล้มเหลว (exit {res.returncode})")
        return out

    def set_power_mode(self, mode_id: int) -> str:
        modes = (self._power_mode() or {}).get("modes", [])
        if not any(m["id"] == mode_id for m in modes):
            raise HardwareError("ไม่มีโหมดพลังงานนี้")
        out = self._helper("mode", str(mode_id))
        if re.search(r"reboot", out, re.I):
            raise HardwareError("โหมดนี้ต้องรีบูตเครื่องก่อนจึงจะมีผล — สั่งบน Jetson: sudo nvpmodel -m %d แล้วตอบ YES" % mode_id)
        return out

    def set_clocks_max(self, on: bool) -> str:
        return self._helper("clocks", "on" if on else "off")

    def set_fan(self, mode: str, percent: Optional[int] = None) -> str:
        if mode == "manual":
            if percent is None or not 20 <= percent <= 100:
                raise HardwareError("ความเร็วพัดลมต้องอยู่ระหว่าง 20–100%")
            out = self._helper("fan", "manual", str(percent))
            self._start_watchdog()
            return out
        if mode not in ("quiet", "cool"):
            raise HardwareError("โหมดพัดลมต้องเป็น quiet, cool หรือ manual")
        return self._helper("fan", "profile", mode)

    def _start_watchdog(self) -> None:
        """While the fan is fixed below 100 %, run it at 100 % if the chip gets hot (it stays fixed)."""
        if self._watchdog and self._watchdog.is_alive():
            return

        def watch() -> None:
            while (pct := _read(STATE_DIR / "fan-manual")) is not None:
                hottest = max((t["c"] for t in self._temperatures()), default=0.0)
                if hottest >= FAN_SAFETY_C and pct != "100":
                    logger.warning("Jetson at %.1f°C with the fan fixed at %s%%: raising it to 100%%", hottest, pct)
                    try:
                        self._helper("fan", "manual", "100")
                    except HardwareError as exc:
                        logger.error("Could not raise the fan speed: %s", exc)
                time.sleep(5)

        self._watchdog = threading.Thread(target=watch, daemon=True, name="FanSafetyWatchdog")
        self._watchdog.start()

    def resume_watchdog(self) -> None:
        """At startup: a fixed fan speed set before a restart is still watched."""
        if is_jetson() and (STATE_DIR / "fan-manual").exists():
            self._start_watchdog()


hardware_service = HardwareService()
