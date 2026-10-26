import { useCallback, useEffect, useMemo, useState } from "react";
import { Button } from "@maxhub/max-ui";
import { api, type Dashboard, type Invite, type ParticipantRow, type TicketsInfo } from "../api";
import { dayLong, deadlineText, formatPhone, initials, isoDate, isPast, money, parseDay, plural, quote, schoolTimeNote, shortName, stamp } from "../format";
import { downloadFile, haptic, isInsideMax, openLink, shareToChat, telHref } from "../max";
import { errorText, toast } from "../store";
import {
  Avatar,
  Card,
  Confirm,
  Hero,
  Icon,
  Loader,
  Notice,
  Page,
  ProgressBar,
  Section,
  Sheet,
  StatTiles,
  Status,
  Tag,
  type StatusTone,
} from "../ui";

const SOURCE_LABEL: Record<string, string> = {
  bot: "кнопкой в чате MAX",
  miniapp: "в приложении ClassGo",
  paper: "бумажное согласие — отметил учитель",
  call: "устно — нужно письменное подтверждение",
  person: "устно — нужно письменное подтверждение",
  demo: "кнопкой в чате MAX (демо)",
  api: "в ClassGo",
};

function rowTone(p: ParticipantRow): StatusTone {
  if (p.consent_status === "REJECTED") return "notgoing";
  if (p.consent_status === "PENDING") return "waiting";
  return "going";
}

function rowStatus(p: ParticipantRow): string {
  if (p.consent_status === "REJECTED") return "Не сможет";
  if (p.consent_status === "PENDING") return "Ждём ответ";
  return "Отпускают";
}

function rowSubtitle(p: ParticipantRow, tz: string): string {
  const role = p.parent_role && p.parent_role !== "Законный представитель" ? p.parent_role : "Родитель";
  if (p.consent_status === "PENDING") {
    return p.bot_activated ? `${role} · приглашение в MAX` : `${role} · не подключён к MAX`;
  }
  const manual = p.signed_source === "paper";
  const when = shortStamp(p.signed_at, tz);
  if (p.consent_status === "REJECTED") return `${p.rejection_reason || "Без причины"} · ${when}`;
  return `${manual ? "Бумажное согласие" : role} · ${when}`;
}

/** День выезда наступил — по календарю школы. */
function tripDayReached(eventDate: string | null, tz: string): boolean {
  if (!eventDate) return false;
  let today: string;
  try {
    today = new Intl.DateTimeFormat("en-CA", { timeZone: tz || undefined }).format(new Date());
  } catch {
    today = isoDate(new Date());
  }
  return eventDate.slice(0, 10) <= today;
}

function shortStamp(value: string | null, tz: string): string {
  return stamp(value, tz).replace(/ в /, ", ");
}

export default function TripScreen({ id }: { id: number }) {
  const [data, setData] = useState<Dashboard | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [invite, setInvite] = useState<Invite | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [selected, setSelected] = useState<ParticipantRow | null>(null);

  const load = useCallback(async () => {
    try {
      const d = await api.dashboard(id);
      setData(d);
      setError(null);
      setSelected((cur) => (cur ? d.participants.find((p) => p.student_id === cur.student_id) ?? null : null));
    } catch (e) {
      setError(errorText(e));
    }
  }, [id]);

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(), 4000);
    return () => window.clearInterval(timer);
  }, [load]);

  const classId = data?.excursion.class_id;
  useEffect(() => {
    if (!classId) return;
    api.invite(classId).then(setInvite).catch(() => setInvite(null));
  }, [classId]);

  const groups = useMemo(() => {
    const rows = data?.participants ?? [];
    return {
      waiting: rows.filter((p) => p.consent_status === "PENDING"),
      going: rows.filter((p) => p.consent_status === "APPROVED"),
      notGoing: rows.filter((p) => p.consent_status === "REJECTED"),
    };
  }, [data]);

  if (!data) {
    return (
      <Page>
        {error ? (
          <Notice tone="error" icon="info" title="Не удалось открыть выезд">
            {error}
          </Notice>
        ) : (
          <Loader label="Открываем выезд…" />
        )}
      </Page>
    );
  }

  const exc = data.excursion;
  const stats = exc.stats ?? {
    total: data.participants.length,
    answered: data.participants.length - groups.waiting.length,
    going: groups.going.length,
    not_going: groups.notGoing.length,
    waiting: groups.waiting.length,
    waiting_ticket: groups.going.filter((p) => p.ticket_status === "WAITING_PAYMENT").length,
  };
  const missingKids = Math.max(0, (exc.class_expected_size || 0) - stats.total);
  const allAnswered = stats.waiting === 0 && stats.total > 0 && missingKids === 0;
  const tripDay = !exc.cancelled && stats.going > 0 && (tripDayReached(exc.event_date, exc.timezone) || Boolean(exc.departed_at));
  const hasUnconnected = groups.waiting.some((p) => !p.bot_activated);
  const shareText =
    `${exc.class_title}: выезд ${quote(exc.title)}, ${dayLong(exc.event_date)}. ` +
    `Родители, ответьте одной кнопкой в ClassGo: «Да» или «Нет».`;

  async function remind() {
    setBusy("remind");
    try {
      const r = await api.remind(id);
      haptic.ok();
      const held = r.skipped_quiet + r.skipped_recent;
      const rest = r.targeted - r.delivered - held;
      const parts: string[] = [];
      if (r.delivered) parts.push(`Напомнили в MAX ${r.delivered} ${plural(r.delivered, "родителю", "родителям", "родителям")}.`);
      if (r.skipped_quiet) parts.push(`${r.skipped_quiet} — сейчас ночь у родителя, напомните после 8:00.`);
      if (r.skipped_recent) parts.push(`${r.skipped_recent} — уже напоминали за последние 12 часов.`);
      if (rest > 0) parts.push(`Ещё ${rest} без MAX — отправьте им ссылку или дайте бумажный бланк.`);
      toast(parts.join(" ") || "Кто не ответил, ещё не подключён к MAX. Отправьте ссылку в чат класса.",
        r.delivered ? "ok" : "info");
    } catch (e) {
      toast(errorText(e), "error");
    } finally {
      setBusy(null);
    }
  }

  async function shareInvite() {
    if (!invite) return;
    const result = await shareToChat(shareText, invite.app_link);
    if (result === "copied") toast("Ссылка скопирована — вставьте её в чат класса.");
    if (result === "shared") toast("Приглашение отправлено в чат.");
  }

  async function downloadDoc(fmt: "pdf" | "docx") {
    try {
      const links = await api.orderLinks(id);
      downloadFile(fmt === "pdf" ? links.pdf_url : links.docx_url, `${fileBase}.${fmt}`);
    } catch (e) {
      toast(errorText(e), "error");
    }
  }

  async function sendDocs() {
    setBusy("docs");
    try {
      const r = await api.sendDocuments(id);
      toast(r.message, r.delivered ? "ok" : "info");
      if (r.delivered) haptic.ok();
    } catch (e) {
      toast(errorText(e), "error");
    } finally {
      setBusy(null);
    }
  }

  const fileBase = `Приказ_${exc.class_title}_${(exc.event_date ?? "").slice(5).replace("-", ".")}`;

  return (
    <Page
      bottom={
        exc.cancelled ? undefined : !allAnswered && stats.waiting > 0 && !exc.departed_at ? (
          <Button size="large" stretched loading={busy === "remind"} onClick={() => void remind()}
            iconBefore={<Icon name="bell" size={20} />}>
            Напомнить {stats.waiting} {plural(stats.waiting, "родителю", "родителям", "родителям")}
          </Button>
        ) : (
          <Button size="large" stretched loading={busy === "docs"} iconBefore={<Icon name="doc" size={20} />}
            onClick={() => void (isInsideMax() ? sendDocs() : downloadDoc("pdf"))}>
            {isInsideMax() ? "Прислать документы в чат" : "Скачать документы (PDF)"}
          </Button>
        )
      }
    >
      <Hero
        overline={`${exc.class_title} · ${dayLong(exc.event_date)}`}
        title={exc.title}
        subtitle={exc.location_name}
        aside={exc.is_demo ? <Tag tone="demo">демо</Tag> : undefined}
      />

      {exc.cancelled && (
        <Notice tone="warn" icon="info" title="Выезд отменён">
          Родители получили сообщение об отмене. Ответы и документы сохранены.
        </Notice>
      )}

      <Card className="cg-facts">
        <Fact icon="clock">
          Сбор в <b>{exc.gathering_time ?? "—"}</b> {exc.meeting_point}
          {exc.return_time && <>, вернёмся к <b>{exc.return_time}</b></>}
        </Fact>
        <Fact icon="pin">
          {exc.address || exc.location_name}
          {exc.transport && <>. Добираемся: {exc.transport}</>}
        </Fact>
        <Fact icon="ticket">
          {exc.ticket_price > 0 ? (
            <>
              Билет <b>{money(exc.ticket_price)}</b> — семьи покупают сами, школа деньги не собирает
              {exc.is_pushkin_card && <>. С 14 лет — «Пушкинской картой»</>}
            </>
          ) : (
            <>Вход бесплатный</>
          )}
        </Fact>
        <Fact icon="users">
          Ведёт: {exc.responsible_teacher || "классный руководитель"}
          {exc.escorts && <>, сопровождают: {exc.escorts}</>}
        </Fact>
        {exc.deadline && (
          <Fact icon="calendar">
            {isPast(exc.deadline) ? "Срок ответа прошёл: " : "Ответить до "}
            <b>{deadlineText(exc.deadline, exc.timezone)}</b>
            {schoolTimeNote(exc.timezone) && <span className="cg-muted"> ({schoolTimeNote(exc.timezone)})</span>}
          </Fact>
        )}
      </Card>

      <Section>
        <StatTiles stats={stats} />
        <ProgressBar stats={stats} />
      </Section>

      {missingKids > 0 && (
        <Notice tone="warn" icon="users" title={`В списке ${stats.total} из ${exc.class_expected_size} учеников`}>
          Ещё {missingKids} {plural(missingKids, "семья не прислала", "семьи не прислали", "семей не прислали")} заявку —
          этих детей нет в приказе и перекличке. Отправьте ссылку в чат класса ещё раз.
        </Notice>
      )}

      {tripDay && (
        <TripDay
          excursionId={id}
          going={groups.going}
          departedAt={exc.departed_at}
          returnedAt={exc.returned_at}
          tz={exc.timezone}
          onChanged={() => void load()}
        />
      )}
      {tripDay && exc.ticket_price > 0 && <TicketsSection excursionId={id} going={groups.going} demo={exc.is_demo} />}

      {allAnswered ? (
        <Notice tone="ok" icon="check" title="Ответили все родители">
          Едут {stats.going} из {stats.total}. Документы для директора готовы.
        </Notice>
      ) : !hasUnconnected ? null : (
        <Card className="cg-actions-card">
          <div className="cg-actions-title">Не все родители в MAX</div>
          <p className="cg-muted">
            Отправьте ссылку в чат класса. Родитель подтвердит номер и сразу увидит приглашение.
          </p>
          <Button size="medium" variant="secondary" stretched disabled={!invite}
            iconBefore={<Icon name="share" size={18} />} onClick={() => void shareInvite()}>
            Отправить ссылку в чат
          </Button>
        </Card>
      )}

      {exc.is_demo && !allAnswered && (
        <p className="cg-muted cg-small cg-live">
          <span className="cg-dot" /> Демо-родители отвечают сами — список обновляется на глазах.
        </p>
      )}

      <StudentGroup title="Ещё не ответили" rows={groups.waiting} tz={exc.timezone} onOpen={setSelected} />
      <StudentGroup title="Отпускают" rows={groups.going} tz={exc.timezone} onOpen={setSelected} />
      <StudentGroup title="Не смогут" rows={groups.notGoing} tz={exc.timezone} onOpen={setSelected} />

      {!tripDay && exc.ticket_price > 0 && groups.going.length > 0 && !exc.cancelled && (
        <TicketsSection excursionId={id} going={groups.going} demo={exc.is_demo} />
      )}

      <Section title="Документы для директора">
        <Card>
          <ul className="cg-doclist">
            <li><Icon name="doc" size={18} />Проект приказа — на подпись директору</li>
            <li><Icon name="users" size={18} />Список группы и список с телефонами родителей</li>
            <li><Icon name="shield" size={18} />Реестр согласий: кто, когда и как ответил</li>
            <li><Icon name="check" size={18} />Ведомость инструктажа и памятка ученикам</li>
            <li><Icon name="edit" size={18} />Бумажные бланки для тех, кто без MAX</li>
          </ul>
          {!allAnswered && (
            <p className="cg-muted cg-small">
              Сейчас в списке {stats.going} {plural(stats.going, "ученик", "ученика", "учеников")} — те, кого уже
              отпустили. Когда ответят остальные, документы обновятся.
            </p>
          )}
          <div className="cg-row-buttons">
            {isInsideMax() && (
              <Button size="medium" variant={allAnswered ? "primary" : "secondary"} loading={busy === "docs"}
                onClick={() => void sendDocs()}>
                В чат MAX
              </Button>
            )}
            <Button size="medium" variant="secondary" onClick={() => void downloadDoc("pdf")}>
              PDF
            </Button>
            <Button size="medium" variant="secondary" onClick={() => void downloadDoc("docx")}>
              DOCX
            </Button>
          </div>
        </Card>
      </Section>

      {!tripDay && !exc.cancelled && stats.going > 0 && exc.is_demo && (
        <TripDay
          excursionId={id}
          going={groups.going}
          departedAt={exc.departed_at}
          returnedAt={exc.returned_at}
          tz={exc.timezone}
          onChanged={() => void load()}
        />
      )}

      {!exc.cancelled && !exc.returned_at && <CancelTrip excursionId={id} onDone={() => void load()} />}

      <StudentSheet
        excursionId={id}
        tz={exc.timezone}
        row={selected}
        onClose={() => setSelected(null)}
        onChanged={() => void load()}
      />
    </Page>
  );
}

/** Билеты класса: кто прислал, все билеты подряд (показать на входе) и одним PDF. */
function TicketsSection({ excursionId, going, demo }: { excursionId: number; going: ParticipantRow[]; demo: boolean }) {
  const [open, setOpen] = useState(false);
  const [info, setInfo] = useState<TicketsInfo | null>(null);
  const [busy, setBusy] = useState(false);
  const [pdfUrl, setPdfUrl] = useState<string | null>(null);
  const withTicket = going.filter((p) => p.ticket_file_id).length;
  const missing = going.filter((p) => !p.ticket_file_id);

  // MAX скачивает файл только по синхронному нажатию — ссылку готовим заранее и обновляем.
  useEffect(() => {
    if (!withTicket) return;
    const refresh = () => api.ticketsPdf(excursionId).then((r) => setPdfUrl(r.url)).catch(() => setPdfUrl(null));
    refresh();
    const timer = window.setInterval(refresh, 8 * 60 * 1000);
    return () => window.clearInterval(timer);
  }, [excursionId, withTicket]);

  async function show() {
    setOpen(true);
    try {
      setInfo(await api.tickets(excursionId));
    } catch (e) {
      toast(errorText(e), "error");
    }
  }

  function pdf() {
    if (pdfUrl) downloadFile(pdfUrl, "Билеты класса.pdf");
  }

  async function toChat() {
    setBusy(true);
    try {
      const r = await api.sendTickets(excursionId);
      toast(r.message, r.delivered ? "ok" : "info");
      if (r.delivered) haptic.ok();
    } catch (e) {
      toast(errorText(e), "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Section title="Билеты">
      <Card className="cg-actions-card">
        <div className="cg-tickets-head">
          <b>Прислали билет: {withTicket} из {going.length}</b>
          <span className="cg-muted cg-small">
            Семьи покупают сами и присылают фото или чек — в чат бота или в приложении.
          </span>
        </div>
        <div className="cg-meter" aria-hidden>
          <span style={{ width: `${going.length ? Math.round((100 * withTicket) / going.length) : 0}%` }} />
        </div>
        {missing.length > 0 && (
          <p className="cg-muted cg-small">
            Ждём билет: {missing.slice(0, 4).map((p) => shortName(p.full_name)).join(", ")}
            {missing.length > 4 ? ` и ещё ${missing.length - 4}` : ""}.
          </p>
        )}
        <div className="cg-row-buttons">
          <Button size="medium" disabled={!withTicket} iconBefore={<Icon name="ticket" size={18} />}
            onClick={() => void show()}>
            Показать билеты
          </Button>
          {isInsideMax() ? (
            <Button size="medium" variant="secondary" disabled={!withTicket} loading={busy} onClick={() => void toChat()}>
              Все билеты в чат
            </Button>
          ) : (
            <Button size="medium" variant="secondary" disabled={!pdfUrl} onClick={pdf}>
              Одним PDF
            </Button>
          )}
        </div>
        {demo && <p className="cg-muted cg-small">В демо билеты присылают виртуальные родители — это картинки-образцы.</p>}
      </Card>

      <Sheet open={open} title={`Билеты класса · ${withTicket}`} onClose={() => setOpen(false)}>
        {!info ? (
          <Loader label="Загружаем билеты…" />
        ) : (
          <div className="cg-ticket-gallery">
            {info.items.map((t) => (
              <figure key={t.id} className="cg-ticket-card">
                <figcaption>
                  <b>{t.student_name}</b>
                  <span className="cg-muted cg-small">{stamp(t.uploaded_at)}</span>
                </figcaption>
                {t.is_image ? (
                  <img src={t.url} alt={`Билет: ${t.student_name}`} loading="lazy" />
                ) : (
                  <button type="button" className="cg-ticket-pdf" onClick={() => openLink(t.url)}>
                    <Icon name="doc" size={22} /> PDF-билет — открыть
                  </button>
                )}
              </figure>
            ))}
            {info.missing.length > 0 && (
              <Notice tone="warn" icon="info" title="Нет билета">
                {info.missing.join(", ")}
              </Notice>
            )}
          </div>
        )}
      </Sheet>
    </Section>
  );
}

function Fact({ icon, children }: { icon: Parameters<typeof Icon>[0]["name"]; children: React.ReactNode }) {
  return (
    <div className="cg-fact">
      <Icon name={icon} size={18} />
      <span>{children}</span>
    </div>
  );
}

function StudentGroup({
  title,
  rows,
  tz,
  onOpen,
}: {
  title: string;
  rows: ParticipantRow[];
  tz: string;
  onOpen: (p: ParticipantRow) => void;
}) {
  if (!rows.length) return null;
  return (
    <Section title={`${title} · ${rows.length}`}>
      <div className="cg-people">
        {rows.map((p) => {
          const tone = rowTone(p);
          return (
            <button key={p.student_id} type="button" className="cg-person" onClick={() => onOpen(p)}>
              <Avatar text={initials(p.full_name)} tone={tone} />
              <span className="cg-person-text">
                <b>{shortName(p.full_name)}</b>
                <span className="cg-muted">{rowSubtitle(p, tz)}</span>
              </span>
              {p.present === false && <Status tone="notgoing">Нет на сборе</Status>}
              {p.present === true && <Status tone="going">На месте</Status>}
              <Icon name="chevron" size={18} className="cg-chev" />
            </button>
          );
        })}
      </div>
    </Section>
  );
}

function StudentSheet({
  excursionId,
  tz,
  row,
  onClose,
  onChanged,
}: {
  excursionId: number;
  tz: string;
  row: ParticipantRow | null;
  onClose: () => void;
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [paper, setPaper] = useState<"APPROVED" | "REJECTED" | null>(null);
  if (!row) return <Sheet open={false} title="" onClose={onClose}>{null}</Sheet>;
  const tel = telHref(row.parent_phone);

  async function mark(status: "APPROVED" | "REJECTED") {
    if (!row) return;
    setBusy(true);
    try {
      await api.consent(excursionId, {
        student_id: row.student_id,
        status,
        source: "paper",
        parent_name: `${row.parent_name || "Законный представитель"} (бумажный бланк, отметил учитель)`,
        reason: status === "REJECTED" ? "Ответ на бумаге" : null,
      });
      toast(status === "APPROVED" ? "Отмечено: отпускают." : "Отмечено: не сможет.");
      setPaper(null);
      onChanged();
      onClose();
    } catch (e) {
      toast(errorText(e), "error");
    } finally {
      setBusy(false);
    }
  }

  async function reset() {
    if (!row) return;
    setBusy(true);
    try {
      const r = await api.resetConsent(excursionId, row.student_id, true);
      toast(r.changed ? "Отметка снята. Ученик снова в списке «Ещё не ответили»." : r.message, r.changed ? "ok" : "info");
      onChanged();
      onClose();
    } catch (e) {
      toast(errorText(e), "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Sheet open title={shortName(row.full_name)} onClose={onClose}>
      <div className="cg-sheet-status">
        <Status tone={rowTone(row)}>{rowStatus(row)}</Status>
      </div>
      <dl className="cg-dl">
        <dt>Родитель</dt>
        <dd>
          {row.parent_name || "не указан"}
          {row.parent_role ? ` · ${row.parent_role.toLowerCase()}` : ""}
        </dd>
        {row.parent_phone && (
          <>
            <dt>Телефон</dt>
            <dd>{formatPhone(row.parent_phone)}</dd>
          </>
        )}
        {row.consent_status !== "PENDING" && (
          <>
            <dt>Ответ</dt>
            <dd>
              {row.consent_status === "APPROVED" ? "Да, пойдёт" : `Нет: ${row.rejection_reason || "без причины"}`}
              <br />
              <span className="cg-muted">
                {stamp(row.signed_at, tz)} · {SOURCE_LABEL[row.signed_source ?? "api"] ?? "в ClassGo"}
              </span>
            </dd>
            {row.signed_by_max_user_id && (
              <>
                <dt>Подпись</dt>
                <dd className="cg-muted">Простая электронная подпись, ID в MAX: {row.signed_by_max_user_id}</dd>
              </>
            )}
          </>
        )}
      </dl>

      {tel && (
        <a className="cg-callbtn" href={tel}>
          <Icon name="phone" size={18} /> Позвонить родителю
        </a>
      )}

      {row.consent_status === "PENDING" ? (
        <div className="cg-manual">
          <div className="cg-actions-title">Родитель принёс бумажный бланк?</div>
          <p className="cg-muted cg-small">
            Отметьте ответ по бланку. В реестре будет видно, что согласие бумажное. Звонок или устный ответ бланк
            не заменяют.
          </p>
          <div className="cg-row-buttons">
            <Button size="medium" disabled={busy} onClick={() => setPaper("APPROVED")}>Бланк: отпускают</Button>
            <Button size="medium" variant="secondary" disabled={busy} onClick={() => setPaper("REJECTED")}>
              Бланк: не сможет
            </Button>
          </div>
          {paper && (
            <div className="cg-inline-confirm">
              <p>
                {paper === "APPROVED" ? "Отпускают" : "Не сможет"} — по бумажному бланку с подписью родителя.
                Бланк сохраните: в реестре будет пометка «бумажное согласие».
              </p>
              <div className="cg-row-buttons">
                <Button size="medium" loading={busy} onClick={() => void mark(paper)}>Да, отметить</Button>
                <Button size="medium" variant="secondary" disabled={busy} onClick={() => setPaper(null)}>Отмена</Button>
              </div>
            </div>
          )}
        </div>
      ) : (
        <button type="button" className="cg-link cg-danger" disabled={busy} onClick={() => void reset()}>
          Снять отметку
        </button>
      )}
    </Sheet>
  );
}

function timeOf(value: string | null, tz: string): string {
  return stamp(value, tz).split(" в ")[1] ?? "";
}

function TripDay({
  excursionId,
  going,
  departedAt,
  returnedAt,
  tz,
  onChanged,
}: {
  excursionId: number;
  going: ParticipantRow[];
  departedAt: string | null;
  returnedAt: string | null;
  tz: string;
  onChanged: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [ask, setAsk] = useState<"departed" | "returned" | null>(null);
  const present = going.filter((p) => p.present === true).length;
  const absent = going.filter((p) => p.present === false).length;
  const unmarked = going.length - present - absent;

  async function mark(studentId: number, value: boolean | null) {
    try {
      await api.attendance(excursionId, studentId, value);
      haptic.tap();
      onChanged();
    } catch (e) {
      toast(errorText(e), "error");
    }
  }

  async function restPresent() {
    setBusy("rest");
    try {
      for (const p of going.filter((x) => x.present == null)) {
        await api.attendance(excursionId, p.student_id, true);
      }
      haptic.ok();
      onChanged();
    } catch (e) {
      toast(errorText(e), "error");
    } finally {
      setBusy(null);
    }
  }

  async function milestone(kind: "departed" | "returned") {
    setBusy(kind);
    try {
      const r = await api.milestone(excursionId, kind);
      haptic.ok();
      const head = kind === "departed" ? "Отмечено: группа выехала." : "Отмечено: группа вернулась.";
      toast(r.notified ? `${head} Написали родителям в MAX: ${r.notified}.` : head);
      setAsk(null);
      onChanged();
    } catch (e) {
      toast(errorText(e), "error");
    } finally {
      setBusy(null);
    }
  }

  return (
    <Section title="День выезда">
      <Card className="cg-actions-card">
        <p className="cg-muted">
          Отметьте, кто пришёл. Родители получат в MAX два сообщения: «Группа выехала» и «Группа вернулась».
        </p>
        <div className="cg-tripday">
          <span><b>{present}</b> на месте</span>
          <span><b>{absent}</b> нет на сборе</span>
          <span><b>{unmarked}</b> не отмечены</span>
        </div>
        <Button size="medium" stretched variant="secondary" iconBefore={<Icon name="check" size={18} />}
          onClick={() => setOpen(true)}>
          Перекличка
        </Button>
        <div className="cg-row-buttons">
          <Button size="medium" variant={departedAt ? "secondary" : "primary"} loading={busy === "departed"}
            disabled={Boolean(departedAt)} onClick={() => setAsk("departed")}>
            {departedAt ? `Выехали в ${timeOf(departedAt, tz)}` : "Группа выехала"}
          </Button>
          <Button size="medium" variant="secondary" loading={busy === "returned"}
            disabled={!departedAt || Boolean(returnedAt)} onClick={() => setAsk("returned")}>
            {returnedAt ? `Вернулись в ${timeOf(returnedAt, tz)}` : "Группа вернулась"}
          </Button>
        </div>
      </Card>

      <Confirm open={ask === "departed"} title="Группа выехала?" yes="Да, сообщить родителям" busy={busy === "departed"}
        onYes={() => void milestone("departed")} onClose={() => setAsk(null)}>
        <p>Родители {going.length} {plural(going.length, "ученика", "учеников", "учеников")} получат сообщение в MAX.</p>
        {absent > 0 && <p>Родителям {absent} отсутствующих напишем, что ребёнок не пришёл на сбор.</p>}
        {unmarked > 0 && (
          <p className="cg-muted">
            Не отмечены: {unmarked}. Их родители получат просто «Группа выехала». Можно сначала провести перекличку.
          </p>
        )}
      </Confirm>
      <Confirm open={ask === "returned"} title="Группа вернулась?" yes="Да, сообщить родителям" busy={busy === "returned"}
        onYes={() => void milestone("returned")} onClose={() => setAsk(null)}>
        <p>Родители {going.length - absent} {plural(going.length - absent, "ученика", "учеников", "учеников")} получат: группа вернулась, можно встречать.</p>
      </Confirm>

      <Sheet open={open} title="Перекличка" onClose={() => setOpen(false)}>
        <p className="cg-muted cg-small">
          Отметьте, кто пришёл на сбор. Родители тех, кого нет, узнают об этом, когда вы нажмёте «Группа выехала».
        </p>
        <div className="cg-people">
          {going.map((p) => (
            <div key={p.student_id} className="cg-person cg-rollrow">
              <span className="cg-person-text"><b>{shortName(p.full_name)}</b></span>
              <button type="button" className={`cg-roll ${p.present === true ? "on" : ""}`} aria-pressed={p.present === true}
                onClick={() => void mark(p.student_id, p.present === true ? null : true)}>
                Есть
              </button>
              <button type="button" className={`cg-roll no ${p.present === false ? "on" : ""}`}
                aria-pressed={p.present === false}
                onClick={() => void mark(p.student_id, p.present === false ? null : false)}>
                Нет
              </button>
            </div>
          ))}
        </div>
        <div className="cg-stack cg-mt">
          {unmarked > 0 && (present > 0 || absent > 0) && (
            <Button size="large" stretched variant="secondary" loading={busy === "rest"} onClick={() => void restPresent()}>
              {unmarked === 1 ? "Последний — на месте" : `Остальные на месте (${unmarked})`}
            </Button>
          )}
          <Button size="large" stretched onClick={() => setOpen(false)}>Готово</Button>
        </div>
      </Sheet>
    </Section>
  );
}

function CancelTrip({ excursionId, onDone }: { excursionId: number; onDone: () => void }) {
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);

  async function cancel() {
    setBusy(true);
    try {
      const r = await api.cancelTrip(excursionId);
      toast(r.notified ? `Выезд отменён. Написали родителям: ${r.notified}.` : "Выезд отменён.", "info");
      setConfirming(false);
      onDone();
    } catch (e) {
      toast(errorText(e), "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <button type="button" className="cg-link cg-danger cg-center-link" onClick={() => setConfirming(true)}>
        Отменить выезд
      </button>
      <Sheet open={confirming} title="Отменить выезд?" onClose={() => setConfirming(false)}>
        <p className="cg-muted">
          Родители получат сообщение в MAX: выезд отменён, ребёнок остаётся на уроках. Отменённый выезд не вернуть —
          только создать заново.
        </p>
        <div className="cg-stack">
          <Button size="large" stretched variant="destructive" loading={busy} onClick={() => void cancel()}>
            Да, отменить выезд
          </Button>
          <Button size="large" stretched variant="secondary" disabled={busy} onClick={() => setConfirming(false)}>
            Не отменять
          </Button>
        </div>
      </Sheet>
    </>
  );
}
