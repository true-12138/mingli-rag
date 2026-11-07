// 表单里的日期/时间字符串 → 后端要的整数。两个排盘面板共用。

export interface Ymd {
  year: number;
  month: number;
  day: number;
}

/** "1995-08-20" → {year, month, day}；格式不对返回 null。 */
export function splitDate(value: string): Ymd | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!match) return null;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  if (month < 1 || month > 12 || day < 1 || day > 31) return null;
  return { year, month, day };
}

/** "14:30" → {hour, minute}；空值按 12:00 算，不给时辰时至少日柱是准的。 */
export function splitTime(value: string): { hour: number; minute: number } {
  const match = /^(\d{1,2}):(\d{2})$/.exec(value.trim());
  if (!match) return { hour: 12, minute: 0 };
  const hour = Math.min(23, Math.max(0, Number(match[1])));
  const minute = Math.min(59, Math.max(0, Number(match[2])));
  return { hour, minute };
}
