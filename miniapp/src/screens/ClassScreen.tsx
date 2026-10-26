import { useCallback, useEffect, useState } from "react";
import { Button } from "@maxhub/max-ui";
import { api, type Invite, type JoinRequestItem, type SchoolClass, type Student } from "../api";
import { formatPhone, initials, plural, shortName } from "../format";
import { copyText, haptic, shareToChat, telHref } from "../max";
import { errorText, push, toast } from "../store";
import { Avatar, Card, Confirm, Field, Hero, Icon, Loader, Notice, Page, QrCode, Section, Sheet, Status, Tag } from "../ui";

function connected(s: Student): boolean {
  return s.parents.some((p) => p.bot_activated);
}

export default function ClassScreen({ id }: { id: number }) {
  const [klass, setKlass] = useState<SchoolClass | null>(null);
  const [invite, setInvite] = useState<Invite | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [qrOpen, setQrOpen] = useState(false);
  const [adding, setAdding] = useState(false);
  const [selected, setSelected] = useState<Student | null>(null);

  const load = useCallback(async () => {
    try {
      const all = await api.myClasses();
      const found = all.find((c) => c.id === id) ?? null;
      setKlass(found);
      setError(found ? null : "Класс не найден или у вас нет к нему доступа.");
    } catch (e) {
      setError(errorText(e));
    }
  }, [id]);

  useEffect(() => {
    void load();
    api.invite(id).then(setInvite).catch(() => setInvite(null));
  }, [id, load]);

  if (!klass) {
    return (
      <Page>
        {error ? <Notice tone="error" icon="info" title="Не удалось открыть класс">{error}</Notice> : <Loader />}
      </Page>
    );
  }

  const shareText =
    `Родители ${klass.title}! Подключитесь к ClassGo: сюда будут приходить приглашения на выезды, ` +
    `ответ — одной кнопкой. Откройте ссылку, впишите ребёнка и подтвердите номер телефона.`;
  const notConnected = klass.students.filter((s) => !connected(s)).length;

  async function share() {
    if (!invite) return;
    const r = await shareToChat(shareText, invite.app_link);
    if (r === "copied") toast("Ссылка скопирована — вставьте её в чат класса.");
    if (r === "shared") toast("Приглашение отправлено.");
  }

  async function copy() {
    if (!invite) return;
    toast((await copyText(invite.app_link)) ? "Ссылка скопирована." : "Не получилось скопировать.", "info");
  }

  return (
    <Page
      bottom={
        <Button size="large" stretched iconBefore={<Icon name="plus" size={20} />} onClick={() => push({ name: "new-trip", classId: klass.id })}>
          Новый выезд для {klass.title}
        </Button>
      }
    >
      <Hero
        overline={klass.school_name || "Класс"}
        title={`${klass.title} класс`}
        subtitle={`${klass.students.length} ${plural(klass.students.length, "ученик", "ученика", "учеников")} · родители в MAX: ${klass.parents_connected} из ${klass.students.length}`}
        aside={klass.is_demo ? <Tag tone="demo">демо</Tag> : undefined}
      />

      <Card className="cg-invite">
        <div className="cg-invite-head">
          <span className="cg-invite-icon"><Icon name="users" size={22} /></span>
          <div>
            <div className="cg-actions-title">Подключите родителей</div>
            <p className="cg-muted">
              Одна ссылка на весь класс. Родитель откроет её в MAX, впишет ребёнка и подтвердит номер — вам останется
              подтвердить заявку. Если номер уже есть в списке класса, ребёнок найдётся сам. Без регистрации и паролей.
            </p>
          </div>
        </div>
        {klass.is_demo && (
          <p className="cg-muted cg-small">В демо-классе все родители уже подключены — ссылку можно открыть со второго аккаунта.</p>
        )}
        <div className="cg-stack">
          <Button size="medium" stretched disabled={!invite} iconBefore={<Icon name="share" size={18} />} onClick={() => void share()}>
            Отправить в чат класса
          </Button>
          <div className="cg-row-buttons">
            <Button size="medium" variant="secondary" disabled={!invite} iconBefore={<Icon name="qr" size={18} />} onClick={() => setQrOpen(true)}>
              QR для собрания
            </Button>
            <Button size="medium" variant="secondary" disabled={!invite} onClick={() => void copy()}>
              Скопировать
            </Button>
          </div>
        </div>
      </Card>

      {klass.can_edit && klass.join_requests > 0 && <JoinRequests classId={klass.id} onDone={() => void load()} />}

      {notConnected > 0 && notConnected < klass.students.length && !klass.is_demo && (
        <Notice tone="warn" icon="info">
          {notConnected} {plural(notConnected, "семья ещё не подключена", "семьи ещё не подключены", "семей ещё не подключены")}.
          Напомните о ссылке в чате класса. Кто без MAX, отвечает на бумажном бланке — он есть в документах выезда.
        </Notice>
      )}

      <Section
        title={`Ученики · ${klass.students.length}`}
        action={klass.can_edit && (
          <button type="button" className="cg-link" onClick={() => setAdding((v) => !v)}>
            {adding ? "Скрыть" : "+ Ученик"}
          </button>
        )}
      >
        {adding && <AddStudent classId={klass.id} onDone={() => { setAdding(false); void load(); }} />}
        <div className="cg-people">
          {klass.students.map((s) => {
            const on = connected(s);
            const parent = s.parents[0];
            return (
              <button key={s.id} type="button" className="cg-person" onClick={() => setSelected(s)}>
                <Avatar text={initials(s.full_name)} tone={on ? "going" : "waiting"} />
                <span className="cg-person-text">
                  <b>{shortName(s.full_name)}</b>
                  <span className="cg-muted">
                    {parent ? `${parent.role}: ${parent.full_name}` : "Родитель не указан"}
                  </span>
                </span>
                <Status tone={on ? "going" : "waiting"}>{on ? "В MAX" : "Не подключён"}</Status>
              </button>
            );
          })}
        </div>
      </Section>

      <Sheet open={qrOpen} title={`QR-код для родителей ${klass.title}`} onClose={() => setQrOpen(false)}>
        {invite && (
          <div className="cg-qr-wrap">
            <QrCode value={invite.app_link} size={240} />
            <p className="cg-muted">
              Покажите на родительском собрании. Родители наведут камеру телефона и подтвердят номер в MAX.
            </p>
            <code className="cg-code">{invite.app_link}</code>
          </div>
        )}
      </Sheet>

      <StudentSheet
        klass={klass}
        student={selected}
        onClose={() => setSelected(null)}
        onChanged={() => { setSelected(null); void load(); }}
      />
    </Page>
  );
}

function AddStudent({ classId, onDone }: { classId: number; onDone: () => void }) {
  const [name, setName] = useState("");
  const [parent, setParent] = useState("");
  const [phone, setPhone] = useState("");
  const [busy, setBusy] = useState(false);

  async function save() {
    if (!name.trim()) return;
    setBusy(true);
    try {
      await api.addStudent(classId, {
        full_name: name.trim(),
        parent_name: parent.trim(),
        parent_phone: phone.trim(),
        parent_role: "Родитель",
      });
      haptic.ok();
      toast("Ученик добавлен. Он уже есть во всех выездах класса.");
      onDone();
    } catch (e) {
      toast(errorText(e), "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="cg-form-card">
      <div className="cg-form">
        <Field label="ФИО ученика">
          <input className="cg-input" value={name} placeholder="Иванов Иван Иванович" onChange={(e) => setName(e.target.value)} />
        </Field>
        <Field label="Родитель">
          <input className="cg-input" value={parent} placeholder="Иванова Анна Петровна" onChange={(e) => setParent(e.target.value)} />
        </Field>
        <Field label="Телефон родителя" hint="По этому номеру родитель подключится к классу.">
          <input className="cg-input" value={phone} inputMode="tel" placeholder="+7 900 123-45-67" onChange={(e) => setPhone(e.target.value)} />
        </Field>
      </div>
      <Button size="medium" stretched loading={busy} disabled={!name.trim()} onClick={() => void save()}>
        Добавить ученика
      </Button>
    </Card>
  );
}

function StudentSheet({
  klass,
  student,
  onClose,
  onChanged,
}: {
  klass: SchoolClass;
  student: Student | null;
  onClose: () => void;
  onChanged: () => void;
}) {
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  useEffect(() => setConfirming(false), [student]);
  if (!student) return null;

  async function remove() {
    if (!student) return;
    if (!confirming) {
      setConfirming(true);
      return;
    }
    setBusy(true);
    try {
      await api.removeStudent(klass.id, student.id);
      toast("Ученик удалён из класса.");
      onChanged();
    } catch (e) {
      toast(errorText(e), "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Sheet open title={shortName(student.full_name)} onClose={onClose}>
      {student.parents.length === 0 && <p className="cg-muted">Родитель не указан.</p>}
      {student.parents.map((p) => {
        const tel = telHref(p.phone_number);
        return (
          <div key={p.id} className="cg-parentbox">
            <div>
              <b>{p.full_name || "Родитель"}</b>
              <span className="cg-muted"> · {p.role.toLowerCase()}</span>
            </div>
            <div className="cg-muted">{formatPhone(p.phone_number) || "телефон не указан"}</div>
            <Status tone={p.bot_activated ? "going" : "waiting"}>
              {p.bot_activated ? (p.confirmed ? "Подключён к MAX" : "Ждёт подтверждения") : "Не подключён к MAX"}
            </Status>
            {tel && (
              <a className="cg-callbtn" href={tel}>
                <Icon name="phone" size={18} /> Позвонить
              </a>
            )}
          </div>
        );
      })}
      {klass.can_edit && !klass.is_demo && (
        <button type="button" className="cg-link cg-danger" disabled={busy} onClick={() => void remove()}>
          {confirming ? "Нажмите ещё раз, чтобы удалить" : "Удалить ученика из класса"}
        </button>
      )}
    </Sheet>
  );
}

/** Родители, которых нет в списке, сами вписали детей — учитель сверяет и подтверждает. */
function JoinRequests({ classId, onDone }: { classId: number; onDone: () => void }) {
  const [items, setItems] = useState<JoinRequestItem[] | null>(null);
  const [busy, setBusy] = useState<number | "all" | null>(null);
  const [editing, setEditing] = useState<Record<number, string>>({});
  const [askAll, setAskAll] = useState(false);
  const [askReject, setAskReject] = useState<JoinRequestItem | null>(null);

  const load = useCallback(() => {
    api.classJoinRequests(classId).then(setItems).catch(() => setItems([]));
  }, [classId]);

  useEffect(() => {
    load();
    // На собрании родители сканируют QR — новые заявки появляются без обновления экрана.
    const timer = window.setInterval(load, 8000);
    return () => window.clearInterval(timer);
  }, [load]);

  async function decide(item: JoinRequestItem, approve: boolean, linkExisting = false) {
    setBusy(item.id);
    try {
      const name = editing[item.id]?.trim();
      await api.decideJoin(item.id, approve, approve && name && name !== item.child_name ? name : undefined, linkExisting);
      haptic.ok();
      toast(
        !approve
          ? "Заявка отклонена."
          : linkExisting
            ? `${shortName(item.match_name || item.child_name)}: второй родитель подключён. Ему ушли приглашения.`
            : `${shortName(name || item.child_name)} — в списке класса. Родителю ушли приглашения.`,
      );
      setAskReject(null);
      load();
      onDone();
    } catch (e) {
      toast(errorText(e), "error");
    } finally {
      setBusy(null);
    }
  }

  async function approveAll() {
    setBusy("all");
    try {
      const done = await api.approveAllJoins(classId);
      const skipped = done.filter((r) => r.status === "PENDING").length;
      haptic.ok();
      toast(
        `Подтвердили ${done.length - skipped}. Родителям ушли приглашения на открытые выезды.` +
          (skipped ? ` Пропустили ${skipped}: у ребёнка уже есть родитель — проверьте по одной.` : ""),
      );
      setAskAll(false);
      load();
      onDone();
    } catch (e) {
      toast(errorText(e), "error");
    } finally {
      setBusy(null);
    }
  }

  if (!items || items.length === 0) return null;
  const ready = items.filter((r) => !r.needs_check).length;
  const checks = items.length - ready;
  return (
    <Section
      title={`Заявки родителей · ${items.length}`}
      action={items.length > 1 && ready > 0 && (
        <button type="button" className="cg-link" onClick={() => setAskAll(true)}>Подтвердить все</button>
      )}
    >
      <div className="cg-list">
        {items.map((r) => {
          const edit = editing[r.id];
          return (
            <Card key={r.id} className="cg-request">
              <div className="cg-request-text">
                {edit === undefined ? (
                  <b>
                    {r.child_name}
                    {r.child_birth_date && <span className="cg-muted"> · {r.child_birth_date.split("-").reverse().join(".")}</span>}
                  </b>
                ) : (
                  <input className="cg-input" value={edit} aria-label="ФИО ребёнка"
                    onChange={(e) => setEditing((m) => ({ ...m, [r.id]: e.target.value }))} />
                )}
                <span className="cg-muted">
                  {r.parent_role}: {r.parent_name || "без имени"}
                  {r.phone_number && <> · <span className="cg-nowrap">{formatPhone(r.phone_number)}</span></>}
                </span>
                {r.needs_check ? (
                  <p className="cg-warnline">
                    Внимание: {r.match_name} уже в списке, у ребёнка есть родитель. Подключайте, только если знаете,
                    что это законный представитель — второй родитель или опекун.
                  </p>
                ) : r.match_name && (
                  <span className="cg-match">
                    <Icon name="check" size={14} /> {r.match_name === r.child_name ? "Есть в списке класса" : `Похоже на ученика из списка: ${r.match_name}`}
                    {r.match_has_parent ? " — по ссылке от его родителя, станет вторым" : ""}
                  </span>
                )}
              </div>
              <div className="cg-row-buttons">
                {r.needs_check ? (
                  <Button size="medium" variant="secondary" loading={busy === r.id} disabled={busy === "all"}
                    onClick={() => void decide(r, true, true)}>
                    Это второй родитель — подключить
                  </Button>
                ) : (
                  <Button size="medium" loading={busy === r.id} disabled={busy === "all"} onClick={() => void decide(r, true)}>
                    Подтвердить
                  </Button>
                )}
                <Button size="medium" variant="secondary" disabled={busy !== null} onClick={() => setAskReject(r)}>
                  {r.needs_check ? "Отклонить" : "Не мой ученик"}
                </Button>
              </div>
              {edit === undefined && !r.needs_check && !r.match_has_parent && (
                <button type="button" className="cg-link cg-small" onClick={() => setEditing((m) => ({ ...m, [r.id]: r.child_name }))}>
                  Исправить ФИО перед подтверждением
                </button>
              )}
            </Card>
          );
        })}
      </div>

      <Confirm open={askAll} title={`Подтвердить все заявки (${ready})?`} yes="Да, подтвердить все" busy={busy === "all"}
        onYes={() => void approveAll()} onClose={() => setAskAll(false)}>
        <p>Сверьте имена со списком класса. Каждому родителю придут приглашения на открытые выезды.</p>
        {checks > 0 && (
          <p>Заявки с пометкой «Внимание» ({checks}) не подтвердятся — у этих детей уже есть родитель, проверьте их по одной.</p>
        )}
      </Confirm>
      <Confirm open={askReject !== null} title="Отклонить заявку?"
        yes={askReject?.needs_check ? "Да, отклонить" : "Да, это не мой ученик"} danger
        busy={askReject !== null && busy === askReject.id}
        onYes={() => askReject && void decide(askReject, false)} onClose={() => setAskReject(null)}>
        <p>{askReject?.child_name}: родитель получит сообщение, что заявку не подтвердили, и ваш номер для связи.</p>
      </Confirm>
    </Section>
  );
}
