import { useEffect, useState } from "react";
import { Button } from "@maxhub/max-ui";
import { api, type JoinInfo } from "../api";
import { refreshMe } from "../App";
import { firstName, plural } from "../format";
import { haptic, isInsideMax, requestContact, type VerifiedContact } from "../max";
import { errorText, resetTo, toast, useAppState } from "../store";
import { Card, Field, Hero, Icon, Loader, Notice, Page, Segmented } from "../ui";

const NO_PHONE = "Номер не получен. Нажмите кнопку ещё раз и разрешите MAX передать номер.";

export default function JoinScreen({ code }: { code: string }) {
  const [info, setInfo] = useState<JoinInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [contact, setContact] = useState<VerifiedContact | null>(null);
  const [addChild, setAddChild] = useState(false);
  const [sent, setSent] = useState<string | null>(null);
  const inside = isInsideMax();

  useEffect(() => {
    api.joinInfo(code).then(setInfo).catch((e) => setError(errorText(e)));
  }, [code]);

  async function confirm() {
    setBusy(true);
    setProblem(null);
    try {
      let payload: { code: string; phone: string; auth_date?: string; hash?: string } = { code, phone: "" };
      if (!info?.is_demo) {
        const contact = await requestContact();
        if (!contact) {
          setProblem(NO_PHONE);
          return;
        }
        payload = { code, phone: contact.phone, auth_date: contact.authDate, hash: contact.hash };
        setContact(contact);
      }
      const r = await api.join(payload);
      if (r.status === "linked") {
        haptic.ok();
        await refreshMe("parent");
        toast(
          info?.is_demo
            ? `Вы родитель ученика демо-класса: ${r.children.join(", ")}. Приглашение уже в чате с ботом.`
            : `Готово! Подключили: ${r.children.map(firstName).join(", ")}. Приглашения будут приходить вам.`,
        );
        resetTo({ name: "home" });
      } else if (r.status === "not_found" && !info?.is_demo) {
        // Номера нет в списке класса — родитель вписывает ребёнка сам, учитель подтвердит.
        setAddChild(true);
      } else {
        setProblem(r.message);
      }
    } catch (e) {
      setProblem(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  if (error) {
    return (
      <Page>
        <Notice tone="error" icon="info" title="Ссылка не работает">
          {error}. Попросите классного руководителя прислать ссылку ещё раз.
        </Notice>
      </Page>
    );
  }
  if (!info) return <Page><Loader /></Page>;

  if (sent) {
    return (
      <Page bottom={<Button size="large" stretched onClick={() => resetTo({ name: "home" })}>Понятно</Button>}>
        <Hero overline={`Класс ${info.class_title}`} title="Заявка у учителя" />
        <Notice tone="ok" icon="check" title={sent}>
          Как только классный руководитель подтвердит, в чат MAX придёт сообщение и приглашения на выезды класса.
        </Notice>
      </Page>
    );
  }

  // В списке класса нет ни одного номера — сверять не с чем: родитель сразу вписывает ребёнка.
  if (addChild || (!info.is_demo && info.phones_listed === 0)) {
    return <AddChildForm code={code} info={info} contact={contact} onSent={setSent} />;
  }

  const canConfirm = info.is_demo || inside;

  return (
    <Page
      bottom={
        canConfirm ? (
          <Button size="large" stretched loading={busy} iconBefore={<Icon name={info.is_demo ? "check" : "shield"} size={20} />}
            onClick={() => void confirm()}>
            {info.is_demo ? "Стать родителем ученика" : "Подтвердить номер телефона"}
          </Button>
        ) : undefined
      }
    >
      <Hero
        overline={info.is_demo ? "Живое демо ClassGo" : "Приглашение от классного руководителя"}
        title={`Класс ${info.class_title}`}
        subtitle={info.school_name}
      />
      <Card className="cg-join">
        <span className="cg-join-icon"><Icon name={info.is_demo ? "spark" : "school"} size={26} /></span>
        {info.is_demo ? (
          <>
            <p>
              Это демо-класс <b>{info.teacher_name}</b>. Нажмите кнопку — и вы станете родителем ученика.
              Когда учитель отправит выезд, приглашение придёт в чат с ботом.
            </p>
            <p className="cg-muted">
              Ответьте «Да» — учитель увидит ответ с именем из вашего профиля MAX. Номер телефона не нужен.
            </p>
          </>
        ) : (
          <>
            <p>
              <b>{info.teacher_name || "Классный руководитель"}</b> приглашает родителей {info.class_title} в ClassGo.
              Сюда приходят приглашения на выезды, ответ — одной кнопкой.
            </p>
            <p className="cg-muted">
              В списке класса {info.students_count} {plural(info.students_count, "ученик", "ученика", "учеников")}.
              Если классный руководитель внёс ваш номер, ребёнок найдётся сам. Если нет — впишете его
              на следующем шаге, учитель подтвердит.
            </p>
          </>
        )}
        {!canConfirm && (
          <Notice tone="info" icon="info">
            Откройте эту ссылку в приложении MAX.
          </Notice>
        )}
      </Card>
      {problem && <Notice tone="warn" icon="info" title="Не получилось подключиться">{problem}</Notice>}
    </Page>
  );
}

const ROLES = ["Мама", "Папа", "Опекун"] as const;

/** Родитель вписывает ребёнка сам, учитель подтверждает одним нажатием. Номер MAX передаёт при отправке. */
function AddChildForm({ code, info, contact, onSent }: {
  code: string;
  info: JoinInfo;
  contact: VerifiedContact | null;
  onSent: (name: string) => void;
}) {
  const { me } = useAppState();
  const [child, setChild] = useState("");
  const [birth, setBirth] = useState("");
  const [role, setRole] = useState<(typeof ROLES)[number]>("Мама");
  const [parentName, setParentName] = useState(me?.name ?? "");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const inside = isInsideMax();
  const ready = child.trim().split(/\s+/).length >= 2 && parentName.trim().length >= 2;
  const teacher = info.teacher_name || "Классный руководитель";

  async function submit() {
    setBusy(true);
    setProblem(null);
    try {
      // requestContact — первым делом, пока длится нажатие: MAX показывает свой диалог.
      const c = contact ?? (await requestContact());
      if (!c) {
        setProblem(NO_PHONE);
        return;
      }
      const r = await api.joinRequest({
        code,
        child_name: child,
        birth_date: birth || null,
        role,
        parent_name: parentName,
        phone: c.phone,
        auth_date: c.authDate,
        hash: c.hash,
      });
      haptic.ok();
      onSent(r.children[0] ?? child);
    } catch (e) {
      setProblem(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Page bottom={inside ? (
      <Button size="large" stretched disabled={!ready} loading={busy} onClick={() => void submit()}>
        {contact ? "Отправить учителю" : "Подтвердить номер и отправить"}
      </Button>
    ) : undefined}>
      <Hero
        overline={contact ? `Класс ${info.class_title}` : "Приглашение от классного руководителя"}
        title={contact ? "Добавьте ребёнка" : `Класс ${info.class_title}`}
        subtitle={contact
          ? "Классный руководитель подтвердит, что он в классе"
          : `${teacher} приглашает родителей в ClassGo: сюда приходят приглашения на выезды, ответ — одной кнопкой`}
      />
      <Card className="cg-form">
        <Field label="Фамилия и имя ребёнка" hint="Отчество — если знаете. Учитель сверит со списком класса.">
          <input className="cg-input" value={child} autoComplete="off" placeholder="Иванов Пётр"
            onChange={(e) => setChild(e.target.value)} />
        </Field>
        <Field label="Дата рождения" hint="По желанию: с 14 лет билет можно оплатить «Пушкинской картой».">
          <input className="cg-input" type="date" value={birth} onChange={(e) => setBirth(e.target.value)} />
        </Field>
        <div className="cg-field">
          <span className="cg-field-label">Кто вы ребёнку</span>
          <Segmented label="Кто вы ребёнку" value={role} options={ROLES.map((r) => ({ value: r, label: r }))}
            onChange={(v) => setRole(v as (typeof ROLES)[number])} />
        </div>
        <Field label="Ваше имя" hint="Его увидит классный руководитель.">
          <input className="cg-input" value={parentName} autoComplete="name" placeholder="Иванова Анна"
            onChange={(e) => setParentName(e.target.value)} />
        </Field>
        <p className="cg-muted cg-small">
          {contact
            ? `Заявку подтвердит ${teacher}. Номер ${contact.phone} уже подтверждён в MAX.`
            : `При отправке MAX попросит разрешение передать ваш номер — его увидит только ${teacher}. Он же подтвердит заявку.`}
        </p>
        {inside && !ready && <p className="cg-muted cg-small">Чтобы отправить, напишите фамилию и имя ребёнка и ваше имя.</p>}
        {!inside && <Notice tone="info" icon="info">Откройте эту ссылку в приложении MAX.</Notice>}
      </Card>
      {problem && <Notice tone="warn" icon="info" title="Не получилось отправить">{problem}</Notice>}
    </Page>
  );
}
