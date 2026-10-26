import { useEffect, useMemo, type ReactNode } from "react";
import qrcode from "qrcode-generator";
import { Button, Spinner } from "@maxhub/max-ui";
import type { TripStats } from "./api";
import { dayParts } from "./format";
import { useAppState } from "./store";

/* ------------------------------------------------------------------ иконки */
type IconName =
  | "check" | "x" | "clock" | "users" | "doc" | "share" | "qr" | "bell" | "chevron"
  | "calendar" | "pin" | "ticket" | "phone" | "plus" | "download" | "chat" | "school"
  | "spark" | "shield" | "edit" | "refresh" | "upload" | "trash" | "info" | "search";

const PATHS: Record<IconName, string> = {
  check: "M5 12.5l4.2 4.2L19 7",
  x: "M6 6l12 12M18 6L6 18",
  clock: "M12 7v5l3 2M21 12a9 9 0 11-18 0 9 9 0 0118 0z",
  users: "M16 19v-1a4 4 0 00-4-4H7a4 4 0 00-4 4v1M9.5 10a3.5 3.5 0 100-7 3.5 3.5 0 000 7zM21 19v-1a4 4 0 00-3-3.87M15.5 3.13a3.5 3.5 0 010 6.74",
  doc: "M14 3H7a2 2 0 00-2 2v14a2 2 0 002 2h10a2 2 0 002-2V8l-5-5zM14 3v5h5M9 13h6M9 17h6",
  share: "M4 12v7a2 2 0 002 2h12a2 2 0 002-2v-7M16 6l-4-4-4 4M12 2v14",
  qr: "M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h2v2h-2zM18 14h2v2h-2zM14 18h2v2h-2zM18 18h2v2h-2z",
  bell: "M18 8a6 6 0 10-12 0c0 7-3 9-3 9h18s-3-2-3-9M13.7 21a2 2 0 01-3.4 0",
  chevron: "M9 6l6 6-6 6",
  calendar: "M8 3v4M16 3v4M4 9h16M5 5h14a1 1 0 011 1v13a1 1 0 01-1 1H5a1 1 0 01-1-1V6a1 1 0 011-1z",
  pin: "M12 21s-7-6.2-7-11.5A7 7 0 0119 9.5C19 14.8 12 21 12 21zM12 12a2.5 2.5 0 100-5 2.5 2.5 0 000 5z",
  ticket: "M3 8a2 2 0 002-2h14a2 2 0 002 2v2a2 2 0 000 4v2a2 2 0 01-2 2H5a2 2 0 01-2-2v-2a2 2 0 000-4V8zM14 6v12",
  phone: "M22 16.9v3a2 2 0 01-2.2 2 19.8 19.8 0 01-8.6-3.1 19.5 19.5 0 01-6-6A19.8 19.8 0 012.1 4.2 2 2 0 014.1 2h3a2 2 0 012 1.7c.1.9.4 1.8.7 2.7a2 2 0 01-.5 2.1L8 9.8a16 16 0 006 6l1.3-1.3a2 2 0 012.1-.4c.9.3 1.8.6 2.7.7a2 2 0 011.7 2z",
  plus: "M12 5v14M5 12h14",
  download: "M4 17v2a2 2 0 002 2h12a2 2 0 002-2v-2M8 12l4 4 4-4M12 3v13",
  chat: "M21 12a8 8 0 01-11.6 7.1L4 20l1.1-4.6A8 8 0 1121 12z",
  school: "M3 10l9-5 9 5-9 5-9-5zM7 12.2V17c0 1 2.2 3 5 3s5-2 5-3v-4.8M21 10v6",
  spark: "M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8L12 3z",
  shield: "M12 3l8 3v6c0 5-3.4 8.2-8 9-4.6-.8-8-4-8-9V6l8-3zM8.5 12l2.5 2.5L15.5 10",
  edit: "M4 20h4L19 9l-4-4L4 16v4zM14 6l4 4",
  refresh: "M20 11a8 8 0 00-14.9-3.5M4 4v4h4M4 13a8 8 0 0014.9 3.5M20 20v-4h-4",
  upload: "M4 17v2a2 2 0 002 2h12a2 2 0 002-2v-2M16 8l-4-4-4 4M12 4v12",
  trash: "M4 7h16M10 11v6M14 11v6M5 7l1 12a2 2 0 002 2h8a2 2 0 002-2l1-12M9 7V4h6v3",
  info: "M12 21a9 9 0 100-18 9 9 0 000 18zM12 11v5M12 8h.01",
  search: "M11 19a8 8 0 100-16 8 8 0 000 16zM21 21l-4.3-4.3",
};

export function Icon({ name, size = 20, className }: { name: IconName; size?: number; className?: string }) {
  return (
    <svg
      className={`cg-icon ${className ?? ""}`}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={PATHS[name]} />
    </svg>
  );
}

/* ------------------------------------------------------------------ каркас */
export function Page({ children, bottom }: { children: ReactNode; bottom?: ReactNode }) {
  return (
    <div className={`cg-page ${bottom ? "has-bottom" : ""}`}>
      {children}
      {bottom && <div className="cg-bottom">{bottom}</div>}
    </div>
  );
}

export function Hero({
  overline,
  title,
  subtitle,
  aside,
}: {
  overline?: ReactNode;
  title: ReactNode;
  subtitle?: ReactNode;
  aside?: ReactNode;
}) {
  return (
    <header className="cg-hero">
      <div className="cg-hero-text">
        {overline && <div className="cg-overline">{overline}</div>}
        <h1 className="cg-h1">{title}</h1>
        {subtitle && <p className="cg-sub">{subtitle}</p>}
      </div>
      {aside}
    </header>
  );
}

export function Section({
  title,
  action,
  children,
  id,
}: {
  title?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  id?: string;
}) {
  return (
    <section className="cg-section" id={id}>
      {(title || action) && (
        <div className="cg-section-head">
          {title && <h2 className="cg-h2">{title}</h2>}
          {action}
        </div>
      )}
      {children}
    </section>
  );
}

export function Card({
  children,
  className,
  onClick,
  as = "div",
}: {
  children: ReactNode;
  className?: string;
  onClick?: () => void;
  as?: "div" | "button";
}) {
  if (as === "button" || onClick) {
    return (
      <button type="button" className={`cg-card cg-card-tap ${className ?? ""}`} onClick={onClick}>
        {children}
      </button>
    );
  }
  return <div className={`cg-card ${className ?? ""}`}>{children}</div>;
}

export function Loader({ label = "Загружаем…" }: { label?: string }) {
  return (
    <div className="cg-loader" role="status" aria-live="polite">
      <Spinner size={28} />
      <span>{label}</span>
    </div>
  );
}

export function SkeletonList({ rows = 3 }: { rows?: number }) {
  return (
    <div className="cg-skeleton" aria-hidden="true">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="cg-skel-card">
          <div className="cg-skel-line w40" />
          <div className="cg-skel-line w80" />
          <div className="cg-skel-line w60" />
        </div>
      ))}
    </div>
  );
}

export function Empty({ icon, title, text, action }: { icon: IconName; title: string; text?: ReactNode; action?: ReactNode }) {
  return (
    <div className="cg-empty">
      <div className="cg-empty-icon">
        <Icon name={icon} size={28} />
      </div>
      <div className="cg-empty-title">{title}</div>
      {text && <p className="cg-empty-text">{text}</p>}
      {action}
    </div>
  );
}

export function Notice({
  tone = "info",
  icon,
  title,
  children,
  action,
}: {
  tone?: "info" | "ok" | "warn" | "demo" | "error";
  icon?: IconName;
  title?: ReactNode;
  children?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className={`cg-notice tone-${tone}`} role={tone === "error" ? "alert" : undefined}>
      {icon && (
        <span className="cg-notice-icon">
          <Icon name={icon} size={20} />
        </span>
      )}
      <div className="cg-notice-body">
        {title && <div className="cg-notice-title">{title}</div>}
        {children && <div className="cg-notice-text">{children}</div>}
        {action && <div className="cg-notice-action">{action}</div>}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ статусы */
export type StatusTone = "going" | "notgoing" | "waiting" | "ticket" | "neutral";

const STATUS_ICON: Record<StatusTone, IconName> = {
  going: "check",
  notgoing: "x",
  waiting: "clock",
  ticket: "ticket",
  neutral: "info",
};

/** Статус всегда словом + значком + цветом (цвет только дополняет, WCAG 1.4.1). */
export function Status({ tone, children }: { tone: StatusTone; children: ReactNode }) {
  return (
    <span className={`cg-status st-${tone}`}>
      <Icon name={STATUS_ICON[tone]} size={14} />
      {children}
    </span>
  );
}

export function StatTiles({ stats, compact = false }: { stats: TripStats; compact?: boolean }) {
  const tiles: { tone: StatusTone; value: number; label: string }[] = [
    { tone: "going", value: stats.going, label: "отпускают" },
    { tone: "waiting", value: stats.waiting, label: "ещё не ответили" },
    { tone: "notgoing", value: stats.not_going, label: "не смогут" },
  ];
  return (
    <div className={`cg-tiles ${compact ? "compact" : ""}`}>
      {tiles.map((t) => (
        <div key={t.tone} className={`cg-tile st-${t.tone}`}>
          <span className="cg-tile-value">{t.value}</span>
          <span className="cg-tile-label">{t.label}</span>
        </div>
      ))}
    </div>
  );
}

export function ProgressBar({ stats, label = true }: { stats: TripStats; label?: boolean }) {
  const total = stats.total || 1;
  const seg = (n: number) => `${(100 * n) / total}%`;
  return (
    <div className="cg-progress-wrap">
      <div
        className="cg-progress"
        role="img"
        aria-label={`Ответили ${stats.answered} из ${stats.total}`}
      >
        <span className="seg st-going" style={{ width: seg(stats.going) }} />
        <span className="seg st-notgoing" style={{ width: seg(stats.not_going) }} />
      </div>
      {label && (
        <div className="cg-progress-label">
          Ответили <b>{stats.answered}</b> из {stats.total}
        </div>
      )}
    </div>
  );
}

export function DateBadge({ date }: { date: string | null }) {
  const p = dayParts(date);
  return (
    <div className="cg-datebadge" aria-hidden="true">
      <span className="d">{p.day}</span>
      <span className="m">{p.month}</span>
    </div>
  );
}

export function Chip({
  active,
  onClick,
  children,
}: {
  active?: boolean;
  onClick?: () => void;
  children: ReactNode;
}) {
  return (
    <button type="button" className={`cg-chip ${active ? "active" : ""}`} aria-pressed={active} onClick={onClick}>
      {children}
    </button>
  );
}

export function Tag({ tone = "neutral", children }: { tone?: "neutral" | "pushkin" | "free" | "demo"; children: ReactNode }) {
  return <span className={`cg-tag tag-${tone}`}>{children}</span>;
}

export function Segmented<T extends string>({
  value,
  options,
  onChange,
  label,
}: {
  value: T;
  options: { value: T; label: string }[];
  onChange: (v: T) => void;
  label: string;
}) {
  return (
    <div className="cg-segmented" role="tablist" aria-label={label}>
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          role="tab"
          aria-selected={o.value === value}
          className={o.value === value ? "active" : ""}
          onClick={() => onChange(o.value)}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: ReactNode;
  children: ReactNode;
}) {
  return (
    <label className="cg-field">
      <span className="cg-field-label">{label}</span>
      {children}
      {hint && <span className="cg-field-hint">{hint}</span>}
    </label>
  );
}

/* ------------------------------------------------------------------ лист снизу */
export function Sheet({
  open,
  title,
  onClose,
  children,
}: {
  open: boolean;
  title: ReactNode;
  onClose: () => void;
  children: ReactNode;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    document.body.classList.add("cg-noscroll");
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.classList.remove("cg-noscroll");
    };
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="cg-sheet-backdrop" onClick={onClose}>
      <div
        className="cg-sheet"
        role="dialog"
        aria-modal="true"
        aria-label={typeof title === "string" ? title : undefined}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="cg-sheet-grip" />
        <div className="cg-sheet-head">
          <div className="cg-sheet-title">{title}</div>
          <button type="button" className="cg-icon-btn" aria-label="Закрыть" onClick={onClose}>
            <Icon name="x" size={20} />
          </button>
        </div>
        <div className="cg-sheet-body">{children}</div>
      </div>
    </div>
  );
}

/** Подтверждение действия, которое нельзя тихо отменить: что произойдёт — словами, и две кнопки. */
export function Confirm({
  open,
  title,
  yes,
  no = "Отмена",
  danger = false,
  busy = false,
  onYes,
  onClose,
  children,
}: {
  open: boolean;
  title: string;
  yes: string;
  no?: string;
  danger?: boolean;
  busy?: boolean;
  onYes: () => void;
  onClose: () => void;
  children: ReactNode;
}) {
  return (
    <Sheet open={open} title={title} onClose={onClose}>
      <div className="cg-confirm-text">{children}</div>
      <div className="cg-stack">
        <Button size="large" stretched variant={danger ? "destructive" : "primary"} loading={busy} onClick={onYes}>
          {yes}
        </Button>
        <Button size="large" stretched variant="secondary" disabled={busy} onClick={onClose}>
          {no}
        </Button>
      </div>
    </Sheet>
  );
}

export function Toaster() {
  const { toast } = useAppState();
  if (!toast) return null;
  return (
    <div className={`cg-toast tone-${toast.tone}`} role="status" aria-live="polite" key={toast.id}>
      <Icon name={toast.tone === "error" ? "info" : "check"} size={18} />
      <span>{toast.text}</span>
    </div>
  );
}

export function QrCode({ value, size = 220 }: { value: string; size?: number }) {
  const svg = useMemo(() => {
    const qr = qrcode(0, "M");
    qr.addData(value);
    qr.make();
    return qr.createSvgTag({ cellSize: 4, margin: 2, scalable: true });
  }, [value]);
  return (
    <div
      className="cg-qr"
      style={{ width: size, height: size }}
      role="img"
      aria-label="QR-код ссылки-приглашения"
      dangerouslySetInnerHTML={{ __html: svg }}
    />
  );
}

export function Avatar({ text, tone = "neutral" }: { text: string; tone?: StatusTone }) {
  return (
    <span className={`cg-avatar st-${tone}`} aria-hidden="true">
      {text}
    </span>
  );
}
