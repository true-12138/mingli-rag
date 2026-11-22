// 关于页：给第一次打开这个站的人（尤其是面试官）一页说清楚三件事——
// 这是什么、凭什么说它做好了、哪一次改动让我发现自己错了。
import { MenuIcon } from "../components/icons";

const GITHUB = "https://github.com/true-12138/mingli-rag";
const MAIL = "3436647858@qq.com";

export function AboutPage({ onOpenDrawer }: { onOpenDrawer: () => void }) {
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
            <h1 className="page__title">关于</h1>
            <p className="page__lead">
              通用模型遇到语料里没有的问题，会用现代常识补出一段读着像古籍、实际并不存在的原文，
              而使用者很难分辨。这个站把回答限制在 <strong>45 部古籍、约 340 万字</strong>上：
              每条结论都能展开到书名 / 卷 / 章 / 行，找不到依据就明确说「证据不足」，而不是硬答。
            </p>
          </div>
          <div className="page__aside">
            <span className="page__count">8,681</span>
            <span className="page__count-label">节语料</span>
          </div>
        </div>
      </header>

      <div className="page__scroll">
        <div className="page__inner">
          <section className="about-sec">
            <h2 className="about-sec__title">怎么做的</h2>
            <ol className="about-list">
              <li>
                <b>语料与切分</b>
                152 部清洗文本里筛出 45 部，切成 8,681 节 / 约 340 万字。按目标 450 字、
                上限 700、句级重叠 60 切分，无标点刻本按行款合并，每节带书名 / 卷 / 章 / 行号。
              </li>
              <li>
                <b>两路召回</b>
                BGE-M3（1024 维）稠密检索 + BM25 字二元组倒排，RRF 融合。
                语料从 2,830 扩到 8,681 后融合掉点，用 280 组配置重扫定位到参数问题，
                改为 rrf_k=10 / candidate_k=40 后回到 75.0%。
              </li>
              <li>
                <b>工具调用与收口</b>
                固定单轮检索改成原生 function calling，注册 7 个工具（分路检索、取原文、书目、
                术语表、历法换算等），由模型按题型自选召回方式；多 Agent 拆成
                Supervisor / Retriever / Verifier 三层。引用编号必须落在真实返回过的
                chunk_id 内，走满 6 步未收口就按「证据不足」拒答。
              </li>
            </ol>
          </section>

          <section className="about-sec">
            <h2 className="about-sec__title">怎么判断它真的做好了</h2>
            <ol className="about-list">
              <li>
                <b>人工标注 30 题</b>
                20 题可答 + 10 题语料外。语料外 10/10 拒答，30 题 0 条不合规输出。
              </li>
              <li>
                <b>多 Agent 不是默认，是被数据否掉的</b>
                同一批 30 题，多 Agent 26/30，单 Agent 23/30；但每题 LLM 调用 7.6 次对 3.0 次，
                P50 从 38.0s 涨到 60.2s。所以默认仍是单轮 RAG，多 Agent 只做成可选项，
                让需要多书对照的人自己选。
              </li>
              <li>
                <b>并发也当成指标</b>
                本地 20 个回答槽，200 路 SSE + 20 并发回答 480/482 成功、错误率 0.41%、
                TTFB P95 1.01s；超出容量返回 429 而不是无限排队。320 项测试：
                316 通过 / 4 条件跳过 / 0 失败。
              </li>
            </ol>
          </section>

          <section className="about-sec">
            <h2 className="about-sec__title">一次我改错的地方</h2>
            <p className="about-p">
              语料从 2,830 节扩到 8,681 节那天，line Recall@5 从 77.5% 掉到 70.0%。
              我第一反应是「新语料质量不行」，差点回去重洗文本。实际原因是 RRF 的融合参数
              还是在旧语料规模下标定的，候选池一变，两路召回的相对权重就失衡了。
              用 280 组配置重扫才把这件事确认下来——如果当时按直觉去动数据，
              真正的 bug 会被埋在语料里，越查越远。
            </p>
          </section>

          <section className="about-sec">
            <h2 className="about-sec__title">现在还不够好的地方</h2>
            <ul className="about-list about-list--plain">
              <li>
                线上跑的是 5 个回答槽的小实例，同时几个人一起问会触发排队或 429。
                上面那组 480/482 的压测数字是在本地 20 槽环境跑的，不是这个实例。
              </li>
              <li>
                多 Agent 的 26/30 只在 30 题上验证过，样本量撑不起「普遍更好」的结论，
                所以它一直没做默认。
              </li>
              <li>
                不做预测吉凶、改运、医疗 / 法律 / 投资建议；排盘只做确定性历法计算。
                本站内容仅供文化研究与娱乐参考，回答请以原文为准。
                完整 17 条局限清单写在 README 里。
              </li>
            </ul>
          </section>

          <section className="about-sec">
            <h2 className="about-sec__title">谁做的</h2>
            <p className="about-p">
              傅楚楚，北京师范大学应用统计硕士（2028 届），方向 LLM 应用与检索增强生成。
              这个站从语料清洗、检索标定、工具编排到前端和部署，全部是我自己搭的。
            </p>
            <div className="about-links">
              <a className="about-link" href={GITHUB} target="_blank" rel="noreferrer">
                源码 · GitHub
              </a>
              <a className="about-link" href={`mailto:${MAIL}`}>
                {MAIL}
              </a>
            </div>
          </section>

          <p className="mem-foot">
            这个站是公开演示，对话只存在这台服务器上，不需要注册。语料来自公开古籍整理本，
            出处与授权说明见仓库的 ATTRIBUTION.md。
          </p>
        </div>
      </div>
    </div>
  );
}
