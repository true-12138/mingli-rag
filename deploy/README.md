# 部署到 ECS（FastAPI + Docker + Nginx）

目标：一台 2 核 4G 的 Ubuntu 22.04，公网能访问 `/health`，`/chat` 能跑，
Nginx 做限流和反代，systemd 保证开机自启。

## 1. 机器准备

```bash
sudo apt update
sudo apt install -y docker.io docker-compose-plugin nginx
sudo systemctl enable --now docker nginx
```

2C4G 足够跑检索和 DeepSeek 调用；**首次查询会下载 BGE-M3 权重（几 GB）**，
建议先挂好 `hf_cache` volume，或把本地权重放进 `MINGLI_MODEL_DIR`。

## 2. 拉代码与配置

```bash
sudo mkdir -p /opt/mingli-rag && sudo chown $USER:$USER /opt/mingli-rag
git clone https://github.com/true-12138/mingli-rag.git /opt/mingli-rag
cd /opt/mingli-rag

cp .env.example .env
# 编辑 .env：至少填 DEEPSEEK_API_KEY，并设置 MINGLI_API_TOKEN
chmod 600 .env
```

`.env` 已在 `.gitignore` 里，不要提交。

## 3. 起服务

```bash
docker compose up -d --build
docker compose ps
curl -s localhost:8000/health
```

首次构建会装 torch / sentence-transformers，镜像比较大；构建完启动时只加载语料和
`embeddings.npy`，BGE-M3 在第一次检索时才加载。

**数据持久化**：compose 把业务库和评测库放在 `mingli_state` 卷（容器内
`/var/lib/mingli`），语料仍在镜像的 `/app/data`，两者不冲突。
`docker compose down` 不会删卷；只有 `down -v` 会。备份：

```bash
docker run --rm -v mingli-rag_mingli_state:/src -v "$PWD":/backup alpine \
  tar czf /backup/mingli-state-$(date +%F).tgz -C /src .
```

**存活与就绪**：`/health` 是存活探针，`/ready` 是就绪探针。`/ready` 在
`DEEPSEEK_API_KEY` 未配置或索引不一致时返回 503；接负载均衡时用它摘流量，
不要用 `/health`。

带 token 调用：

```bash
curl -s localhost:8000/chat \
  -H "Authorization: Bearer $MINGLI_API_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"question":"羊刃分几种？","mode":"rag"}'
```

## 4. Nginx + HTTPS

```bash
sudo cp deploy/nginx.conf /etc/nginx/sites-available/mingli-api
sudo ln -s /etc/nginx/sites-available/mingli-api /etc/nginx/sites-enabled/
# 改 server_name 为自己的域名
sudo nginx -t && sudo systemctl reload nginx

sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d api.example.com
```

Nginx 里已经做了 `2r/s` + burst 10 的限流；应用层还有 `MINGLI_MAX_CONCURRENCY`
（默认 4）兜底，超了返回 429。

## 5. 开机自启

```bash
sudo cp deploy/mingli-api.service /etc/systemd/system/
# 把 WorkingDirectory 改成 /opt/mingli-rag
sudo systemctl daemon-reload
sudo systemctl enable --now mingli-api
sudo systemctl status mingli-api
```

## 6. 验收清单

- [ ] `curl https://api.example.com/health` 返回 200，`chunks=8681`、`embedding_dim=1024`
- [ ] `curl https://api.example.com/ready` 返回 200；临时清空 key 后返回 503
- [ ] `docker compose down && docker compose up -d` 后，之前的会话仍能查到（卷生效）
- [ ] `/chat` 三种 `mode` 都能返回；`rag` 和 `agent` 至少各跑 1 条真实问题
- [ ] 不带 token 返回 401（设置了 `MINGLI_API_TOKEN` 时）
- [ ] 并发打 10 个请求，超出部分返回 429，服务不崩
- [ ] `docker compose logs -f api` 里没有 key、没有 traceback
- [ ] 重启机器后 `systemctl status mingli-api` 是 active，`/health` 自动恢复

## 7. 还没做的

- Langfuse 自建与逐轮 trace（下一步）
- P50/P95、token/成本统计（下一步）
- 多副本 / 负载均衡（单机 2C4G 暂时不需要）
