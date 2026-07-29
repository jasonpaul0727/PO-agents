# 部署日志 / Deploy Log — PO Intake Agent

记录把 `backend/app.py`（PO Intake 网站）部署到 AWS EC2 的完整过程，作为学习笔记 + 后续操作参考。

## 目标与架构

- **为什么不能随便部署**：`/api/process` 会调用 Anthropic API（真实花钱），所以公开部署前必须加登录门禁 + 限流,详见 `backend/security.py`。
- **为什么不用国内云**：应用需要稳定访问 `api.anthropic.com`，架在中国大陆网络下这个出站请求不可靠，所以选了 AWS（人也在美国）。
- **架构**：EC2（Ubuntu 26.04, t3.micro）→ Docker 容器跑 FastAPI 应用 → （下一步）nginx 反代 80/443 → 容器只监听内部端口。

## 服务器信息

| 项 | 值 |
|---|---|
| 实例 ID | `i-0329115fa5f609883` |
| 公网 IP | `3.17.209.141`（Elastic IP，已固定，不会再变；旧的动态 IP `3.144.72.92` 关联后已失效） |
| 系统 | Ubuntu 26.04 LTS |
| 登录方式 | `ssh -i ~/.ssh/po-agents-key.pem ubuntu@3.17.209.141` |
| 密钥文件位置 | WSL: `~/.ssh/po-agents-key.pem`（权限 400）；Windows 原始下载：`Downloads/po-agents-key.pem` |
| 代码目录 | `~/PO-agents`（`git clone` 自 `github.com/jasonpaul0727/PO-agents`,public repo） |

## 已完成的步骤

### 1. 本地代码准备（Phase A）
- 新增 `Dockerfile`、`.dockerignore`：只打包 `backend/` + `frontend/`，`sample_request` 的 Gmail 凭证目录 (`secrets/`) 完全不进镜像。
- 新增 `backend/security.py`：HTTP Basic Auth（`DEMO_USERNAME`/`DEMO_PASSWORD` 未设置时是 no-op,不影响本地开发和测试）+ `/api/process` 每分钟限流。
- 新增 `.github/workflows/ci.yml`：push/PR 自动跑 `pytest tests backend/sample_request/tests`。
- 本地 commit（`ab3387e`）→ push 到 `origin/master`。

### 2. 起服务器（AWS 控制台操作）
- EC2 → Launch Instance → Ubuntu 22.04（实际给的是 26.04）→ `t3.micro`（免费套餐）
- 创建密钥对（RSA + `.pem` 格式）,下载后 `chmod 400` 存进 WSL `~/.ssh/`
- 安全组：目前只放行 `22`（SSH,来源限我的 IP）,`80`/`443` 还没开

### 3. SSH 上去装环境
```bash
sudo apt-get update -y && sudo apt-get install -y ca-certificates curl
# 加 Docker 官方源 + GPG key
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker ubuntu
sudo docker run hello-world   # 验证安装成功
```

### 4. 部署应用
```bash
git clone https://github.com/jasonpaul0727/PO-agents.git
cd PO-agents
docker build -t po-intake .        # 打包镜像，验证 Dockerfile 没问题
```

**配置密钥（`.env`）**：本地已有一份配置好的 `.env`（含真实 `ANTHROPIC_API_KEY`），通过 `scp` 直接传到服务器，追加了部署专属配置项后写入 `~/PO-agents/.env`：
```
ANTHROPIC_API_KEY=（真实值，不写进本文档 — 只存在服务器的 .env 里）
PO_MODEL=claude-opus-4-8
PO_DB=/app/data/po.db
PO_SEED=backend/seed
DEMO_USERNAME=demo
DEMO_PASSWORD=（真实值，不写进本文档 — 只存在服务器的 .env 里）
PROCESS_RATE_LIMIT_PER_MINUTE=5
```
**本文档从此不再写任何真实密钥/密码值**——之前这里写过明文密码，虽然本文档从未被 git 提交过（没有真的泄露到仓库），但后来一次 nano 编辑时把整个 `.env`（包括真实 `ANTHROPIC_API_KEY`）贴进了 AI 对话记录，属于真实暴露。处理方式：Anthropic 控制台撤销旧 key + 生成新 key、`DEMO_PASSWORD` 也换成新的随机值（`openssl rand -base64 18` 生成，没有贴进对话），容器用新 `.env` 重建，验证旧密码返回 401（已失效）、说明轮换生效。**教训：查看/编辑 `.env` 时只用 `grep -c "^KEY="` 这种只确认"存不存在"、不显示真实值的命令，永远不要把整个文件内容贴出来。**

**运行容器**：
```bash
docker run -d --name po-intake \
  --env-file .env \
  -v po_data:/app/data \        # SQLite 数据持久化，容器重建也不丢
  -p 127.0.0.1:8000:8000 \      # 只绑本机，暂不对外网开放
  po-intake
```

**验证**（服务器内部执行）：
```bash
curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/            # -> 401（无密码,门禁生效）
curl -s -o /dev/null -w "%{http_code}" -u demo:<password> http://127.0.0.1:8000/  # -> 200
docker logs po-intake   # 无报错，Uvicorn 正常启动
```

### 5. 加固与固定 IP（本次会话新增）

**容器重启策略**（服务器上执行，不用删容器重建）：
```bash
docker update --restart unless-stopped po-intake
docker inspect po-intake --format '{{.HostConfig.RestartPolicy.Name}}'   # -> unless-stopped
```
现在服务器重启或 Docker 崩溃后，容器会自动拉起来，不用手动 `docker run`。

**Elastic IP**（AWS 控制台操作，区域 US East (Ohio) / `us-east-2`）：
- EC2 → 网络和安全 → 弹性 IP → 分配 Elastic IP 地址（Amazon 的 IPv4 地址池，默认设置）→ 已成功分配
- 关联到实例：勾选「允许重新关联此弹性 IP」（不影响这次操作，是为以后换实例时省一步解绑），操作 → 关联 Elastic IP 地址 → 资源类型选实例 → 选中 `i-0329115fa5f609883`
- ✅ **已完成**：`3.17.209.141` 已成功关联到实例。公网 IP 固定下来了，之后重启/停开实例都不会再变。**SSH 和一切对外访问都要用新 IP，旧的 `3.144.72.92` 已经失效。**

### 6. 安全组开放 80/443（本次会话新增）

安全组 `sg-0851d1523886c68de`（launch-wizard-1，绑定在实例 `i-0329115fa5f609883` 上）编辑入站规则：
- 新增 HTTP（80/TCP）,来源 `0.0.0.0/0`
- 新增 HTTPS（443/TCP）,来源 `0.0.0.0/0`
- ⚠️ 踩坑记录：编辑时手滑把原有 SSH（22）规则的来源也改成了 `0.0.0.0/0`（对全世界开放,有被扫描/爆破的风险）,已经改回**"我的 IP"**（`107.128.206.246/32`）修复。**以后每次编辑入站规则,存之前要检查一遍所有行的来源,不只是新加的那两条。**

现在 80/443 端口能收到外部流量了,但**服务器上还没有任何程序监听这两个端口**（容器仍然只绑 `127.0.0.1:8000`），所以目前请求打过去还是连不通——下一步要装 nginx 做反向代理才能真正打通。

### 7. nginx 反向代理（本次会话新增）

**问题**：nginx 转发请求后，应用看到的"客户端 IP"永远是 nginx 自己（`127.0.0.1`），会导致 `backend/security.py` 里按 IP 算的限流失效（所有人共用一个配额）。

**修复（本地 → push → 服务器重新 build）**：
- `Dockerfile` 的 `CMD` 加了 `--proxy-headers --forwarded-allow-ips=127.0.0.1`（commit `2bdc7f0`），让 Uvicorn 信任 nginx 转发过来的 `X-Forwarded-For`，把真实客户端 IP 还原到 `request.client.host`。
- 服务器上 `git pull` 拉到这个修复 → `docker build -t po-intake .` 重新打镜像 → `docker stop/rm` 旧容器 → 用新镜像 `docker run`（这次直接在 `run` 里带上 `--restart unless-stopped`,不用像上次一样事后再 `docker update`）。

**nginx 配置**（服务器上 `/etc/nginx/sites-available/po-intake`，软链接到 `sites-enabled`，同时删掉了默认的 `sites-enabled/default`）：
```nginx
server {
    listen 80;
    server_name _;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```
`sudo nginx -t` 测试通过 → `sudo systemctl reload nginx` 生效。

**✅ 第一次真正意义上的公网验证**（本地笔记本直接对公网 IP 发请求，不是服务器内部测 `127.0.0.1`）：
```bash
curl -s -o /dev/null -w "%{http_code}\n" http://3.17.209.141/            # -> 401
curl -s -o /dev/null -w "%{http_code}\n" -u demo:<password> http://3.17.209.141/  # -> 200
```
外部任意一台联网设备现在都能访问 `http://3.17.209.141/`（会先撞上 Basic Auth 门禁）。

**⚠️ 已知风险**：
1. 现在是 HTTP，不是 HTTPS——Basic Auth 的账号密码是明文过公网的，等域名 + Let's Encrypt 做完才算安全。
2. ✅ **已解决**：密码曾经明文写在本文档里的问题——本文档从未被提交过，没有真的泄露到 public repo；但后续操作中意外把真实 `.env`（含 API key）贴进了 AI 对话，已完成 key 撤销重发 + 密码轮换，详见「部署应用」一节的记录。

### 8. 域名 + HTTPS（本次会话新增）

**买域名**：Namecheap 买了 `yanxiabu001.com`。买的时候注意跳过了它搭售的 "Web Hosting"（共享虚拟主机，跟自建 EC2 服务器完全是两条路，用不上）。

**DNS 配置**（Namecheap → Domain List → Manage → Advanced DNS）：
- 删掉了买域名自动生成的两条默认记录（会跟真实解析冲突）：`URL Redirect Record`（`@` 指向停放页）、`CNAME Record`（`www` 指向 `parkingpage.namecheap.com`）。
- 加了两条 **A 记录**，`@` 和 `www` 都指向 `3.17.209.141`：
  ```
  A Record    @      3.17.209.141    Automatic
  A Record    www    3.17.209.141    Automatic
  ```
- `nslookup yanxiabu001.com` 验证生效（几分钟内就传播完了）。

**nginx 配置加域名**：`/etc/nginx/sites-available/po-intake` 里 `server_name _;` 改成 `server_name yanxiabu001.com www.yanxiabu001.com;`，`nginx -t` + `reload`。

**申请证书**：
```bash
sudo apt-get install -y certbot python3-certbot-nginx
sudo certbot --nginx -d yanxiabu001.com -d www.yanxiabu001.com
```
选了"HTTP 自动跳转 HTTPS"。证书签发成功，certbot 自动改好了 nginx 配置、设置了到期自动续期（有效期到 2026-10-26，到期前会自动续，不用手动管）。

**✅ 验证通过**：
```bash
curl https://yanxiabu001.com/                          # -> 401
curl -u demo:<password> https://yanxiabu001.com/       # -> 200
curl http://yanxiabu001.com/                            # -> 301/308，自动跳转 https
```

至此 `https://yanxiabu001.com` 是真正加密、浏览器认可（不再显示"不安全"警告）的公网地址,Basic Auth 密码不再明文过公网。

### 9. 自动化 CD 部署（本次会话新增）

**自动部署流程**：每次 `git push` 到 `master` 分支后，GitHub Actions 的 `ci.yml` 工作流自动触发：
1. `test` 任务：运行 `pytest tests backend/sample_request/tests` + `ruff check --fix && ruff format` 进行 lint 和格式检查
2. `test` 通过后，自动拉起 `deploy` 任务：使用 GitHub 内置的 Docker 注册表（GHCR）， `docker build` 打镜像 → 推送到 `ghcr.io/jasonpaul0727/po-agents`（公开仓库），每次构建打两个标签：
   - `<commit-sha>`：当前提交的完整哈希值（可用于精确回滚）
   - `latest`：最新构建

3. 镜像推送完成后，自动 SSH 连接到服务器（`3.17.209.141`），执行新容器启动脚本：
   ```bash
   ssh -i ~/.ssh/po-agents-key.pem ubuntu@3.17.209.141
   cd ~/PO-agents
   docker pull ghcr.io/jasonpaul0727/po-agents:latest
   docker stop po-intake && docker rm po-intake
   docker run -d --name po-intake \
     --env-file .env \
     -v po_data:/app/data \
     -p 127.0.0.1:8000:8000 \
     --restart unless-stopped \
     ghcr.io/jasonpaul0727/po-agents:latest
   ```
   新容器启动后自动接管所有流量，整个过程**无需手动干预**。

**镜像仓库**：
- 地址：`ghcr.io/jasonpaul0727/po-agents`（GitHub Container Registry，完全公开）
- 访问：任何人都能 `docker pull`（无需私钥），但只有 CI 工作流有权限 `docker push`（使用 GitHub Actions 内置的 `GITHUB_TOKEN` 身份认证）

**本节新增之前是如何部署的（现为后备方案/回滚程序）**：见 §4「部署应用」中的手工操作步骤。如果自动部署失败（例如 CI 工作流中途断线、网络问题等），或需要紧急回滚到旧版本，可以手工 SSH 上服务器执行上述命令，把 `ghcr.io/jasonpaul0727/po-agents:latest` 替换成特定的 commit SHA 标签（例如 `ghcr.io/jasonpaul0727/po-agents:abc1234567def`）来拉取指定版本。

**回滚命令（紧急恢复旧版本）**：如需回滚到某个旧 commit（例如 `<old-sha>`），在服务器上执行：
```bash
ssh -i ~/.ssh/po-agents-key.pem ubuntu@3.17.209.141
cd ~/PO-agents
docker pull ghcr.io/jasonpaul0727/po-agents:<old-sha>
docker stop po-intake && docker rm po-intake
docker run -d --name po-intake \
  --env-file .env \
  -v po_data:/app/data \
  -p 127.0.0.1:8000:8000 \
  --restart unless-stopped \
  ghcr.io/jasonpaul0727/po-agents:<old-sha>
```

## 当前状态：约 95%

| 完成 ✅ | 待办 ⬜ |
|---|---|
| 代码/CI/安全防护 | AWS 账单告警 + Anthropic 消费上限确认 |
| EC2 + SSH + Docker | |
| 镜像 build 成功 | |
| `.env` 配置完成 | |
| 容器跑通 + volume 持久化 | |
| 内部访问验证通过（401/200） | |
| 容器重启策略 `--restart unless-stopped` | |
| Elastic IP 分配 + 关联（`3.17.209.141`） | |
| 安全组开放 80/443（SSH 仍限本机 IP） | |
| nginx 反向代理 + 公网 401/200 验证通过 | |
| API key 撤销重发 + demo 密码轮换（旧密码验证已 401） | |
| 域名（`yanxiabu001.com`）+ HTTPS（Let's Encrypt，自动续期已设置） | |
| 自动化 CD 部署（GitHub Actions 构建 → 推送 GHCR → 部署容器） | |

## 常用排查命令
```bash
docker ps                    # 查看运行中的容器
docker logs po-intake        # 查看应用日志
docker images                # 查看本地镜像
cat ~/PO-agents/.env         # 查看当前配置（含真实 key，谨慎操作）
```
