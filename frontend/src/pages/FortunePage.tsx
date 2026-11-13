// 排盘页：八字 / 星盘 / 塔罗三个页签。
// 页签状态不放进 URL 的 query，但整个页面定位在 #/fortune，刷新还能回到这里。
import { useState } from "react";

import { AstroPanel } from "../components/fortune/AstroPanel";
import { BaziPanel } from "../components/fortune/BaziPanel";
import { TarotPanel } from "../components/fortune/TarotPanel";
import { MenuIcon } from "../components/icons";
import type { FortuneKind } from "../api";

const TABS: { key: FortuneKind; label: string; hint: string }[] = [
  { key: "bazi", label: "八字", hint: "四柱 · 大运" },
  { key: "astro", label: "星盘", hint: "本命 · 整宫制" },
  { key: "tarot", label: "塔罗", hint: "可复现生成牌面" },
];

export function FortunePage({ onOpenDrawer }: { onOpenDrawer: () => void }) {
  const [tab, setTab] = useState<FortuneKind>("bazi");

  return (
    <div className="page">
      <header className="page__head">
        <div className="page__head-inner">
          <div className="page__head-text">
            <button
              className="icon-btn page__drawer"
              onClick={onOpenDrawer}
              aria-label="导航"
            >
              <MenuIcon />
            </button>
            <p className="page__kicker">排盘</p>
            <h1 className="page__title">先算出盘，再谈解读</h1>
            <p className="page__lead">
              干支、行星、牌面都是确定性计算，同样的输入永远同一个结果。
              解读只解释已经算出来的盘面，不改盘。
            </p>
          </div>
          <nav className="tabs" aria-label="排盘类型">
            {TABS.map((item) => (
              <button
                key={item.key}
                type="button"
                className={`tabs__item${tab === item.key ? " tabs__item--on" : ""}`}
                onClick={() => setTab(item.key)}
                aria-current={tab === item.key ? "page" : undefined}
              >
                <span className="tabs__label">{item.label}</span>
                <span className="tabs__hint">{item.hint}</span>
              </button>
            ))}
          </nav>
        </div>
      </header>

      <div className="page__scroll">
        <div className="page__inner">
          {tab === "bazi" && <BaziPanel />}
          {tab === "astro" && <AstroPanel />}
          {tab === "tarot" && <TarotPanel />}
        </div>
      </div>
    </div>
  );
}
