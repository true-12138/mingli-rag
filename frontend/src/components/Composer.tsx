// 输入区：模式选择 + 文本域 + 发送/停止。
// Enter 发送，Shift+Enter 换行；中文输入法选词时的 Enter 不能当发送。
import { useEffect, useRef, useState } from "react";

import type { Mode } from "../api";

// 模式名够短就直接显示；解释放 title，鼠标悬停和读屏都能拿到。
const MODES: { value: Mode; label: string; hint: string }[] = [
  { value: "rag", label: "原文直答", hint: "单轮检索，最快" },
  { value: "agent", label: "查证后回答", hint: "多步翻书取证，更慢也更全" },
  { value: "multi", label: "多书对照", hint: "比较多部古籍的说法" },
];

const PLACEHOLDER = "输入问题，或贴一段原文";

interface Props {
  mode: Mode;
  onModeChange: (mode: Mode) => void;
  streaming: boolean;
  // 挂上盘面后由外面按盘型给占位文字，输入框自己也提示「这一问跟着盘走」
  placeholder?: string;
  onSend: (question: string) => void;
  onStop: () => void;
}

export function Composer({
  mode,
  onModeChange,
  streaming,
  placeholder,
  onSend,
  onStop,
}: Props) {
  const [text, setText] = useState("");
  const inputRef = useRef<HTMLTextAreaElement>(null);

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
              title={item.hint}
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
            placeholder={placeholder ?? PLACEHOLDER}
            onChange={(event) => setText(event.target.value)}
            onKeyDown={(event) => {
              if (event.key !== "Enter" || event.shiftKey) return;
              if (event.nativeEvent.isComposing || event.keyCode === 229) return;
              event.preventDefault();
              submit();
            }}
            aria-label="输入问题"
            title="Enter 发送，Shift + Enter 换行"
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
      </div>
    </div>
  );
}
