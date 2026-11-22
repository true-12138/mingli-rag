// 相术：面相 / 手相共用一套「特征卡 → 追问」流程。
//
// 这里不做识图：照片只在本机预览，用来对照着选特征，不上传、不分析。
// 古籍问答只据用户自己确认过的特征检索，所以 prompt 里写的是「用户自述」。
import { useEffect, useRef, useState } from "react";

import type { PhysiognomyChart } from "../../api";

type Subject = "face" | "palm";

const FIELDS: Record<Subject, { key: string; options: string[] }[]> = {
  face: [
    { key: "脸型", options: ["鹅蛋脸", "圆脸", "方脸", "长脸", "瓜子脸", "菱形脸"] },
    { key: "眉形", options: ["浓眉", "淡眉", "柳叶眉", "剑眉", "八字眉", "一字眉"] },
    { key: "眼形", options: ["杏眼", "凤眼", "桃花眼", "细长眼", "圆眼", "三角眼"] },
    { key: "鼻形", options: ["悬胆鼻", "蒜头鼻", "鹰钩鼻", "挺直鼻", "扁鼻"] },
    { key: "口形", options: ["阔口", "小口", "厚唇", "薄唇", "嘴角上扬"] },
    { key: "耳", options: ["贴脑耳", "招风耳", "垂珠厚", "耳薄"] },
  ],
  palm: [
    { key: "掌型", options: ["木型掌", "水型掌", "火型掌", "土型掌", "金型掌"] },
    { key: "生命线", options: ["深长", "浅短", "断续", "分叉"] },
    { key: "感情线", options: ["平直", "上扬", "下垂", "断续"] },
    { key: "智慧线", options: ["平直", "下垂", "上翘", "断续"] },
    { key: "事业线", options: ["清晰", "断续", "无"] },
    { key: "掌色", options: ["红润", "偏白", "偏黄", "偏青"] },
  ],
};

const SUBJECT_NAME: Record<Subject, "面相" | "手相"> = {
  face: "面相",
  palm: "手相",
};

const PHOTO_HINT: Record<Subject, string> = {
  face: "正面、平视、光线均匀；照片只在本机预览，不上传。",
  palm: "手掌摊平、自然光下拍清掌纹；照片只在本机预览，不上传。",
};

interface Props {
  subject: Subject;
  onChart: (chart: PhysiognomyChart) => void;
}

export function PhysiognomyPanel({ subject, onChart }: Props) {
  const fields = FIELDS[subject];
  const [picked, setPicked] = useState<Record<string, string>>({});
  const [note, setNote] = useState("");
  const [photo, setPhoto] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  // 换面相/手相时清空旧特征，免得把「柳叶眉」挂到手相上
  useEffect(() => {
    setPicked({});
    setNote("");
  }, [subject]);

  useEffect(
    () => () => {
      if (photo) URL.revokeObjectURL(photo);
    },
    [photo],
  );

  const chosen = Object.entries(picked).filter(([, value]) => value);
  const count = chosen.length;

  // 选一项就挂一项：问答栏的盘面标签会实时跟着变，用户知道现在问的是哪张卡。
  useEffect(() => {
    if (count === 0) return;
    onChart({
      kind: "physiognomy",
      subject: SUBJECT_NAME[subject],
      features: Object.fromEntries(chosen),
      note: note.trim() || undefined,
    });
    // chosen/note 每次渲染都是新对象，这里只按内容变化触发
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(chosen), note, subject]);

  const pickPhoto = (file: File | null) => {
    if (photo) URL.revokeObjectURL(photo);
    setPhoto(file ? URL.createObjectURL(file) : null);
  };

  return (
    <>
      <div className="ph-photo">
        {photo ? (
          <img className="ph-photo__img" src={photo} alt={`${SUBJECT_NAME[subject]}参考照片`} />
        ) : (
          <div className="ph-photo__empty" aria-hidden="true">
            对照照片选特征
          </div>
        )}
        <div className="ph-photo__side">
          <input
            ref={fileRef}
            className="ph-photo__input"
            type="file"
            accept="image/*"
            onChange={(event) => pickPhoto(event.target.files?.[0] ?? null)}
          />
          <button
            type="button"
            className="btn"
            onClick={() => fileRef.current?.click()}
          >
            {photo ? "换一张" : "选一张照片"}
          </button>
          {photo && (
            <button
              type="button"
              className="ph-photo__remove"
              onClick={() => {
                pickPhoto(null);
                if (fileRef.current) fileRef.current.value = "";
              }}
            >
              移除照片
            </button>
          )}
        </div>
      </div>
      <p className="f-hint">{PHOTO_HINT[subject]}</p>

      <div className="ph-form">
        {fields.map((field) => (
          <label className="f-field" key={field.key}>
            <span className="f-label">{field.key}</span>
            <select
              className="f-input"
              value={picked[field.key] ?? ""}
              onChange={(event) =>
                setPicked((prev) => ({ ...prev, [field.key]: event.target.value }))
              }
            >
              <option value="">不确定</option>
              {field.options.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </label>
        ))}
      </div>

      <label className="f-field f-field--note">
        <span className="f-label">补充</span>
        <input
          className="f-input"
          type="text"
          maxLength={80}
          value={note}
          placeholder="例如：左脚踝有痣、右眉尾高"
          onChange={(event) => setNote(event.target.value)}
        />
      </label>

      <p className="ph-status" role="status">
        {count === 0
          ? "先选两三处特征，右边就能按古籍查。"
          : count < 3
            ? `已选 ${count} 项。再多选两项，检索到的段落会更贴。`
            : `已选 ${count} 项，已在右侧问答栏。`}
      </p>
    </>
  );
}
