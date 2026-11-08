# 迁到一台常驻云服务器（7×24 可用）

CloudStudio 是开发沙箱：工作区关掉或空闲回收，`https://<id>--80...cloudstudio.club`
就打不开了。要「把网址发给谁都能随时点开」，需要一台常驻机器。本文是从零到可访问的完整步骤，
假设用 Docker Compose（`docker-compose.yml` 已包含 api / embed / web / postgres / redis）。

## 0. 买机器

| 项 | 建议 |
|---|---|
| 规格 | **2C4G 起**（4C8G 更从容）；BGE-M3 常驻约 2.5–3 GB |
| 系统 | Ubuntu 22.04 / 24.04 |
| 磁盘 | ≥ 40 GB（模型权重 ~2.3 GB + 镜像 + Postgres） |
| 网络 | 有公网 IP；安全组放行 **22 / 80 / 443** |
| 区域 | 国内用户选上海 / 广州；有备案需求再考虑域名 |

> 2C4G 能稳定跑「单人/小流量演示」，但**复现不了 README 里的 200 连接 / 20 并发**——
> 那组数字是在 8 核机器上测的。要压测就上 8C 或另起一台压测机。

## 1. 装 Docker

```bash
sudo apt-get update && sudo apt-get install -y ca-certificates curl git
curl -fsSL https://get.docker.com | sudo sh
sudo systemctl enable --now docker
docker compose version
```

国内下载慢可以给 Docker 配镜像加速（可选），或直接用系统源的 `docker.io` + `docker-compose-v2`。

## 2. 拉代码、配 `.env`

```bash
sudo mkdir -p /opt && cd /opt
sudo git clone https://github.com/true-12138/mingli-rag.git
cd mingli-rag
cp .env.example .env
chmod 600 .env
```

编辑 `.env`，至少填三项：

```dotenv
DEEPSEEK_API_KEY=sk-...            # 你的模型 key
MINGLI_API_TOKEN=<随机串>          # 用下面的命令生成，别手编
POSTGRES_PASSWORD=换成一个随机密码
```

生成 token 但不打印：

```bash
sed -i "s|^# MINGLI_API_TOKEN=.*|MINGLI_API_TOKEN=$(openssl rand -hex 24)|" .env
grep -c '^MINGLI_API_TOKEN=..' .env    # 应为 1
```

## 3. 起服务

```bash
cd /opt/mingli-rag
sudo docker compose up -d --build
sudo docker compose ps
```

- 首次构建 10–20 分钟（2C 机器；npm + pip 都要下东西）。
- 首次启动 `embed` 会下载 BGE-M3 权重（~2.3 GB）到 `hf_cache` volume，期间 `embed` 显示
  `starting` 是正常的；等它 healthy，`api` 才会起来。
- 关注进度：`sudo docker compose logs -f embed`。

## 4. 验收

```bash
curl -s -o /dev/null -w 'api-direct:%{http_code}\n' http://127.0.0.1:8000/trace/x   # 401
curl -s -o /dev/null -w 'via-nginx:%{http_code}\n' http://127.0.0.1/api/trace/x     # 404
curl -s -o /dev/null -w 'metrics:%{http_code}\n'   http://127.0.0.1/metrics         # 404
curl -s -o /dev/null -w 'frontend:%{http_code}\n'  http://127.0.0.1/                # 200
curl -s http://127.0.0.1/health
```

浏览器打开 `http://<公网IP>/`，问一句确认逐 token 流式。四条含义见 README「公网部署实录」。

## 5. 重启后自动恢复

compose 里每个服务都是 `restart: unless-stopped`，只要 Docker 开机自启（第 1 步已
`systemctl enable`），机器重启后服务会自己回来。想显式加一层开机单元，用
[`mingli-api.service`](mingli-api.service)：

```bash
sudo cp deploy/mingli-api.service /etc/systemd/system/
# 仓库不在 /opt/mingli-rag 时，改 unit 里的 WorkingDirectory
sudo systemctl daemon-reload && sudo systemctl enable --now mingli-api
```

## 6. 域名与 HTTPS

### 6.1 先看清备案这个前提

- **服务器在中国大陆**：域名解析到它的 80/443 必须先完成 ICP 备案（1–3 周，需实名）。
  CloudStudio 给的 `<id>--80...cloudstudio.club` 是平台自己的域名，不需要你备案。
- **不想备案**：买香港/新加坡的轻量（腾讯云/阿里云都有，免备案），或者用 6.3 的隧道。

### 6.2 自己的域名 + 云服务器

**A. 直接解析 + certbot**（大陆需备案；香港/海外不用）

```bash
sudo apt-get install -y certbot
sudo certbot --nginx -d demo.example.com
```

注意 `web` 容器内部监听 80、宿主机 80 已映射给它。若在宿主机再装 nginx 做 TLS 终止，
要把 `docker-compose.yml` 里 `web` 的端口改成 `127.0.0.1:8080:80`，再反代过去。

**B. 域名托管到 Cloudflare（更省事）**：A 记录指向服务器 IP，开橙云（Proxied），
SSL/TLS 用 `Full`（源站只有 80 时用 `Flexible`）。HTTPS、CDN、隐藏源站 IP 一次到位，
源站继续跑 80。

### 6.3 不换机器也能有固定域名：Cloudflare Tunnel

适用：还在 CloudStudio / 自己电脑上跑，但想要 `https://demo.你的域名`。

```bash
curl -L -o /usr/local/bin/cloudflared \
  https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64
chmod +x /usr/local/bin/cloudflared
cloudflared tunnel login          # 浏览器授权，选你的域名
cloudflared tunnel create mingli  # 记下输出的 tunnel id
```

写 `~/.cloudflared/config.yml`：

```yaml
tunnel: mingli
credentials-file: /root/.cloudflared/<tunnel-id>.json
ingress:
  - hostname: demo.example.com
    service: http://127.0.0.1:80
  - service: http_status:404
```

```bash
cloudflared tunnel route dns mingli demo.example.com
cloudflared tunnel run mingli
```

SSE 能透传。如果发现逐字变成整段，在 Cloudflare 关掉 Rocket Loader，并把该主机的
Browser Cache TTL 设为 `Respect Existing Headers`——`/api/` 不能被缓存。

**局限**：隧道进程必须一直活着；机器/工作区停了，链接照样 502。它解决的是
「网址好看 + HTTPS」，不解决「机器常驻」。

### 6.4 完全免费、临时给别人看

```bash
cloudflared tunnel --url http://127.0.0.1:80
```

会输出一个 `https://xxxx.trycloudflare.com`，重启就变。适合临时发给同学，不适合放简历。

## 7. 日常

| 操作 | 命令 |
|---|---|
| 看日志 | `sudo docker compose logs -f api` |
| 更新代码 | `git pull && sudo docker compose up -d --build` |
| 重启 API | `sudo docker compose restart api` |
| 备份业务库 | `sudo docker compose exec postgres pg_dump -U mingli mingli > backup.sql` |
| 改 token | 改 `.env` → `sudo docker compose up -d web api` |

## 8. 只想先跑起来、不做 Docker？

宿主机直跑也行，步骤见 [`README.md`](README.md) §6；用
[`../scripts/serve.sh`](../scripts/serve.sh) 一条命令起 Redis / API / Nginx。
缺点是依赖装在本机、升级要手工 pip，长期维护不如 compose 省心。
