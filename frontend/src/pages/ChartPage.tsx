// 排盘页：八字 / 星盘 / 姓名 / 塔罗四个页签共用右侧常驻问答栏。
// 排盘和追问在同一屏完成，盘一生成就挂到对话上。
import { useEffect, useState } from "react";

import { ChatColumn } from "../components/ChatColumn";
import { SUGGESTIONS } from "../components/EmptyState";
import { AstroPanel } from "../components/fortune/AstroPanel";
import { BaziPanel } from "../components/fortune/BaziPanel";
import { NamePanel } from "../components/fortune/NamePanel";
import { TarotPanel } from "../components/fortune/TarotPanel";
import { MenuIcon } from "../components/icons";
import type { Mode } from "../api";
import type { useChat } from "../useChat";

const TABS = [
  { key: "bazi", label: "八字", hint: "四柱 · 大运" },
  { key: "astro", label: "星盘", hint: "本命盘 · 宫位" },
  { key: "name", label: "姓名", hint: "康熙笔画 · 五格三才" },
  { key: "tarot", label: "塔罗", hint: "可复现生成牌面" },
] as const;

type TabKey = (typeof TABS)[number]["key"];

// 旧的 #/astro、#/name 链接直接落到对应页签，老书签不作废。
function readTab(): TabKey {
  const hash = window.location.hash.replace(/^#\/?/, "");
  if (hash === "astro" || hash === "name") return hash;
  return "bazi";
}

interface Props {
  chat: ReturnType<typeof useChat>;
  mode: Mode;
  onModeChange: (mode: Mode) => void;
  onOpenDrawer: () => void;
}

export function ChartPage({ chat, mode, onModeChange, onOpenDrawer }: Props) {
  const [tab, setTab] = useState<TabKey>(readTab);

  // 侧栏点「命盘」时 hash 会变回 /chart，页签跟着回到八字
  useEffect(() => {
    const onHash = () => setTab(readTab());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  // 换页签就摘掉上一张盘：八字的日主不能被带到星盘检索里去
  const clearChart = chat.clearChart;
  useEffect(() => {
    clearChart();
  }, [tab, clearChart]);

  const pickTab = (key: TabKey) => {
    setTab(key);
    const next = key === "astro" ? "/astro" : key === "name" ? "/name" : "/chart";
    if (window.location.hash !== `#${next}`) window.location.hash = next;
  };

  const suggestions =
    tab === "astro" ? SUGGESTIONS.astro : tab === "bazi" ? SUGGESTIONS.bazi : undefined;

  return (
    <div className="page page--split">
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
            <h1 className="page__title">命盘</h1>
          </div>
          <nav className="tabs" aria-label="命盘类型">
            {TABS.map((item) => (
              <button
                key={item.key}
                type="button"
                className={`tabs__item${tab === item.key ? " tabs__item--on" : ""}`}
                onClick={() => pickTab(item.key)}
                aria-current={tab === item.key ? "page" : undefined}
                title={item.hint}
              >
                <span className="tabs__label">{item.label}</span>
              </button>
            ))}
          </nav>
        </div>
      </header>

      <div className="workspace">
        <div className="workspace__panel">
          <div className="page__inner">
            {tab === "bazi" && <BaziPanel onChart={chat.attachChart} />}
            {tab === "astro" && <AstroPanel onChart={chat.attachChart} />}
            {tab === "name" && <NamePanel onChart={chat.attachChart} />}
            {tab === "tarot" && <TarotPanel onChart={chat.attachChart} />}
          </div>
        </div>
        <ChatColumn
          chat={chat}
          mode={mode}
          onModeChange={onModeChange}
          onNew={chat.startNew}
          suggestions={suggestions}
        />
      </div>
    </div>
  );
}
