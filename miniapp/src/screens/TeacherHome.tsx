import { useCallback, useEffect, useState } from "react";
import { Button } from "@maxhub/max-ui";
import { api, type Excursion, type SchoolClass } from "../api";
import { refreshMe, startDemo } from "../App";
import { deadlineText, firstName, isPast, parseDay, plural } from "../format";
import { errorText, push, toast, useAppState } from "../store";
import { Card, DateBadge, Empty, Hero, Icon, Notice, Page, ProgressBar, Section, SkeletonList, Status, Tag } from "../ui";

export default function TeacherHome() {
  const { me } = useAppState();
  const [classes, setClasses] = useState<SchoolClass[] | null>(null);
  const [trips, setTrips] = useState<Excursion[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showPast, setShowPast] = useState(false);
  const [resetting, setResetting] = useState(false);

  const load = useCallback(async () => {
    try {
      const [c, t] = await Promise.all([api.myClasses(), api.myTrips()]);
      setClasses(c);
      setTrips(t);
      setError(null);
    } catch (e) {
      setError(errorText(e));
    }
  }, []);

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(), 6000);
    return () => window.clearInterval(timer);
  }, [load]);

  async function resetDemo() {
    setResetting(true);
    try {
      await api.demoReset();
      await refreshMe("teacher");
      await load();
      toast("Демо начато заново: новый класс и пример выезда.");
    } catch (e) {
      toast(errorText(e), "error");
    } finally {
      setResetting(false);
    }
  }

  const name = me?.name ? firstName(me.name) || me.name : "";
  const hasDemo = Boolean(classes?.some((c) => c.is_demo));
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const isPastTrip = (t: Excursion) => t.cancelled || Boolean(t.event_date && (parseDay(t.event_date) ?? today) < today);
  const upcoming = (trips ?? []).filter((t) => !isPastTrip(t));
  const past = (trips ?? []).filter(isPastTrip);
  const loading = classes === null || trips === null;
  const noClasses = classes !== null && classes.length === 0;

  return (
    <Page
      bottom={
        !loading && (
          <Button
            size="large"
            stretched
            iconBefore={<Icon name="plus" size={20} />}
            onClick={() => push(noClasses ? { name: "new-class" } : { name: "new-trip" })}
          >
            {noClasses ? "Добавить класс" : "Новый выезд"}
          </Button>
        )
      }
    >
      <Hero
        overline="Классный руководитель"
        title={name ? `Здравствуйте, ${name}` : "Мои выезды"}
        subtitle={
          classes && classes.length
            ? `${classes.map((c) => c.title).join(", ")} · ` +
              (upcoming.length
                ? `${upcoming.length} ${plural(upcoming.length, "выезд", "выезда", "выездов")} впереди`
                : "выездов пока нет")
            : undefined
        }
      />

      {error && (
        <Notice tone="error" icon="info" title="Не удалось обновить данные" action={
          <button type="button" className="cg-link" onClick={() => void load()}>Повторить</button>
        }>
          {error}
        </Notice>
      )}

      {hasDemo && (
        <Notice
          tone="demo"
          icon="spark"
          title="Демо-режим"
          action={
            <button type="button" className="cg-link" disabled={resetting} onClick={() => void resetDemo()}>
              {resetting ? "Пересоздаём…" : "Начать демо заново"}
            </button>
          }
        >
          7Б — ваш демо-класс. Остальные родители в нём ненастоящие и отвечают сами за минуту. Вы ещё и родитель
          Тимура: переключитесь на «Я родитель» вверху или ответьте в чате с ботом.
        </Notice>
      )}

      {loading && <SkeletonList rows={3} />}

      {!loading && noClasses && (
        <Empty
          icon="users"
          title="Добавьте свой класс"
          text="Загрузите список из Excel или введите вручную: ФИО ученика и телефон родителя."
          action={
            <div className="cg-stack">
              <Button size="large" stretched onClick={() => push({ name: "new-class" })}>
                Добавить класс
              </Button>
              <Button
                size="large"
                stretched
                variant="secondary"
                onClick={() => void startDemo().then(load).catch((e) => toast(errorText(e), "error"))}
              >
                Попробовать на демо-классе
              </Button>
            </div>
          }
        />
      )}

      {!loading && !noClasses && (
        <Section title="Выезды">
          {upcoming.length === 0 && (
            <Empty
              icon="calendar"
              title="Выездов пока нет"
              text="Выберите спектакль, музей или выставку — приглашение уйдёт родителям в MAX."
            />
          )}
          <div className="cg-list">
            {upcoming.map((t) => (
              <TripCard key={t.id} trip={t} />
            ))}
          </div>
          {past.length > 0 && (
            <button type="button" className="cg-link cg-more" onClick={() => setShowPast((v) => !v)}>
              {showPast ? "Скрыть прошедшие и отменённые" : `Прошедшие и отменённые (${past.length})`}
            </button>
          )}
          {showPast && (
            <div className="cg-list">
              {past.map((t) => (
                <TripCard key={t.id} trip={t} />
              ))}
            </div>
          )}
        </Section>
      )}

      {!loading && classes && classes.length > 0 && (
        <Section
          title="Мои классы"
          action={
            <button type="button" className="cg-link" onClick={() => push({ name: "new-class" })}>
              + Класс
            </button>
          }
        >
          <div className="cg-list">
            {classes.map((c) => (
              <Card key={c.id} onClick={() => push({ name: "class", id: c.id })}>
                <div className="cg-classrow">
                  <span className="cg-classbadge">{c.title}</span>
                  <span className="cg-classinfo">
                    <b>
                      {c.students.length} {plural(c.students.length, "ученик", "ученика", "учеников")}
                      {c.is_demo && <Tag tone="demo">демо</Tag>}
                    </b>
                    <span className="cg-muted">
                      Родители в MAX: {c.parents_connected} из {c.students.length}
                    </span>
                    {c.join_requests > 0 && (
                      <Status tone="waiting">
                        {c.join_requests} {plural(c.join_requests, "заявка", "заявки", "заявок")} от родителей
                      </Status>
                    )}
                  </span>
                  <Icon name="chevron" size={20} className="cg-chev" />
                </div>
              </Card>
            ))}
          </div>
        </Section>
      )}
    </Page>
  );
}

function TripCard({ trip }: { trip: Excursion }) {
  const s = trip.stats;
  const done = s && s.waiting === 0 && s.total > 0;
  const closed = isPast(trip.deadline);
  return (
    <Card onClick={() => push({ name: "trip", id: trip.id })}>
      <div className="cg-tripcard">
        <DateBadge date={trip.event_date} />
        <div className="cg-tripcard-body">
          <div className="cg-tripcard-title">{trip.title}</div>
          <div className="cg-muted">
            {trip.location_name} · {trip.class_title}
          </div>
          {s && !trip.cancelled && <ProgressBar stats={s} label={false} />}
          <div className="cg-tripcard-foot">
            {trip.cancelled && <Status tone="neutral">Выезд отменён</Status>}
            {s && !trip.cancelled && done && <Status tone="going">Ответили все: едут {s.going}</Status>}
            {s && !trip.cancelled && !done && <Status tone="waiting">Ждём ответа: {s.waiting} из {s.total}</Status>}
            {s && !trip.cancelled && !done && trip.deadline && (
              <span className="cg-muted cg-small cg-deadline">
                {closed ? "Срок ответа прошёл" : `Ответить до ${deadlineText(trip.deadline, trip.timezone)}`}
              </span>
            )}
          </div>
        </div>
        <Icon name="chevron" size={20} className="cg-chev" />
      </div>
    </Card>
  );
}
