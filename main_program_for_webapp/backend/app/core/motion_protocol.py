"""Protocol v2 implementation for Nano XY Stage."""
import math
import time
from typing import Callable, List, Optional, Tuple


def raster_points(
    x: float,
    y: float,
    columns: int,
    rows: int,
    pitch_x: float,
    pitch_y: float,
    steps_per_mm: float,
    limits: Tuple[int, int]
) -> List[Tuple[int, int]]:
    """Generate serpentine raster scan points in machine steps."""
    values = (x, y, pitch_x, pitch_y, steps_per_mm)
    if not all(math.isfinite(v) for v in values) or min(x, y, pitch_x, pitch_y) < 0 or steps_per_mm <= 0:
        raise ValueError("Coordinates and pitch must be finite and non-negative; steps/mm must be positive.")
    if not (1 <= columns <= 100 and 1 <= rows <= 100 and columns * rows <= 400):
        raise ValueError("Use 1–400 scan points.")
    points = []
    for row in range(rows):
        col_range = range(columns) if row % 2 == 0 else reversed(range(columns))
        for col in col_range:
            point = (
                round((x + col * pitch_x) * steps_per_mm),
                round((y + row * pitch_y) * steps_per_mm)
            )
            if not (0 <= point[0] <= limits[0] and 0 <= point[1] <= limits[1]):
                raise ValueError("Scan exceeds machine travel limits. Reduce origin, pitch or point count.")
            points.append(point)
    if len(set(points)) != len(points):
        raise ValueError("Scan contains duplicate positions. Increase the pitch.")
    return points


class MotionClient:
    """Nonblocking serial pump for firmware protocol v2."""

    def __init__(
        self,
        transport,
        clock: Callable[[], float] = time.monotonic,
        startup_delay: float = 0.0,
        on_event: Optional[Callable[[str, any], None]] = None
    ):
        self.transport = transport
        self.clock = clock
        self.on_event = on_event
        self.ready = False
        self.homed = False
        self.closed = False
        self.home_verified = False
        self.position = (0, 0)
        self.limits = (21167, 20446)
        self.soft_limits = None
        self.pending = None
        self.sequence = 0
        self.buffer = bytearray()
        self.events = []
        self.started = self.last_rx = self.last_ping = clock()
        self.transmit_after = self.started + startup_delay
        if startup_delay == 0:
            self._write("HELLO")

    def _emit(self, kind: str, data: any = None):
        self.events.append((kind, data))
        if self.on_event:
            try:
                self.on_event(kind, data)
            except Exception:
                pass

    def _write(self, line: str):
        data = (line + "\n").encode("ascii")
        if self.transport.write(data) != len(data):
            raise IOError("Incomplete serial write")
        self._emit("wire", "TX  " + line)

    def command(self, kind: str, x: int = 0, y: int = 0, speed: int = 800) -> int:
        if self.closed or not self.ready:
            raise ValueError("Connect and wait for firmware v2 first.")
        if kind not in ("MOVE", "HOME", "STOP", "OFF"):
            raise ValueError("Unsupported motion command")
        if self.pending and kind not in ("STOP", "OFF"):
            raise ValueError("Wait for the current motion to finish.")
        if kind == "MOVE":
            if not self.homed:
                raise ValueError("HOME is required before moving.")
            max_x = min(self.limits[0], self.soft_limits[0]) if self.soft_limits else self.limits[0]
            max_y = min(self.limits[1], self.soft_limits[1]) if self.soft_limits else self.limits[1]
            if not all(isinstance(v, int) for v in (x, y, speed)) or not (0 <= x <= max_x and 0 <= y <= max_y and 20 <= speed <= 1500):
                raise ValueError("Move is outside travel or speed limits.")
        self.sequence += 1
        timeout = 540 if kind == "HOME" else (
            max(abs(x - self.position[0]), abs(y - self.position[1])) / speed + 15 if kind == "MOVE" else 5
        )
        self.pending = (self.sequence, kind, self.clock() + timeout, (x, y))
        if kind in ("HOME", "OFF"):
            self.homed = False
            self.home_verified = False
        self._write(f"@{self.sequence} {kind}" + (f" {x} {y} {speed}" if kind == "MOVE" else ""))
        return self.sequence

    def _fault(self, message: str):
        if self.closed:
            return
        self._emit("error", message)
        self.close()

    def close(self):
        if self.closed:
            return
        try:
            self._write("STOP")
        except Exception:
            pass
        try:
            self.transport.close()
        finally:
            self.closed = True
            self.ready = self.homed = False
            self.pending = None

    def _line(self, line: str):
        self._emit("wire", "RX  " + line)
        parts = line.split()
        if not parts:
            return
        tag = parts[0]
        try:
            if tag == "[READY]":
                version, x, y, mx, my, homed = map(int, parts[1:])
                if version != 2 or not (0 < mx <= 100000 and 0 < my <= 100000) or homed not in (0, 1):
                    raise ValueError("Unsupported firmware or invalid travel limits")
                if self.ready and (self.pending or self.home_verified or self.position != (x, y)):
                    raise ValueError("Controller restarted; reconnect and HOME again")
                self.limits, self.position = (mx, my), (x, y)
                self.ready, self.homed = True, False
                self._emit("ready", None)
            elif tag in ("[POS]", "[DONE]", "[ERR]"):
                ident = int(parts[1])
                fields = parts[3:] if tag == "[ERR]" else parts[2:]
                x, y, homed = map(int, fields)
                if homed not in (0, 1):
                    raise ValueError("Invalid home status")
                if tag == "[ERR]":
                    raise ValueError("Controller: " + parts[2])
                if tag == "[DONE]" and (not self.pending or ident != self.pending[0]):
                    return
                if tag == "[DONE]" and self.pending[1] == "HOME" and homed:
                    self.home_verified = True
                self.position, self.homed = (x, y), bool(homed) and self.home_verified
                if tag == "[DONE]":
                    _, kind, _, target = self.pending
                    if kind == "MOVE" and (not self.homed or self.position != target):
                        raise ValueError("Move completion does not match requested position")
                    if kind == "HOME" and not self.homed:
                        raise ValueError("HOME did not complete")
                    self.pending = None
                    self._emit("done", kind)
            elif tag == "[ACK]":
                if len(parts) != 2:
                    raise ValueError("Malformed acknowledgement")
            else:
                return
            self.last_rx = self.clock()
        except (ValueError, TypeError) as exc:
            self._fault(str(exc))

    def tick(self):
        if self.closed:
            return
        try:
            self.buffer.extend(self.transport.read(min(self.transport.in_waiting, 4096)))
            if len(self.buffer) > 16384:
                raise IOError("Serial input exceeded buffer limit")
            while b"\n" in self.buffer and not self.closed:
                line, _, remainder = self.buffer.partition(b"\n")
                self.buffer = bytearray(remainder)
                self._line(line.decode("ascii", errors="replace").strip())
            if self.closed:
                return
            now = self.clock()
            if now >= self.transmit_after and now - self.last_ping >= 1.0:
                self._write("POS" if self.ready else "HELLO")
                self.last_ping = now
            if not self.ready and now - self.started > 8.0:
                raise IOError("No firmware v2 handshake. Check port, baud and connection.")
            if self.ready and now - self.last_rx > 6.0:
                raise IOError("Motion link lost; scan stopped. Reconnect and HOME.")
            if self.pending and now > self.pending[2]:
                raise IOError("Motion completion timed out; scan stopped.")
        except Exception as exc:
            self._fault(str(exc))


class SimulatedTransport:
    """Software simulator for the XY stage; never touches serial hardware."""

    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self.clock = clock
        self.buffer = bytearray()
        self.position = (0, 0)
        self.homed = False
        self.job = None
        self.closed = False

    def emit(self, text: str):
        self.buffer.extend((text + "\n").encode())

    @property
    def in_waiting(self) -> int:
        if self.job and self.clock() >= self.job[0]:
            _, ident, kind, target = self.job
            self.position = target
            if kind == "HOME":
                self.homed = True
            self.job = None
            self.emit(f"[DONE] {ident} {self.position[0]} {self.position[1]} {int(self.homed)}")
        return len(self.buffer)

    def read(self, size: int) -> bytes:
        data = bytes(self.buffer[:size])
        del self.buffer[:size]
        return data

    def write(self, data: bytes) -> int:
        if self.closed:
            raise IOError("Simulator disconnected")
        parts = data.decode().strip().split()
        if not parts:
            return len(data)
        ident = int(parts.pop(0)[1:]) if parts[0].startswith("@") else 0
        kind = parts[0]
        if kind == "HELLO":
            self.emit(f"[READY] 2 {self.position[0]} {self.position[1]} 21167 20446 {int(self.homed)}")
        elif kind == "POS":
            self.emit(f"[POS] {self.job[1] if self.job else 0} {self.position[0]} {self.position[1]} {int(self.homed)}")
        elif kind in ("HOME", "MOVE"):
            target = tuple(map(int, parts[1:3])) if kind == "MOVE" else (0, 0)
            self.job = (self.clock() + 0.15, ident, kind, target)
            self.emit(f"[ACK] {ident}")
        elif kind in ("STOP", "OFF"):
            if kind == "OFF" or (self.job and self.job[2] == "HOME"):
                self.homed = False
            self.job = None
            self.emit(f"[DONE] {ident} {self.position[0]} {self.position[1]} {int(self.homed)}")
        return len(data)

    def close(self):
        self.closed = True
