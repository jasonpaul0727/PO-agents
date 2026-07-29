# 操作手册 / Runbook — PO Intake Agent

日常"怎么访问网站""怎么本地跑起来""怎么上服务器操作"的速查表。部署原理、CI/CD 细节、踩坑记录见 `DEPLOY.md`；产品功能说明见 `README.md`。

## 一、访问已上线的网站

- URL：`https://yanxiabu001.com/`
- 认证：HTTP Basic Auth，浏览器会弹出用户名/密码框
  - 用户名：`demo`
  - 密码：**不写在任何文档或对话记录里**——历史上有过一次整份 `.env` 被贴进 AI 对话导致真实泄露的教训（撤销重发过一轮密钥），现在的规矩是密码只存在服务器 `.env` 里。自己在自己的终端查，不要贴给 AI 看：
    ```bash
    ssh -i ~/.ssh/po-agents-key.pem ubuntu@3.17.209.141
    grep '^DEMO_PASSWORD=' ~/PO-agents/.env
    ```
- 正常情况下会先弹认证框（对应 `curl` 探活时看到的那个 401）；输入对了才进得去。如果直接看到页面内容、没弹框，说明认证配置坏了，需要排查。

## 二、本地开发环境启动（不碰服务器，本机跑一份）

```bash
python3.12 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # 填 ANTHROPIC_API_KEY，其余按需
python tests/make_sample_pdfs.py   # 生成本地测试用示例 PDF（可选）
uvicorn backend.app:app --reload
# 打开 http://localhost:8000
```

本地不设 `DEMO_USERNAME`/`DEMO_PASSWORD` 的话，`backend/security.py` 里的认证是 no-op，直接能访问，不用登录。

## 三、服务器常用操作

```bash
# SSH 上服务器（操作者个人密钥，非 CI 专用密钥）
ssh -i ~/.ssh/po-agents-key.pem ubuntu@3.17.209.141

# 查看容器状态 / 实时日志
docker ps
docker logs po-intake --tail 100 -f

# 只是重启容器（不换版本、不用凭证）
docker restart po-intake

# 确认 .env 里某个 key 存在（不显示真实值——永远不要 cat 整个 .env）
grep -c "^ANTHROPIC_API_KEY=" ~/PO-agents/.env

# 手动回滚到某个旧版本 —— 完整命令见 DEPLOY.md §9「回滚命令」
```

## 四、正常发版流程

1. 改代码 → commit → push 到 `master`
2. GitHub Actions 自动跑：`test`（pytest + ruff lint/format）→ `build-and-deploy`（build 镜像推 GHCR → SSH 部署到 EC2 → HTTP 健康检查）
3. **例外**：如果这次改动碰了 `scripts/deploy.sh` 本身（或它依赖的服务器端文件），需要额外手动同步一次服务器上的 git checkout——CI 目前不会自动做这一步（已知设计取舍，见 `DEPLOY.md` §9 的踩坑记录）：
   ```bash
   ssh -i ~/.ssh/po-agents-key.pem ubuntu@3.17.209.141 "cd ~/PO-agents && git pull"
   ```
4. 查看 / 重跑 CI：
   ```bash
   gh run list --branch master --limit 5
   gh run watch <run-id>
   gh run rerun <run-id> --failed
   ```

## 五、遇到问题先做什么

1. `curl -s -o /dev/null -w "%{http_code}\n" https://yanxiabu001.com/` —— `401` 是健康；`502`/连不上才是真出问题。
2. 上服务器看容器：`docker ps -a --filter name=po-intake`（带 `-a`，容器不是 running 状态也能看到）。
3. 看应用日志：`docker logs po-intake`。
4. 看最近一次自动部署有没有失败：`gh run list --branch master --limit 5`。
5. 仍拿不到线索，回 `DEPLOY.md` 找对应章节（§9 自动化 CD 部署 / 常用排查命令）。
