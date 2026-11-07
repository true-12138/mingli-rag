import { useCallback, useEffect, useState } from "react";

import { Sidebar, type View } from "./components/Sidebar";
import { ChatPage } from "./pages/ChatPage";
import { FortunePage } from "./pages/FortunePage";
import { MemoryPage } from "./pages/MemoryPage";
import type { Mode } from "./api";
import { useChat } from "./useChat";

// 轻量 hash 路由：#/chat、#/fortune、#/memory。
// 不用 react-router——三个页面还不值得引一个路由库。
function readView(): View {
  const hash = window.location.hash.replace(/^#\/?/, "");
  if (hash === "fortune") return "fortune";
  if (hash === "memory") return "memory";
  return "chat";
}

export default function App() {
  // useChat 放在 App：切到排盘页再回来，正在生成的回答不会丢
  const chat = useChat();
  const [mode, setMode] = useState<Mode>("rag");
  const [view, setView] = useState<View>(readView);
  const [drawer, setDrawer] = useState(false);

  useEffect(() => {
    const onHash = () => {
      setView(readView());
      setDrawer(false);
    };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  const go = useCallback((next: View) => {
    window.location.hash = `/${next}`;
    setView(next);
    setDrawer(false);
  }, []);

  return (
    <div className={`app${drawer ? " app--drawer" : ""}`}>
      <Sidebar
        conversations={chat.conversations}
        activeId={chat.activeId}
        loading={chat.loadingList}
        streaming={chat.streaming}
        view={view}
        onView={go}
        onSelect={(id) => {
          chat.select(id);
          setDrawer(false);
        }}
        onNew={() => {
          chat.startNew();
          setDrawer(false);
        }}
        onRemove={chat.remove}
      />

      <div className="scrim" onClick={() => setDrawer(false)} aria-hidden="true" />

      <main className="main">
        {view === "chat" && (
          <ChatPage
            chat={chat}
            mode={mode}
            onModeChange={setMode}
            onOpenDrawer={() => setDrawer((open) => !open)}
          />
        )}
        {view === "fortune" && (
          <FortunePage onOpenDrawer={() => setDrawer((open) => !open)} />
        )}
        {view === "memory" && (
          <MemoryPage onOpenDrawer={() => setDrawer((open) => !open)} />
        )}
      </main>
    </div>
  );
}
