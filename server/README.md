# MMC Server — 24/7 self-hosted stack

This folder is the single-host server layout for MMC. It keeps the existing
OTC implementation untouched and adds the Real Market cloud browser, local
PostgreSQL storage, continuous Real Market signal generation, health checks,
and automatic container restart.

## Services

- `mmc-web` — existing MMC web/API application.
- `postgres` — local persistent PostgreSQL database.
- `quotex-real-collector` — headless Chromium collector for Quotex Real Market.
- `real-signal-worker` — continuous Real Market signal engine.

Docker Compose uses `restart: unless-stopped` so crashed containers are
restarted automatically. Health checks also gate startup dependencies.

## Windows laptop setup

1. Install Docker Desktop and keep WSL2 enabled.
2. Copy `server/.env.server.example` to `server/.env.server`.
3. Set a strong `POSTGRES_PASSWORD`.
4. Set the existing `QUOTEX_INGEST_SECRET` used by MMC.
5. Set `QUOTEX_REAL_ASSET=AUDCAD` for the first Real Market test.
6. Provide either `QUOTEX_STORAGE_STATE_B64` or the optional Quotex login
   variables. Do not put credentials in GitHub or chat.
7. From the repository root run:

   `docker compose --env-file server/.env.server -f server/docker-compose.yml up -d --build`

8. Check the stack:

   `docker compose --env-file server/.env.server -f server/docker-compose.yml ps`

9. Follow logs:

   `docker compose --env-file server/.env.server -f server/docker-compose.yml logs -f quotex-real-collector real-signal-worker`

10. Stop the stack only when intentionally shutting the server down:

   `docker compose --env-file server/.env.server -f server/docker-compose.yml down`

## 8 GB RAM profile

Start with one Chromium browser and one Real Market pair. Keep the laptop
awake, disable Windows sleep/hibernate while plugged in, and avoid running
other heavy applications. If memory pressure appears, reduce background apps
before adding more pairs.

## Security

`server/.env.server` is ignored by Git. Never commit `QUOTEX_INGEST_SECRET`,
Quotex credentials, or browser storage state. The collector only handles Real
Market data; it deliberately does not handle OTC data.

## Moving to a VPS later

The same Compose stack can be moved to a Linux VPS. The application layout is
not tied to Windows, and persistent PostgreSQL data is stored in the named
Docker volume `mmc-postgres-data`.
