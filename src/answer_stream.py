# -*- coding: utf-8 -*-
"""从流式 `json_object` 里增量提取 `answer` 字段。

模型在 JSON 模式下仍然是一个字符一个字符地吐：
`{"can_answer": true, "answer": "正官与七杀...", "citations": [1]}`。
前端要看到的是纯文本，不是半个 JSON，所以服务端边收边解码：

- 找到 `"answer"` 键和开引号后进入字符串状态；
- 处理转义（`\\n`、`\\"`、`\\uXXXX`），不把反斜杠漏给前端；
- 读到未转义的闭引号就停，后面的 citations 不参与流式输出。

假设 `answer` 是顶层键（prompt 固定了字段顺序）。如果模型不按 JSON 输出，
这里什么都不吐，最终由完整响应的解析逻辑兜底报错。
"""
from __future__ import annotations

import re

_KEY_RE = re.compile(r'"answer"\s*:\s*"')

_SIMPLE_ESCAPES = {
    '"': '"',
    "\\": "\\",
    "/": "/",
    "b": "\b",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
}


class AnswerExtractor:
    def __init__(self) -> None:
        self._buf = ""
        self._pos = 0
        self._state = "seek"      # seek → string → done
        self._esc = ""            # "" / "\\" / "\\u"
        self._hex = ""

    @property
    def done(self) -> bool:
        return self._state == "done"

    def feed(self, chunk: str) -> str:
        """喂一段原始 JSON 文本，返回新解码出的正文（可能为空串）。"""
        if not chunk or self._state == "done":
            return ""
        self._buf += chunk

        if self._state == "seek":
            m = _KEY_RE.search(self._buf)
            if not m:
                # 键可能被切在两个分片之间；只保留尾部，避免缓冲无限增长
                if len(self._buf) > 256:
                    self._buf = self._buf[-64:]
                return ""
            self._pos = m.end()
            self._state = "string"
            # 已经消费掉的前缀不再需要，释放内存
            self._buf = self._buf[self._pos:]
            self._pos = 0

        out: list[str] = []
        buf = self._buf
        n = len(buf)
        while self._pos < n:
            c = buf[self._pos]

            if self._esc == "\\":
                if c == "u":
                    self._esc = "\\u"
                    self._hex = ""
                    self._pos += 1
                    continue
                if c in _SIMPLE_ESCAPES:
                    out.append(_SIMPLE_ESCAPES[c])
                    self._esc = ""
                    self._pos += 1
                    continue
                # 未知转义：原样保留字符，别吞掉内容
                out.append(c)
                self._esc = ""
                self._pos += 1
                continue

            if self._esc == "\\u":
                if c in "0123456789abcdefABCDEF":
                    self._hex += c
                    self._pos += 1
                    if len(self._hex) == 4:
                        out.append(chr(int(self._hex, 16)))
                        self._esc = ""
                        self._hex = ""
                    continue
                # 非法 \u：把已收的十六进制原样吐出，重新按普通字符处理
                out.append("\\u" + self._hex)
                self._esc = ""
                self._hex = ""
                continue

            if c == "\\":
                self._esc = "\\"
                self._pos += 1
                continue
            if c == '"':
                self._state = "done"
                self._pos += 1
                break
            out.append(c)
            self._pos += 1

        self._buf = buf
        return "".join(out)


def extract_streamed_answer(chunks) -> str:
    """便利函数：把一串分片喂给 extractor，返回拼接后的正文。"""
    ex = AnswerExtractor()
    return "".join(ex.feed(c) for c in chunks)
