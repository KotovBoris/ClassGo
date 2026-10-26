/**
 * Обёртка над MAX Bridge (window.WebApp, скрипт https://st.max.ru/js/max-web-app.js).
 *
 * Важное про платформу (dev.max.ru + код web.max.ru):
 * — openLink, downloadFile и shareMaxContent требуют клика пользователя: вызывать
 *   синхронно в обработчике, ссылки готовить заранее;
 * — методы WebApp — методы класса, им нужен this: вызывать только как wa().method(),
 *   не сохраняя в переменную, иначе метод падает и вызов молча не доходит до MAX;
 * — в web.max.ru не работают haptic, QR-сканер, DeviceStorage — только на телефоне;
 * — localStorage в iframe веб-версии эфемерный, поэтому каждый запрос к API
 *   несёт подписанный initData в заголовке, а состояние хранится на сервере.
 */

type Platform = "ios" | "android" | "desktop" | "web";

interface MaxUser {
  id: number;
  first_name?: string;
  last_name?: string;
  username?: string;
  photo_url?: string;
}

interface WebAppApi {
  initData?: string;
  initDataUnsafe?: { user?: MaxUser; start_param?: string; chat?: { id: number; type: string } };
  platform?: Platform | null;
  version?: string | null;
  deviceName?: string | null;
  ready?: () => void;
  close?: () => void;
  BackButton?: { show(): void; hide(): void; onClick(cb: () => void): void; offClick(cb: () => void): void };
  HapticFeedback?: {
    impactOccurred(style: "light" | "medium" | "heavy" | "soft" | "rigid"): Promise<unknown>;
    notificationOccurred(type: "success" | "error" | "warning"): Promise<unknown>;
  };
  requestContact?: () => Promise<{ phone: string; authDate: string | number; hash: string }>;
  enableClosingConfirmation?: () => void;
  disableClosingConfirmation?: () => void;
  openLink?: (url: string) => void;
  openMaxLink?: (url: string) => void;
  downloadFile?: (url: string, fileName: string) => Promise<{ status: string }>;
  shareMaxContent?: (p: { text?: string; link?: string }) => Promise<{ status: string }>;
}

declare global {
  interface Window {
    WebApp?: WebAppApi;
  }
}

const wa = (): WebAppApi | undefined => (typeof window !== "undefined" ? window.WebApp : undefined);

export function isInsideMax(): boolean {
  return Boolean(wa()?.initData);
}

export function initData(): string {
  return wa()?.initData ?? "";
}

export function platform(): Platform {
  return (wa()?.platform as Platform) || "web";
}

export function isMobile(): boolean {
  const p = platform();
  return isInsideMax() && (p === "ios" || p === "android");
}

export function maxUser(): MaxUser | null {
  return wa()?.initDataUnsafe?.user ?? null;
}

export function startParam(): string | null {
  const fromBridge = wa()?.initDataUnsafe?.start_param;
  if (fromBridge) return fromBridge;
  const url = new URL(window.location.href);
  return url.searchParams.get("startapp") || url.searchParams.get("WebAppStartParam");
}

/** Вне MAX (веб-проверка экспертом) — стабильный демо-идентификатор этого браузера. */
export function webDemoUserId(): number | null {
  if (isInsideMax()) return null;
  const url = new URL(window.location.href);
  const raw = url.searchParams.get("user_id");
  if (raw && /^\d+$/.test(raw)) return Number(raw);
  try {
    const stored = localStorage.getItem("classgo_demo_uid");
    if (stored && /^\d+$/.test(stored)) return Number(stored);
    const generated = 500000 + Math.floor(Math.random() * 400000);
    localStorage.setItem("classgo_demo_uid", String(generated));
    return generated;
  } catch {
    return 599999;
  }
}

export function ready(): void {
  try {
    wa()?.ready?.();
  } catch {
    /* необязательно */
  }
}

let backHandler: (() => void) | null = null;

/** Системная кнопка «Назад» в шапке MAX вместо собственной. */
export function setBackButton(handler: (() => void) | null): void {
  const back = wa()?.BackButton;
  if (!back) return;
  if (backHandler) back.offClick(backHandler);
  backHandler = handler;
  if (handler) {
    back.onClick(handler);
    back.show();
  } else {
    back.hide();
  }
}

export function setClosingConfirmation(on: boolean): void {
  try {
    if (on) wa()?.enableClosingConfirmation?.();
    else wa()?.disableClosingConfirmation?.();
  } catch {
    /* необязательно */
  }
}

export const haptic = {
  tap(): void {
    if (isMobile()) void wa()?.HapticFeedback?.impactOccurred("light").catch(() => undefined);
  },
  ok(): void {
    if (isMobile()) void wa()?.HapticFeedback?.notificationOccurred("success").catch(() => undefined);
  },
  warn(): void {
    if (isMobile()) void wa()?.HapticFeedback?.notificationOccurred("warning").catch(() => undefined);
  },
};

export interface VerifiedContact {
  phone: string;
  authDate: string;
  hash: string;
}

/** Номер телефона, подтверждённый MAX (подпись проверяет сервер). */
export async function requestContact(): Promise<VerifiedContact | null> {
  const w = wa();
  if (!w?.requestContact || !isInsideMax()) return null;
  try {
    const r = await w.requestContact();
    return { phone: String(r.phone), authDate: String(r.authDate), hash: String(r.hash) };
  } catch {
    return null;
  }
}

/** Открыть внешнюю ссылку (сайт музея). Вызывать синхронно в onClick. */
export function openLink(url: string): void {
  const w = wa();
  if (isInsideMax() && w?.openLink) {
    try {
      w.openLink(url);
      return;
    } catch {
      /* ниже — запасной путь */
    }
  }
  window.open(url, "_blank", "noopener");
}

/** Скачать файл. В MAX — нативный диалог (только https и только из клика). */
export function downloadFile(url: string, fileName: string): void {
  const absolute = new URL(url, window.location.href).toString();
  const w = wa();
  if (isInsideMax() && w?.downloadFile && absolute.startsWith("https://")) {
    try {
      void w.downloadFile(absolute, fileName).catch(() => window.open(absolute, "_blank", "noopener"));
      return;
    } catch {
      /* ниже — запасной путь */
    }
  }
  const a = document.createElement("a");
  a.href = absolute;
  a.download = fileName;
  a.rel = "noopener";
  document.body.appendChild(a);
  a.click();
  a.remove();
}

/**
 * Поделиться в чат MAX (выбор чата внутри мессенджера) — работает и в веб-версии.
 * Если MAX не открыл выбор чата — копируем текст со ссылкой в буфер.
 * Вне MAX — системный шеринг или копирование в буфер. Возвращает способ.
 */
export async function shareToChat(text: string, link: string): Promise<"shared" | "copied" | "cancelled"> {
  const w = wa();
  const inside = isInsideMax();
  if (inside && w?.shareMaxContent) {
    try {
      const r = await w.shareMaxContent({ text, link });
      return r?.status === "shared" ? "shared" : "cancelled";
    } catch {
      /* запасной путь ниже */
    }
  }
  try {
    if (!inside && navigator.share) {
      await navigator.share({ text, url: link });
      return "shared";
    }
  } catch {
    return "cancelled";
  }
  try {
    await navigator.clipboard.writeText(`${text}\n${link}`);
    return "copied";
  } catch {
    return "cancelled";
  }
}

export async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

/** Ссылка на телефон для звонка родителю в одно касание. */
export function telHref(phone: string | null | undefined): string | null {
  const digits = (phone ?? "").replace(/[^\d+]/g, "");
  return digits.length >= 10 ? `tel:${digits}` : null;
}
