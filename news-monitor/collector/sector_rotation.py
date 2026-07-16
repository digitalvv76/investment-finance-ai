"""Sector rotation tracker — plate-level capital flow via Futu OpenD.

Post-market: fetch 20-30 key US plates, rank by capital flow, cross-validate
with individual stock divergence signals.

Futu APIs: get_plate_list, get_plate_stock, get_capital_flow
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Key US plates to track (Futu plate codes — discovered via get_plate_list)
# ---------------------------------------------------------------------------
_DEFAULT_PLATES = [
    "US.LIST2136",   # 人工智能
    "US.LIST2548",   # AI芯片
    "US.LIST2015",   # 半导体
    "US.LIST2016",   # 半导体设备与材料
    "US.LIST20077",  # 半导体精选
    "US.LIST24212",  # 功率半导体
    "US.LIST2540",   # 云计算服务商
    "US.LIST2520",   # SaaS概念
    "US.LIST21044",  # 云计算ETF
    "US.LIST21033",  # AI ETF
    "US.LIST2653",   # 机器人概念股
    "US.LIST2594",   # 量子计算概念
    "US.LIST2556",   # 太空概念
    "US.LIST2089",   # 航空航天与国防
    "US.LIST20010",  # 加密货币概念股
    "US.LIST2069",   # 生物技术
    "US.LIST23492",  # AI应用软件股
    "US.LIST21032",  # 半导体ETF
    "US.LIST22908",  # AI PC
    "US.LIST24173",  # 太空主题ETF
]


@dataclass
class PlateFlow:
    """Single plate capital flow summary."""
    plate_code: str
    plate_name: str = ""
    super_big_net: float = 0.0      # 特大单 3日累计
    main_net: float = 0.0           # 主力 (super+big) 3日累计
    total_net: float = 0.0          # 全部净流入 3日累计
    change_rate: float = 0.0        # 最近一日涨跌幅
    leading_tickers: List[str] = field(default_factory=list)  # top 5 by flow
    error: str = ""


@dataclass
class SectorSummary:
    """Post-market sector rotation summary."""
    timestamp: float = field(default_factory=time.time)
    top5: List[PlateFlow] = field(default_factory=list)
    bottom5: List[PlateFlow] = field(default_factory=list)
    plates_scanned: int = 0
    errors: int = 0


class SectorRotationCollector:
    """Sector capital flow + rotation signal collector.

    Strategy:
    1. Discover US plates via get_plate_list
    2. Get top stocks per plate via get_plate_stock
    3. Aggregate capital flow for top-5 stocks per plate as sector proxy
    4. Rank all plates by aggregated main_net
    5. Cross-validate with individual stock signals
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 11111,
        plates: Optional[List[str]] = None,
    ):
        self._host = host
        self._port = port
        self._target_plates = plates or _DEFAULT_PLATES

    async def collect_post_market(self) -> Optional[SectorSummary]:
        """Post-market: rank sectors by capital flow."""
        try:
            flows = await asyncio.to_thread(self._fetch_sector_flows)
        except Exception as e:
            logger.error("SectorRotation failed: %s", e)
            return None

        ranked = sorted(flows, key=lambda f: f.main_net, reverse=True)
        top5 = ranked[:5]
        bottom5 = ranked[-5:] if len(ranked) >= 5 else []

        summary = SectorSummary(
            top5=top5,
            bottom5=bottom5,
            plates_scanned=len(flows),
            errors=sum(1 for f in flows if f.error),
        )

        logger.info(
            "SectorRotation: %d plates, top=%s, bottom=%s",
            len(flows),
            top5[0].plate_name if top5 else "-",
            bottom5[-1].plate_name if bottom5 else "-",
        )
        return summary

    def _fetch_sector_flows(self) -> List[PlateFlow]:
        """Synchronous — runs in thread pool."""
        from futu import OpenQuoteContext, RET_OK, Market, Plate

        ctx = OpenQuoteContext(host=self._host, port=self._port)
        flows: List[PlateFlow] = []

        try:
            # Step 1: Get all US plates
            ret, plate_data = ctx.get_plate_list(Market.US, Plate.ALL)
            if ret != RET_OK:
                logger.warning("get_plate_list failed: %s", plate_data)
                # Fall back to default plates
                plate_map = {}
            else:
                plate_map = {
                    str(row["code"]): str(row["plate_name"])
                    for _, row in plate_data.iterrows()
                }

            # Step 2: For each target plate, get top stocks and aggregate flow
            for plate_code in self._target_plates:
                try:
                    flow = self._fetch_single_plate(ctx, plate_code, plate_map)
                    flows.append(flow)
                    time.sleep(0.3)  # rate limit safety (running in thread pool)
                except Exception as e:
                    logger.debug("Plate %s error: %s", plate_code, e)
                    flows.append(PlateFlow(
                        plate_code=plate_code,
                        plate_name=plate_map.get(plate_code, plate_code),
                        error=str(e),
                    ))
        finally:
            ctx.close()

        return flows

    def _fetch_single_plate(
        self, ctx, plate_code: str, plate_map: dict
    ) -> PlateFlow:
        """Fetch flow data for one plate."""
        from futu import RET_OK, PeriodType

        name = plate_map.get(plate_code, plate_code)
        flow = PlateFlow(plate_code=plate_code, plate_name=name)

        # Get plate stocks
        ret, stocks = ctx.get_plate_stock(plate_code)
        if ret != RET_OK or stocks is None or len(stocks) == 0:
            flow.error = "no stocks"
            return flow

        # Take top 10 stocks
        top_codes = [str(s) for s in stocks["code"].head(10).tolist()]

        # Aggregate capital flow for each top stock (最近3日)
        end = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")

        super_sum = big_sum = total_sum = 0.0
        leading: List[tuple] = []

        for code in top_codes:
            try:
                ret_f, flow_data = ctx.get_capital_flow(
                    code,
                    period_type=PeriodType.DAY,
                    start=start,
                    end=end,
                )
                if ret_f != RET_OK or flow_data is None or len(flow_data) == 0:
                    continue

                recent = flow_data.tail(3)
                s = float(recent["super_in_flow"].sum())
                b = float(recent["big_in_flow"].sum())
                t = float(recent["in_flow"].sum())

                super_sum += s
                big_sum += b
                total_sum += t
                leading.append((code, s + b))
            except Exception:
                continue

        flow.super_big_net = super_sum
        flow.main_net = super_sum + big_sum
        flow.total_net = total_sum
        flow.leading_tickers = [
            c for c, _ in sorted(leading, key=lambda x: abs(x[1]), reverse=True)[:5]
        ]

        return flow

    async def close(self):
        pass

    # ------------------------------------------------------------------
    # Push formatting
    # ------------------------------------------------------------------

    @staticmethod
    def format_summary(summary: SectorSummary) -> str:
        """Format sector rotation for TG push."""
        lines = ["🔥 板块资金流排名 (3日累计)\n"]

        lines.append("📈 TOP5 主力净流入:")
        for i, p in enumerate(summary.top5, 1):
            direction = "流入" if p.main_net > 0 else "流出"
            tickers = ", ".join(p.leading_tickers[:3]) if p.leading_tickers else "-"
            lines.append(
                f"  {i}. {p.plate_name}  {direction} {abs(p.main_net)/1e8:.1f}亿  [{tickers}]"
            )

        if summary.bottom5:
            lines.append("\n📉 BOTTOM5 主力净流出:")
            for i, p in enumerate(summary.bottom5, 1):
                direction = "流入" if p.main_net > 0 else "流出"
                tickers = ", ".join(p.leading_tickers[:3]) if p.leading_tickers else "-"
                lines.append(
                    f"  {i}. {p.plate_name}  {direction} {abs(p.main_net)/1e8:.1f}亿  [{tickers}]"
                )

        return "\n".join(lines)
