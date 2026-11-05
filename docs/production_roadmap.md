# 从可部署 Demo 到可运营服务：生产化路线

这份文档把「离上线还差什么」拆成可验收的里程碑。每完成一个里程碑都应当能单独部署、
单独回滚，而不是攒到最后一次性上线。

当前定位：**L1 单机可部署 Demo**。目标：**L2 小规模公开 Beta**（陌生用户可用、
成本可控、故障可排、版本可回滚）。L3（SLA、多副本、多租户、合规）暂不作为目标。

## 状态总览

| 里程碑 | 内容 | 状态 |
|---|---|---|
| M1 | 并发与持久化地基 | ✅ 代码完成，待 CI |
| M2 | 身份与配额 | ⬜ 未开始 |
| M3 | Postgres 与备份 | ⬜ 未开始 |
| M4 | 记忆压缩 | ⬜ 未开始 |
| M5 | 高可用与上游韧性 | ⬜ 未开始 |
| M6 | 交付流水线与回滚 | ⬜ 未开始 |
| M7 | 产品缺口（星座运势 / 前端形态） | ⬜ 待决策 |

---

## M1 并发与持久化地基（已完成）

**问题**：容器重建丢业务库；SQLite 并发写直接 `database is locked`；冷启动多个请求
各加载一份 BGE-M3；没有就绪探针。

**改动**：

- `src/db/base.py`：SQLite 连接统一开 `WAL`、`busy_timeout=5000`、`synchronous=NORMAL`；
- `docker-compose.yml`：新增 `mingli_state` 卷，业务库与评测库放到 `/var/lib/mingli`，
  与镜像内的语料目录 `/app/data` 分开；
- `src/retrieval.py`：`_LazyModel` 双重检查锁，冷启动只加载一次；
- `src/api.py`：新增 `/ready` 就绪探针（缺 key / 索引不一致返回 503），`/health` 只做存活；
- 测试：SQLite pragma、`/ready` 两种状态、并发冷启动只加载一次。

**验收**：

```bash
docker compose down && docker compose up -d
# 之前的会话仍在
curl -s localhost:8000/ready
pytest -q tests/test_db_models.py tests/test_api.py tests/test_retrieval_runtime.py
```

**仍然不解决**：多副本共享 SQLite、API 无配额、单上游无重试。这些进入 M2/M3/M5。

---

## M2 身份与配额

**问题**：API 只有一个全局静态 Bearer token；`X-Anonymous-Id` 客户端可伪造；
Streamlit 的 `.quota.json` 无锁、多进程会丢计数；API 路径完全没有额度，单 token
泄露即可烧穿预算。

**范围**：

1. 把 `quota_ledger` 接进请求路径（模型已存在，见 `src/db/models.py:223`）：
   - 三层额度：单匿名 ID 每日、单 IP 每日、全站每日；
   - 只在用服务端 key 时计数；访客自带 key 不占额度；
   - 用一条 `UPDATE ... WHERE used < limit` 或事务 + 唯一约束做原子递增，
     不依赖进程内计数。
2. `/chat` 与 `/v1/.../chat` 共用同一套额度检查；Streamlit 逐步改用同一账本。
3. API token 改为**默认拒绝**：未配置 `MINGLI_API_TOKEN` 时，非本机请求返回 503
   并提示配置，避免“忘了设置就全公开”。
4. 额度耗尽返回 429，并在响应里带 `Retry-After` 与剩余额度。

**验收**：并发 50 个请求只放行额度内的数量；重启进程后计数不重置；多进程共享同一上限。

---

## M3 Postgres 与备份

**问题**：SQLite 是单写者，WAL 只缓解不解决；多副本、连接池、在线备份都需要 Postgres。

**范围**：

1. `MINGLI_DB_URL=postgresql+psycopg://...` 作为默认部署方式，SQLite 只保留本地开发；
2. 增加 `psycopg[binary]` 依赖；compose 增加 `postgres` service（profile 可选）；
3. Alembic 在 Postgres 上跑一遍 `upgrade head` / `downgrade`，确认 batch 模式不需要；
4. 连接池参数（`pool_size`、`pool_pre_ping`、`pool_recycle`）；
5. 备份：每日 `pg_dump` + 保留 7 天；恢复演练写进 `deploy/README.md`；
6. 平台/评测中台若继续用 SQLite，明确它不参与线上请求路径。

**验收**：两台 API 副本同时写同一会话不死锁；`pg_dump` 恢复后会话、消息、run 完整。

---

## M4 记忆压缩

**问题**：当前只有硬截断（3 轮 / 1200 字、服务端 6 条消息）；`conversations.summary`
字段建了但从未生成。长对话会丢早期约束，且没有长期记忆。

**范围**：

1. 滚动摘要：超过 N 条消息后，用一次低成本模型调用把更早的消息压成
   `conversations.summary`，prompt 使用「摘要 + 最近 K 条」；
2. 摘要写入做成后台任务或请求内低优先级调用，失败时退回纯截断，不影响回答；
3. 摘要也要标注「不作为回答证据」，引用仍只来自本轮工具返回；
4. token 预算：摘要 + 最近消息 + 证据 + 输出的总预算写进 `agent_config.json`，
   进入 `state_version`；
5. 可选长期记忆：用户偏好/常用书目单独建表，只用于排序和改写，不作为证据。

**验收**：20 轮对话后仍能正确回答依赖第 1 轮约束的问题；摘要失败时行为与现在一致；
token 不随轮数线性增长。

---

## M5 高可用与上游韧性

**问题**：单进程、单节点、单上游；`requests` 120s 超时期间一直占信号量；无重试、
熔断、降级；trace 与 usage 在进程内。

**范围**：

1. 多副本：至少 2 个 API 实例 + Nginx/云 LB；`/ready` 接 LB；优雅停机（停止接新请求，
   等在途请求结束）；
2. 全局限流与并发：Redis 或数据库计数，替换进程内 `BoundedSemaphore`；
3. 上游：连接/读超时分离、指数退避重试（只重试幂等失败）、熔断、备用模型供应商开关；
4. 可观测：Prometheus + Grafana（或云监控），至少 4 个告警：5xx 率、P95、上游 429、
   额度耗尽；trace 落 Langfuse 或等价后端；
5. 压测：10 / 50 并发、上游超时、进程重启、迁移回滚，记录容量结论。

**验收**：杀掉一个副本，LB 自动摘流量，用户无感；上游 429 时服务降级而不是雪崩；
P95 和成本有看板与告警。

---

## M6 交付流水线与回滚

**问题**：CI 只跑 pytest；没有镜像仓库、CD、staging、灰度与回滚；systemd 开机
`--build` 每次重新构建。

**范围**：

1. CI：ruff / pyright（或 mypy）、`docker build`、`alembic upgrade head` 冒烟、
   依赖审计、覆盖率门槛；
2. 镜像推仓库，打 commit sha tag；部署只拉镜像，不在机器上构建；
3. staging 环境 + 发布清单；灰度：先 1 个副本，观察 5xx/P95，再全量；
4. 回滚：镜像回退 + 迁移可逆（或只做向前兼容迁移）；
5. 部署后自动跑 `/ready` + 一条真实问答冒烟。

**验收**：一次发布可以在 10 分钟内回滚；迁移失败不会留下半升级数据库。

---

## M7 产品缺口（需要先决策）

1. **星座**：当前是**本命盘**（行星黄经、上升/天顶、整宫制、相位），不是每日/每周
   星座运势。要做运势需要行运（transit）、日期维度与内容策略；做合盘需要另一套算法。
2. **前端**：当前是 Streamlit，不是独立 SPA。如果目标是「AI 生成的前端工程」，
   需要决定是换 React/Next，还是保留 Streamlit 并把 API 作为唯一后端。

这两项是产品决策，不与生产化里程碑混在一起做。

---

## 明确不做（L2 阶段）

- Kubernetes / 服务网格；
- 多租户计费系统；
- 自研向量数据库（8,681 条暴力检索足够）；
- 微调模型；
- 把 Streamlit 和 API 合并成同一个进程。
