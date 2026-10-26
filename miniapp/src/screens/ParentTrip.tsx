import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@maxhub/max-ui";
import { api, type ParentChild, type ParentTrip as Trip } from "../api";
import { dayLong, deadlineText, firstName, formatPhone, isPast, money, parseDay, stamp } from "../format";
import { haptic, openLink, telHref } from "../max";
import { errorText, toast, useAppState } from "../store";
import { Card, Hero, Icon, Loader, Notice, Page, Sheet, Tag } from "../ui";
import { Terms } from "./Terms";

// Без медицинских подробностей: сведения о здоровье — особая категория ПДн (152-ФЗ, ст. 10).
const REASONS = ["Личные причины", "Семейные обстоятельства", "Другие планы"];

function pushkinNote(trip: Trip): string {
  if (!trip.is_pushkin_card) return "";
  if (trip.pushkin_ok === true) return " Можно «Пушкинской картой» ребёнка.";
  if (trip.pushkin_ok === null) return " Если ребёнку уже 14, можно «Пушкинской картой».";
  return "";
}

/** Карточка выезда для родителя: ответ в одно касание, квитанция, «Изменить ответ», контакт учителя. */
export function ParentTripView({
  child,
  trip,
  onChanged,
  full = false,
}: {
  child: ParentChild;
  trip: Trip;
  onChanged: () => Promise<void> | void;
  full?: boolean;
}) {
  const [busy, setBusy] = useState(false);
  const [askReason, setAskReason] = useState(false);
  const [changing, setChanging] = useState(false);
  const name = firstName(child.student_name);
  const pending = trip.consent_status === "PENDING";
  const late = isPast(trip.deadline);
  const tel = telHref(child.teacher_phone);

  async function answer(status: "APPROVED" | "REJECTED", reason?: string) {
    setBusy(true);
    try {
      if (!pending) {
        // Новый ответ вместо прежнего: прежний действует, пока родитель не выбрал другой.
        if (status === trip.consent_status && (status === "APPROVED" || reason === trip.rejection_reason)) {
          toast("Ответ не изменился.", "info");
          setChanging(false);
          setAskReason(false);
          return;
        }
        const reset = await api.resetConsent(trip.excursion_id, child.student_id);
        if (!reset.changed) {
          toast(reset.message, "info");
          setChanging(false);
          setAskReason(false);
          await onChanged();
          return;
        }
      }
      const r = await api.consent(trip.excursion_id, {
        student_id: child.student_id,
        status,
        reason: reason ?? null,
        source: "miniapp",
        parent_name: child.parent_name,
      });
      if (r.changed) haptic.ok();
      else toast(r.message, "info");
      if (r.changed && !pending) toast("Ответ изменён. Учитель видит новый.");
      setAskReason(false);
      setChanging(false);
      await onChanged();
    } catch (e) {
      toast(errorText(e), "error");
    } finally {
      setBusy(false);
    }
  }

  const weekday = (() => {
    const d = parseDay(trip.event_date);
    return Boolean(d && d.getDay() > 0 && d.getDay() < 6);
  })();

  return (
    <Card className={`cg-ptrip ${pending && !trip.started && !trip.cancelled ? "pending" : ""}`}>
      <div className="cg-ptrip-head">
        <div>
          <div className="cg-overline">{dayLong(trip.event_date)}</div>
          <div className="cg-ptrip-title">{trip.title}</div>
          <div className="cg-muted">{trip.location_name}</div>
        </div>
      </div>

      <div className="cg-facts-inline">
        <div className="cg-fact">
          <Icon name="clock" size={18} />
          <span>
            Сбор в <b>{trip.gathering_time ?? "—"}</b> {trip.meeting_point}
            {trip.return_time && <>, вернёмся к <b>{trip.return_time}</b></>}
          </span>
        </div>
        <div className="cg-fact">
          <Icon name="ticket" size={18} />
          <span>
            {trip.ticket_price > 0 ? (
              <>
                Билет <b>{money(trip.ticket_price)}</b> — покупаете сами, на сайте или в кассе.
                {pushkinNote(trip)} Школа деньги не собирает.
              </>
            ) : (
              <>Вход бесплатный.</>
            )}
          </span>
        </div>
        {full && (
          <div className="cg-fact">
            <Icon name="pin" size={18} />
            <span>{trip.address || trip.location_name}</span>
          </div>
        )}
        <div className="cg-fact">
          <Icon name="users" size={18} />
          <span>Ведёт: {trip.responsible_teacher || child.teacher_name || "классный руководитель"}</span>
        </div>
      </div>

      {trip.cancelled && (
        <Notice tone="warn" icon="info" title="Выезд отменён">
          {weekday ? `${name} учится по расписанию. ` : ""}Если вы уже купили билет — вернуть его можно там, где
          покупали.
        </Notice>
      )}

      {pending && !trip.started && !trip.cancelled && (
        <>
          <div className="cg-question">
            {name} пойдёт на выезд?
            {trip.deadline && (
              <span className={late ? "cg-late" : "cg-muted"}>
                {late
                  ? "Срок прошёл, но ответить ещё можно."
                  : `Ответьте до ${deadlineText(trip.deadline, trip.timezone)}.`}
              </span>
            )}
          </div>
          <div className="cg-stack">
            <Button size="large" stretched loading={busy && !askReason} onClick={() => void answer("APPROVED")}
              iconBefore={<Icon name="check" size={22} />}>
              Да, {name} пойдёт
            </Button>
            <Button size="large" stretched variant="secondary" disabled={busy} onClick={() => setAskReason(true)}>
              Нет, {name} не пойдёт
            </Button>
          </div>
          <p className="cg-note">
            Ответ кнопкой — ваша подпись под согласием. Платить здесь ничего не нужно. Удобнее на бумаге? Бланк —
            у классного руководителя.
          </p>
        </>
      )}

      {pending && trip.started && !trip.cancelled && (
        <Notice tone="warn" icon="clock" title="Выезд уже начался">
          Ответить уже нельзя. Если {name} всё же едет — позвоните классному руководителю.
        </Notice>
      )}

      {trip.consent_status === "APPROVED" && !trip.cancelled && (
        <div className="cg-receipt ok">
          <Icon name="check" size={22} />
          <div>
            <b>Готово: {name} идёт на выезд.</b>
            <span>Подпись записана {stamp(trip.signed_at, trip.timezone)}. Учитель уже видит ответ.</span>
          </div>
        </div>
      )}

      {trip.consent_status === "REJECTED" && !trip.cancelled && (
        <div className="cg-receipt no">
          <Icon name="x" size={22} />
          <div>
            <b>Вы ответили: {name} не пойдёт.</b>
            <span>
              {trip.rejection_reason || "Без причины"} · {stamp(trip.signed_at, trip.timezone)}. Учитель уже видит ответ.
            </span>
          </div>
        </div>
      )}

      {trip.consent_status === "APPROVED" && trip.ticket_price > 0 && !trip.cancelled && !trip.returned && (
        <TicketStep child={child} trip={trip} onChanged={onChanged} />
      )}

      {((!pending && trip.can_change) || tel) && (
        <div className="cg-ptrip-links">
          {!pending && trip.can_change && (
            <button type="button" className="cg-link" disabled={busy} onClick={() => setChanging(true)}>
              Изменить ответ
            </button>
          )}
          {tel && (
            <a className="cg-link cg-linkrow" href={tel}>
              <Icon name="phone" size={16} /> Позвонить учителю · {formatPhone(child.teacher_phone)}
            </a>
          )}
        </div>
      )}

      <Sheet open={changing && !askReason} title="Изменить ответ" onClose={() => setChanging(false)}>
        <p className="cg-muted">
          Сейчас: {trip.consent_status === "APPROVED" ? `${name} идёт на выезд` : `${name} не пойдёт`}. Пока вы не
          выберете новый ответ, действует прежний.
        </p>
        <div className="cg-stack">
          {trip.consent_status !== "APPROVED" && (
            <Button size="large" stretched loading={busy} onClick={() => void answer("APPROVED")}
              iconBefore={<Icon name="check" size={22} />}>
              Да, {name} пойдёт
            </Button>
          )}
          <Button size="large" stretched variant="secondary" disabled={busy} onClick={() => setAskReason(true)}>
            {trip.consent_status === "REJECTED" ? "Указать другую причину" : `Нет, ${name} не пойдёт`}
          </Button>
          <Button size="large" stretched variant="secondary" disabled={busy} onClick={() => setChanging(false)}>
            Оставить как есть
          </Button>
        </div>
      </Sheet>

      <Sheet open={askReason} title={`Почему ${name} не пойдёт?`} onClose={() => setAskReason(false)}>
        <p className="cg-muted">Учитель увидит только выбранный вариант. Подробности не нужны.</p>
        <div className="cg-stack">
          {REASONS.map((r) => (
            <Button key={r} size="large" stretched variant="secondary" disabled={busy} onClick={() => void answer("REJECTED", r)}>
              {r}
            </Button>
          ))}
        </div>
      </Sheet>
    </Card>
  );
}

/** Билет: семья покупает сама и присылает фото, PDF или чек — учитель видит покупку и билеты класса. */
function TicketStep({ child, trip, onChanged }: { child: ParentChild; trip: Trip; onChanged: () => Promise<void> | void }) {
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const has = Boolean(trip.ticket_file_id);

  async function upload(file: File | undefined) {
    if (!file) return;
    setBusy(true);
    try {
      await api.uploadTicket(trip.excursion_id, child.student_id, file);
      haptic.ok();
      toast("Билет получен. Учитель видит его и покажет на входе.");
      await onChanged();
    } catch (e) {
      toast(errorText(e), "error");
    } finally {
      setBusy(false);
      if (input.current) input.current.value = "";
    }
  }

  async function open() {
    try {
      const info = await api.tickets(trip.excursion_id);
      const mine = info.items.find((t) => t.student_id === child.student_id);
      if (mine) openLink(mine.url);
    } catch (e) {
      toast(errorText(e), "error");
    }
  }

  return (
    <div className={`cg-ticketstep ${has ? "done" : ""}`}>
      <div className="cg-actions-title">
        <Icon name="ticket" size={18} /> {has ? "Билет получен" : "Билет"}
      </div>
      {has ? (
        <p className="cg-muted">
          Прислан {stamp(trip.ticket_uploaded_at, trip.timezone)}. Учитель видит его и покажет билеты класса на входе.
        </p>
      ) : (
        <>
          <p className="cg-muted">
            Купили билет? Пришлите его фото или PDF — учитель увидит покупку и покажет билеты класса на входе.
          </p>
          <p className="cg-muted cg-small">
            Есть только чек? Подойдёт скриншот — закройте номер карты, баланс и другие покупки. Если трудно оплатить —
            скажите классному руководителю.
          </p>
        </>
      )}
      <input ref={input} type="file" accept="image/*,application/pdf" hidden
        onChange={(e) => void upload(e.target.files?.[0])} />
      <div className="cg-row-buttons">
        <Button size="medium" variant={has ? "secondary" : "primary"} loading={busy}
          iconBefore={<Icon name="upload" size={18} />} onClick={() => input.current?.click()}>
          {has ? "Отправить другой файл" : "Отправить фото билета"}
        </Button>
        {has ? (
          <Button size="medium" variant="secondary" onClick={() => void open()}>Посмотреть</Button>
        ) : (
          trip.ticket_sale_url && (
            <Button size="medium" variant="secondary" onClick={() => openLink(trip.ticket_sale_url)}>
              Купить на сайте
            </Button>
          )
        )}
      </div>
      {!has && <p className="cg-muted cg-small">Можно и проще: отправьте фото билета в чат с ботом.</p>}
    </div>
  );
}

export default function ParentTrip({ excursionId, studentId }: { excursionId: number; studentId: number }) {
  const { me } = useAppState();
  const [child, setChild] = useState<ParentChild | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!me?.user_id) return;
    try {
      const ctx = await api.parentContext(me.user_id);
      const c = ctx.children.find((x) => x.student_id === studentId) ?? null;
      setChild(c);
      setError(c ? null : "Этого выезда нет среди выездов ваших детей.");
    } catch (e) {
      setError(errorText(e));
    }
  }, [me?.user_id, studentId]);

  useEffect(() => {
    void load();
  }, [load]);

  const trip = child?.excursions.find((e) => e.excursion_id === excursionId);
  if (!child || !trip) {
    return (
      <Page>{error ? <Notice tone="error" icon="info" title="Не удалось открыть выезд">{error}</Notice> : <Loader />}</Page>
    );
  }
  if (me && !me.terms_accepted && trip.consent_status === "PENDING" && !trip.cancelled) {
    return <Terms children={[child]} />;
  }
  return (
    <Page>
      <Hero
        overline={`${child.student_name} · ${child.class_title}`}
        title="Приглашение на выезд"
        aside={child.is_demo ? <Tag tone="demo">демо</Tag> : undefined}
      />
      <ParentTripView child={child} trip={trip} onChanged={load} full />
    </Page>
  );
}
