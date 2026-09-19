# Domain And TLS Deployment Preparation

This repository's supported production shape is a single-process Docker
Compose deployment. The current Compose file publishes the frontend over HTTP
on port 80 and the backend on port 8000 for local health checks. It does not
provision DNS, certificates, a public domain, or a remote reverse proxy.

This document records the configuration steps for a later domain/TLS rollout.
It is intentionally operational guidance only: it does not authorize changes
to a server, DNS zone, certificate store, or production data.

## Target topology

The registered domain is `dscourse.cn`, confirmed by the owner on 2026-09-19.
The examples below use its apex as the proposed application origin. The earlier
handoff preferred `agent.dscourse.cn`; choose the final hostname before setting
DNS, issuing a certificate, and configuring production CORS.

The current deployment host's public IPv4 address is `39.108.81.31`. Before
cutover, create an `A` record for the selected hostname pointing to this address.
As of 2026-09-19, direct HTTP access to the host serves the application and
`/api/health` returns JSON with HTTP 200. `/api/readyz` still returns HTTP 404,
which shows that the public host is running the older application version.
Port 443 does not yet complete a TLS handshake.

Use a TLS-terminating reverse proxy on the deployment host or at the selected
edge provider:

```text
student browser
    |
    | https://dscourse.cn
    v
TLS reverse proxy :443
    |
    | HTTP to the private frontend listener
    v
frontend nginx :80  --->  backend :8000
```

The browser should use one origin for the Vue application and its `/api`
requests. The frontend nginx container keeps proxying `/api` to `backend:8000`,
so the public reverse proxy only needs to forward the site origin to the
frontend container. Bind the backend host port to `127.0.0.1:8000:8000` for
`deploy/update.sh` checks after the proxy is in place. The container health
check and Docker service traffic do not require a published backend port.
If the TLS proxy runs on the host, give the frontend a private listener such
as `127.0.0.1:8080:80` and update `DEPLOY_FRONTEND_URL` to match; the proxy
then owns public ports 80 and 443.

## Configuration before cutover

Set these values in the production secret/configuration mechanism, not in a
committed file:

```dotenv
APP_ENV=production
AUTH_SECRET_KEY=<at-least-32-random-characters>
AUTH_COOKIE_SECURE=true
CORS_ALLOW_ORIGINS=https://dscourse.cn
AUTH_REGISTRATION_MODE=invite
AUTH_INVITE_CODE=<short-lived-class-invite>
```

`CORS_ALLOW_ORIGINS` must contain the exact HTTPS origin, without a path or a
wildcard. If the final hostname changes, update this value before the proxy
starts serving the new origin. `AUTH_COOKIE_SECURE=true` is required for
production readiness and makes the session cookie HTTPS-only.

Keep the existing production protections enabled unless there is an explicit
capacity decision:

- `PYTHON_EXEC_ENABLED=false` unless the Docker sandbox is configured and
  verified.
- `API_PER_STUDENT_REQUESTS_PER_WINDOW=600` and
  `API_REQUEST_QUOTA_WINDOW_SECONDS=3600` for the current single-process
  Compose shape.
- The per-student API quota must remain disabled or be replaced with shared
  limiter state before adding multiple API workers or instances.

## DNS and certificate sequence

Complete these steps with the domain owner and hosting provider:

1. Confirm the canonical hostname under `dscourse.cn` (the examples use
   the apex `dscourse.cn`).
2. Point its DNS record at the TLS edge or deployment host according to the
   provider's instructions. Do not publish the backend port as a DNS target.
3. Provision a certificate for the exact hostname and configure automatic
   renewal before enabling HTTPS-only traffic.
4. Configure the reverse proxy to forward the complete origin to frontend
   port 80 and preserve the request `Host` header. Forward `/api` as part of
   the same origin so browser cookies remain same-site.
5. Allow inbound TCP 443. Keep TCP 8000 private; port 80 may be used only for
   the proxy's HTTP-to-HTTPS redirect or certificate validation.
6. Validate the public `/api/health` and `/api/readyz` paths through the intended proxy
   path, then run the authenticated login, registration, SSE chat, session
   deletion, and assessment flows.

At the frontend, `/health` and `/readyz` fall through to the Vue HTML page;
an HTTP 200 there is not a backend health check. Use the `/api` paths for
public checks and require their JSON response. A production index and its
matching manifest must be installed before `/api/readyz` can return 200.

The exact proxy syntax is provider-specific and belongs in the infrastructure
repository or host configuration, not in this application repository.

## Application checks

Run these checks from the repository checkout before a rollout:

```bash
docker compose -f deploy/compose.yaml config --quiet
python -m pytest tests/test_readiness.py tests/test_api_request_quota.py -q
```

On the host, the deployment script should still use the local readiness URL:

```bash
DEPLOY_BACKEND_URL=http://127.0.0.1:8000/readyz \
DEPLOY_FRONTEND_URL=http://127.0.0.1/ \
./deploy/update.sh
```

The external TLS health check is a separate post-cutover check. Do not change
`deploy/update.sh` to require the public hostname unless the host's DNS and
certificate lifecycle are managed together with that script.

## Cutover and rollback notes

- Take a runtime backup before changing the public entry point. Follow
  [`runtime_backup_runbook.md`](runtime_backup_runbook.md).
- Apply configuration and certificate changes before switching DNS or traffic.
- Verify `/readyz` locally and the public HTTPS origin independently.
- Confirm that the browser receives a `Secure` session cookie and that SSE
  remains connected through the proxy.
- Keep the previous image tags and proxy configuration available until login,
  chat, session deletion, and assessment smoke checks pass.
- If the public check fails, restore the prior proxy/DNS target first, then use
  the Compose rollback path. Do not delete runtime databases or chat history as
  part of a web rollback.

## Open decisions

The following require an explicit deployment decision before implementation:

- DNS and certificate ownership, renewal, and alerting.
- Whether the TLS proxy runs on the same host, a managed edge, or a school
  network gateway.
- Whether port 8000 can be removed from the host publish list after health
  checks move inside the Compose network.
- The load model and shared limiter design if the backend becomes multi-worker
  or multi-instance.
