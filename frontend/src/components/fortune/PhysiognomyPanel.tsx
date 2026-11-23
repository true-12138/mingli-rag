// 相术：面相 / 手相共用一套「特征卡 → 追问」流程。
//
// 这里不做识图：照片只在本机预览，用来对照着选特征，不上传、不分析。
// 古籍问答只据用户自己确认过的特征检索，所以 prompt 里写的是「用户自述」。
import { useEffect, useRef, useState } from "react";

import type { PhysiognomyChart } from "../../api";

type Subject = "face" | "palm";

// 选项只用这批相书里真出现过的说法，选了才有原文可引。
// 例如「鹅蛋脸」「蒜头鼻」「方掌」在现代相术书里常见，但这 10 部古籍一次都没写过，
// 留着只会让检索返回「片段中没有」，所以按语料改写成 面圆 / 鼻大 / 掌方 这类原词。
const FIELDS: Record<Subject, { key: string; options: string[] }[]> = {
  face: [
    { key: "脸型", options: ["面圆", "面方", "面长", "面尖", "面瘦", "面肥"] },
    { key: "眉形", options: ["眉浓", "眉疏", "眉秀", "眉短", "眉低", "眉竖", "剑眉"] },
    { key: "眼形", options: ["眼长", "眼圆", "眼秀", "眼露", "眼深", "眼恶", "三角眼", "凤眼"] },
    { key: "鼻形", options: ["鼻大", "鼻小", "鼻高", "鼻低", "鹰嘴", "鼻如悬胆"] },
    { key: "口形", options: ["口大", "口小", "口阔", "口方", "唇红", "唇厚", "唇薄", "唇青"] },
    { key: "耳", options: ["耳白", "耳大", "耳小", "耳厚", "耳薄", "耳反", "耳垂"] },
  ],
  // 手相按古籍自己的说法来：五形掌、掌形、掌厚薄、指形、掌纹、掌色。
  // 依据：神相铁关刀「五形五局」「相掌秘诀」、柳庄相法「手为一身之苗」「手掌气色总论」、
  // 神相全编「八取手足」，以及 11_相术 补录的《神相全编·卷八》掌纹专卷。
  // 生命线/感情线/智慧线/事业线是现代叫法，这批相书检索不到，
  // 选了只会得到「证据不足」，所以不放进选项。
  palm: [
    { key: "掌型", options: ["木形掌", "土形掌", "金形掌", "火形掌", "水形掌"] },
    { key: "掌形", options: ["掌方", "掌圆", "掌长", "掌短", "掌大", "掌小"] },
    { key: "厚薄", options: ["掌厚", "掌薄", "掌平"] },
    { key: "指形", options: ["指长", "指短", "指圆", "指方", "指尖", "指节露"] },
    { key: "掌纹", options: ["纹深", "纹浅", "纹乱", "直纹多", "横纹多"] },
    // 有专名的掌纹只在《神相全编·卷八》里有断语，卷八已于 2026-11-22 入库。
    // 只收吉纹与中性纹；棺材纹、断头纹这类凶纹不进选项，但用户可以在「补充」里自己写。
    {
      key: "掌纹名",
      // 前四条是现代叫法 + 古籍原名：用户只认生命线/智慧线/感情线/事业线（开源项目
      // timerzz/kanxiang 等也都这么叫），但这批相书里叫地纹/人纹/天纹/玉柱纹。
      // 选项值把两套词都带上：检索时繁简与古今叫法都能命中原文。
      // 三才纹定义在 9632（相三才）、诗句在 9616；川字纹在 9616；玉柱纹在 9615。
      // 异体 / 繁体名也写进选项值：原文是「鴈陣紋」，字二元组 BM25 里「雁阵」与
      // 「鴈陣」一个字都不重合——实测「雁阵纹」排 656 名，带上「鴈陣紋」后第 1 名
      // （957 块相术组，2026-11-22）。其余带括号的名字同理，避免界面上看得懂、检索却落空。
      options: [
        "生命线（地纹）", "智慧线（人纹）", "感情线（天纹）", "事业线（玉柱纹）",
        "金井纹", "玉阶纹（玉階紋）", "玉柱纹", "川字纹", "三才纹", "双鱼纹（雙魚紋）",
        "雁阵纹（鴈陣紋）", "十字纹", "印纹", "学堂纹（學堂紋）", "车轮纹（車輪紋）",
        "华盖纹（華蓋紋）",
      ],
    },
    // 掌色用肉眼能说的词：红润 / 白 / 黄 / 紫 / 青 / 黑。
    // 古籍原文是「掌中生黄」「掌中紫色」「掌白不润」「暗黑」，断语带吉凶，
    // 放进选项会吓人；检索问句会带上「掌色」，落到同一批段落。
    { key: "掌色", options: ["红润", "白", "黄", "紫", "青", "黑"] },
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

const NOTE_HINT: Record<Subject, string> = {
  face: "例如：右眉尾有疤、左颊有痣",
  palm: "例如：无名指下有一道直纹、掌背有痣",
};

interface Props {
  subject: Subject;
  onChart: (chart: PhysiognomyChart) => void;
  onClear: () => void;
}

export function PhysiognomyPanel({ subject, onChart, onClear }: Props) {
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
  // 全清空（或换面相/手相）时把旧卡摘掉，否则下一问还带着上一张的脸。
  useEffect(() => {
    if (count === 0) {
      onClear();
      return;
    }
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
          placeholder={NOTE_HINT[subject]}
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
