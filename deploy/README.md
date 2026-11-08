# 部署（Docker Compose + Nginx 同源）

> 要「网址发出去、别人随时能打开」，需要一台常驻机器而不是开发沙箱——完整步骤见
> [`VPS.md`](VPS.md)。本文是同一套部署的细节说明。

目标：公网只暴露一个入口。Nginx 提供前端静态页，并把 `/api/` 反代到 FastAPI，
**在服务端注入 Bearer token**——浏览器不持有、也拿不到 `MINGLI_API_TOKEN`。

```
Browser ──▶ Nginx (:80) ──/api/──▶ FastAPI (:8000) ──▶ Redis / Postgres / Embed
              └── 前端静态资源
```

> 不要把 token 编进前端（`VITE_*`）。打包后任何人都能在 JS 里看到它。

## 1. 机器准备

```bash
sudo apt update
sudo apt install -y docker.io docker-compose-plugin
sudo systemctl enable --now docker
```

2C4G 可以跑，但 BGE-M3 由独立的 `embed` 服务常驻（compose 已配置
`MINGLI_EMBED_URL=http://embed:8100`），不要改成每个 worker 本地加载。
首次启动会下载模型权重到 `hf_cache` volume。

## 2. 配置

```bash
git clone https://github.com/true-12138/mingli-rag.git /opt/mingli-rag
cd /opt/mingli-rag
cp .env.example .env
# 至少填 DEEPSEEK_API_KEY，并设置 MINGLI_API_TOKEN
chmod 600 .env
```

`.env` 已在 `.gitignore` 里，不要提交。

## 3. 起服务

```bash
docker compose up -d --build
docker compose ps
curl -s localhost/health
```

打开 `http://<服务器IP>/` 应该能进对话页。`8000` 端口只绑在
`127.0.0.1`，公网直接访问不到——这是故意的，防止绕过 Nginx 的 token 注入。

## 4. 鉴权验证

```bash
# 1) 绕过 Nginx 直连 API：应 401
curl -s -o /dev/null -w '%{http_code}\n' -X POST http://127.0.0.1:8000/chat \
  -H 'Content-Type: application/json' \
  -d '{"question":"羊刃分几种？","mode":"rag"}'
# 期望：401

# 2) 经过 Nginx：token 由服务端注入，应 200
curl -s -o /dev/null -w '%{http_code}\n' -X POST http://127.0.0.1/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"question":"羊刃分几种？","mode":"rag"}'
# 期望：200

# 3) 确认 8000 没有对公网监听
ss -ltn | grep ':8000'      # 应只有 127.0.0.1:8000

# 4) /metrics 不对外
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1/metrics   # 404
```

## 5. HTTPS

- 云平台自带负载均衡/证书：直接把平台入口指向实例的 80 端口即可。
- 自己在宿主机做 TLS：让宿主机 Nginx/Caddy 监听 443，反代到
  `127.0.0.1:8080`；同时把 compose 里 `web` 的端口改成
  `127.0.0.1:8080:80`，避免 80 端口冲突。

## 6. 不用 Docker 的部署方式

宿主机直接跑 uvicorn + Nginx。配置好一次之后，重启机器/工作区只要：

```bash
./scripts/serve.sh up       # Redis → API（127.0.0.1）→ Nginx，并打印四条验收
```

下面是脚本做的事，手工执行时照这个顺序：

```bash
# 后端：必须绑 127.0.0.1。api.py 默认 0.0.0.0，那样 8000 会直接暴露到公网，
# 绕过 Nginx 的同源入口（token 仍然校验，但入口不唯一了）。
MINGLI_HOST=127.0.0.1 MINGLI_WORKERS=2 MINGLI_REDIS_URL=redis://127.0.0.1:6379/0 \
  nohup python src/api.py > api.log 2>&1 &

# 前端：服务器上没装 Node 时，直接从已构建的 web 镜像里取产物
sudo mkdir -p /var/www/mingli-dist
_cid=$(docker create mingli-rag-web:local)
sudo docker cp "$_cid":/usr/share/nginx/html/. /var/www/mingli-dist/
docker rm "$_cid"
# 或者本地构建：cd frontend && npm ci && npm run build && sudo cp -r dist/* /var/www/mingli-dist/

# Nginx：生成配置时注入 token，不落盘到仓库
MINGLI_API_TOKEN=... envsubst '${MINGLI_API_TOKEN}' < deploy/nginx.conf \
  | sudo tee /etc/nginx/sites-available/mingli > /dev/null
sudo ln -s /etc/nginx/sites-available/mingli /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

## 7. 验收清单

- [ ] `curl https://<域名>/health` 返回 200，`chunks=8681`、`embedding_dim=1024`
- [ ] 不带 token 直连 `127.0.0.1:8000/chat` 返回 401
- [ ] 经 `/api/chat` 的请求正常返回（token 由 Nginx 注入）
- [ ] 前端三种模式都能流式输出，引用可展开
- [ ] `docker compose logs api` 里没有 key、没有 traceback
- [ ] `docker compose restart` 后 `/health` 自动恢复

## 8. 还没做的

- Langfuse 自建与逐轮 trace
- 多副本 / 负载均衡（需把 Redis 槽与语义缓存迁到共享实例，已具备条件）
