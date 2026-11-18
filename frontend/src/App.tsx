import { useCallback, useEffect, useState } from "react";

import { Sidebar, type View } from "./components/Sidebar";
import { ChatPage } from "./pages/ChatPage";
import { FortunePage } from "./pages/FortunePage";
import { MaterialsPage } from "./pages/MaterialsPage";
import { MemoryPage } from "./pages/MemoryPage";
import type { FortuneChart, Mode } from "./api";
import { useChat } from "./useChat";

// 轻量 hash 路由：#/chat、#/fortune、#/memory、#/materials。
// 不用 react-router——四个页面还不值得引一个路由库。
function readView(): View {
  const hash = window.location.hash.replace(/^#\/?/, "");
  if (hash === "fortune") return "fortune";
  if (hash === "memory") return "memory";
  if (hash === "materials") return "materials";
  return "chat";
}

export default function App() {
  // useChat 放在 App：切到排盘页再回来，正在生成的回答不会丢
  const chat = useChat();
  // 默认用「查证后回答」而不是固定 RAG：三种模式里它最稳，
  // 固定 RAG 是单次检索、最容易给出「主题相近但答不上」的答案。
  const [mode, setMode] = useState<Mode>("agent");
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

  // 排盘页点「就这个盘继续问」：把盘挂到对话上，再切到对话页。
  // 盘面只是前端状态，后端不落库——刷新后需要重新带一次。
  const { attachChart } = chat;
  const askWithChart = useCallback(
    (chart: FortuneChart) => {
      attachChart(chart);
      go("chat");
    },
    [attachChart, go],
  );

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
          <FortunePage onOpenDrawer={() => setDrawer((open) => !open)} onAsk={askWithChart} />
        )}
        {view === "memory" && (
          <MemoryPage onOpenDrawer={() => setDrawer((open) => !open)} />
        )}
        {view === "materials" && (
          <MaterialsPage onOpenDrawer={() => setDrawer((open) => !open)} />
        )}
      </main>
    </div>
  );
}
