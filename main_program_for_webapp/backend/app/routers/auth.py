"""Control lease and operator session endpoints."""
from typing import Optional
from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel

from ..config import settings
from ..core.schemas import ControlLease
from ..core.security import lease_manager

router = APIRouter(prefix="/api/auth", tags=["auth"])


class AcquireLeaseRequest(BaseModel):
    operator_name: str = "Operator"
    passcode: Optional[str] = None
    force: bool = False


class LeaseResponse(BaseModel):
    success: bool
    operator_token: Optional[str] = None
    operator_id: Optional[str] = None  # Alias for backward compatibility
    message: str
    lease: ControlLease


@router.get("/lease", response_model=ControlLease)
def get_lease():
    """Get the current control lease status (publicly visible info only)."""
    return lease_manager.get_lease_info()


@router.post("/acquire", response_model=LeaseResponse)
def acquire_lease(req: AcquireLeaseRequest, request: Request):
    """Request exclusive operator control over stage and scan operations."""
    client_ip = request.client.host if request.client else "unknown"

    # Enforce passcode if station passcode is set
    if settings.operator_passcode:
        if not req.passcode or req.passcode != settings.operator_passcode:
            raise HTTPException(status_code=403, detail="Invalid or missing operator passcode.")
    elif req.force:
        raise HTTPException(status_code=403, detail="Cannot force takeover without a configured system passcode.")

    # Only permit takeover (force) if caller has the correct passcode
    success, token, message = lease_manager.acquire_lease(
        operator_name=req.operator_name,
        client_ip=client_ip,
        force=req.force
    )

    if not success:
        return LeaseResponse(
            success=False,
            operator_token=None,
            operator_id=None,
            message=message,
            lease=lease_manager.get_lease_info()
        )

    return LeaseResponse(
        success=True,
        operator_token=token,
        operator_id=token,
        message=message,
        lease=lease_manager.get_lease_info()
    )


@router.post("/renew")
def renew_lease(
    x_operator_token: Optional[str] = Header(None, alias="X-Operator-Token"),
    x_operator_id: Optional[str] = Header(None, alias="X-Operator-Id")
):
    """Renew the active control lease TTL."""
    token = x_operator_token or x_operator_id
    if not token or not lease_manager.renew_lease(token):
        raise HTTPException(status_code=403, detail="Active operator lease required to renew.")
    return {"success": True, "lease": lease_manager.get_lease_info()}


@router.post("/release")
def release_lease(
    x_operator_token: Optional[str] = Header(None, alias="X-Operator-Token"),
    x_operator_id: Optional[str] = Header(None, alias="X-Operator-Id")
):
    """Voluntarily release operator control lease."""
    token = x_operator_token or x_operator_id
    if not token or not lease_manager.release_lease(token):
        raise HTTPException(status_code=400, detail="Cannot release lease: not current operator.")
    return {"success": True, "message": "Lease released."}

