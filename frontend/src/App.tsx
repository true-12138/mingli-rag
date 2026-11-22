import { useCallback, useEffect, useState } from "react";

import { Sidebar, type View } from "./components/Sidebar";
import { AboutPage } from "./pages/AboutPage";
import { AstroPage } from "./pages/AstroPage";
import { ChartPage } from "./pages/ChartPage";
import { MaterialsPage } from "./pages/MaterialsPage";
import { MemoryPage } from "./pages/MemoryPage";
import { PhysiognomyPage } from "./pages/PhysiognomyPage";
import type { Mode } from "./api";
import { useChat } from "./useChat";

// 轻量 hash 路由：#/chart、#/astro、#/physiognomy、#/memory、#/materials、#/about。
// 问答已并入三个术数页面，旧的 #/chat、#/fortune 落到命盘页，旧链接不作废。
function readView(): View {
  const hash = window.location.hash.replace(/^#\/?/, "");
  if (hash === "astro") return "astro";
  if (hash === "physiognomy") return "physiognomy";
  if (hash === "memory") return "memory";
  if (hash === "materials") return "materials";
  if (hash === "about") return "about";
  return "chart";
}

export default function App() {
  // useChat 放在 App：切页签时正在生成的回答不会丢，盘面也只挂一份
  const chat = useChat();
  // 默认用固定 RAG：实测 2.9–3.3s/题，查证后回答（agent）196.8s/题。
  // 公网工具态先保证「问一句等几秒」；需要多步查证时用户可手动切到「查证后回答」。
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

  const openDrawer = () => setDrawer((open) => !open);

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
        {view === "chart" && (
          <ChartPage
            chat={chat}
            mode={mode}
            onModeChange={setMode}
            onOpenDrawer={openDrawer}
          />
        )}
        {view === "astro" && (
          <AstroPage
            chat={chat}
            mode={mode}
            onModeChange={setMode}
            onOpenDrawer={openDrawer}
          />
        )}
        {view === "physiognomy" && (
          <PhysiognomyPage
            chat={chat}
            mode={mode}
            onModeChange={setMode}
            onOpenDrawer={openDrawer}
          />
        )}
        {view === "memory" && <MemoryPage onOpenDrawer={openDrawer} />}
        {view === "materials" && <MaterialsPage onOpenDrawer={openDrawer} />}
        {view === "about" && <AboutPage onOpenDrawer={openDrawer} />}
      </main>
    </div>
  );
}
