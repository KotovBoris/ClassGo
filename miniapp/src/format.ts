const MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"];
const MONTHS_SHORT = ["янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"];
const WEEKDAYS = ["воскресенье", "понедельник", "вторник", "среда", "четверг", "пятница", "суббота"];
const WEEKDAYS_SHORT = ["вс", "пн", "вт", "ср", "чт", "пт", "сб"];

/** «2026-11-08» → Date в локальной зоне (без сдвига на UTC). */
export function parseDay(value: string | null | undefined): Date | null {
  if (!value) return null;
  const [y, m, d] = value.slice(0, 10).split("-").map(Number);
  if (!y || !m || !d) return null;
  return new Date(y, m - 1, d);
}

/** Сервер отдаёт время в UTC без суффикса — добавляем «Z», чтобы показать местное. */
export function parseUtc(value: string | null | undefined): Date | null {
  if (!value) return null;
  const iso = /[zZ]|[+-]\d\d:?\d\d$/.test(value) ? value : `${value}Z`;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? null : d;
}

export function dayLong(value: string | null | undefined): string {
  const d = parseDay(value);
  if (!d) return "дата уточняется";
  return `${WEEKDAYS[d.getDay()]}, ${d.getDate()} ${MONTHS[d.getMonth()]}`;
}

export function dayShort(value: string | null | undefined): string {
  const d = parseDay(value);
  if (!d) return "—";
  return `${WEEKDAYS_SHORT[d.getDay()]}, ${d.getDate()} ${MONTHS[d.getMonth()]}`;
}

export function dayParts(value: string | null | undefined): { day: string; month: string } {
  const d = parseDay(value);
  if (!d) return { day: "?", month: "" };
  return { day: String(d.getDate()), month: MONTHS_SHORT[d.getMonth()] };
}

/** День, месяц и время момента по часам пояса tz (по умолчанию — пояс телефона). */
function partsIn(d: Date, tz?: string): { day: number; month: number; time: string } {
  try {
    const parts = new Intl.DateTimeFormat("ru-RU", {
      timeZone: tz || undefined, day: "numeric", month: "numeric", hour: "2-digit", minute: "2-digit", hourCycle: "h23",
    }).formatToParts(d);
    const get = (type: string) => parts.find((p) => p.type === type)?.value ?? "";
    return { day: Number(get("day")), month: Number(get("month")) - 1, time: `${get("hour")}:${get("minute")}` };
  } catch {
    const time = d.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
    return { day: d.getDate(), month: d.getMonth(), time };
  }
}

/** Срок ответа по времени школы: «27 октября, 18:00». */
export function deadlineText(value: string | null | undefined, tz?: string): string {
  const d = parseUtc(value);
  if (!d) return "";
  const p = partsIn(d, tz);
  return `${p.day} ${MONTHS[p.month]}, ${p.time}`;
}

export function stamp(value: string | null | undefined, tz?: string): string {
  const d = parseUtc(value);
  if (!d) return "";
  const p = partsIn(d, tz);
  return `${p.day} ${MONTHS[p.month]} в ${p.time}`;
}

export function deviceTimeZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "";
  } catch {
    return "";
  }
}

/** Пометка, если часы школы не совпадают с часами телефона: «время школы, UTC+5». */
export function schoolTimeNote(tz?: string): string {
  if (!tz) return "";
  const now = new Date();
  if (partsIn(now, tz).time === partsIn(now).time) return "";
  try {
    const name = new Intl.DateTimeFormat("ru-RU", { timeZone: tz, timeZoneName: "shortOffset" })
      .formatToParts(now).find((p) => p.type === "timeZoneName")?.value;
    return name ? `время школы, ${name.replace("GMT", "UTC")}` : "время школы";
  } catch {
    return "время школы";
  }
}

export function isPast(value: string | null | undefined): boolean {
  const d = parseUtc(value);
  return Boolean(d && d.getTime() < Date.now());
}

export function money(value: number): string {
  return `${Math.round(value).toLocaleString("ru-RU")} ₽`;
}

/** 1 родитель, 2 родителя, 5 родителей. */
export function plural(n: number, one: string, few: string, many: string): string {
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod10 === 1 && mod100 !== 11) return one;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return few;
  return many;
}

/** «Сафин Тимур Ренатович» → «Тимур Сафин»: так короче в списках и карточках. */
export function shortName(full: string): string {
  const parts = full.trim().split(/\s+/);
  if (parts.length >= 2) return `${parts[1]} ${parts[0]}`;
  return full;
}

export function firstName(full: string): string {
  const parts = full.trim().split(/\s+/);
  return parts.length >= 2 ? parts[1] : full;
}

export function initials(full: string): string {
  const parts = full.trim().split(/\s+/);
  const a = parts[1]?.[0] ?? parts[0]?.[0] ?? "";
  const b = parts[0]?.[0] ?? "";
  return (a + b).toUpperCase();
}

export function isoDate(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

export function addDays(d: Date, days: number): Date {
  const r = new Date(d);
  r.setDate(r.getDate() + days);
  return r;
}

export function formatPhone(raw: string | null | undefined): string {
  const digits = (raw ?? "").replace(/\D/g, "");
  if (digits.length === 11) {
    return `+${digits[0]} ${digits.slice(1, 4)} ${digits.slice(4, 7)}-${digits.slice(7, 9)}-${digits.slice(9)}`;
  }
  return raw ?? "";
}

/** Название в «ёлочках», если их ещё нет. */
export function quote(title: string): string {
  return title.includes("«") ? title : `«${title}»`;
}
