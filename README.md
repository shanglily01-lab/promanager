# ProManager

基于 **GitHub 提交记录** 的轻量项目管理辅助工具：同步指定仓库的提交到本地数据库，按人汇总 **日报 / 周报**，并给出 **是否有提交**、**提交列表** 与 **习惯分析**（UTC 时段分布、星期分布、说明长度、是否习惯带 `#issue` 引用）。

## 功能概览

| 能力 | 说明 |
|------|------|
| 同步 | 调用 GitHub REST API 拉取 `owner/repo` 在指定天数内的 commits 并去重入库；**仓库列表可存数据库**（`/api/repos`），与 `.env` / `repos.txt` 合并去重 |
| 仓库中心 | 对合并列表中的仓库在本机执行 `git clone` / `git fetch`（默认目录 `backend/data/repo_mirrors`，见 `REPO_MIRROR_ROOT`），检查是否都能拉回本地；前端 **仓库中心** 页或 `GET/POST /api/repo-mirrors*`。CodeCommit 依赖 **本 venv 内的 `awscli`**（已写入 `requirements.txt`）及 `.env` 中的 AWS 凭证，无需单独安装系统 AWS CLI。 |
| 日报 | 某一 UTC 日历日内，每位成员是否有提交、提交条数与摘要 |
| 周报 | 以周一为起点的一周（UTC），同上，并附每人习惯统计；**提交说明标签**（`commit_message_tags`，Conventional/ Merge/ 中英文/ 多行等启发式）+ **代码改动画像**（`style_tags`，扩展名、diff 缩进等，依赖 `GITHUB_COMMIT_STYLE_*` 单条 commit 详情拉取） |
| 成员查询 | 按报表主键查提交与习惯：`GitHub登录`、`email:邮箱`、`contrib:档案ID` |
| 成员档案 | 为每人设置**昵称、备注**，并绑定多个**邮箱**与 **GitHub 登录**；报表中合并为同一 `contrib:编号` |

> **说明**：GitHub 上「项目」若指 **Projects / Issues**，本版本以 **代码提交** 为核心数据源；后续可在此基础上接 Issues、Pull Requests 等 API。

## 最近更新（对照界面看）

| 项 | 去哪看 / 配置 |
|----|----------------|
| **多 GitHub Token** | `.env`：`GITHUB_TOKEN_REPO_MAP`（JSON）；同步时按仓库选 Token |
| **仓库中心** | 顶栏 **仓库中心**：`git clone`/`fetch` 到 `REPO_MIRROR_ROOT`；CodeCommit 用 venv 内 `awscli`（`pip install -r requirements.txt`） |
| **提交说明个人标签** | **周报**卡片、**成员提交与习惯**：紫色标签 = `commit_message_tags`；灰色系 = 代码画像 `style_tags` |
| **GitHub API 报错提示** | 同步失败信息更易读（401/404/私有库/SSO 等） |
| **Windows 特殊仓** | 含非法文件名的仓可自动 `--no-checkout` 仅拉对象；`git` 子进程禁用易坏的 `credential.helper` 链 |

## 环境要求

- Python 3.11+、Node.js 18+

## 怎么跑起来

### 启动命令（就这两条）

在 **`backend`** 目录（已装好依赖、配好 `.env`）：

```text
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

后台定时同步依赖**单个** ASGI 进程；若使用 `uvicorn --workers 2+`，请设 `BACKGROUND_SYNC_ENABLED=false` 或改为单 worker，避免重复拉取。

Windows 若没先 `activate` 虚拟环境，可写成：

```text
.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Linux / macOS 未激活 venv 时：

```text
.venv/bin/python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

在 **`frontend`** 目录（首次先执行 `npm install`）：

```text
npm run dev
```

开发时一般 **两个终端各跑上面一条**：API 与文档在 <http://127.0.0.1:8000>（含 `/docs`），页面在 <http://127.0.0.1:3008>（Vite 会把 `/api` 转到 8000）。

**Windows**：也可双击仓库根目录 **`start-dev.bat`**，会依次打开两个窗口（后端带 `--reload-dir app --reload-delay 1`，减轻热重载断连）。

### CodeCommit「仓库没拉回来」或同步报仓库不存在

- **列表**：在「同步」页填 **区域** 后点 **自动拉取该区域全部仓库**，依赖 `AWS_ACCESS_KEY_ID` 等凭证与 `codecommit:ListRepositories`；结果会写入批量导入框，仍需点 **导入到数据库** 才会进「合并后可用于同步」列表。
- **仓库名大小写**：CodeCommit 仓库名 **区分大小写**。若列举结果被改成小写，会导致 `GetBranch` 失败。当前版本列举结果与 AWS 控制台一致；若库里已有错误小写记录，请删除后重新从列表导入。

### Vite 里 `http proxy error` / `read ECONNRESET` 是什么？

- **`connect ECONNREFUSED 127.0.0.1:8000`**：8000 上 **没有进程在听**，即 **后端没启动或已退出**。请先起 `uvicorn`，或用 **`start-dev.bat`**。
- **`read ECONNRESET`**：连上后被对端掐断，多见于 **热重载重启** 或进程崩溃。

表示浏览器经 Vite 访问 `/api` 时，连到 `127.0.0.1:8000` 出问题。常见原因：

1. **后端没在跑或刚退出**：先看跑 uvicorn 的那个终端是否还在、有没有报错；没起来时前端会一直代理失败（控制台 ECONNREFUSED；页面上会尽量返回 502 说明文字）。
2. **`--reload` 热重载**：保存 `backend/app` 下文件会重启工作进程，**正在飞的请求**可能被掐断，就会偶发 ECONNRESET；**过一两秒刷新页面**通常就好。若短时间内多文件被保存，可能连续失败几次，属正常现象。
3. **想更稳**：调前端时可先 **去掉 `--reload`** 跑后端；或只监视 `app` 并加大重载间隔，例如：  
   `python -m uvicorn app.main:app --reload --reload-dir app --reload-delay 1 --host 127.0.0.1 --port 8000`

---

**第一次**（只做一次）：在 `backend` 建虚拟环境、装依赖、复制 `.env` 并编辑（至少 `GITHUB_TOKEN`；MySQL 填 `DB_*`）。

```bat
cd backend
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
copy .env.example .env
```

（Linux / macOS：`./.venv/bin/pip`、`cp .env.example .env`。）

---

**可选：只跑 Python 一个进程打开界面**（改前端要先重新打包）：

```text
cd frontend && npm run build
cd ../backend && python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

然后浏览器打开 <http://127.0.0.1:8000>（存在 `frontend/dist` 时后端会顺带提供静态页）。

---

**可选：Windows 批处理**（项目根目录）`dev.cmd` / `start-backend.cmd` / `start-frontend.cmd`，等价于上面命令。

### 配置说明（`backend/.env`）

- **GitHub**：`GITHUB_TOKEN`。**私有仓库必须配置**：到 [GitHub → Settings → Developer settings → Tokens](https://github.com/settings/tokens) 创建经典 PAT 并勾选 **`repo`**，或创建细粒度 PAT 并对目标仓库勾选 **Contents: Read**、**Metadata: Read**；令牌所属账号须对该私有库有读权限，组织库若启用 SSO 需在令牌页对组织 **Authorize**。将令牌写入 `backend/.env` 的 `GITHUB_TOKEN=` 后**重启 uvicorn**。
- **多账号 / 多 Token**：在 `.env` 增加 **`GITHUB_TOKEN_REPO_MAP`**（一行 JSON）。键为 **`owner/repo`**（小写），也可用 **`owner/*`** 作为该 owner 的默认 Token；未命中时仍用 `GITHUB_TOKEN`。示例：`GITHUB_TOKEN_REPO_MAP={"myorg/a":"ghp_aaa","other/b":"github_pat_bbb","myorg/*":"ghp_org_fallback"}`。修改后重启 uvicorn。
- **AWS CodeCommit**：`AWS_ACCESS_KEY_ID`、`AWS_SECRET_ACCESS_KEY`、`AWS_DEFAULT_REGION`；IAM 需读提交相关权限。仓库写法：`cc:区域/仓库名` 或 `cc:区域/仓库名@分支`（如 `cc:ap-southeast-1/my-app@prod`），可写进 `DEFAULT_REPOS`、repos 文件或前端批量导入。
- **仓库合并**：`DEFAULT_REPOS` 或 `REPOS_FILE`（见 `repos.example.txt`）；也可在前端维护，与数据库合并去重。
- **数据库**：默认 SQLite（`data/promanager.db`）。用 MySQL 时填 `DB_*` 或 `DATABASE_URL`，细节见 `backend/.env.example`。

### API 摘要

- `GET /api/health` — 健康检查与是否配置了 Token（含 `github_token_repo_map_entries`：按仓库 Token 映射条目数，不含密钥）  
- `GET /api/codecommit/repos?region=` — 列出该区域账号下 CodeCommit 仓库，返回 `cc:区域/仓库名` 列表（需 AWS 凭证与 `codecommit:ListRepositories`）  
- `GET /api/config/repos` — 返回合并后的仓库列表（**数据库已启用** + **DEFAULT_REPOS / REPOS_FILE** 去重）  
- `GET /api/repo-mirrors` — 仓库中心：镜像根目录、git/aws 是否可用、各仓库上次 clone/fetch 状态  
- `POST /api/repo-mirrors/scan` — body `{ "repos": [] }`，空数组表示对**合并列表全部**后台依次拉取；进行中再调返回 409  
- `GET|POST|PATCH|DELETE /api/repos` — 在数据库中维护跟踪仓库；`POST /api/repos/bulk` 批量添加  
- `POST /api/sync` — body: `{ "repos": [], "since_days": 15 }`，`repos` 空则用上述合并列表；默认回溯 **15 天**（`DEFAULT_SINCE_DAYS` / `since_days`）  
- `POST /api/sync/stream` — 同上，响应为 **SSE**（`text/event-stream`，每行 `data: {JSON}`），阶段含 `start` / `repo_fetch_*` / `write_*` / `complete` 等，供前端展示进度（**仅发起该次请求的那个浏览器**能收到）  
- `GET /api/sync/logs?limit=` — 最近若干次同步的**数据库摘要**（`sync_logs`），所有访问同一后端的用户均可查看  
- **后台同步**：`uvicorn` 进程内每 **4 小时**自动执行一次上述「空 repos」同步（`BACKGROUND_SYNC_*`，见 `backend/.env.example`）；**多 worker 时会各跑一份**，生产建议 `--workers 1` 或关掉 `BACKGROUND_SYNC_ENABLED` 改由外部 cron 调 `/api/sync`  
- `GET /api/reports/daily?date=YYYY-MM-DD`  
- `GET /api/reports/daily.md?date=...` — Markdown  
- `GET /api/reports/weekly?week_start=YYYY-MM-DD`（周一）  
- `GET /api/reports/weekly.md?week_start=...`  
- `GET /api/employees` — 返回 `employee_keys` 与 `employee_key_options`（`{ key, label }`，`contrib:` 用成员昵称作 `label` 供下拉展示）  
- `GET /api/employees/{key}/commits?from=&to=` — `key` 可为 `zhangsan`、`email:a@b.com`、`contrib:1`、`_unknown`  
- `GET /api/employees/{key}/habits?from=&to=` — 含时间/说明习惯；**commit_message_tags**（由提交说明启发式：Conventional 占比与类型主导、Merge/Revert、中英文倾向、多行说明、修复/功能措辞等）；**style_tags**（文件扩展名、diff 缩进等，依赖 `GITHUB_COMMIT_STYLE_*` 画像）  
- `GET|POST|PUT|DELETE /api/contributors` — 成员档案 CRUD（绑定邮箱 / GitHub 登录）  

**识别规则（简）**：每条提交先按**邮箱**是否在档案中匹配；否则按 **GitHub 登录**；否则归入裸登录或 `email:地址` 桶。档案内同一人的多个邮箱、多个登录会汇总到同一 `contrib:ID`。

开发模式下 Vite 把 `/api` 代理到 `http://127.0.0.1:8000`，所以要先起后端再起前端。

## 定时自动生成报告

可用系统计划任务在每天固定时间调用：

- `GET http://127.0.0.1:8000/api/reports/daily.md?date=...`  
- `GET http://127.0.0.1:8000/api/reports/weekly.md?week_start=...`  

将输出写入邮件、飞书、企业微信等。

## 限制与注意

- 日期边界按 **UTC**；若团队在国内，可把「工作日」理解成需自行偏移或后续扩展时区配置。  
- 未与 GitHub 账号关联的提交（无 `author.login`）会归入 `_unknown`。  
- 大量仓库 / 长历史首次同步可能较慢，受 GitHub API 速率限制；建议合理设置 `since_days` 并配置 Token。  
- **多仓库同步**：若某一个 GitHub/CodeCommit 仓库拉取失败（如仓库已删、无权限），**其余仓库仍会照常写入**；本次同步在接口里记为 `status=partial`，并在 `message` 中列出失败仓库。仅当**全部**仓库都拉取失败且没有任何提交可写时，才整次记为 `error`。  
- **升级代码后若「导入数据库」报错**：多为本地 SQLite 还缺新表（如 `tracked_repos`）。请**完全重启**后端（`uvicorn`）；启动时会自动 `create_all` 补表。仍失败时在 `backend` 目录执行：  
  `python -c "from app.database import init_db; init_db()"`。

## 目录结构

```
promanager/
  dev.cmd           # 一键前后端（Windows）
  start-backend.cmd
  start-frontend.cmd
  backend/          # FastAPI + uvicorn
  frontend/         # Vite + React
  README.md
```
