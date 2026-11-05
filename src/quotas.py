# -*- coding: utf-8 -*-
"""API 侧的三层每日额度：单个匿名 ID、单个 IP、全站。

为什么放在数据库里，而不是进程内计数器：
- uvicorn 可能开多个 worker，进程内计数各算各的；
- 重启进程不能把已用额度清零；
- `data/.quota.json` 这类文件在多进程下会互相覆盖。

占用额度的顺序是「用户 -> IP -> 全站」。每一层都用一条
`UPDATE ... WHERE used < limit` 完成「判断 + 加一」，靠数据库行锁保证原子性。
任意一层失败时，把前面已占用的层退回去，避免一次拒绝白扣用户额度。

只有使用服务端 `DEEPSEEK_API_KEY` 的请求才计数；访客在 `X-DeepSeek-Key`
里自带 key 时不占服务端预算。额度按 UTC 自然日重置。
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from db.base import SessionLocal
from db.models import QuotaUsage

logger = logging.getLogger("mingli.quotas")

DEFAULT_USER_DAILY = 20
DEFAULT_IP_DAILY = 60
DEFAULT_GLOBAL_DAILY = 300


@dataclass(frozen=True)
class Reservation:
    """一次请求成功占用的额度，失败时可凭它整笔退回。"""

    day: str
    buckets: tuple[str, ...] = field(default_factory=tuple)


class QuotaExceeded(Exception):
    """某一层额度用完。API 层把它映射成 429 + Retry-After。"""

    def __init__(self, bucket: str, limit: int, remaining: int = 0) -> None:
        self.bucket = bucket
        self.limit = limit
        self.remaining = max(0, remaining)
        self.retry_after = seconds_to_reset()
        super().__init__("额度已用完：{}（每日上限 {}）".format(bucket, limit))


def enabled() -> bool:
    return os.environ.get("MINGLI_QUOTA_ENABLED", "1").strip() != "0"


def _int_env(name: str, default: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        return max(0, int(raw))
    except ValueError:
        logger.warning("环境变量 %s=%r 不是整数，使用默认值 %d", name, raw, default)
        return default


def limits() -> tuple[int, int, int]:
    """返回 (单匿名 ID, 单 IP, 全站) 的每日上限。"""
    return (
        _int_env("MINGLI_QUOTA_USER_DAILY", DEFAULT_USER_DAILY),
        _int_env("MINGLI_QUOTA_IP_DAILY", DEFAULT_IP_DAILY),
        _int_env("MINGLI_QUOTA_GLOBAL_DAILY", DEFAULT_GLOBAL_DAILY),
    )


def utc_day() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def seconds_to_reset() -> int:
    """距离下一个 UTC 零点还有多少秒，至少 1。"""
    now = datetime.now(timezone.utc)
    tomorrow = (now + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return max(1, int((tomorrow - now).total_seconds()))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _consume_one(session: Session, bucket: str, day: str, limit: int) -> bool:
    """原子占用一层额度；返回是否成功。"""
    if limit <= 0:
        return False

    def bump() -> int:
        result = session.execute(
            update(QuotaUsage)
            .where(
                QuotaUsage.bucket == bucket,
                QuotaUsage.day == day,
                QuotaUsage.used < limit,
            )
            .values(used=QuotaUsage.used + 1, updated_at=_now())
            .execution_options(synchronize_session=False)
        )
        session.commit()
        return int(result.rowcount or 0)

    if bump():
        return True

    # 没更新到行：要么今天还没有这一行，要么行存在但已到上限。
    # 直接尝试插入，让主键唯一约束裁决，不做「先 SELECT 再 INSERT」——
    # 后者在并发下会把读事务升级成写事务，SQLite 可能直接报 locked。
    try:
        session.add(QuotaUsage(bucket=bucket, day=day, used=1, updated_at=_now()))
        session.commit()
        return True
    except IntegrityError:
        # 另一个进程抢先插入了同一行（或行已满），退回到 UPDATE 路径。
        session.rollback()
        return bool(bump())


def consume(
    anonymous_id: str | None,
    ip: str | None,
    visitor_key: str | None = None,
    session: Session | None = None,
) -> Reservation | None:
    """申请一次生成请求的额度。

    返回 `None` 表示「本次不需要计数」（额度关闭、访客自带 key、没有服务端 key）；
    返回 `Reservation` 表示三层都已占用，调用方应在生成失败时调用 `refund`；
    抛出 `QuotaExceeded` 表示已拒绝，且前面占用的层已经退回。
    """
    if not enabled():
        return None
    if (visitor_key or "").strip():
        return None
    if not (os.environ.get("DEEPSEEK_API_KEY") or "").strip():
        # 没有服务端 key 时请求本来就会 503，不必占用用户可见的额度。
        return None

    user_limit, ip_limit, global_limit = limits()
    day = utc_day()
    anonymous_id = (anonymous_id or "").strip()
    ip = (ip or "").strip()

    plan: list[tuple[str, int]] = []
    if anonymous_id:
        plan.append(("user:" + anonymous_id[:120], user_limit))
    if ip:
        plan.append(("ip:" + ip[:120], ip_limit))
    plan.append(("global", global_limit))

    own = session is None
    active = SessionLocal() if session is None else session
    reserved: list[str] = []
    try:
        for bucket, limit in plan:
            if _consume_one(active, bucket, day, limit):
                reserved.append(bucket)
                continue

            used = active.execute(
                select(QuotaUsage.used).where(
                    QuotaUsage.bucket == bucket, QuotaUsage.day == day
                )
            ).scalar_one_or_none()
            # 结束只读事务再写：SQLite 下读事务直接升级为写事务可能报 locked
            active.rollback()
            _refund_buckets(active, day, reserved)
            raise QuotaExceeded(bucket, limit, remaining=limit - int(used or 0))

        return Reservation(day=day, buckets=tuple(reserved))
    finally:
        if own:
            active.close()


def _refund_buckets(session: Session, day: str, buckets: list[str] | tuple[str, ...]) -> None:
    for bucket in buckets:
        session.execute(
            update(QuotaUsage)
            .where(
                QuotaUsage.bucket == bucket,
                QuotaUsage.day == day,
                QuotaUsage.used > 0,
            )
            .values(used=QuotaUsage.used - 1, updated_at=_now())
            .execution_options(synchronize_session=False)
        )
    session.commit()


def refund(reservation: Reservation | None, session: Session | None = None) -> None:
    """生成失败时退回整笔额度。退回失败只记日志，不能遮住原始错误。"""
    if reservation is None or not reservation.buckets:
        return
    own = session is None
    active = SessionLocal() if session is None else session
    try:
        _refund_buckets(active, reservation.day, reservation.buckets)
    except Exception:
        active.rollback()
        logger.warning("额度退回失败 day=%s buckets=%s", reservation.day,
                       reservation.buckets, exc_info=True)
    finally:
        if own:
            active.close()
