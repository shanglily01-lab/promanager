# 在 AWS Linux 上部署 ProManager（裸机，无 Docker）

推荐流程：**系统装 Node + Python → 放代码 → 构建前端与 venv → 配 `.env` → systemd 常驻**（可选 Nginx + HTTPS）。

**前提**

- 安全组放行 **3000**（若用 Nginx 则放行 **80/443**，后端只监听本机 3000 即可）。
- 服务器上准备 `backend/.env`（复制 `backend/.env.example`），**勿**提交真实密钥到 Git。

---

## 1. 系统依赖（Amazon Linux 2023 示例）

```bash
sudo dnf install -y git gcc python3.12 python3.12-devel
# pip 编译扩展失败时再补：sudo dnf install -y mariadb-connector-c-devel 等

curl -fsSL https://rpm.nodesource.com/setup_20.x | sudo bash -
sudo dnf install -y nodejs
```

**Amazon Linux 2** 若无 `python3.12`，可用 `python3.11` / `python3`，保证版本 ≥ 3.11；`build-on-server.sh` 会依次尝试 `python3.12`、`python3.11`、`python3`。

---

## 2. 放置代码

例如 `/opt/promanager`：

- **`git clone`** 本仓库，或  
- 在 Windows 上执行 **`deploy/package-for-deploy.ps1`**，将生成的 **`deploy/out/promanager-deploy-*.tar.gz`** 上传到服务器后解压：

```bash
mkdir -p /opt/promanager && cd /opt/promanager
tar -xzf /path/to/promanager-deploy-*.tar.gz
```

---

## 3. 构建前端 + Python 虚拟环境

```bash
cd /opt/promanager
chmod +x deploy/*.sh
./deploy/build-on-server.sh
```

- 若压缩包里**已带** `frontend/dist`（例如用 `package-for-deploy.ps1` 打的包），脚本会**跳过**前端 `npm`，只装后端依赖。
- 若要在服务器上重新打前端：先 `rm -rf frontend/dist` 再执行脚本，或设 `SKIP_FRONTEND_BUILD=0`。

---

## 4. 配置环境变量

```bash
cp backend/.env.example backend/.env
nano backend/.env   # 或 vim
```

若浏览器访问的**页面域名**与 **API 域名**不一致，增加例如：`CORS_ORIGINS=https://你的前端域名`；同源（只开 :3000 或 Nginx 同一域名反代）通常**不用**配。

---

## 5. systemd 常驻

1. 编辑 **`deploy/promanager.service`**：把 `User`/`Group`（如 `ec2-user`）和 **`WorkingDirectory` / `ExecStart` 里的路径**改成你的安装目录（默认示例为 `/opt/promanager`）。

2. 安装并启动：

```bash
sudo cp /opt/promanager/deploy/promanager.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now promanager
sudo systemctl status promanager
```

查看日志：`journalctl -u promanager -f`

**手动前台跑一遍（排查用）：**

```bash
cd /opt/promanager/backend
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 3000 --workers 1
```

浏览器访问：`http://<公网IP>:3000`（存在 `frontend/dist` 时由后端一并提供静态页）。

---

## 6.（可选）Nginx 反代 HTTPS

参考同目录 **`nginx-promanager.conf.example`**，修改 `server_name`、证书路径，并把 `proxy_pass` 指向 `127.0.0.1:3000`。

---

## 在 Windows 开发机上打部署包

在项目根目录（需已安装 Node.js）：

```powershell
.\deploy\package-for-deploy.ps1
```

输出：**`deploy/out/promanager-deploy-*.tar.gz`**（不含 `node_modules`、`.venv`、`.env`、`backend/data`）。上传到服务器后按上文 **步骤 2～5** 即可。

---

## 生产注意

| 项 | 说明 |
|----|------|
| Worker 数 | 后台定时同步、SQLite 建议 **`--workers 1`**；多 worker 请关 `BACKGROUND_SYNC_ENABLED` 或改外部 cron 调 `/api/sync` |
| 数据库 | 生产推荐 **MySQL/RDS**，在 `.env` 配 `DB_*` 或 `DATABASE_URL` |
| 密钥 | `GITHUB_TOKEN`、AWS、数据库密码只放在服务器 `.env` |

升级版本：`git pull`（或上传新包解压覆盖）后执行 `./deploy/build-on-server.sh`，再 `sudo systemctl restart promanager`。

更多 API 与配置见仓库根目录 **`README.md`**。
