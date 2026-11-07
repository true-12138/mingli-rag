// 输入区：模式选择 + 文本域 + 发送/停止。
// Enter 发送，Shift+Enter 换行；中文输入法选词时的 Enter 不能当发送。
import { useEffect, useRef, useState } from "react";

import type { Mode } from "../api";

const MODES: { value: Mode; label: string; placeholder: string }[] = [
  { value: "rag", label: "原文直答", placeholder: "问一个概念，或贴一句断语，比如「天乙贵人怎么查」" },
  { value: "agent", label: "查证后回答", placeholder: "让 Agent 自己翻书，比如「七杀有制和无制差在哪」" },
  { value: "multi", label: "多书对照", placeholder: "想比较哪几部书，比如「三命通会和滴天髓怎么论格局」" },
];

interface Props {
  mode: Mode;
  onModeChange: (mode: Mode) => void;
  streaming: boolean;
  onSend: (question: string) => void;
  onStop: () => void;
}

export function Composer({ mode, onModeChange, streaming, onSend, onStop }: Props) {
  const [text, setText] = useState("");
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const placeholder = MODES.find((m) => m.value === mode)?.placeholder ?? "";

  useEffect(() => {
    const el = inputRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 168)}px`;
  }, [text]);

  const submit = () => {
    const question = text.trim();
    if (!question || streaming) return;
    setText("");
    onSend(question);
    inputRef.current?.focus();
  };

  return (
    <div className="composer">
      <div className="composer__inner">
        <div className="modes" role="tablist" aria-label="回答方式">
          {MODES.map((item) => (
            <button
              key={item.value}
              type="button"
              role="tab"
              aria-selected={mode === item.value}
              className={`modes__item${mode === item.value ? " modes__item--on" : ""}`}
              onClick={() => onModeChange(item.value)}
              disabled={streaming}
            >
              {item.label}
            </button>
          ))}
        </div>

        <div className="composer__box">
          <textarea
            ref={inputRef}
            rows={1}
            value={text}
            placeholder={placeholder}
            onChange={(event) => setText(event.target.value)}
            onKeyDown={(event) => {
              if (event.key !== "Enter" || event.shiftKey) return;
              if (event.nativeEvent.isComposing || event.keyCode === 229) return;
              event.preventDefault();
              submit();
            }}
            aria-label="输入问题"
          />
          {streaming ? (
            <button type="button" className="send send--stop" onClick={onStop}>
              <span className="send__square" aria-hidden="true" />
              停止
            </button>
          ) : (
            <button
              type="button"
              className="send"
              onClick={submit}
              disabled={text.trim().length === 0}
              aria-label="发送"
            >
              发送
              <span className="send__arrow" aria-hidden="true">
                ↑
              </span>
            </button>
          )}
        </div>

        <p className="composer__hint">Enter 发送 · Shift + Enter 换行 · 回答仅供参考，请以原文为准</p>
      </div>
    </div>
  );
}
