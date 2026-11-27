# OneDeploy backend

## Deploying a service

Create a project and service using the authenticated `/projects` and
`/projects/{project_id}/services` APIs. Then:

1. `POST /projects/{project_id}/services/{service_id}/github` with
   `{"repository_url":"https://github.com/owner/repository"}` to clone a
   public GitHub repository into OneDeploy's managed workspace.
2. `POST /projects/{project_id}/services/{service_id}/build` to build its
   root `Dockerfile` as a versioned image. Each build receives a new `v1`,
   `v2`, etc. tag; `latest` remains an alias for the newest successful build.
3. `POST /projects/{project_id}/services/{service_id}/containers` with optional
   `ports` (for example `{"8000/tcp":8000}`), `environment` mappings, and
   `image_version` to enqueue a deployment. The API returns a `pending`
   deployment record; poll the deployment history endpoint for its state.
   Omitting `image_version` deploys the latest successfully built immutable
   version.

`GET /projects/{project_id}/services/{service_id}/image-versions` lists build
history, and `GET /projects/{project_id}/services/{service_id}/deployments`
lists deployment attempts and their state (`pending`, `building`, `running`,
`failed`, or `rolled_back`). To roll a deployment back, call
`POST /projects/{project_id}/services/{service_id}/deployments/{deployment_id}/rollback`.
This enqueues a new deployment of the most recent earlier successful image;
the target attempt is marked `rolled_back` after the rollback succeeds.
Previous versioned images are kept for future rollbacks.

The service-scoped container endpoints list containers, retrieve logs, start,
stop, restart, and remove them. A reachable Docker Engine is required by both
the API and worker; they must connect to the same Engine. Its connection is
configured using the Docker SDK's standard environment settings. GitHub
cloning currently supports public HTTPS repositories on `github.com`.

## Queue and worker

Redis is the RQ queue backend. Set `REDIS_URL` (default
`redis://localhost:6379/0`) and `DATABASE_URL`. From `Backend`, start Redis
with Docker Compose:

```powershell
docker compose up -d redis
uv run python -c "from redis import Redis; from core.config import settings; print(Redis.from_url(settings.REDIS_URL).ping())"
```

Start the recurring health-check scheduler once, then run the RQ scheduler
and worker in separate terminals:

```powershell
uv run python -m services.schedule_health_checks
uv run rqscheduler --url redis://localhost:6379/0
```

Run the RQ worker in a separate terminal:

```powershell
uv run rq worker --with-scheduler deployments health
```

The RQ worker consumes deployment jobs and scheduled health checks.
Health-check progress is persisted in Postgres, so it survives worker restarts.
Deployment responses include an RQ `queue_job_id`, which can be inspected with
`GET /projects/{project_id}/services/{service_id}/deployments/{deployment_id}/job`.
Deployment jobs retry twice after transient Docker errors. Builds remain
synchronous API operations. Rollback is manual; deployments are not
automatically reverted when health checks detect a bad release.

## Health monitoring

The worker's scheduled watchdog polls OneDeploy containers. It checks Docker
status, an optional `com.onedeploy.health-url` label, and memory usage.
Containers with `com.onedeploy.auto-heal=false` are excluded.

An incident is opened after three failed polls by default. The watchdog waits
briefly before restarting, rechecks health, and resolves or escalates the
incident. Restart attempts are capped at three per container.

Incident settings can be overridden with `WATCHDOG_INTERVAL_SECONDS`,
`WATCHDOG_FAILED_CHECKS`, `WATCHDOG_MAX_RESTART_ATTEMPTS`, and
`WATCHDOG_MEMORY_PERCENT_THRESHOLD`. Deployments with a configured
`health_url` are not marked `running` until it responds successfully, up to
`DEPLOYMENT_HEALTH_TIMEOUT_SECONDS` (30 seconds by default).