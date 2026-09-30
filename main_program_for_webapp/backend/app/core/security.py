"""Control lease management and role-based authorization for LAN operation."""
from __future__ import annotations

import threading
import time
import uuid
from typing import Optional, Tuple
from .schemas import ControlLease


class ControlLeaseManager:
    """Manages exclusive operator control lease for stage and scan operations.
    
    Prevents race conditions when multiple LAN devices (e.g. iPad and PC)
    view the station simultaneously.
    """

    def __init__(self, ttl_seconds: float = 20.0):
        self.ttl_seconds = ttl_seconds
        self._lock = threading.Lock()
        self._operator_token: Optional[str] = None
        self.operator_name: Optional[str] = None
        self.client_ip: Optional[str] = None
        self.granted_at: Optional[float] = None
        self.expires_at: Optional[float] = None

    def get_lease_info(self) -> ControlLease:
        with self._lock:
            now = time.monotonic()
            is_active = (
                self._operator_token is not None
                and self.expires_at is not None
                and now < self.expires_at
            )
            if not is_active and self._operator_token is not None:
                # Lease expired
                self._operator_token = None
                self.operator_name = None
                self.client_ip = None
                self.granted_at = None
                self.expires_at = None

            return ControlLease(
                active_operator_id=None,  # Never expose credential token publicly
                client_ip=self.client_ip,
                granted_at=self.granted_at,
                expires_at=self.expires_at,
                is_controlled=bool(self._operator_token),
                operator_name=self.operator_name
            )

    def is_operator(self, token: Optional[str]) -> bool:
        """Check if the provided private token matches the active control lease."""
        if not token:
            return False
        with self._lock:
            now = time.monotonic()
            if self._operator_token is None or self.expires_at is None or now >= self.expires_at:
                return False
            return self._operator_token == token

    def acquire_lease(
        self,
        operator_name: str,
        client_ip: str,
        force: bool = False
    ) -> Tuple[bool, str, str]:
        """Attempt to acquire the control lease.
        
        Returns (success, operator_token, message).
        The operator_token is a private secret returned only to the successful caller.
        """
        with self._lock:
            now = time.monotonic()
            is_active = (
                self._operator_token is not None
                and self.expires_at is not None
                and now < self.expires_at
            )

            if is_active and not force:
                return (
                    False,
                    "",
                    f"Station is currently controlled by '{self.operator_name}' from {self.client_ip}."
                )

            new_token = uuid.uuid4().hex
            self._operator_token = new_token
            self.operator_name = operator_name or "Operator"
            self.client_ip = client_ip
            self.granted_at = now
            self.expires_at = now + self.ttl_seconds

            return (True, new_token, "Control lease acquired successfully.")

    def renew_lease(self, token: Optional[str]) -> bool:
        """Renew the active lease TTL using the private token."""
        if not token:
            return False
        with self._lock:
            now = time.monotonic()
            if (
                self._operator_token is not None
                and self._operator_token == token
                and self.expires_at is not None
                and now < self.expires_at
            ):
                self.expires_at = now + self.ttl_seconds
                return True
            return False

    def release_lease(self, token: Optional[str]) -> bool:
        """Release the control lease voluntarily using the private token."""
        if not token:
            return False
        with self._lock:
            if self._operator_token is not None and self._operator_token == token:
                self._operator_token = None
                self.operator_name = None
                self.client_ip = None
                self.granted_at = None
                self.expires_at = None
                return True
            return False


lease_manager = ControlLeaseManager()

