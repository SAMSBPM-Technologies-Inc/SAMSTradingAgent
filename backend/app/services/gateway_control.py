"""
IB Gateway Recovery
───────────────────
Two ways to get the broker session back, deliberately separated because they
carry very different risk.

`force_reconnect()` asks the adapter to open a session now instead of waiting
out the backoff in `broker._reconnect_loop` (15s → 300s). It needs no special
privileges and fixes the common case: the gateway is up and authenticated, but
this process is holding a dead socket.

`restart_gateway()` restarts the gateway container. It is the only thing that
helps when the gateway itself is unauthenticated — after IBKR's weekend
maintenance, or a 2FA prompt nobody answered — and it is **off by default**,
because restarting a sibling container requires the host Docker socket inside
the API container, which is effectively root on the host.

Enable it only if you want that trade: set `ALLOW_GATEWAY_RESTART=true` and
mount the socket (see docker-compose.prod.yml). The runbook in
`runbooks/ib-gateway-offline.md` covers doing it over SSH instead, which needs
no such grant.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

from app.config import get_settings
from app.services import broker as ibkr
from app.utils.logger import get_logger

logger = get_logger(__name__)

#: IBC needs roughly 90–120s to complete login after a restart. Callers should
#: present this rather than implying the session is back the moment we return.
GATEWAY_LOGIN_SECONDS = 120

_DOCKER_SOCKET = "/var/run/docker.sock"


class GatewayControlUnavailable(RuntimeError):
    """Restart was requested but this deployment is not set up to allow it."""


@dataclass
class RecoveryResult:
    action: str
    connected: bool
    detail: str
    #: True when the caller should expect to wait (and possibly answer 2FA)
    #: rather than treating `connected=False` as failure.
    pending: bool = False


async def force_reconnect() -> RecoveryResult:
    """
    Attempt a broker connection immediately.

    Safe to call at any time and safe to call repeatedly — `broker.connect` is
    idempotent when a session already exists, and the background reconnect loop
    keeps running either way.
    """
    if ibkr.is_connected():
        return RecoveryResult(
            action="reconnect", connected=True,
            detail="Already connected — nothing to do.",
        )

    try:
        connected = await ibkr.connect()
    except Exception as exc:
        logger.warning("force_reconnect_failed", error=str(exc))
        return RecoveryResult(
            action="reconnect", connected=False,
            detail=f"Could not reach the gateway: {exc}",
        )

    if connected:
        logger.info("force_reconnect_succeeded")
        return RecoveryResult(
            action="reconnect", connected=True,
            detail="Reconnected to IB Gateway.",
        )

    logger.info("force_reconnect_no_session")
    return RecoveryResult(
        action="reconnect", connected=False,
        detail=(
            "The gateway did not accept a session. It is usually unauthenticated "
            "rather than down — after IBKR's weekend maintenance or an unanswered "
            "2FA prompt, only a gateway restart clears it."
        ),
    )


def restart_available() -> tuple[bool, str]:
    """Whether `restart_gateway` can run here, and why not if it cannot."""
    settings = get_settings()
    if not settings.allow_gateway_restart:
        return False, (
            "Gateway restart is disabled on this server. Set "
            "ALLOW_GATEWAY_RESTART=true and mount the Docker socket to enable it, "
            "or restart the container over SSH."
        )
    import os

    if not os.path.exists(_DOCKER_SOCKET):
        return False, (
            "ALLOW_GATEWAY_RESTART is set but the Docker socket is not mounted "
            "into this container, so it cannot reach the gateway."
        )
    return True, ""


async def restart_gateway() -> RecoveryResult:
    """
    Restart the IB Gateway container, then let the reconnect loop pick it up.

    Deliberately does not wait for the session: IBC login takes ~2 minutes and
    may require someone to approve a 2FA push on their phone. Blocking an HTTP
    request on that would time out and tell the caller nothing useful, so this
    returns `pending` and the UI explains what to expect.
    """
    ok, reason = restart_available()
    if not ok:
        raise GatewayControlUnavailable(reason)

    settings = get_settings()
    name = settings.gateway_container_name

    # Talked to over the socket with curl rather than pulling in the docker SDK
    # for one call. The API image already has neither; this keeps the dependency
    # surface where it is.
    proc = await asyncio.create_subprocess_exec(
        "curl", "--silent", "--show-error", "--fail",
        "--unix-socket", _DOCKER_SOCKET,
        "-X", "POST",
        f"http://localhost/containers/{name}/restart?t=30",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()

    if proc.returncode != 0:
        message = (stderr or b"").decode().strip() or f"exit {proc.returncode}"
        logger.error("gateway_restart_failed", container=name, error=message)
        return RecoveryResult(
            action="restart", connected=False,
            detail=f"Could not restart {name}: {message}",
        )

    logger.info("gateway_restart_requested", container=name)
    return RecoveryResult(
        action="restart",
        connected=False,
        pending=True,
        detail=(
            f"Restarting {name}. IBC login takes about {GATEWAY_LOGIN_SECONDS} "
            "seconds. If IBKR sends a two-factor prompt, approve it on your phone "
            "or the session will not come up. The backend reconnects on its own "
            "once the gateway is ready."
        ),
    )
