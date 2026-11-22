// 相术页：面相和手相共用一页，同一套「对照照片选特征 → 追问」流程。
import { useState } from "react";

import { ChatColumn } from "../components/ChatColumn";
import { PhysiognomyPanel } from "../components/fortune/PhysiognomyPanel";
import { MenuIcon } from "../components/icons";
import type { Mode } from "../api";
import type { useChat } from "../useChat";

const TABS = [
  { key: "face", label: "面相" },
  { key: "palm", label: "手相" },
] as const;

type TabKey = (typeof TABS)[number]["key"];

interface Props {
  chat: ReturnType<typeof useChat>;
  mode: Mode;
  onModeChange: (mode: Mode) => void;
  onOpenDrawer: () => void;
}

export function PhysiognomyPage({ chat, mode, onModeChange, onOpenDrawer }: Props) {
  const [tab, setTab] = useState<TabKey>("face");

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
            <h1 className="page__title">相术</h1>
          </div>
          <nav className="tabs" aria-label="相术类型">
            {TABS.map((item) => (
              <button
                key={item.key}
                type="button"
                className={`tabs__item${tab === item.key ? " tabs__item--on" : ""}`}
                onClick={() => setTab(item.key)}
                aria-current={tab === item.key ? "page" : undefined}
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
            <PhysiognomyPanel subject={tab} onChart={chat.attachChart} />
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
