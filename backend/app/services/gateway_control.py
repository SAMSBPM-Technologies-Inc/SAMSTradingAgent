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
maintenance, or a 2FA prompt nobody answered.

It goes through a **filtered Docker proxy**, never the host socket. Handing this
container the raw socket would be root on the host; the proxy answers only the
container endpoints and refuses images, volumes, networks, exec and the rest.
That is a much smaller grant, not zero — see the `dockerproxy` service in
docker-compose.prod.yml for exactly what it allows.

Still gated on `ALLOW_GATEWAY_RESTART` so a deployment can decline the capability
entirely. `runbooks/ib-gateway-offline.md` covers recovering over SSH, which
needs no grant at all.
"""
from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.config import get_settings
from app.services import broker as ibkr
from app.utils.logger import get_logger

logger = get_logger(__name__)

#: IBC needs roughly 90–120s to complete login after a restart. Callers should
#: present this rather than implying the session is back the moment we return.
GATEWAY_LOGIN_SECONDS = 120

#: Docker's own default stop timeout before it escalates to SIGKILL. IB Gateway
#: is a JVM and wants a moment to shut down cleanly.
_RESTART_TIMEOUT_SECONDS = 30


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
            "ALLOW_GATEWAY_RESTART=true to enable it, or restart the container "
            "over SSH — see runbooks/ib-gateway-offline.md."
        )
    if not settings.docker_proxy_url:
        return False, (
            "ALLOW_GATEWAY_RESTART is set but DOCKER_PROXY_URL is empty, so there "
            "is no Docker endpoint to reach the gateway through."
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
    url = f"{settings.docker_proxy_url.rstrip('/')}/containers/{name}/restart"

    # Plain HTTP to the filtered proxy — no docker SDK, no unix socket, and
    # nothing added to the image's dependency surface.
    try:
        async with httpx.AsyncClient(timeout=_RESTART_TIMEOUT_SECONDS + 15) as client:
            resp = await client.post(url, params={"t": _RESTART_TIMEOUT_SECONDS})
    except Exception as exc:
        logger.error("gateway_restart_unreachable", container=name, error=str(exc))
        return RecoveryResult(
            action="restart", connected=False,
            detail=f"Could not reach the Docker proxy to restart {name}: {exc}",
        )

    # 204 is success. 404 means the container name is wrong, and 403 means the
    # proxy refused the endpoint — distinct problems worth distinguishing.
    if resp.status_code == 404:
        logger.error("gateway_restart_container_missing", container=name)
        return RecoveryResult(
            action="restart", connected=False,
            detail=f"No container named {name}. Check GATEWAY_CONTAINER_NAME.",
        )
    if resp.status_code in (401, 403):
        logger.error("gateway_restart_forbidden", container=name, status=resp.status_code)
        return RecoveryResult(
            action="restart", connected=False,
            detail=(
                "The Docker proxy refused the restart. It needs CONTAINERS=1 and "
                "POST=1 — see the dockerproxy service in docker-compose.prod.yml."
            ),
        )
    if resp.status_code >= 400:
        body = (resp.text or "").strip()[:200]
        logger.error("gateway_restart_failed", container=name, status=resp.status_code, body=body)
        return RecoveryResult(
            action="restart", connected=False,
            detail=f"Could not restart {name}: HTTP {resp.status_code} {body}",
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
