<div align="center">

English | [中文](README.cn.md)

**Video App** - A self-hosted video metadata, streaming and browsing platform over local filesystem and S3-compatible storage

[![Python](https://img.shields.io/badge/Python-3.12-blue?logo=python)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.128-009688?logo=fastapi)](https://fastapi.tiangolo.com/)
[![Strawberry](https://img.shields.io/badge/Strawberry%20GraphQL-0.289-ff6b9d)](https://strawberry.rocks/)
[![Angular](https://img.shields.io/badge/Angular-22-dd0031?logo=angular)](https://angular.dev/)
[![MongoDB](https://img.shields.io/badge/MongoDB-Beanie%20ODM-47A248?logo=mongodb)](https://www.mongodb.com/)
[![Docker](https://img.shields.io/badge/Docker-compose-2496ed?logo=docker)](https://www.docker.com/)

</div>

---

## Introduction

Video App is a full-stack application for managing, browsing and playing your own video library. Point it at existing directories or S3 buckets in the configuration and it scans them, generates thumbnails, and lets you manage metadata — titles, authors, tags, series, favourites — through a web UI.

Storage sits behind a strategy interface, so a local disk and an S3-compatible bucket (MinIO, RustFS, …) are browsed, played and migrated the same way. Long-running work such as file migration runs in a process-wide worker pool fully decoupled from client connections: closing the tab never interrupts a task, and a task left unfinished by a restart resumes from the phase it stopped at.

## Architecture

The backend is organised by business capability, not by technical layer, with a strictly one-way dependency chain:

```
resolvers/ + schema/   GraphQL delivery — validate, delegate, map
        ↓
features/              catalog · browsing · playback · migration
        ↓
platform/              storage · media · cache · jobs (reusable, knows no feature)
```

**The direction is enforced, not just documented.** `tests/unit/test_architecture.py` parses every module's imports and fails the build if a feature imports strawberry or a GraphQL type, if a resolver imports a document model, or if `platform/` imports a feature. A reversed import is invisible in review and in green tests — it only surfaces later as a service that cannot be reused and a directory-walk test that has to build a GraphQL schema.

<!-- TODO: architecture diagram -->

## Tech Stack

### Backend

| Technology | Version | Purpose |
| ---------- | ------- | ------- |
| Python | 3.12+ | Language (managed by [uv](https://docs.astral.sh/uv/)) |
| FastAPI | 0.128.0 | Web framework |
| Strawberry GraphQL | 0.289.2 | GraphQL server (queries, mutations, WebSocket subscriptions, custom scalars) |
| MongoDB + Beanie | 2.0.1 | Database + async ODM |
| Motor / PyMongo | 3.7+ / 4.16 | Async MongoDB driver |
| Pydantic | 2.12.5 | Input contracts and settings |
| boto3 | 1.42+ | S3-compatible storage |
| cachetools | 6.2+ | In-memory TTL cache |
| loguru | 0.7+ | Structured logging |
| envyaml | 1.10+ | `$VAR\|default` substitution in `config.yaml` |
| pytest | 8.0+ | Testing (unit + GraphQL + integration) |

### Frontend

| Technology | Version | Purpose |
| ---------- | ------- | ------- |
| Angular | 22.1 | UI framework (standalone, signals, zoneless) |
| Signal Forms | 22.1 | The only form implementation; no `ReactiveFormsModule` |
| TypeScript | 6.0 | Language |
| Apollo Angular | 13.0 | GraphQL client |
| graphql-ws | 6.0 | WebSocket subscriptions |
| Angular Material | 22.1 | UI component library |
| Tailwind CSS | 4.1 | Styling framework |
| Video.js | 8.23 | Video player |
| graphql-codegen | 6.1 | TypeScript types + Apollo services generation |
| Vitest | 4.0 | Unit testing |

### Deployment

| Technology | Version | Purpose |
| ---------- | ------- | ------- |
| Docker Compose | - | Orchestration (frontend / backend / MongoDB / RustFS) |
| Nginx | alpine | Frontend server + reverse proxy |
| ffmpeg / ffprobe | - | Thumbnails, duration probing, on-the-fly transcoding |
| RustFS / MinIO | - | S3-compatible object storage (optional) |

## Features

### Catalog & Search

- **Paginated search** across title, author and tags, with category filtering and five sort options (Latest Viewed, Last Updated, Most Viewed, Loved, Longest).
- **Autocomplete** for titles, authors and tags; tag suggestions are ranked by reference count, with prefix matches ahead of substring matches.
- **Metadata editing** — title, author, introduction, tags, favourite, series. Tag reference counts move by the difference between the old and new sets, so a tag that survives an edit is neither double-counted nor dropped.
- **View tracking** — view counts and last-viewed timestamps, merged into the page without a re-query.

### Directory Browsing & Batch Operations

- **Three-level navigation** — root → category → configured mount point → filesystem entries, over local disks and S3 buckets alike.
- **Batched document sync** — entering a directory resolves all its videos in one query and at most one bulk write; `ffprobe` runs only for entries whose duration is missing.
- **In-directory recursive search** by name, author and tags. A MongoDB query narrows the candidates and a storage walk confirms which files still exist, so deleted-but-still-recorded entries never surface as playable.
- **Batch edit and delete** over a selection or a whole directory, with progress streamed over WebSocket. One request carries both `addTags` and `removeTags`, resolved as `(old | add) - remove`.
- **Explicit empty-folder visibility** — folders you created or chose to keep stay listed even when empty; folders you deleted stay hidden regardless of what is still inside them.

### Series Management

- **Ordered series** with autocomplete over existing names (substring match, prefix matches first).
- **Series are documents of their own** — each one is a name plus the ordered list of its members' ids, and a video only points back at its series. Position is the index in that list, so there is no stored number to drift: gaps and duplicate order values cannot occur, and a video leaving a series (edited out, moved elsewhere, or deleted) simply closes up behind it.
- **Reordering a subset is safe** — the batch panel sends a relative sequence and the backend decides the placement, so reordering three videos inside a series of five moves only those three and leaves the rest where they are.
- **Empty series disappear** — when the last member leaves, the series document is removed, so autocomplete never offers a name with nothing behind it.

### Playback & Thumbnails

- **Range-request streaming** in 1 MB chunks for `mp4`/`webm`; other formats are transcoded to fragmented MP4 on the fly.
- **Thumbnails** generated with ffmpeg, optionally persisted to S3. The storage key is derived from the video's ObjectId, so it survives renames and migrations, and keys written by the old naming scheme are detected and regenerated lazily.
- **Series side panel** on the player page, auto-scrolled to the video being played and refreshed in place when any listed entry changes.

### File Migration & Background Tasks

- **Preflight checks** — source exists, free space, name conflicts, active tasks, same-location detection — with `rename` / `overwrite` / `skip` conflict strategies.
- **Three-phase state machine** — copy, repoint the database, clean up the source — with a crash-recovery matrix that resumes from the phase a restart interrupted rather than starting over.
- **Tasks outlive connections** — migrations run in a worker pool sized by `tasks.max_concurrent`. Subscribing never starts a task and unsubscribing never stops one, so refreshing the page or watching from several tabs is safe.
- **Migration locks propagate** — every query returning a video fills an `isLocked` flag in one batched lookup, and the UI disables every entry point for locked rows. Each mutation re-checks independently, so bypassing the UI is refused too.

### Storage Abstraction

- **Declarative backend selection** — `handler_config` names a `type` per category and a lookup table maps it to a handler class. Adding a backend is two registrations; the dispatcher does not change.
- **Local filesystem and S3** behind one interface, including directory creation and deletion, which S3 has no native concept of.
- **Configuration errors fail at startup** — a misspelled storage type is rejected by a Pydantic discriminated union during `init_settings()`, not on the first user request.

## Quick Start

Requirements:

| Dependency | Version | Required | Notes |
| ---------- | ------- | -------- | ----- |
| Python | 3.12+ | Yes | Backend runtime |
| uv | latest | Yes | Python package manager |
| Node.js | 24+ | Yes | Frontend build |
| MongoDB | 6.0+ | Yes | Database |
| ffmpeg / ffprobe | - | Yes | Thumbnails, duration, transcoding |
| Docker | - | Recommended | One-command deployment (see below) |

> If you prefer not to install MongoDB locally, start just that service from `docker-compose.yml`.

### 1. Clone the project

```bash
git clone <repository-url>
cd video-app
```

### 2. Install uv

```bash
# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 3. Configure the backend

Edit `config.yaml`. It uses [envyaml](https://github.com/thesimj/envyaml) syntax — `$ENV_VAR|default_value`:

```yaml
# Leave empty for local development; Docker sets it via environment variable
ROOT_PATH: $ROOT_PATH|

# Video resource paths (category -> pseudo_name -> host path)
resource_paths:
  Local-resource:
    Resource-1: /your/video/path1
    Resource-2: /your/video/path2

mongo:
  host: $MONGO_HOST|localhost
  port: $MONGO_PORT|27017
  database: $MONGO_DATABASE|video_tag_db
  username: $MONGO_USERNAME|          # leave empty if auth is disabled
  password: $MONGO_PASSWORD|
```

Make sure MongoDB is running — either a local installation or the container from `docker-compose.yml`. A user with CRUD, collection and index permissions on `video_tag_db` is optional if auth is disabled.

See [Configuration Reference](#configuration-reference) for every option, including S3 storage and thumbnail persistence.

### 4. Start the application

**Backend:**

```bash
uv sync
uv run main.py
```

The backend runs at `http://localhost:12000`.

**Frontend:**

Point `front-end/video-app-front/src/environments/environment.development.ts` at the backend:

```typescript
export const environment = {
    production: false,
    backend_api: "http://localhost:12000",
    // ... keep the rest as-is
}
```

```bash
cd front-end/video-app-front
npm install

# Only needed when the backend GraphQL schema changed
npm run codegen

npm start
```

The frontend runs at `http://localhost:4200`.

## Docker Deployment

Docker Compose orchestrates four services: the Angular frontend (Nginx), the FastAPI backend, MongoDB, and RustFS as S3-compatible storage. Data is persisted through bind mounts, so `docker-compose down` does not lose it.

### 1. Prerequisites

- [Docker](https://www.docker.com/products/docker-desktop/) and Docker Compose
- The host directories holding the videos you want to serve

### 2. Map your video directories

Edit `docker-compose.yml` and point the backend volumes at your library. The container path must read `/app/resources/<Category>/<PseudoName>`:

```yaml
backend:
  volumes:
    - ./logs:/app/logs
    - /your/video/path1:/app/resources/Local-resource/Resource-1
    - /your/video/path2:/app/resources/Local-resource/Resource-2
  environment:
    - ROOT_PATH=/app/resources
    - MONGO_HOST=mongodb
    # Optional S3 storage — overrides config.yaml for Docker networking
    # - S3_RESOURCE_1_ENDPOINT_URL=http://rustfs:9000
    # - S3_RESOURCE_1_ACCESS_KEY=rustfsadmin
    # - S3_RESOURCE_1_SECRET_KEY=rustfsadmin
    # - S3_RESOURCE_1_BUCKET=video-app
```

Declare the same categories in `config.yaml`:

```yaml
resource_paths:
  Local-resource:
    Resource-1: /your/video/path1
    Resource-2: /your/video/path2
```

> To use the bundled RustFS service, uncomment the S3 environment variables above along with the `handler_config` and `thumbnail_config` sections in `config.yaml`.

### 3. Start

```bash
docker-compose up -d
```

### 4. Service access

| Service | Address | Default user | Default password | Notes |
| ------- | ------- | ------------ | ---------------- | ----- |
| **Frontend** | [http://localhost](http://localhost) | - | - | Web UI |
| **Backend API** | [http://localhost:12000](http://localhost:12000) | - | - | GraphQL + REST |
| **MongoDB** | `localhost:27017` | - | - | Database (`video_tag_db`) |
| **RustFS console** | [http://localhost:10086](http://localhost:10086) | `rustfsadmin` | `rustfsadmin` | Object storage management |
| **RustFS API** | `localhost:9000` | `rustfsadmin` | `rustfsadmin` | S3-compatible endpoint |

### 5. Common operations

```bash
# Service status
docker-compose ps

# Backend logs
docker-compose logs -f backend

# Rebuild and redeploy after pulling new code
docker-compose up -d --build

# Live-reload during development
docker-compose watch

# Stop and remove services (bind-mounted data is kept)
docker-compose down

# Prune intermediate build layers
docker image prune -f
```

## Upgrading

### Series moved into their own collection

Earlier versions stored a series as `seriesName` / `seriesOrder` on every video. The backend now reads series only from the `series` collection, so **an existing database must be migrated once before starting the new backend** — otherwise every series appears empty.

Back up the database, then run from the project root on the host (the Docker image does not ship `scripts/`; point `config.yaml` at the MongoDB instance, e.g. `localhost:27017` for the compose service):

```bash
uv run python -m scripts.migrate_series_to_collection
```

The script groups videos by their old series name, keeps the order they used to read in (numbered first, then by name), writes each video's `seriesId`, and removes the old fields and index. It is idempotent — running it again, or after an interrupted run, is safe. The GraphQL API is unchanged, so the frontend needs no rebuild for this.

## Screenshots

<!-- TODO: screenshots -->

## Project Structure

```
video-app/
├── main.py                          # Backend entry (localhost:12000)
├── config.yaml                      # Configuration (envyaml syntax)
├── Dockerfile                       # Backend image
├── docker-compose.yml               # frontend + backend + MongoDB + RustFS
├── pyproject.toml                   # Dependencies and metadata
│
├── scripts/
│   └── migrate_series_to_collection.py  # One-off: legacy series fields → series collection
│
├── src/
│   ├── app.py                       # App factory: logging, Mongo, TaskRunner boot, CORS, routers
│   ├── config.py                    # Settings (Pydantic + envyaml), handler config union
│   ├── context.py                   # DI container: 13 services + path-lock registry
│   ├── errors.py                    # Custom exceptions
│   ├── logger.py                    # loguru configuration
│   │
│   ├── db/
│   │   └── setup_mongo.py           # Mongo client + Beanie init (registers the 5 documents)
│   │
│   ├── platform/                    # ── Reusable core; imports no feature ──
│   │   ├── cache/                   # base_cache · cachetools_cache · cache_service
│   │   ├── media/
│   │   │   └── ffmpeg_service.py    # Thumbnails, duration, transcoding (semaphore-gated)
│   │   ├── storage/                 # Strategy pattern over storage backends
│   │   │   ├── base_resource_handler.py   # Abstract handler + HandlerBuildSpec
│   │   │   ├── base_file_entry.py         # File entry abstraction + FileStat
│   │   │   ├── absolute_path.py           # DB path ↔ FS path conversion
│   │   │   ├── resource_handler_service.py# storage_type → handler class lookup
│   │   │   ├── local_fs/                  # os.scandir + aiofiles
│   │   │   └── s3/                        # boto3, presigned URLs, prefix listing
│   │   └── jobs/                    # Generic background-task template
│   │       ├── task_model.py        # TaskStatus + BaseTaskModel (progress via accessors)
│   │       ├── progress.py          # ProgressFrame — unit-agnostic current/total
│   │       ├── state_machine.py     # TaskStateMachine[TTask] — 3 phases, crash recovery
│   │       ├── task_runner.py       # FIFO queue, worker pool, progress broadcast
│   │       └── path_locks.py        # PathLockRegistry — "is this path busy?"
│   │
│   ├── features/                    # ── Business capabilities ──
│   │   ├── catalog/                 # Video metadata
│   │   │   ├── video.py · video_tag.py · series.py  # Documents
│   │   │   ├── catalog_service.py         # Search, suggest, update, record view, delete
│   │   │   ├── series_service.py          # Sole writer of series membership and order
│   │   │   └── tag_operation_service.py   # Tag reference counts
│   │   ├── browsing/                # Directory browsing and batch operations
│   │   │   ├── dir_metadata.py · dir_metadata_service.py
│   │   │   ├── directory_deletion.py      # DirectoryDeletionStrategy
│   │   │   ├── browse_file_service.py     # 3-level navigation, in-directory search
│   │   │   └── batch_operation_service.py # Batch update/delete, streaming progress
│   │   ├── playback/                # Streaming and thumbnails (REST)
│   │   │   └── video_stream_service.py · thumbnail_service.py · video_router.py
│   │   └── migration/               # File migration
│   │       ├── migration_task.py          # Extends BaseTaskModel
│   │       └── migration_service.py       # TaskStateMachine subclass
│   │
│   ├── resolvers/                   # ── GraphQL delivery: validate → delegate → map ──
│   │   ├── query_resolver.py · mutation_resolver.py
│   │   └── subscription_resolver.py · migration_resolver.py
│   │
│   └── schema/                      # ── GraphQL types and schema assembly ──
│       ├── strawberry_schema.py     # Schema + BigInt scalar + error logging
│       ├── query_schema.py · mutation_schema.py · subscription_schema.py
│       └── types/
│           ├── video_type.py · search_type.py · fileBrowse_type.py
│           ├── migration_type.py · scalars.py
│           └── pydantic_types/      # GraphQL input contracts
│
├── tests/                           # 703 cases (pytest --strict-markers), 90% coverage
│   ├── conftest.py                  # test_settings, MongoDB, document factories
│   ├── unit/                        # Mirrors src/
│   │   ├── test_architecture.py     # Dependency-direction guards (AST scan)
│   │   ├── test_context_wiring.py · test_task_runner_bootstrap.py
│   │   ├── platform/                # cache · jobs · media · storage
│   │   ├── features/                # catalog · browsing · playback · migration
│   │   ├── scripts/                 # One-off data migrations
│   │   └── schema/                  # Pydantic input contracts
│   ├── graphql/                     # Resolver tests (queries, mutations, subscriptions)
│   └── integration/                 # End-to-end (testcontainers MongoDB)
│
└── front-end/video-app-front/
    ├── codegen.ts                   # GraphQL codegen config
    ├── Dockerfile · nginx.conf      # Two-stage build → Nginx + reverse proxy
    └── src/app/
        ├── app.ts · app.routes.ts · app.config.ts   # Root, routes, Apollo (HTTP + WS links)
        ├── core/graphql/
        │   ├── documents/           # queries · mutations · subscription · migration
        │   └── generated/graphql.ts # Auto-generated — never edit by hand
        ├── pages/
        │   ├── homepage/            # Loved / Latest / Last updated / Most viewed + tag cloud
        │   ├── search/              # Filters, sorting, pagination
        │   ├── video-player/        # Player on top, details + series below
        │   ├── file-browser/        # Directory navigation, selection, batch operations
        │   └── management/          # Migration task list
        ├── services/
        │   ├── GQL-service/         # Centralised GraphQL access, ResultState<T>
        │   ├── Http-client-service/ · Page-state-service/ · path-history-service/
        │   ├── migration-tracker-service/ # Tab-scoped owner of progress subscriptions
        │   ├── theme-service/ · toast-service/
        │   ├── validation-service/  # validation.service.ts + validation.rules.ts
        │   └── video-update-event-service/ # Cross-tab event bus (BroadcastChannel)
        └── shared/
            ├── components/
            │   ├── video-card/ · pagination/ · header/ · sidebar/ · toast-displayer/
            │   ├── video-player-host/     # The only file importing video.js
            │   ├── video-edit-panel/ · batch-operation-panel/ · delete-check-panel/
            │   ├── new-folder-panel/ · search-panel/ · migration-panel/
            │   ├── file-browse-table/ · bottom-toolbar/ · migration-task-list/
            │   ├── series-panel/ · series-reorder-list/ · series-name-input/
            │   └── tag-chip-input/        # FormValueControl<string[]>
            ├── interceptor/ · models/
            └── environments/
```

> **Adding a background task type**: subclass `BaseTaskModel` (declaring its own `Settings.name`) and `TaskStateMachine[YourModel]`, implement the three phases, then register it with `TaskRunner.register_executor(key, executor)`. The scheduler needs no changes — a test drives a non-migration task type through the template to prove it.

> **Adding a storage backend**: declare `storage_type` on the handler, implement `from_config(spec)`, add it to `_HANDLER_TYPES`, and add a category config model to the `HandlerConfig` union. `_create_handler` does not change, and two guard tests pin the two registrations to each other.

## Configuration Reference

`config.yaml` uses [envyaml](https://github.com/thesimj/envyaml) syntax: `$ENV_VAR|default_value`.

```yaml
# Container mount base path (set via env var in Docker, empty for local dev)
ROOT_PATH: $ROOT_PATH|

# Video resource path mapping (category -> pseudo_name -> host path)
resource_paths:
  Local-resource:                             # Local filesystem category
    Resource-1: /your/video/path1
    Resource-2: /your/video/path2
  # S3-resource:                              # S3-compatible category
  #   Resource-1: /                           # host path is unused for S3

# Storage backend per category. A category with no entry is served by the local
# filesystem. `type` is the lookup key; a misspelling fails at startup.
# handler_config:
#   S3-resource:
#     type: s3
#     mounts:
#       Resource-1:
#         endpoint_url: $S3_RESOURCE_1_ENDPOINT_URL|http://localhost:9000
#         access_key: $S3_RESOURCE_1_ACCESS_KEY|admin
#         secret_key: $S3_RESOURCE_1_SECRET_KEY|admin
#         bucket: $S3_RESOURCE_1_BUCKET|video-app
#         region: $S3_RESOURCE_1_REGION|us-east-1

# Thumbnail persistence (optional, needs S3-compatible storage).
# Without it, thumbnails are generated on the fly and not persisted.
# thumbnail_config:
#   storage_category: S3-resource
#   storage_pseudo_name: Resource-1

cache_config:
  max_size: 2048                 # Maximum cache entries
  ttl: 300                       # Expiry in seconds
  cache_type: cachetools

# Effective value is max(ffmpeg_semaphore_limit, cpu_count // 2)
ffmpeg_semaphore_limit: 4

suggestion_limit:
  name: 10
  author: 10
  tag: 20

video_extensions:
  - .mp4
  - .avi
  - .mkv
  - .mov
  - .wmv
  - .flv
  - .webm
  - .m4v
  - .mpg
  - .mpeg

# Must stay in sync with the frontend's environment.ts
validation:
  name_max_length: 200
  author_max_length: 50
  introduction_max_length: 2000
  tag_max_length: 30
  max_tags_count: 50
  page_number_min: 1
  page_number_max: 10000
  series_name_max_length: 100

tasks:
  max_concurrent: 2              # Concurrent tasks; also the worker pool size. Migrations
                                 # are IO-bound, so a high value mostly makes them compete
                                 # for bandwidth.
  progress_flush_interval: 3.0   # Seconds between progress writes to MongoDB. Live progress
                                 # is held in memory, so this only bounds how stale the task
                                 # list looks to a client with no active subscription.

logging:
  log_dir: logs
  rotation: "10 MB"
  retention: "30 days"

mongo:
  host: $MONGO_HOST|localhost
  port: $MONGO_PORT|27017
  database: $MONGO_DATABASE|video_tag_db
  username: $MONGO_USERNAME|
  password: $MONGO_PASSWORD|
```

### Frontend environment

| File | `backend_api` | Meaning |
| ---- | ------------- | ------- |
| `environment.development.ts` | `"http://localhost:12000"` | Points at the local backend |
| `environment.ts` | `""` | Relative paths, proxied by Nginx |