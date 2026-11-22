// 星盘页：出生信息 → 本命盘，右侧常驻问答栏。
import { ChatColumn } from "../components/ChatColumn";
import { AstroPanel } from "../components/fortune/AstroPanel";
import { MenuIcon } from "../components/icons";
import type { Mode } from "../api";
import type { useChat } from "../useChat";

interface Props {
  chat: ReturnType<typeof useChat>;
  mode: Mode;
  onModeChange: (mode: Mode) => void;
  onOpenDrawer: () => void;
}

export function AstroPage({ chat, mode, onModeChange, onOpenDrawer }: Props) {
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
            <h1 className="page__title">星盘</h1>
          </div>
        </div>
      </header>

      <div className="workspace">
        <div className="workspace__panel">
          <div className="page__inner">
            <AstroPanel onChart={chat.attachChart} />
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
