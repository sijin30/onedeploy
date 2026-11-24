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