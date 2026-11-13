// 追问表单：后端说缺哪些字段，这里就渲染哪些字段。
// 不维护自己的字段清单——排盘需要什么由 /v1/fortune/intake 决定。
import { useEffect, useState } from "react";

import type { IntakeField } from "../../api";

export function Questionnaire({
  message,
  fields,
  busy,
  onSubmit,
}: {
  message: string;
  fields: IntakeField[];
  busy: boolean;
  onSubmit: (values: Record<string, unknown>) => void;
}) {
  const [values, setValues] = useState<Record<string, string>>({});

  // 换了一组字段（比如上次填错又被问一遍）时，保留仍然存在的输入。
  const signature = fields.map((field) => field.name).join(",");
  useEffect(() => {
    setValues((prev) => {
      const next: Record<string, string> = {};
      for (const field of fields) {
        const seeded = prev[field.name] ?? field.value;
        if (seeded !== undefined && seeded !== null) next[field.name] = String(seeded);
      }
      return next;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [signature]);

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    if (busy) return;
    const payload: Record<string, unknown> = {};
    for (const field of fields) {
      const raw = values[field.name];
      if (raw === undefined || raw.trim() === "") continue;
      payload[field.name] =
        field.type === "int" || field.type === "float" ? Number(raw) : raw.trim();
    }
    onSubmit(payload);
  };

  return (
    <form className="f-ask" onSubmit={submit}>
      <p className="f-ask__message">{message}</p>
      <div className="f-ask__fields">
        {fields.map((field) => {
          const id = `ask-${field.name}`;
          return (
            <label className={`f-field${field.error ? " f-field--bad" : ""}`} key={field.name} htmlFor={id}>
              <span className="f-label">{field.label}</span>
              {field.type === "enum" && field.options ? (
                <select
                  className="f-input"
                  id={id}
                  value={values[field.name] ?? ""}
                  onChange={(event) =>
                    setValues((prev) => ({ ...prev, [field.name]: event.target.value }))
                  }
                >
                  <option value="">请选择</option>
                  {field.options.map((option) => (
                    <option key={option} value={option}>
                      {field.option_labels?.[option] ?? option}
                    </option>
                  ))}
                </select>
              ) : (
                <input
                  className="f-input f-input--ask"
                  id={id}
                  type={field.type === "int" || field.type === "float" ? "number" : "text"}
                  inputMode={field.type === "int" || field.type === "float" ? "numeric" : undefined}
                  min={field.min}
                  max={field.max}
                  maxLength={field.max_length}
                  step={field.type === "float" ? "any" : undefined}
                  placeholder={field.example !== undefined ? String(field.example) : ""}
                  value={values[field.name] ?? ""}
                  onChange={(event) =>
                    setValues((prev) => ({ ...prev, [field.name]: event.target.value }))
                  }
                />
              )}
              {field.error && <span className="f-ask__error">{field.error}</span>}
            </label>
          );
        })}
      </div>
      <div className="f-ask__foot">
        <button className="btn btn--solid" type="submit" disabled={busy}>
          {busy ? "计算中…" : "继续"}
        </button>
        <span className="f-ask__hint">只问缺的几项，已有的不会重复问。</span>
      </div>
    </form>
  );
}
