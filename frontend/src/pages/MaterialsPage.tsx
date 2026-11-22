// 素材页：收藏的原文 + 自己的笔记，一键导出 Markdown。
// 这里展示的是语料原文（和引用同一份），不经过模型改写；笔记只存在本机匿名身份下。
import { useCallback, useEffect, useRef, useState } from "react";

import {
  ApiError,
  deleteFavorite,
  exportFavorites,
  listFavorites,
  saveFavorite,
  type Favorite,
} from "../api";
import { MenuIcon } from "../components/icons";
import { formatWhen } from "../format";

export function MaterialsPage({ onOpenDrawer }: { onOpenDrawer: () => void }) {
  const [items, setItems] = useState<Favorite[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);
  const [confirmId, setConfirmId] = useState<number | null>(null);
  const timer = useRef<number | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setItems(await listFavorites());
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "素材加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
    return () => {
      if (timer.current != null) window.clearTimeout(timer.current);
    };
  }, [load]);

  const remove = async (id: number) => {
    if (confirmId !== id) {
      setConfirmId(id);
      if (timer.current != null) window.clearTimeout(timer.current);
      timer.current = window.setTimeout(() => setConfirmId(null), 2600);
      return;
    }
    setConfirmId(null);
    try {
      await deleteFavorite(id);
      setItems((prev) => prev.filter((item) => item.id !== id));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "删除失败，请再试一次");
    }
  };

  const saveNote = async (item: Favorite, note: string) => {
    try {
      const next = await saveFavorite(item.chunk_id, note);
      setItems((prev) => prev.map((old) => (old.id === next.id ? next : old)));
      setError(null);
      return true;
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "笔记保存失败，请再试一次");
      return false;
    }
  };

  const download = async () => {
    setExporting(true);
    try {
      const { blob, filename } = await exportFavorites();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "导出失败，请再试一次");
    } finally {
      setExporting(false);
    }
  };

  return (
    <div className="page">
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
            <h1 className="page__title">素材</h1>
          </div>
          {items.length > 0 && (
            <div className="page__aside">
              <span className="page__count">{items.length}</span>
              <span className="page__count-label">条素材</span>
            </div>
          )}
        </div>
      </header>

      <div className="page__scroll">
        <div className="page__inner">
          {error && (
            <p className="note note--error" role="alert">
              {error}
            </p>
          )}

          {items.length > 0 && (
            <div className="mat-toolbar">
              <button
                type="button"
                className="mat-export"
                disabled={exporting}
                onClick={() => void download()}
              >
                {exporting ? "正在导出…" : `导出 Markdown（${items.length} 条）`}
              </button>
            </div>
          )}

          {loading && items.length === 0 && <p className="mem-tip">正在读取…</p>}

          {!loading && items.length === 0 && (
            <p className="page-empty">
              还没有素材。展开引用点「收藏」；素材按浏览器保存。
            </p>
          )}

          {items.length > 0 && (
            <ul className="mat-list">
              {items.map((item) => (
                <MaterialCard
                  key={item.id}
                  item={item}
                  confirming={confirmId === item.id}
                  onRemove={() => void remove(item.id)}
                  onSaveNote={(note) => saveNote(item, note)}
                />
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}

function MaterialCard({
  item,
  confirming,
  onRemove,
  onSaveNote,
}: {
  item: Favorite;
  confirming: boolean;
  onRemove: () => void;
  onSaveNote: (note: string) => Promise<boolean>;
}) {
  const [draft, setDraft] = useState(item.note ?? "");
  const [saving, setSaving] = useState(false);
  const dirty = draft !== (item.note ?? "");

  useEffect(() => {
    setDraft(item.note ?? "");
  }, [item.id, item.note]);

  const meta = [item.volume, item.chapter].filter(Boolean).join(" · ");
  const location = item.line_start != null
    ? `第 ${item.line_start}–${item.line_end ?? item.line_start} 行`
    : "";

  async function save() {
    setSaving(true);
    try {
      await onSaveNote(draft);
    } finally {
      setSaving(false);
    }
  }

  return (
    <li className="mat">
      <div className="mat__head">
        <span className="mat__title">{item.title}</span>
        {meta && <span className="mat__meta">{meta}</span>}
        <span className="mat__when">{formatWhen(item.created_at)}</span>
      </div>
      <p className="mat__text">{item.text}</p>
      <p className="mat__loc">
        {item.sourcefile}
        {location ? `，${location}` : ""}
      </p>
      <div className="mat__note-row">
        <textarea
          className="mat__note"
          value={draft}
          maxLength={2000}
          rows={2}
          placeholder="批注"
          onChange={(event) => setDraft(event.target.value)}
        />
        <button
          type="button"
          className="mat__save"
          disabled={!dirty || saving}
          onClick={() => void save()}
        >
          {saving ? "保存中…" : "存笔记"}
        </button>
      </div>
      <button
        type="button"
        className={`mat__del${confirming ? " mat__del--armed" : ""}`}
        onClick={onRemove}
      >
        {confirming ? "确认删除" : "删除"}
      </button>
    </li>
  );
}
