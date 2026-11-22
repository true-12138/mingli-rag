// 命盘页：八字与塔罗两个页签，右侧常驻问答栏。
// 盘一生成就挂到对话上，追问不必换页面。
import { useState } from "react";

import { ChatColumn } from "../components/ChatColumn";
import { BaziPanel } from "../components/fortune/BaziPanel";
import { TarotPanel } from "../components/fortune/TarotPanel";
import { MenuIcon } from "../components/icons";
import type { Mode } from "../api";
import type { useChat } from "../useChat";

const TABS = [
  { key: "bazi", label: "八字", hint: "四柱 · 大运" },
  { key: "tarot", label: "塔罗", hint: "可复现生成牌面" },
] as const;

type TabKey = (typeof TABS)[number]["key"];

interface Props {
  chat: ReturnType<typeof useChat>;
  mode: Mode;
  onModeChange: (mode: Mode) => void;
  onOpenDrawer: () => void;
}

export function ChartPage({ chat, mode, onModeChange, onOpenDrawer }: Props) {
  const [tab, setTab] = useState<TabKey>("bazi");

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
                onClick={() => setTab(item.key)}
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
            {tab === "bazi" ? (
              <BaziPanel onChart={chat.attachChart} />
            ) : (
              <TarotPanel onChart={chat.attachChart} />
            )}
          </div>
        </div>
        <ChatColumn
          chat={chat}
          mode={mode}
          onModeChange={onModeChange}
          onNew={chat.startNew}
        />
      </div>
    </div>
  );
}
