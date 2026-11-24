# OneDeploy backend

## Deploying a service

Create a project and service using the authenticated `/projects` and
`/projects/{project_id}/services` APIs. Then:

1. `POST /projects/{project_id}/services/{service_id}/github` with
   `{"repository_url":"https://github.com/owner/repository"}` to clone a
   public GitHub repository into OneDeploy's managed workspace.
2. `POST /projects/{project_id}/services/{service_id}/build` to build its
   root `Dockerfile` as a service-tagged image.
3. `POST /projects/{project_id}/services/{service_id}/containers` with optional
   `ports` (for example `{"8000/tcp":8000}`) and `environment` mappings to
   start a container.

The service-scoped container endpoints list containers, retrieve logs, start,
stop, restart, and remove them. A reachable Docker Engine is required; its
connection is configured using the Docker SDK's standard environment settings.
GitHub cloning currently supports public HTTPS repositories on `github.com`.

## Health monitoring

The watchdog runs in the FastAPI process and polls OneDeploy containers. It
checks Docker status, an optional `com.onedeploy.health-url` label, and memory
usage. Containers with `com.onedeploy.auto-heal=false` are excluded.

An incident is opened after three failed polls by default. The watchdog waits
briefly before restarting, rechecks health, and resolves or escalates the
incident. Restart attempts are capped at three per container.

Incident settings can be overridden with `WATCHDOG_INTERVAL_SECONDS`,
`WATCHDOG_FAILED_CHECKS`, `WATCHDOG_MAX_RESTART_ATTEMPTS`, and
`WATCHDOG_MEMORY_PERCENT_THRESHOLD`.