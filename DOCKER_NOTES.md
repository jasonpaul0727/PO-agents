# Docker 学习笔记 — 面试问答整理

来自 PO Intake Agent 部署实践,配合 `DEPLOY.md` 一起看（操作记录看 DEPLOY.md,概念理解看这份）。

## EC2 实例建好之后，一步一步具体发生了什么（详细版）

这一节把 `DEPLOY.md` 里"一行带过"的步骤全部摊开，每条命令写清楚**在哪台机器上跑**、**具体干了什么**、**为什么要这么做**。

> 说明：GPG key / apt 源那几条是 Docker 官方安装文档的标准写法，`DEPLOY.md` 当时只记了"加 Docker 官方源 + GPG key"一句话，这里补全成具体命令，不是凭空编的。

### 1. EC2 实例建好只是有了一台空白的云主机

在 AWS 控制台点完 Launch Instance 之后，你拿到的是：一个公网 IP（`3.144.72.92`）、一个装了 Ubuntu 系统的空机器、一个私钥文件（`.pem`）。这台机器里**什么都没装**，跟你自己买一台裸机放机房是一个概念，Docker 都还没影子。

### 2. SSH 连上服务器 —— 之后的命令都是在服务器上跑的，不是本地

```bash
ssh -i ~/.ssh/po-agents-key.pem ubuntu@3.144.72.92
```
- `-i ~/.ssh/po-agents-key.pem`：用这个私钥文件证明"我是有权限登录这台服务器的人"（对应 AWS 那边存的公钥）。
- `ubuntu`：Ubuntu 官方 AMI 默认自带的登录用户名。
- 连上之后，命令行提示符会从你本地的 `paul2@localhost` 变成 `ubuntu@ip-172-31-39-37`——**这一步之后敲的每一条命令，都是在云端那台机器上执行，不是在你自己电脑上**（你们之前 `docker ps -a` 报错"命令未找到"，就是因为在本地敲的，没连上服务器）。

### 3. 装 Docker 之前，先让系统能安全地从外网下东西

```bash
sudo apt-get update -y
sudo apt-get install -y ca-certificates curl
```
- `apt-get update`：刷新 Ubuntu 的软件包索引列表（不刷新的话，系统还在用镜像制作时那份可能过期的软件列表）。
- 装 `ca-certificates` + `curl`：为了下一步能用 HTTPS 去 Docker 官网下载 GPG 签名文件——没有这两个包，`curl https://...`可能因为证书验证失败而下载不了。

### 4. 添加 Docker 官方软件源（不用 Ubuntu 自带的旧版本）

```bash
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
  https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
```
- 前三行：下载 Docker 官方的 GPG 公钥，存到系统信任的密钥目录——这样系统才能验证"待会下载的 Docker 安装包，确实是 Docker 官方发布的，没被篡改"。
- 第四行：往 apt 的软件源列表里加一条，告诉它"以后装 docker 相关的包，去 `download.docker.com` 这个地址找，不要去 Ubuntu 自己那个仓库"。**为什么要这么麻烦而不是直接 `apt install docker.io`**：Ubuntu 自带仓库里的 Docker 版本通常落后官方好几个版本，功能和安全更新都滞后。
- 最后 `apt-get update`：让新加的软件源生效。

### 5. 真正安装 Docker

```bash
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```
装的其实是好几个组件：
- `docker-ce`：Docker 引擎本体（守护进程 `dockerd`，负责真正创建/管理容器）。
- `docker-ce-cli`：你敲的 `docker` 命令行工具本身，通过它跟 `dockerd` 通信。
- `containerd.io`：底层真正负责"启动/隔离一个容器进程"的运行时，`dockerd` 是在它上面再包一层好用的接口。
- `docker-buildx-plugin`：`docker build` 用的扩展构建引擎。
- `docker-compose-plugin`：`docker compose` 命令（这个项目目前还没用到，因为只有一个容器，没有多容器编排）。

### 6. 让 `ubuntu` 用户不用每次都敲 `sudo docker ...`

```bash
sudo usermod -aG docker ubuntu
```
`docker` 命令默认要 `sudo` 权限（因为要跟系统级的 `dockerd` 通信）。把 `ubuntu` 用户加进 `docker` 用户组之后，这个用户就有权限直接跑 `docker` 命令，不用每次都打 `sudo`。**这一步做完通常要重新登录一次（退出 SSH 再连一次，或者 `newgrp docker`）新的用户组权限才会生效。**

### 7. 怎么测试 Docker 装没装成功

```bash
docker run hello-world
```
这条命令具体发生的事情，一步步拆开：
1. Docker 先检查本机有没有 `hello-world` 这个镜像——没有。
2. 于是去 **Docker Hub**（Docker 官方的公共镜像仓库，类似 GitHub 之于代码）把这个镜像拉下来。
3. 用这个镜像启动一个容器，容器里就一个程序：打印一段"Hello from Docker!"的说明文字，解释"如果你看到这段话，说明你的安装是正常工作的"。
4. 打印完，这个容器的任务就结束了，进程退出（容器状态变成 `Exited (0)`——`0` 表示正常退出，没报错）。

这就是为什么你们之前 `docker ps -a` 的输出里能看到一行：
```
c1d7bfcc39cd   hello-world   "/hello"   ...   Exited (0) About an hour ago   cool_jepsen
```
这不是部署失败的残留，这是**当初装完 Docker 时特意用来验证安装成功的测试容器**，跑完就退出了，属于正常现象。它跟真正跑应用的 `po-intake` 容器是两回事——`hello-world` 只是"Docker 能不能正常拉镜像、起容器"的自检，完全不涉及你自己的代码。

### 8. 装完 Docker、测试通过之后，才开始部署真正的应用

```bash
git clone https://github.com/jasonpaul0727/PO-agents.git
cd PO-agents
docker build -t po-intake .
```
- `git clone`：把你的代码仓库拉到服务器本地 `~/PO-agents` 目录——注意这时候代码在服务器硬盘上了，但**还没打成镜像，也没在运行**。
- `docker build -t po-intake .`：读取当前目录下的 `Dockerfile`，按里面写的步骤一行行执行（装依赖、拷代码），最后把结果打包成一个镜像，取名叫 `po-intake`（`-t` = tag，给镜像起名字，不然只能用一串哈希 ID 认它）。这一步跑完，`docker images` 就能看到 `po-intake` 这一行了，但**这仍然只是一个静止的模板，还没有任何容器在运行它**。

### 9. 配置 `.env`（在你本地机器上跑的这一条，不是服务器）

```bash
scp -i ~/.ssh/po-agents-key.pem .env ubuntu@3.144.72.92:~/PO-agents/.env
```
`scp` = 通过 SSH 通道复制文件，把你本地已经配好（含真实 `ANTHROPIC_API_KEY`）的 `.env` 文件传到服务器的 `~/PO-agents/.env`。传上去之后又手动加了几行部署专属的配置（`DEMO_USERNAME`、`DEMO_PASSWORD`、`PROCESS_RATE_LIMIT_PER_MINUTE`）。

### 10. 你问的"进去 8000 之后"——这一步才是真正让应用跑起来、监听端口的命令

```bash
docker run -d --name po-intake \
  --env-file .env \
  -v po_data:/app/data \
  -p 127.0.0.1:8000:8000 \
  po-intake
```
这一条命令是整个部署里最关键的一步，逐个参数拆开：

- **`-d`**（detached）：让容器在后台运行，不霸占你当前的 SSH 终端——不加这个，容器会占着你的终端前台运行，一旦你 `Ctrl+C` 或者断开 SSH，容器就可能被打断。
- **`--name po-intake`**：给这个容器起个好记的名字，之后 `docker logs po-intake`、`docker stop po-intake` 都能直接用名字，不用记那串随机哈希 ID。
- **`--env-file .env`**：把 `.env` 文件里每一行 `KEY=VALUE` 都当作环境变量注入容器内部——你代码里 `os.getenv("ANTHROPIC_API_KEY")`、`os.getenv("DEMO_USERNAME")` 这些调用，取到的值就是从这里来的。
- **`-v po_data:/app/data`**：创建（如果不存在）或复用一个叫 `po_data` 的具名 volume，挂载到容器内部的 `/app/data` 目录——SQLite 数据库文件就写在这个目录里，所以数据库内容独立于容器生命周期，容器删了重建，数据还在。
- **`-p 127.0.0.1:8000:8000`**：端口映射。容器内部 Uvicorn（Dockerfile 里 `CMD` 指定）监听的是容器自己的 8000 端口；这条参数把宿主机（服务器）的 `127.0.0.1:8000` 转发到容器的 8000。因为绑的是 `127.0.0.1` 不是 `0.0.0.0`，所以**只有服务器自己能访问这个端口，外网（包括你自己的笔记本）现在还连不进去**。
- **`po-intake`**：用第 8 步 build 出来的那个镜像来启动这个容器。

这条命令跑完，Docker 做的事情是：从 `po-intake` 镜像新建一个容器实例 → 注入环境变量 → 挂上 volume → 启动 Dockerfile 里定义的进程（`uvicorn backend.app:app --host 0.0.0.0 --port 8000`）→ 建立端口转发 → 因为 `-d`，立刻把控制权还给你的终端，只打印出新容器的 ID。

### 11. 起来之后怎么确认它真的工作正常

```bash
docker logs po-intake
```
看容器内部程序的输出日志——正常情况下能看到 Uvicorn 打印类似 `Uvicorn running on http://0.0.0.0:8000` 的行，没有 Python 报错堆栈（traceback）。

```bash
curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/
curl -s -o /dev/null -w "%{http_code}" -u demo:<password> http://127.0.0.1:8000/
```
这两条必须**在服务器里面跑**（因为端口只绑了 `127.0.0.1`），分别验证"没带密码应该被拒（401）"和"带对密码应该放行（200）"——是对 `require_demo_auth` 这个门禁逻辑在真实部署环境里的端到端验证，而不只是本地跑 `pytest` 时的单元测试验证。

### 12. 现在停在哪

以上这些都做完了，容器目前是 `Up`（跑着的）状态。**还没做的**是：重启策略、Elastic IP、安全组开放 80/443、nginx 反代、域名 + HTTPS、CD 自动部署——这些是下一阶段的事，跟"服务器上怎么把 Docker 装起来、把这一个容器跑起来"是两个不同阶段。

## 镜像（Image）和容器（Container）的区别是什么？

- **镜像**是一个只读的模板，打包了运行程序所需的一切（代码、依赖、运行环境）。对应我们跑的 `docker build -t po-intake .`。
- **容器**是镜像的一个运行实例，在镜像基础上加了一层可写层。同一个镜像可以启动出很多个容器，互相独立。对应我们跑的 `docker run ... po-intake`。

## 为什么容器里的 `po.db` 不挂 volume 会丢数据？

容器的可写层是**跟容器绑定的临时存储**——容器被删除（`docker rm`，不是重启）之后,可写层里的数据跟着一起消失。

**Volume** 是独立于容器生命周期的存储，挂载进容器内部某个路径，但数据实际存在宿主机（或专门的存储系统）上。即使容器被删掉重建，只要重新挂载同一个 volume，数据还在。

我们的做法：
```bash
docker run -v po_data:/app/data ...
```
`po_data` 是一个具名 volume,容器里的 `/app/data` 目录实际上指向这个 volume，`po.db` 就存在里面,不受容器重建影响。

## `.dockerignore` 的作用是什么？

控制"构建上下文"（build context，也就是 `docker build` 时发给 Docker daemon 的文件集合）里哪些文件**不参与**这次构建。两个作用：

1. **减小体积、加速构建**——排除 `.git`、`__pycache__`、测试文件等不需要打进镜像的东西。
2. **安全**——防止把不该打包的敏感文件（比如我们项目里 `sample_request` 模块的 Gmail 凭证目录 `secrets/`）意外打进镜像层里。镜像一旦发布出去（哪怕只是内部共享），里面的每一层历史都可能被人扒出来，`.dockerignore` 从源头上排除这个风险。

我们的 `.dockerignore` 明确排除了 `secrets/`、`.env`、`tests/`、`docs/` 等目录。

## Docker 的端口映射 / 网络模型

我们用的命令：
```bash
docker run -p 127.0.0.1:8000:8000 po-intake
```
`-p` 参数格式是 `宿主机绑定地址:宿主机端口:容器端口`：

- **容器端口（右边的 8000）**：应用在容器内部实际监听的端口（Uvicorn 跑在容器里的 8000）。
- **宿主机端口（中间的 8000）**：外部通过服务器的这个端口访问,会被转发进容器。
- **绑定地址（左边的 127.0.0.1）**：限制只有服务器自己能通过这个端口访问，外网连不进来。如果写成 `0.0.0.0:8000:8000` 或者省略地址只写 `8000:8000`，就是对**所有**能访问这台服务器的网络开放。

我们故意先用 `127.0.0.1` 做内部验证，等确认应用没问题、且前面有 nginx + HTTPS 兜底之后，再考虑怎么对外开放。

## 已知的生产环境差距（面试官大概率会追问的点）

- **没有重启策略**：`docker run -d` 没加 `--restart unless-stopped`，服务器重启或 Docker 崩溃后容器不会自动拉起来。生产环境要加这个参数,或者用 systemd/docker compose 管理。
- **没有健康检查**：可以在 Dockerfile 里加 `HEALTHCHECK` 指令，或者在负载均衡器层面配健康检查。
- **单机部署，没有编排**：现在是单个 `docker run`,没有用 Docker Compose 或者 Kubernetes/ECS 这类编排工具管理多容器/多副本。适合演示项目，生产环境要考虑扩展性和容错。

## 这次部署过程中，实际遇到了哪些困难？

（整理自 `git show ab3387e` 的实际改动和 `DEPLOY.md` 的记录，是真实的技术取舍点，不是场面话。）

1. **怎么保证 Gmail 凭证不进镜像**——项目里 `sample_request` 模块有自己的 Gmail OAuth 凭证目录 `secrets/`。如果 Dockerfile 图省事写 `COPY . .`，这些凭证会被打进镜像层，之后就算从文件系统删掉也还留在镜像历史里。解法是 Dockerfile 精确写 `COPY backend/ backend/` + `COPY frontend/ frontend/`（根本不碰 `sample_request` 目录），`.dockerignore` 再做一层兜底。

2. **加安全防护不能破坏已有 138 个测试**——`/api/process` 要挂登录门禁和限流，但本地开发、CI 跑测试时不能强制要求配用户名密码。做法是 `require_demo_auth` 在 `DEMO_USERNAME`/`DEMO_PASSWORD` 都没设时直接 `return`（no-op），默认行为不变，只有显式配了这两个环境变量的部署环境才真正启用门禁——新功能默认关闭、显式开启才生效。

3. **限流器的已知局限，是主动接受不是没想到**——`RateLimiter` 是进程内存实现（一个 dict 记时间戳），意味着以后从单容器扩成多副本时，限流状态不会在副本间共享，相当于失效。当前单机部署够用，代码注释里也写明了这个边界。

4. **端口暴露范围的选择**——`-p 8000:8000` 不写绑定地址时默认是 `0.0.0.0`，等于对外网所有能碰到这台服务器的流量开放。所以先故意绑 `127.0.0.1`，等 nginx + HTTPS 落地之后再考虑放开，避免在反代和限流没验证完整前裸奔上公网。

5. **真正的难点可能还在后面**——目前进度约 55%，剩下的 nginx 反代、Let's Encrypt 证书、安全组开放 80/443 通常才是这类部署最容易卡壳的地方（证书签发依赖域名解析先生效、nginx 配置写错整个服务就不可达）。这些还没做。

## curl 验证门禁那两条命令里，401 和 200 是什么意思？

```bash
curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/                            # -> 401
curl -s -o /dev/null -w "%{http_code}" -u demo:<password> http://127.0.0.1:8000/          # -> 200
```

- **200 OK**：请求成功，服务器正常处理并返回内容。
- **401 Unauthorized**：字面是"未授权"，更准确说是**没提供有效的身份凭证**——服务器不知道你是谁（或者用户名密码不对），拒绝处理，让你先去认证。

**401 vs 403（面试常见追问）**：
- 401 = 没证明自己是谁，或者证明错了 → 去登录
- 403 = 已经证明了身份，但这个身份就是没权限 → 换账号也没用

对应到我们的代码：`backend/security.py` 的 `require_demo_auth` 没收到凭证或凭证不对时抛 `HTTPException(401, ...)` —— 这是"没通过身份验证"，不是"权限不够"，所以用 401 而不是 403。

**第一条为什么是 401**：curl 不带 `-u`，请求头里没有 `Authorization` 字段，`require_demo_auth` 检测到没凭证，拒绝。

**第二条为什么是 200**：`-u demo:<password>` 让 curl 自动把用户名密码 Base64 编码后塞进 `Authorization: Basic ...` 请求头，服务器验证通过，正常返回页面。

**面试官可能会挖的细节**：HTTP Basic Auth 只是 Base64 编码，**不是加密**——如果走明文 HTTP 传输，密码等于裸奔。这正是为什么现在故意先绑 `127.0.0.1:8000`（只有服务器自己能访问），要等 nginx + HTTPS 落地、密码在传输过程中被加密之后，才考虑对公网开放。
