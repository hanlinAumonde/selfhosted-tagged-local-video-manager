<div align="center">

[English](README.md) | 中文

**Video App** - 面向本地文件系统与 S3 兼容存储的自托管视频元数据管理、流媒体播放与浏览平台

[![Python](https://img.shields.io/badge/Python-3.12-blue?logo=python)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.128-009688?logo=fastapi)](https://fastapi.tiangolo.com/)
[![Strawberry](https://img.shields.io/badge/Strawberry%20GraphQL-0.289-ff6b9d)](https://strawberry.rocks/)
[![Angular](https://img.shields.io/badge/Angular-22-dd0031?logo=angular)](https://angular.dev/)
[![MongoDB](https://img.shields.io/badge/MongoDB-Beanie%20ODM-47A248?logo=mongodb)](https://www.mongodb.com/)
[![Docker](https://img.shields.io/badge/Docker-compose-2496ed?logo=docker)](https://www.docker.com/)

</div>

---

## 项目介绍

Video App 是一个用于管理、浏览和播放自有视频库的全栈应用。在配置中把已有的目录或 S3 bucket 映射进来，它会自动扫描、生成缩略图，并通过 Web 界面管理视频元数据——标题、作者、标签、系列、收藏。

存储位于策略接口之后，所以本地磁盘和 S3 兼容存储（MinIO、RustFS 等）在浏览、播放、迁移上的行为完全一致。文件迁移这类长耗时工作跑在进程级 worker 池里，与客户端连接彻底解耦：关掉标签页不会中断任务，进程重启时未完成的任务会从中断的那个阶段继续，而不是从头再来。

## 系统架构

后端按**业务能力**垂直切分，而非按技术分层，依赖严格单向：

```
resolvers/ + schema/   GraphQL 交付层 —— 校验、委托、映射
        ↓
features/              catalog · browsing · playback · migration
        ↓
platform/              storage · media · cache · jobs（可复用内核，不认识任何 feature）
```

**这个方向是被钉死的，不只是写在文档里。** `tests/unit/test_architecture.py` 扫描每个模块的 import，只要 feature 引入了 strawberry 或 GraphQL 类型、resolver 引入了文档模型、或 `platform/` 引入了 feature，构建就会失败。反向依赖在 code review 和绿色测试里都是隐形的——它只会在很久之后，以「这个服务没法复用」和「测个目录遍历还得建 GraphQL schema」的形式暴露。

<!-- TODO: 架构图 -->

## 技术栈

### 后端技术

| 技术 | 版本 | 说明 |
| ---- | ---- | ---- |
| Python | 3.12+ | 开发语言（由 [uv](https://docs.astral.sh/uv/) 管理） |
| FastAPI | 0.128.0 | Web 框架 |
| Strawberry GraphQL | 0.289.2 | GraphQL 服务端（查询、变更、WebSocket 订阅、自定义标量） |
| MongoDB + Beanie | 2.0.1 | 数据库 + 异步 ODM |
| Motor / PyMongo | 3.7+ / 4.16 | 异步 MongoDB 驱动 |
| Pydantic | 2.12.5 | 输入契约与配置 |
| boto3 | 1.42+ | S3 兼容存储 |
| cachetools | 6.2+ | 内存 TTL 缓存 |
| loguru | 0.7+ | 结构化日志 |
| envyaml | 1.10+ | `config.yaml` 的 `$VAR\|default` 语法支持 |
| pytest | 8.0+ | 测试（单元 + GraphQL + 集成） |

### 前端技术

| 技术 | 版本 | 说明 |
| ---- | ---- | ---- |
| Angular | 22.1 | UI 框架（Standalone、Signals、zoneless） |
| Signal Forms | 22.1 | 全部表单的唯一实现，无 `ReactiveFormsModule` |
| TypeScript | 6.0 | 开发语言 |
| Apollo Angular | 13.0 | GraphQL 客户端 |
| graphql-ws | 6.0 | WebSocket 订阅 |
| Angular Material | 22.1 | UI 组件库 |
| Tailwind CSS | 4.1 | 样式框架 |
| Video.js | 8.23 | 视频播放器 |
| graphql-codegen | 6.1 | TypeScript 类型 + Apollo Service 自动生成 |
| Vitest | 4.0 | 单元测试 |

### 部署技术

| 技术 | 版本 | 说明 |
| ---- | ---- | ---- |
| Docker Compose | - | 容器编排（前端 / 后端 / MongoDB / RustFS） |
| Nginx | alpine | 前端服务器 + 反向代理 |
| ffmpeg / ffprobe | - | 缩略图、时长探测、实时转码 |
| RustFS / MinIO | - | S3 兼容对象存储（可选） |

## 功能特性

### 视频目录与搜索

- **分页搜索**：按标题、作者、标签过滤，支持分类筛选和五种排序（最近观看、最近更新、最多观看、收藏、最长）。
- **自动补全**：标题、作者、标签三个字段均支持；标签建议按引用计数排序，前缀匹配优先于包含匹配。
- **元数据编辑**：标题、作者、简介、标签、收藏、系列。标签引用计数按新旧集合的**差值**增减，所以一次编辑里存活下来的标签既不会被重复计数，也不会被误减。
- **观看统计**：观看次数与最后观看时间，成功后局部合并进当前页面，不重新查询整条记录。

### 目录浏览与批量操作

- **三级导航**：根目录 → 分类 → 配置的挂载点 → 文件系统条目，本地磁盘和 S3 bucket 一视同仁。
- **批量文档解析**：进入一个目录时，所有视频一次查询解析完，最多一次 bulk write；只有缺失时长的条目才会跑 `ffprobe`。
- **目录内递归搜索**：按名称、作者、标签查找。MongoDB 查询负责**收窄**候选集，遍历存储负责**确认**文件还在，所以「库里有记录、磁盘上已删除」的条目不会被当成可播放的东西端出来。
- **批量编辑与删除**：可按选中项或整个目录执行，进度经 WebSocket 实时推送。一次请求同时携带 `addTags` 和 `removeTags`，按 `(old | add) - remove` 一次解析。
- **空文件夹的可见性是显式的**：你新建的、或删除视频时选择保留的文件夹，空着也照常列出；你删掉的文件夹，无论里面还剩什么都不再出现。

### 系列管理

- **有序系列**：系列名自动补全（子串匹配，前缀优先）。
- **系列是独立的文档**：每个系列是一个名字加上成员 id 的有序列表，视频只保存指向所属系列的引用。位置就是列表下标，没有需要维护的编号，所以不会出现空号或重复号；视频离开系列（被移出、移到别的系列、或被删除）时，后面的成员自动前移。
- **重排子集是安全的**：批量面板发的是**相对顺序**，落位由后端决定，所以在一个 5 集的系列里重排其中 3 个，只会移动这 3 个，其余成员留在原位。
- **空系列自动消失**：最后一个成员离开时系列文档随之删除，自动补全不会给出一个没有任何视频的名字。

### 播放与缩略图

- **Range 流式播放**：`mp4`/`webm` 按 1MB 分块直接流式传输；其他格式实时转码为 fragmented MP4。
- **缩略图**：由 ffmpeg 生成，可选持久化到 S3。存储 key 由视频的 ObjectId 推导，所以重命名和迁移后依然有效；旧命名方案写入的 key 会被识别并惰性重新生成。
- **播放页系列侧栏**：自动滚动定位到当前播放的视频，列表中任一条目变化时原地刷新。

### 文件迁移与后台任务

- **迁移预检**：源文件存在性、剩余空间、命名冲突、活跃任务、同位置检测，冲突时提供 `rename` / `overwrite` / `skip` 三种策略。
- **三阶段状态机**：复制 → 改数据库记录 → 清理源文件，配一张崩溃恢复矩阵，进程重启后从中断的那个阶段继续，而不是一律从头开始。
- **任务活得比连接长**：迁移跑在由 `tasks.max_concurrent` 决定大小的 worker 池里。订阅不启动任务、退订不终止任务，所以刷新页面、多标签页同时观察都安全。
- **迁移锁会传播**：每个返回视频的查询都会用一次批量查找填充 `isLocked`，前端据此禁用所有入口。后端各 mutation 另有独立校验，绕过 UI 直接发请求同样会被拒绝。

### 存储抽象

- **声明式选择后端**：`handler_config` 为每个分类声明一个 `type`，由一张查表映射到 handler 类。新增一种后端只需两处登记，分发器一行不改。
- **本地文件系统与 S3 共用一套接口**，包括 S3 本身没有的目录创建与删除概念。
- **配置错误在启动时就失败**：拼错的存储类型会被 Pydantic discriminated union 在 `init_settings()` 阶段挡下，而不是变成某个用户第一次访问该分类时的报错。

## 快速开始

环境要求：

| 依赖 | 版本 | 必需 | 说明 |
| ---- | ---- | ---- | ---- |
| Python | 3.12+ | 是 | 后端运行时 |
| uv | 最新 | 是 | Python 包管理器 |
| Node.js | 24+ | 是 | 前端构建 |
| MongoDB | 6.0+ | 是 | 数据库 |
| ffmpeg / ffprobe | - | 是 | 缩略图、时长、转码 |
| Docker | - | 推荐 | 一键部署（见下文） |

> 不想本地装 MongoDB 的话，可以只启动 `docker-compose.yml` 里的那一个服务。

### 1. 克隆项目

```bash
git clone <repository-url>
cd video-app
```

### 2. 安装 uv

```bash
# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 3. 配置后端

编辑 `config.yaml`，它使用 [envyaml](https://github.com/thesimj/envyaml) 的 `$ENV_VAR|default_value` 语法：

```yaml
# 本地开发留空；Docker 通过环境变量注入
ROOT_PATH: $ROOT_PATH|

# 视频资源路径（分类 -> pseudo_name -> 宿主机路径）
resource_paths:
  Local-resource:
    Resource-1: /your/video/path1
    Resource-2: /your/video/path2

mongo:
  host: $MONGO_HOST|localhost
  port: $MONGO_PORT|27017
  database: $MONGO_DATABASE|video_tag_db
  username: $MONGO_USERNAME|          # 无鉴权时留空
  password: $MONGO_PASSWORD|
```

确保 MongoDB 正在运行——本地安装或 `docker-compose.yml` 里的容器都可以。若开启鉴权，需要一个在 `video_tag_db` 上有 CRUD、集合和索引权限的用户；不开启则无需。

完整选项（含 S3 存储与缩略图持久化）见 [配置参考](#配置参考)。

### 4. 启动应用

**后端：**

```bash
uv sync
uv run main.py
```

后端服务启动于 `http://localhost:12000`。

**前端：**

先把 `front-end/video-app-front/src/environments/environment.development.ts` 指向后端：

```typescript
export const environment = {
    production: false,
    backend_api: "http://localhost:12000",
    // ... 其余保持默认
}
```

```bash
cd front-end/video-app-front
npm install

# 仅在后端 GraphQL schema 变更后需要
npm run codegen

npm start
```

前端服务启动于 `http://localhost:4200`。

## Docker 快速部署

Docker Compose 编排了 4 个服务：Angular 前端（Nginx）、FastAPI 后端、MongoDB、以及作为 S3 兼容存储的 RustFS。数据通过 bind mount 持久化，`docker-compose down` 不会丢失。

### 1. 前置准备

- 安装 [Docker](https://www.docker.com/products/docker-desktop/) 和 Docker Compose
- 准备好要提供服务的宿主机视频目录

### 2. 映射视频目录

编辑 `docker-compose.yml`，把 backend 的 volumes 指向你的视频库。容器内路径必须写成 `/app/resources/<分类>/<PseudoName>`：

```yaml
backend:
  volumes:
    - ./logs:/app/logs
    - /your/video/path1:/app/resources/Local-resource/Resource-1
    - /your/video/path2:/app/resources/Local-resource/Resource-2
  environment:
    - ROOT_PATH=/app/resources
    - MONGO_HOST=mongodb
    # 可选的 S3 存储——为 Docker 网络覆盖 config.yaml 的默认值
    # - S3_RESOURCE_1_ENDPOINT_URL=http://rustfs:9000
    # - S3_RESOURCE_1_ACCESS_KEY=rustfsadmin
    # - S3_RESOURCE_1_SECRET_KEY=rustfsadmin
    # - S3_RESOURCE_1_BUCKET=video-app
```

在 `config.yaml` 里声明同样的分类：

```yaml
resource_paths:
  Local-resource:
    Resource-1: /your/video/path1
    Resource-2: /your/video/path2
```

> 要使用内置的 RustFS 服务，把上面的 S3 环境变量连同 `config.yaml` 里的 `handler_config` 和 `thumbnail_config` 一起取消注释。

### 3. 启动

```bash
docker-compose up -d
```

### 4. 服务访问

| 服务 | 地址 | 默认账号 | 默认密码 | 说明 |
| ---- | ---- | -------- | -------- | ---- |
| **前端应用** | [http://localhost](http://localhost) | - | - | 用户访问入口 |
| **后端 API** | [http://localhost:12000](http://localhost:12000) | - | - | GraphQL + REST |
| **MongoDB** | `localhost:27017` | - | - | 数据库（`video_tag_db`） |
| **RustFS 控制台** | [http://localhost:10086](http://localhost:10086) | `rustfsadmin` | `rustfsadmin` | 对象存储管理 |
| **RustFS API** | `localhost:9000` | `rustfsadmin` | `rustfsadmin` | S3 兼容接口 |

### 5. 常用运维命令

```bash
# 查看服务状态
docker-compose ps

# 查看后端日志
docker-compose logs -f backend

# 拉取新代码后重新构建部署
docker-compose up -d --build

# 开发时的热重载
docker-compose watch

# 停止并移除服务（bind mount 的数据保留）
docker-compose down

# 清理构建产生的中间层镜像
docker image prune -f
```

## 版本升级

### 系列迁移到独立集合

旧版本把系列存成每个视频上的 `seriesName` / `seriesOrder`。现在后端只从 `series` 集合读取系列，所以**已有数据库在启动新版后端之前必须迁移一次**，否则所有系列都会显示为空。

先备份数据库，然后在宿主机的项目根目录运行（Docker 镜像不包含 `scripts/`；让 `config.yaml` 指向对应的 MongoDB，例如 compose 里的服务为 `localhost:27017`）：

```bash
uv run python -m scripts.migrate_series_to_collection
```

脚本按旧的系列名分组，保留原来的显示顺序（有编号的在前，同号按名称），回写每个视频的 `seriesId`，并删除旧字段和旧索引。脚本是幂等的：重复运行、或中断后再运行都安全。GraphQL 接口没有变化，前端无需为此重新构建。

## 效果展示

<!-- TODO: 效果截图 -->

## 项目结构

```
video-app/
├── main.py                          # 后端入口（localhost:12000）
├── config.yaml                      # 全局配置（envyaml 语法）
├── Dockerfile                       # 后端镜像构建
├── docker-compose.yml               # 前端 + 后端 + MongoDB + RustFS
├── pyproject.toml                   # 项目依赖与元数据
│
├── scripts/
│   └── migrate_series_to_collection.py  # 一次性：旧系列字段 → series 集合
│
├── src/
│   ├── app.py                       # 应用工厂：日志、Mongo、TaskRunner 启动、CORS、路由
│   ├── config.py                    # Settings（Pydantic + envyaml）、handler 配置 union
│   ├── context.py                   # 依赖注入容器：13 个服务 + 路径锁注册表
│   ├── errors.py                    # 自定义异常
│   ├── logger.py                    # loguru 日志配置
│   │
│   ├── db/
│   │   └── setup_mongo.py           # Mongo 连接 + Beanie 初始化（注册 5 个文档）
│   │
│   ├── platform/                    # ── 可复用内核，不认识任何 feature ──
│   │   ├── cache/                   # base_cache · cachetools_cache · cache_service
│   │   ├── media/
│   │   │   └── ffmpeg_service.py    # 缩略图、时长、转码（信号量限并发）
│   │   ├── storage/                 # 存储后端的策略模式
│   │   │   ├── base_resource_handler.py   # 抽象 handler + HandlerBuildSpec
│   │   │   ├── base_file_entry.py         # 文件条目抽象 + FileStat
│   │   │   ├── absolute_path.py           # 逻辑路径 ↔ 物理路径转换
│   │   │   ├── resource_handler_service.py# storage_type → handler 类的查表分发
│   │   │   ├── local_fs/                  # os.scandir + aiofiles
│   │   │   └── s3/                        # boto3、预签名 URL、前缀列举
│   │   └── jobs/                    # 通用后台任务模板
│   │       ├── task_model.py        # TaskStatus + BaseTaskModel（进度走访问器）
│   │       ├── progress.py          # ProgressFrame —— 单位无关的 current/total
│   │       ├── state_machine.py     # TaskStateMachine[TTask] —— 三阶段、崩溃恢复
│   │       ├── task_runner.py       # FIFO 队列、worker 池、进度广播
│   │       └── path_locks.py        # PathLockRegistry —— 「这个路径被占着吗」
│   │
│   ├── features/                    # ── 按业务能力切分 ──
│   │   ├── catalog/                 # 视频元数据
│   │   │   ├── video.py · video_tag.py · series.py  # 文档模型
│   │   │   ├── catalog_service.py         # 搜索、建议、更新、观看记录、删除
│   │   │   ├── series_service.py          # 系列成员关系与顺序的唯一写入方
│   │   │   └── tag_operation_service.py   # 标签引用计数
│   │   ├── browsing/                # 目录浏览与批量操作
│   │   │   ├── dir_metadata.py · dir_metadata_service.py
│   │   │   ├── directory_deletion.py      # DirectoryDeletionStrategy
│   │   │   ├── browse_file_service.py     # 三级浏览、目录内搜索
│   │   │   └── batch_operation_service.py # 批量更新/删除、流式进度
│   │   ├── playback/                # 播放与缩略图（REST）
│   │   │   └── video_stream_service.py · thumbnail_service.py · video_router.py
│   │   └── migration/               # 文件迁移
│   │       ├── migration_task.py          # 继承 BaseTaskModel
│   │       └── migration_service.py       # TaskStateMachine 子类
│   │
│   ├── resolvers/                   # ── GraphQL 交付层：校验 → 委托 → 映射 ──
│   │   ├── query_resolver.py · mutation_resolver.py
│   │   └── subscription_resolver.py · migration_resolver.py
│   │
│   └── schema/                      # ── GraphQL 类型与 schema 装配 ──
│       ├── strawberry_schema.py     # Schema + BigInt 标量 + 错误日志
│       ├── query_schema.py · mutation_schema.py · subscription_schema.py
│       └── types/
│           ├── video_type.py · search_type.py · fileBrowse_type.py
│           ├── migration_type.py · scalars.py
│           └── pydantic_types/      # GraphQL 输入契约
│
├── tests/                           # 703 个用例（pytest --strict-markers），覆盖率 90%
│   ├── conftest.py                  # test_settings、MongoDB、文档 factory
│   ├── unit/                        # 目录结构镜像 src/
│   │   ├── test_architecture.py     # 依赖方向守卫（AST 扫描）
│   │   ├── test_context_wiring.py · test_task_runner_bootstrap.py
│   │   ├── platform/                # cache · jobs · media · storage
│   │   ├── features/                # catalog · browsing · playback · migration
│   │   ├── scripts/                 # 一次性数据迁移
│   │   └── schema/                  # Pydantic 输入契约
│   ├── graphql/                     # 解析器测试（查询、变更、订阅）
│   └── integration/                 # 端到端集成测试（testcontainers MongoDB）
│
└── front-end/video-app-front/
    ├── codegen.ts                   # GraphQL Codegen 配置
    ├── Dockerfile · nginx.conf      # 两阶段构建 → Nginx + 反向代理
    └── src/app/
        ├── app.ts · app.routes.ts · app.config.ts   # 根组件、路由、Apollo（HTTP + WS 分链路）
        ├── core/graphql/
        │   ├── documents/           # queries · mutations · subscription · migration
        │   └── generated/graphql.ts # 自动生成 —— 不要手改
        ├── pages/
        │   ├── homepage/            # 收藏 / 最近观看 / 最近更新 / 最多观看 + 标签云
        │   ├── search/              # 过滤、排序、分页
        │   ├── video-player/        # 播放器在上，信息与系列在下
        │   ├── file-browser/        # 目录导航、选择、批量操作
        │   └── management/          # 迁移任务列表
        ├── services/
        │   ├── GQL-service/         # 中心化 GraphQL 访问，ResultState<T>
        │   ├── Http-client-service/ · Page-state-service/ · path-history-service/
        │   ├── migration-tracker-service/ # 标签页级的进度订阅持有者
        │   ├── theme-service/ · toast-service/
        │   ├── validation-service/  # validation.service.ts + validation.rules.ts
        │   └── video-update-event-service/ # 跨标签页事件总线（BroadcastChannel）
        └── shared/
            ├── components/
            │   ├── video-card/ · pagination/ · header/ · sidebar/ · toast-displayer/
            │   ├── video-player-host/     # 全项目唯一 import video.js 的文件
            │   ├── video-edit-panel/ · batch-operation-panel/ · delete-check-panel/
            │   ├── new-folder-panel/ · search-panel/ · migration-panel/
            │   ├── file-browse-table/ · bottom-toolbar/ · migration-task-list/
            │   ├── series-panel/ · series-reorder-list/ · series-name-input/
            │   └── tag-chip-input/        # FormValueControl<string[]>
            ├── interceptor/ · models/
            └── environments/
```

> **新增一种后台任务类型**：继承 `BaseTaskModel`（在子类上声明自己的 `Settings.name`）和 `TaskStateMachine[YourModel]`，实现三个阶段，再用 `TaskRunner.register_executor(key, executor)` 注册。调度器一行不用改——有一个测试真的定义了第二种非迁移任务类型来证明这一点。

> **新增一种存储后端**：在 handler 上声明 `storage_type`、实现 `from_config(spec)`、加进 `_HANDLER_TYPES`，再往 `HandlerConfig` union 里加一个分类配置模型。`_create_handler` 不变，两条守卫测试把这两处登记互相钉死。

## 配置参考

`config.yaml` 使用 [envyaml](https://github.com/thesimj/envyaml) 语法：`$ENV_VAR|default_value`。

```yaml
# 容器挂载基础路径（Docker 通过环境变量注入，本地开发留空）
ROOT_PATH: $ROOT_PATH|

# 视频资源路径映射（分类 -> pseudo_name -> 宿主机路径）
resource_paths:
  Local-resource:                             # 本地文件系统分类
    Resource-1: /your/video/path1
    Resource-2: /your/video/path2
  # S3-resource:                              # S3 兼容存储分类
  #   Resource-1: /                           # S3 用不到宿主机路径

# 每个分类的存储后端。没有条目的分类由本地文件系统服务。
# `type` 是查表的键，拼错会在启动阶段就失败。
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

# 缩略图持久化存储（可选，需要 S3 兼容存储）。
# 不配置则由 ffmpeg 实时生成，不持久化。
# thumbnail_config:
#   storage_category: S3-resource
#   storage_pseudo_name: Resource-1

cache_config:
  max_size: 2048                 # 最大缓存条目数
  ttl: 300                       # 缓存过期时间（秒）
  cache_type: cachetools

# 实际生效值为 max(ffmpeg_semaphore_limit, cpu_count // 2)
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

# 必须与前端 environment.ts 保持同步
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
  max_concurrent: 2              # 同时运行的任务数，也就是 worker 池大小。迁移是 IO 密集的，
                                 # 调高主要让它们互相抢带宽。
  progress_flush_interval: 3.0   # 进度落库的间隔（秒）。实时进度保存在内存里，所以这个值只
                                 # 决定「没有活跃订阅的客户端看到的任务列表有多旧」。

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

### 前端环境配置

| 文件 | `backend_api` | 含义 |
| ---- | ------------- | ---- |
| `environment.development.ts` | `"http://localhost:12000"` | 指向本地后端 |
| `environment.ts` | `""` | 相对路径，由 Nginx 代理 |
