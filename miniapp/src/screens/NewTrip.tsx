import { useEffect, useMemo, useState } from "react";
import { Button, Input } from "@maxhub/max-ui";
import { api, type CultureEvent, type SchoolClass } from "../api";
import { addDays, dayLong, dayShort, firstName, isoDate, money, parseDay, plural, quote } from "../format";
import { haptic, setClosingConfirmation } from "../max";
import { errorText, replace, toast } from "../store";
import { Card, Chip, Empty, Field, Hero, Icon, Loader, Notice, Page, Section, Tag } from "../ui";

type Filter = "all" | "free" | "pushkin";
type Transport = "walk" | "bus" | "other";

const AGE_ORDER = ["0+", "6+", "12+", "16+", "18+"];
const TRANSPORT_LABEL: Record<Exclude<Transport, "other">, string> = {
  walk: "пешком и на общественном транспорте",
  bus: "заказной автобус (организованная перевозка)",
};

/** Какой возрастной ценз подходит классу: 1–4 → до 6+, 5–8 → до 12+, 9–11 → до 16+. */
function maxAgeForGrade(grade: string): string {
  const g = parseInt(grade, 10);
  if (!g) return "16+";
  if (g <= 4) return "6+";
  if (g <= 8) return "12+";
  return "16+";
}

function gradeOf(klass: SchoolClass | undefined): string {
  return klass ? klass.title.replace(/\D/g, "") : "";
}

/** За N рабочих дней до даты (суббота и воскресенье не считаются). */
function workdaysBefore(day: Date, n: number): Date {
  let d = new Date(day);
  let left = n;
  while (left > 0) {
    d = addDays(d, -1);
    if (d.getDay() !== 0 && d.getDay() !== 6) left -= 1;
  }
  return d;
}

export default function NewTrip({ classId }: { classId?: number }) {
  const [step, setStep] = useState(1);
  const [classes, setClasses] = useState<SchoolClass[] | null>(null);
  const [events, setEvents] = useState<CultureEvent[] | null>(null);
  const [selectedClass, setSelectedClass] = useState<number | null>(classId ?? null);
  const [filter, setFilter] = useState<Filter>("all");
  const [byAge, setByAge] = useState(true);
  const [query, setQuery] = useState("");
  const [event, setEvent] = useState<CultureEvent | null>(null);
  const [custom, setCustom] = useState(false);
  const [title, setTitle] = useState("");
  const [venue, setVenue] = useState("");
  const [address, setAddress] = useState("");
  const [price, setPrice] = useState("");
  const [ticketUrl, setTicketUrl] = useState("");
  const [date, setDate] = useState("");
  const [gathering, setGathering] = useState("09:00");
  const [returning, setReturning] = useState("13:00");
  const [meeting, setMeeting] = useState("у главного входа школы");
  const [escorts, setEscorts] = useState("");
  const [transport, setTransport] = useState<Transport>("walk");
  const [transportOther, setTransportOther] = useState("");
  const [deadlineDate, setDeadlineDate] = useState("");
  const [deadlineTime, setDeadlineTime] = useState("18:00");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([api.myClasses(), api.events()])
      .then(([c, e]) => {
        setClasses(c);
        setEvents(e);
        if (!classId && c.length) setSelectedClass(c[0].id);
      })
      .catch((e) => setError(errorText(e)));
  }, [classId]);

  // Пока мастер не закончен, случайное закрытие спросит подтверждение.
  useEffect(() => {
    setClosingConfirmation(step > 1 || event !== null || custom);
    return () => setClosingConfirmation(false);
  }, [step, event, custom]);

  const klass = classes?.find((c) => c.id === selectedClass);
  const maxAge = maxAgeForGrade(gradeOf(klass));

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (events ?? [])
      .filter((e) => (filter === "free" ? e.is_free : filter === "pushkin" ? e.pushkin_eligible : true))
      .filter((e) => !byAge || AGE_ORDER.indexOf(e.age_rating) <= AGE_ORDER.indexOf(maxAge))
      .filter((e) => !q || `${e.title} ${e.venue}`.toLowerCase().includes(q))
      .sort((a, b) => (a.event_date ?? "").localeCompare(b.event_date ?? ""));
  }, [events, filter, byAge, query, maxAge]);

  function defaultDeadline(day: string) {
    const eventDay = parseDay(day) ?? addDays(new Date(), 7);
    const dl = workdaysBefore(eventDay, 3);
    const tomorrow = addDays(new Date(), 1);
    setDeadlineDate(isoDate(dl > tomorrow ? dl : tomorrow));
  }

  function pick(e: CultureEvent) {
    haptic.tap();
    setCustom(false);
    setEvent(e);
    const day = e.event_date ?? isoDate(addDays(new Date(), 7));
    setDate(day);
    defaultDeadline(day);
  }

  function pickCustom() {
    haptic.tap();
    setEvent(null);
    setCustom(true);
    const day = isoDate(addDays(new Date(), 10));
    setDate(day);
    defaultDeadline(day);
  }

  const connected = klass ? klass.parents_connected : 0;
  const total = klass ? klass.students.length : 0;
  // Превью на примере первого ученика из списка — так же, как придёт настоящей семье.
  const sampleKid = klass?.students[0]?.full_name ?? "";
  const kidName = sampleKid ? firstName(sampleKid) : "Имя";
  const todayIso = isoDate(new Date());
  const deadlineOk = deadlineDate >= todayIso && (!date || deadlineDate <= date);
  const timesOk = !gathering || !returning || returning > gathering;
  const eventDay = parseDay(date);
  const tight = Boolean(eventDay && deadlineDate && deadlineDate > isoDate(workdaysBefore(eventDay, 2)));
  const customOk = !custom || Boolean(title.trim() && venue.trim());
  const transportText = transport === "other" ? transportOther.trim() : TRANSPORT_LABEL[transport];
  const step2Ok = Boolean(date && deadlineOk && timesOk && customOk && escorts.trim() && transportText);

  const shown = custom
    ? {
        title: title.trim() || "Свой выезд",
        venue: venue.trim(),
        price: Number(price.replace(",", ".")) || 0,
      }
    : event
      ? { title: event.title, venue: event.venue, price: event.price }
      : null;

  async function submit() {
    if (!klass || !shown) return;
    setBusy(true);
    setError(null);
    try {
      // Срок — по часам школы: сервер переводит его в UTC по поясу класса.
      const deadline = `${deadlineDate}T${deadlineTime || "18:00"}:00`;
      const common = {
        class_id: klass.id,
        event_date: date,
        gathering_time: gathering,
        return_time: returning,
        meeting_point: meeting.trim() || "у главного входа школы",
        escorts: escorts.trim(),
        transport: transportText,
        deadline,
      };
      const trip = await api.createTrip(
        custom
          ? {
              ...common,
              title: shown.title,
              location_name: venue.trim(),
              address: address.trim(),
              ticket_price: shown.price,
              ticket_sale_url: ticketUrl.trim(),
              is_pushkin_card: false,
            }
          : { ...common, culture_event_id: event!.id },
      );
      setClosingConfirmation(false);
      haptic.ok();
      toast(
        klass.is_demo
          ? "Приглашения отправлены. Демо-родители ответят за минуту."
          : `Приглашения отправлены ${connected} ${plural(connected, "родителю", "родителям", "родителям")} в MAX.`,
      );
      replace({ name: "trip", id: trip.id });
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  if (!classes || !events) {
    return (
      <Page>
        {error ? <Notice tone="error" icon="info" title="Не удалось открыть афишу">{error}</Notice> : <Loader />}
      </Page>
    );
  }

  const stepTitle = ["Куда идём?", "Когда и как?", "Проверьте приглашение"][step - 1];

  const bottom =
    step === 1 ? (
      <Button size="large" stretched disabled={!(event || custom) || !klass} onClick={() => setStep(2)}>
        {event || custom ? "Далее" : "Выберите, куда идём"}
      </Button>
    ) : step === 2 ? (
      <div className="cg-bottom-pair">
        <Button size="large" variant="secondary" onClick={() => setStep(1)}>Назад</Button>
        <Button size="large" stretched disabled={!step2Ok} onClick={() => setStep(3)}>
          Далее
        </Button>
      </div>
    ) : (
      <div className="cg-bottom-pair">
        <Button size="large" variant="secondary" onClick={() => setStep(2)} disabled={busy}>Назад</Button>
        <Button size="large" stretched loading={busy} onClick={() => void submit()}>
          Отправить родителям
        </Button>
      </div>
    );

  return (
    <Page bottom={bottom}>
      <Hero overline={`Новый выезд · шаг ${step} из 3`} title={stepTitle} />
      <div className="cg-steps" aria-hidden="true">
        {[1, 2, 3].map((n) => (
          <span key={n} className={n <= step ? "on" : ""} />
        ))}
      </div>

      {error && <Notice tone="error" icon="info" title="Не получилось создать выезд">{error}</Notice>}

      {step === 1 && (
        <>
          {classes.length > 1 && (
            <Section title="Класс">
              <div className="cg-chips">
                {classes.map((c) => (
                  <Chip key={c.id} active={c.id === selectedClass} onClick={() => setSelectedClass(c.id)}>
                    {c.title}
                    {c.is_demo ? " (демо)" : ""}
                  </Chip>
                ))}
              </div>
            </Section>
          )}
          <Card className={`cg-event cg-custom ${custom ? "selected" : ""}`} onClick={pickCustom}>
            <div className="cg-event-head">
              <span className="cg-event-title">
                <Icon name="plus" size={18} /> Свой вариант
              </span>
              <span className={`cg-radio ${custom ? "on" : ""}`} aria-hidden="true">
                {custom && <Icon name="check" size={14} />}
              </span>
            </div>
            <div className="cg-muted">Музей, театр, парк, завод — название и место укажете дальше.</div>
          </Card>
          <Section title="Или из афиши Казани">
            <Input
              mode="contrast"
              placeholder="Музей, театр, выставка…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              withClearButton
              iconBefore={<Icon name="search" size={18} />}
            />
            <div className="cg-chips cg-mt">
              <Chip active={filter === "all"} onClick={() => setFilter("all")}>Все</Chip>
              <Chip active={filter === "free"} onClick={() => setFilter("free")}>Бесплатные</Chip>
              <Chip active={filter === "pushkin"} onClick={() => setFilter("pushkin")}>Пушкинская карта</Chip>
              <Chip active={byAge} onClick={() => setByAge((v) => !v)}>Для {klass?.title ?? "класса"}: до {maxAge}</Chip>
            </div>
          </Section>
          {visible.length === 0 && (
            <Empty icon="calendar" title="Ничего не нашлось" text="Снимите фильтр, измените запрос или выберите «Свой вариант»." />
          )}
          <div className="cg-list">
            {visible.map((e) => {
              const active = event?.id === e.id;
              return (
                <Card key={e.id} className={`cg-event ${active ? "selected" : ""}`} onClick={() => pick(e)}>
                  <div className="cg-event-head">
                    <span className="cg-event-title">{e.title}</span>
                    <span className={`cg-radio ${active ? "on" : ""}`} aria-hidden="true">
                      {active && <Icon name="check" size={14} />}
                    </span>
                  </div>
                  <div className="cg-muted">{e.venue}</div>
                  <div className="cg-tags">
                    <Tag>{dayShort(e.event_date)}</Tag>
                    {e.is_free ? <Tag tone="free">бесплатно</Tag> : <Tag>{money(e.price)}</Tag>}
                    {e.pushkin_eligible && <Tag tone="pushkin">Пушкинская карта 14+</Tag>}
                    <Tag>{e.age_rating}</Tag>
                    <Tag>{e.duration_min} мин</Tag>
                  </div>
                  {active && e.description && <p className="cg-event-desc">{e.description}</p>}
                </Card>
              );
            })}
          </div>
          <p className="cg-fineprint">
            Афиша — демо-данные PRO.Культура.РФ по Казани. В рабочей версии она обновляется из открытых данных
            Минкультуры.
          </p>
        </>
      )}

      {step === 2 && shown && (
        <>
          {custom ? (
            <Section title="Куда идём">
              <div className="cg-form">
                <Field label="Название">
                  <input className="cg-input" value={title} placeholder="Экскурсия в музей…" onChange={(e) => setTitle(e.target.value)} />
                </Field>
                <Field label="Место">
                  <input className="cg-input" value={venue} placeholder="Национальный музей РТ" onChange={(e) => setVenue(e.target.value)} />
                </Field>
                <Field label="Адрес">
                  <input className="cg-input" value={address} placeholder="г. Казань, ул. …" onChange={(e) => setAddress(e.target.value)} />
                </Field>
                <div className="cg-form-row">
                  <Field label="Билет, ₽" hint="0 — бесплатно">
                    <input className="cg-input" inputMode="numeric" value={price} placeholder="0"
                      onChange={(e) => setPrice(e.target.value.replace(/[^\d.,]/g, ""))} />
                  </Field>
                  <Field label="Сайт для билетов">
                    <input className="cg-input" value={ticketUrl} placeholder="Необязательно" onChange={(e) => setTicketUrl(e.target.value)} />
                  </Field>
                </div>
              </div>
            </Section>
          ) : (
            <Card className="cg-picked">
              <b>{event!.title}</b>
              <span className="cg-muted">{event!.venue}</span>
            </Card>
          )}
          <Section>
            <div className="cg-form">
              <Field label="Дата выезда">
                <input className="cg-input" type="date" value={date} min={todayIso} onChange={(e) => setDate(e.target.value)} />
              </Field>
              <div className="cg-form-row">
                <Field label="Сбор">
                  <input className="cg-input" type="time" value={gathering} onChange={(e) => setGathering(e.target.value)} />
                </Field>
                <Field label="Вернёмся к">
                  <input className="cg-input" type="time" value={returning} onChange={(e) => setReturning(e.target.value)} />
                </Field>
              </div>
              {!timesOk && <p className="cg-error">Время возвращения должно быть позже сбора.</p>}
              <Field label="Где собираемся">
                <input className="cg-input" value={meeting} onChange={(e) => setMeeting(e.target.value)} />
              </Field>
              <div className="cg-field">
                <span className="cg-field-label">Как добираемся</span>
                <div className="cg-chips">
                  <Chip active={transport === "walk"} onClick={() => setTransport("walk")}>Пешком / общественный транспорт</Chip>
                  <Chip active={transport === "bus"} onClick={() => setTransport("bus")}>Заказной автобус</Chip>
                  <Chip active={transport === "other"} onClick={() => setTransport("other")}>Другое</Chip>
                </div>
                {transport === "other" && (
                  <input className="cg-input cg-mt" value={transportOther} placeholder="Например: электричка" onChange={(e) => setTransportOther(e.target.value)} />
                )}
                {transport === "bus" && (
                  <span className="cg-field-hint">
                    За 24 часа нужно уведомить Госавтоинспекцию (постановление Правительства РФ № 680). Это будет в
                    приказе, а в список добавится возраст детей.
                  </span>
                )}
              </div>
              <Field label="Помощник руководителя группы" hint="Обязательно. ФИО и должность — попадёт в приказ.">
                <input className="cg-input" value={escorts} placeholder="Петрова О. И., педагог-организатор" onChange={(e) => setEscorts(e.target.value)} />
              </Field>
              <div className="cg-form-row">
                <Field label="Ответить до">
                  <input className="cg-input" type="date" value={deadlineDate} min={todayIso} max={date || undefined}
                    onChange={(e) => setDeadlineDate(e.target.value)} />
                </Field>
                <Field label="Время">
                  <input className="cg-input" type="time" value={deadlineTime} onChange={(e) => setDeadlineTime(e.target.value)} />
                </Field>
              </div>
              {!deadlineOk && <p className="cg-error">Срок ответа — не раньше сегодня и не позже дня выезда.</p>}
              {deadlineOk && tight && (
                <p className="cg-warnline">Оставьте 2–3 рабочих дня до выезда: подписать приказ и провести инструктаж.</p>
              )}
            </div>
          </Section>
          <Notice tone="info" icon="bell">
            Кто не ответит, тому ClassGo сам напомнит — до трёх раз перед сроком. Ночью не пишем.
          </Notice>
        </>
      )}

      {step === 3 && shown && klass && (
        <>
          <Section title="Так увидят родители">
            <div className="cg-preview">
              <div className="cg-preview-bubble">
                <b>{sampleKid || "ФИО ребёнка"} ({klass.title}) — приглашение на выезд</b>
                <p>
                  Здравствуйте! Классный руководитель {klass.teacher_name || "класса"}
                  {klass.school_name ? `, ${klass.school_name},` : ""} зовёт класс:
                  <br />
                  <br />
                  {quote(shown.title)}
                  {shown.venue && (
                    <>
                      <br />
                      Где: {shown.venue}
                    </>
                  )}
                  <br />
                  Когда: {dayShort(date)}, сбор в {gathering} {meeting}, вернёмся к {returning}
                  <br />
                  {shown.price > 0
                    ? `Билет: ${money(shown.price)} — покупаете сами, на сайте или в кассе. Школа деньги не собирает.`
                    : "Вход бесплатный."}
                </p>
                <p className="cg-muted">
                  {deadlineDate ? `Ответьте до ${dayLong(deadlineDate).split(", ")[1]}, ${deadlineTime}. ` : ""}Ответ кнопкой — ваша
                  подпись под согласием. Платить в чате ничего не нужно.
                  <br />
                  Вопросы — {klass.teacher_name || "классный руководитель"}
                  {klass.teacher_phone ? `, ${klass.teacher_phone}` : ""}.
                </p>
              </div>
              <div className="cg-preview-buttons">
                <span>✅ Да, {kidName} пойдёт</span>
                <span>Нет, {kidName} не пойдёт</span>
                <span>Подробнее</span>
              </div>
            </div>
          </Section>
          <Card className="cg-sendto">
            <div className="cg-fact">
              <Icon name="chat" size={18} />
              <span>
                Приглашение в MAX получат <b>{connected}</b> из {total} {plural(total, "семьи", "семей", "семей")}.
              </span>
            </div>
            {total - connected > 0 && (
              <div className="cg-fact">
                <Icon name="share" size={18} />
                <span>
                  {total - connected} {plural(total - connected, "семья ещё не подключена", "семьи ещё не подключены", "семей ещё не подключены")}.
                  Отправьте ссылку в чат класса или раздайте бумажные бланки.
                </span>
              </div>
            )}
            <div className="cg-fact">
              <Icon name="users" size={18} />
              <span>Руководитель: {klass.teacher_name || "—"}, помощник: {escorts || "—"}. Добираемся: {transportText}.</span>
            </div>
            {klass.is_demo && (
              <div className="cg-fact">
                <Icon name="spark" size={18} />
                <span>Демо: остальные родители ответят сами, а вам придёт приглашение как родителю Тимура.</span>
              </div>
            )}
          </Card>
        </>
      )}
    </Page>
  );
}
