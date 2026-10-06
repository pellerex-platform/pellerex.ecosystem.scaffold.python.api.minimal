# RepoUniqueNormalisedIdentifier — FastAPI Managed API scaffold

A minimal, **parity-complete** FastAPI scaffold for the Pellerex Managed API Service product.
It satisfies the same platform contract as the .NET/Go/Node minimal scaffolds, so the generic
provisioning chain runs against it with no special-casing.

## What you get

- **FastAPI + uvicorn** on port **<port-number>** (`uvicorn app.main:app --host 0.0.0.0 --port <port-number>`).
- Health routes at the **root**: `/health/startup`, `/health/live`, `/health/ready` (no `/api`).
- A sample router (`/v1/hello`, `/v1/echo`) with Pydantic request/response models.
- Config via **pydantic-settings** (env + `config.{env}.json`), validated at boot (fail fast).
- Secrets read from the **CSI tmpfs file mount** via `secrets_dir` — never env vars, never etcd.
- Telemetry via the first-party **`azure-monitor-opentelemetry`** distro (auto-instruments FastAPI).
- **Structured logging** (Serilog parity, all stdlib): JSON console + daily-rolling
  `log-<date>.log`/`.json` files + App Insights (the distro exports the `app` logger) —
  enriched with service name/version/environment and a per-request `X-Correlation-Id`.
- Multi-stage **`python:3.12-slim`** Dockerfile (builder venv → clean slim runtime), non-root.
- Helm chart (`Deployment`+`Service`+`serviceaccount`, no k8s probes) with pod/container
  hardening: read-only root FS, dropped capabilities, `runAsNonRoot`, seccomp `RuntimeDefault`.
  There is no `Ingress`: ProxyApi is the only front door to the product.
- CI pipeline: `pip install` → `pip-audit` → `pytest` → docker build → push.

## Layout

```
app/                 FastAPI app: main.py, config.py (Settings + Secrets), telemetry.py,
                     logging_config.py (JSON console + rolling file sinks),
                     middleware.py (correlation id + request log), routers/
config.{env}.json    Per-env config (carries the tokenised App Insights connection string)
tests/               pytest: routes, config validation, secret-from-tmpfs read
infrastructure/      Helm chart, secret-provider-class-{env}.yaml, azure-containers-pipelines.yml
start/               run-local.sh, run-docker.sh, setup-secrets.sh
Dockerfile           multi-stage python:3.12-slim
requirements.txt     pinned runtime deps
```

## Run locally

```bash
./start/setup-secrets.sh          # seeds ~/.pellerex/secrets/<product>/ from secrets.example (one file per secret)
./start/run-local.sh              # http://127.0.0.1:<port-number> — reads secrets from the local mount (prod parity)
curl http://127.0.0.1:<port-number>/health/ready
```

## Run in Docker

```bash
./start/run-docker.sh
curl http://127.0.0.1:<port-number>/health/ready
```

## Test

```bash
pip install -r requirements-dev.txt
pytest -q
pip-audit --strict --requirement requirements.txt
```

## Logging (Serilog parity)

Structured logging via the **stdlib `logging` module** (no extra dependencies), fanned out to
three sinks like the .NET scaffold's Serilog:

1. **Console** — JSON to stdout (always; collected by the platform). uvicorn's lifecycle logs
   flow through the same sinks; its plain access log is replaced by one structured request
   line per request.
2. **Files** — daily-rolling `log-<date>.log` (text) + `log-<date>.json` (JSON) under
   `log_file_directory` (default `logs` locally, `/var/log/app` in-cluster on a writable
   `emptyDir`), pruned after `log_retention_days`.
3. **Azure Application Insights** — `configure_azure_monitor` attaches the first-party OTel
   exporter to the `app` logger, so every `app.*` record also lands in App Insights
   (in-process, no collector).

Every record carries `service.name` / `service.version` / `deployment.environment`; every
request is logged with a correlation id (inbound `X-Correlation-Id` honoured, otherwise a
UUID; always echoed on the response). Settings precedence: env var (`LOG_LEVEL`,
`LOG_FILE_ENABLED`, `LOG_FILE_DIRECTORY`, `LOG_RETENTION_DAYS`) > `config.{env}.json` > default.

## Config & secrets

| Concern | Source | Notes |
|---|---|---|
| Config | env vars + `config.{ENVIRONMENT}.json` | `ENVIRONMENT` is required; validated at boot |
| App Insights connection string | `config.{env}.json` token | `<azure-app-insights-connection-string-in-{env}>` |
| Secret material (e.g. DB) | CSI tmpfs file mount (`/mnt/secrets-store`) | one file per secret, read via `secrets_dir`; never env |

The Key Vault *name* is the only secret-related value tokenised into the repo
(`secret-provider-class-{env}.yaml`); no secret value ever lands in the repo, image, config,
etcd, or process environment.

## Tokens

`RepoUniqueNormalisedIdentifier`, `RepoUniqueIdentifier`, `<marketplace-product-id>`,
`<{env}-namespace>`, `<{env}-keyvault-name>`, `<secret-provider-class-enabled>`,
`<azure-app-insights-connection-string-in-{env}>`, `<target-branch>`, `<identity-id>`,
`<tenant-id>` are substituted at `InstallRepoTemplate`. The container **port is the
`<port-number>` token**, provisioned platform-wide.
