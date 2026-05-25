# INTP Study Manager 香橙派 / Docker / 公网访问部署指南

本文档说明如何把 `INTP_Study_Manager` 部署到香橙派这类小型 Linux 开发板上，并通过公网访问。

推荐方案：

```text
Docker Compose
+ Cloudflare Tunnel
+ Cloudflare Access 登录保护
+ SQLite 数据目录持久化
```

如果你有公网 IP，也可以使用：

```text
Docker Compose
+ Caddy / Nginx 反向代理
+ 路由器端口映射
+ HTTPS
+ 登录鉴权
```

不建议直接把 Streamlit 的 `8501` 端口暴露到公网。

---

## 1. 部署目标架构

### 推荐公网架构

```text
公网用户
  ↓
https://study.example.com
  ↓
Cloudflare Tunnel / Caddy / Nginx
  ↓
香橙派 Docker 服务
  ↓
INTP Study Manager Streamlit :8501
  ↓
SQLite 数据目录 ./data
```

### 本地服务结构

```text
INTP_Study_Manager/
├── app.py
├── requirements.txt
├── data/
│   ├── study_manager.db
│   └── api_keys.enc.json
├── Dockerfile
├── docker-compose.yml
└── .streamlit/
    └── config.toml
```

---

## 2. 香橙派系统准备

以下命令以 Ubuntu / Debian 系统为例。

### 2.1 更新系统

```bash
sudo apt update
sudo apt upgrade -y
```

### 2.2 安装基础工具

```bash
sudo apt install -y curl git vim ca-certificates gnupg
```

### 2.3 安装 Docker

```bash
curl -fsSL https://get.docker.com | sh
```

把当前用户加入 Docker 用户组：

```bash
sudo usermod -aG docker $USER
```

然后退出 SSH，重新登录，验证：

```bash
docker version
```

### 2.4 安装 Docker Compose

新版 Docker 通常自带 Compose 插件，验证：

```bash
docker compose version
```

如果能输出版本号，说明可用。

---

## 3. 在项目中添加 Docker 文件

进入项目目录：

```bash
cd INTP_Study_Manager
```

### 3.1 新建 `Dockerfile`

在 `INTP_Study_Manager/Dockerfile` 写入：

```dockerfile
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV TZ=Asia/Shanghai

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8501

CMD ["streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true"]
```

关键点：

```bash
--server.address=0.0.0.0
```

这会让 Streamlit 监听容器内所有网络地址，否则外部设备可能访问不到。

---

### 3.2 新建 `.dockerignore`

在 `INTP_Study_Manager/.dockerignore` 写入：

```dockerignore
__pycache__/
*.pyc
*.pyo
*.pyd
.Python
.venv/
venv/
env/
.git/
.gitignore
.pytest_cache/
.mypy_cache/
.ruff_cache/
.DS_Store
*.log
```

注意：这里不要忽略 `data/`，因为本项目默认使用本地 SQLite 数据库。实际部署时推荐用 volume 挂载 `data` 目录。

---

### 3.3 新建 Streamlit 配置

创建目录：

```bash
mkdir -p .streamlit
```

在 `.streamlit/config.toml` 写入：

```toml
[server]
address = "0.0.0.0"
port = 8501
headless = true
enableCORS = false
enableXsrfProtection = true

[browser]
gatherUsageStats = false
```

如果后续通过反向代理访问出现页面加载异常，可以再根据实际情况调整 `enableCORS` 和 `enableXsrfProtection`。

---

### 3.4 新建 `docker-compose.yml`

在 `INTP_Study_Manager/docker-compose.yml` 写入：

```yaml
services:
  intp-study-manager:
    build: .
    container_name: intp-study-manager
    restart: unless-stopped
    ports:
      - "8501:8501"
    volumes:
      - ./data:/app/data
    environment:
      - TZ=Asia/Shanghai
```

这个配置会把宿主机的：

```text
./data
```

挂载到容器内：

```text
/app/data
```

因此 SQLite 数据库和加密 API Key 文件会保留在宿主机上，容器重建后不会丢失。

---

## 4. 本机先验证 Docker 部署

在项目目录执行：

```bash
docker compose build
```

启动服务：

```bash
docker compose up -d
```

查看容器状态：

```bash
docker compose ps
```

查看日志：

```bash
docker compose logs -f
```

浏览器访问：

```text
http://localhost:8501
```

如果是在香橙派局域网访问，用：

```text
http://香橙派局域网IP:8501
```

例如：

```text
http://192.168.1.50:8501
```

停止服务：

```bash
docker compose down
```

重新启动：

```bash
docker compose up -d
```

---

## 5. 把项目部署到香橙派

### 5.1 方式一：使用 Git 拉取

在香橙派上执行：

```bash
git clone <你的项目仓库地址>
cd INTP_Study_Manager
```

如果是私有仓库，需要先配置 SSH Key 或使用 GitHub token。

### 5.2 方式二：使用 `scp` 上传

在电脑上执行：

```bash
scp -r INTP_Study_Manager 用户名@香橙派IP:/home/用户名/
```

然后 SSH 到香橙派：

```bash
ssh 用户名@香橙派IP
cd ~/INTP_Study_Manager
```

### 5.3 创建数据目录

```bash
mkdir -p data
chmod 755 data
```

如果你已有本地数据库，把这些文件复制到香橙派的 `data/` 目录：

```text
data/study_manager.db
data/api_keys.enc.json
```

其中：

- `study_manager.db` 是学习数据。
- `api_keys.enc.json` 是本地加密 API Key 仓库。

请妥善备份这两个文件。

### 5.4 启动服务

```bash
docker compose up -d --build
```

查看日志：

```bash
docker compose logs -f
```

局域网访问：

```text
http://香橙派IP:8501
```

---

## 6. 公网访问方案 A：Cloudflare Tunnel，推荐

适合场景：

- 家里没有公网 IP。
- 不想配置路由器端口映射。
- 希望自动 HTTPS。
- 希望只有自己能登录访问。

### 6.1 前置条件

你需要：

1. 一个域名。
2. 域名 DNS 托管在 Cloudflare。
3. 香橙派可以访问互联网。
4. 本地 Streamlit 服务已经能通过 `http://localhost:8501` 访问。

### 6.2 安装 `cloudflared`

ARM64 Debian / Ubuntu 可以参考 Cloudflare 官方文档安装。

一种常见方式是下载对应架构的 `.deb` 包后安装：

```bash
sudo dpkg -i cloudflared-linux-arm64.deb
```

验证：

```bash
cloudflared --version
```

### 6.3 登录 Cloudflare

```bash
cloudflared tunnel login
```

命令会输出一个登录链接。打开链接，选择你的域名授权。

### 6.4 创建 Tunnel

```bash
cloudflared tunnel create intp-study-manager
```

记录输出中的 Tunnel ID。

### 6.5 创建配置文件

创建目录：

```bash
mkdir -p ~/.cloudflared
```

编辑：

```bash
vim ~/.cloudflared/config.yml
```

写入：

```yaml
tunnel: <你的Tunnel ID>
credentials-file: /home/<你的用户名>/.cloudflared/<你的Tunnel ID>.json

ingress:
  - hostname: study.example.com
    service: http://localhost:8501
  - service: http_status:404
```

把 `study.example.com` 改成你的真实域名。

### 6.6 绑定 DNS

```bash
cloudflared tunnel route dns intp-study-manager study.example.com
```

### 6.7 测试运行

```bash
cloudflared tunnel run intp-study-manager
```

然后访问：

```text
https://study.example.com
```

### 6.8 安装成系统服务

```bash
sudo cloudflared service install
```

启动：

```bash
sudo systemctl start cloudflared
```

设置开机自启：

```bash
sudo systemctl enable cloudflared
```

查看状态：

```bash
sudo systemctl status cloudflared
```

---

## 7. 给公网访问加登录保护

强烈建议加 Cloudflare Access。

### 7.1 进入 Cloudflare Zero Trust

在 Cloudflare 后台进入：

```text
Zero Trust → Access → Applications
```

### 7.2 添加应用

选择：

```text
Self-hosted
```

应用域名填写：

```text
study.example.com
```

### 7.3 配置访问策略

例如只允许你的邮箱访问：

```text
Include → Emails → your-email@example.com
```

保存后，访问 `https://study.example.com` 时会先要求登录验证。

这一步非常重要，因为项目里可能包含学习记录、API Provider 配置和加密密钥库入口。

---

## 8. 公网访问方案 B：公网 IP + Caddy 反向代理

适合场景：

- 你有公网 IP。
- 路由器可以做端口映射。
- 域名能解析到你的公网 IP。

### 8.1 安装 Caddy

在香橙派上安装 Caddy，参考 Caddy 官方文档。

### 8.2 修改 `docker-compose.yml`

可以把 Streamlit 端口只监听本机，避免局域网直接访问：

```yaml
services:
  intp-study-manager:
    build: .
    container_name: intp-study-manager
    restart: unless-stopped
    ports:
      - "127.0.0.1:8501:8501"
    volumes:
      - ./data:/app/data
    environment:
      - TZ=Asia/Shanghai
```

重启：

```bash
docker compose up -d --build
```

### 8.3 配置 Caddy

编辑：

```bash
sudo vim /etc/caddy/Caddyfile
```

写入：

```caddyfile
study.example.com {
    reverse_proxy 127.0.0.1:8501
}
```

重载 Caddy：

```bash
sudo systemctl reload caddy
```

Caddy 会自动申请 HTTPS 证书。

### 8.4 路由器端口映射

在路由器管理页面中，把公网端口映射到香橙派：

```text
公网 80  → 香橙派 80
公网 443 → 香橙派 443
```

不要映射：

```text
公网 8501 → 香橙派 8501
```

### 8.5 增加 Basic Auth，可选但建议

生成密码哈希：

```bash
caddy hash-password
```

然后 Caddyfile 改成：

```caddyfile
study.example.com {
    basicauth {
        yourname <生成的密码哈希>
    }

    reverse_proxy 127.0.0.1:8501
}
```

重载：

```bash
sudo systemctl reload caddy
```

---

## 9. 公网访问方案 C：Tailscale，只给自己用

如果只需要自己手机、电脑、平板访问，这是最安全简单的方案。

### 9.1 安装 Tailscale

香橙派上：

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
```

你的电脑和手机也安装 Tailscale 并登录同一个账号。

### 9.2 访问服务

查看香橙派 Tailscale IP：

```bash
tailscale ip -4
```

然后访问：

```text
http://香橙派TailscaleIP:8501
```

这种方式不是真正公开给全网，而是只在你的 Tailscale 私有网络内可访问。

---

## 10. 数据备份与恢复

### 10.1 需要备份的文件

重点备份：

```text
data/study_manager.db
data/api_keys.enc.json
```

说明：

- `study_manager.db`：学习记录、复习计划、Provider 配置等。
- `api_keys.enc.json`：加密 API Key 仓库。

如果忘记加密仓库主密码，`api_keys.enc.json` 无法恢复明文 Key。

### 10.2 手动备份

```bash
mkdir -p backups
cp data/study_manager.db backups/study_manager_$(date +%F).db
cp data/api_keys.enc.json backups/api_keys_$(date +%F).enc.json 2>/dev/null || true
```

### 10.3 定时备份示例

编辑 crontab：

```bash
crontab -e
```

添加：

```cron
30 3 * * * cd /home/<你的用户名>/INTP_Study_Manager && mkdir -p backups && cp data/study_manager.db backups/study_manager_$(date +\%F).db && cp data/api_keys.enc.json backups/api_keys_$(date +\%F).enc.json 2>/dev/null || true
```

每天凌晨 3:30 备份一次。

---

## 11. 更新项目

如果使用 Git 部署：

```bash
cd ~/INTP_Study_Manager
git pull
docker compose up -d --build
```

查看日志：

```bash
docker compose logs -f
```

如果更新前担心数据库迁移风险，先备份：

```bash
mkdir -p backups
cp data/study_manager.db backups/study_manager_before_update_$(date +%F_%H%M%S).db
cp data/api_keys.enc.json backups/api_keys_before_update_$(date +%F_%H%M%S).enc.json 2>/dev/null || true
```

---

## 12. 常用运维命令

### 查看容器

```bash
docker compose ps
```

### 查看日志

```bash
docker compose logs -f
```

### 重启服务

```bash
docker compose restart
```

### 停止服务

```bash
docker compose down
```

### 重新构建并启动

```bash
docker compose up -d --build
```

### 查看端口监听

```bash
ss -tulpn | grep 8501
```

### 进入容器

```bash
docker exec -it intp-study-manager bash
```

---

## 13. 安全注意事项

### 13.1 不要裸露 Streamlit 端口

不推荐：

```text
公网 → 香橙派:8501
```

推荐：

```text
公网 → HTTPS → 登录保护 → 反向代理 → Streamlit
```

### 13.2 必须保护这些数据

```text
data/study_manager.db
data/api_keys.enc.json
```

不要上传到公开仓库。

### 13.3 建议开启访问控制

推荐优先级：

1. Cloudflare Access
2. Tailscale 私有网络
3. Caddy / Nginx Basic Auth
4. 应用内登录功能

目前项目主要是本地工具，不能默认假设它已经适合直接公开给互联网。

### 13.4 API Key 使用建议

公网部署后，不建议在没有访问控制的页面里输入 API Key。

推荐：

- 使用加密 API Key 仓库。
- 设置强主密码。
- 限制公网访问用户。
- 定期备份密钥库文件。

---

## 14. PPT / PDF 功能在香橙派上的限制

本项目有 PPT / PDF 相关功能。部署到 Linux ARM 开发板后要注意：

1. Windows PowerPoint 自动导出 PPT 图片的能力在香橙派 Linux Docker 中不可用。
2. PDF 渲染如果依赖 PyMuPDF，一般可以继续工作。
3. PPTX 原样渲染如果依赖 Windows COM，需要改为 LibreOffice headless 或其他 Linux 方案。

如果部署后 PPTX 渲染失败，可以先保证以下功能可用：

- 学习登记
- 知识点卡片
- 复习计划
- AI 调用
- 余额查询
- PDF 阅读和讲解

PPTX 原始页面图片导出可以后续单独适配。

---

## 15. 最终推荐落地步骤

按这个顺序执行最稳：

1. 在项目中添加：
   - `Dockerfile`
   - `.dockerignore`
   - `docker-compose.yml`
   - `.streamlit/config.toml`
2. 本机执行：

   ```bash
   docker compose up -d --build
   ```

3. 本机访问：

   ```text
   http://localhost:8501
   ```

4. 把项目上传到香橙派。
5. 香橙派执行：

   ```bash
   docker compose up -d --build
   ```

6. 局域网访问：

   ```text
   http://香橙派IP:8501
   ```

7. 配置 Cloudflare Tunnel。
8. 配置 Cloudflare Access 登录保护。
9. 公网访问：

   ```text
   https://study.example.com
   ```

10. 设置数据库和密钥库定期备份。

---

## 16. 排障清单

### 16.1 局域网打不开

检查容器：

```bash
docker compose ps
```

检查日志：

```bash
docker compose logs -f
```

检查端口：

```bash
ss -tulpn | grep 8501
```

确认 `docker-compose.yml` 中有：

```yaml
ports:
  - "8501:8501"
```

确认 Streamlit 启动参数有：

```bash
--server.address=0.0.0.0
```

### 16.2 容器启动后数据库为空

检查是否挂载了数据目录：

```yaml
volumes:
  - ./data:/app/data
```

检查宿主机目录：

```bash
ls -lh data
```

### 16.3 无法写入数据库

检查权限：

```bash
ls -ld data
ls -lh data/study_manager.db
```

临时修复：

```bash
chmod 755 data
chmod 644 data/study_manager.db
```

如果仍失败，可以根据容器用户进一步调整权限。

### 16.4 Cloudflare Tunnel 访问失败

检查本地服务：

```bash
curl http://localhost:8501
```

检查 Tunnel 状态：

```bash
sudo systemctl status cloudflared
```

查看日志：

```bash
journalctl -u cloudflared -f
```

确认 `~/.cloudflared/config.yml` 中：

```yaml
service: http://localhost:8501
```

### 16.5 HTTPS 正常但页面白屏

可能是反向代理、WebSocket 或 CORS/XSRF 配置问题。优先检查 Streamlit 配置：

```toml
[server]
enableCORS = false
enableXsrfProtection = true
```

如果仍有问题，再查看浏览器开发者工具 Console 和 Network。
