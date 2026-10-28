"""按 slug 取算法的唯一入口。

保存算法是**插入新行**（版本递增），不是更新：`save_algorithm` 会为同一个 slug
写入 version 1、2、3……这是有意的，历史版本要留痕。但各处的查询写的是
``scalar_one_or_none()``——它在读到第二行时抛 ``MultipleResultsFound``。

后果是：同一个 slug 存第三次，入库接口 500；而且**运行路径上是同样的写法**，
所以一个被修改过两次的算法之后再被调用也会 500。自扩展功能因此实际不可用。

这里把语义固定成一句话：**按 slug 查，拿到的是当前版本**（version 最大的那行，
同版本时取 id 最大）。所有调用点都走这个函数，不要再自己拼 select。
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import Algorithm

__all__ = ["latest_algorithm"]


async def latest_algorithm(
    session: AsyncSession,
    slug: str,
    owner_id: Optional[int] = None,
) -> Optional[Algorithm]:
    """取某个 slug 的当前版本。

    :param session: 数据库会话。
    :param slug: 算法 slug。
    :param owner_id: 限定归属；``None`` 表示不限（内置/公共查找路径用）。
    :returns: 当前版本的算法行，没有则 ``None``。
    """
    stmt = select(Algorithm).where(Algorithm.slug == slug)
    if owner_id is not None:
        stmt = stmt.where(Algorithm.owner_id == owner_id)
    stmt = stmt.order_by(Algorithm.version.desc(), Algorithm.id.desc()).limit(1)
    return (await session.execute(stmt)).scalars().first()
