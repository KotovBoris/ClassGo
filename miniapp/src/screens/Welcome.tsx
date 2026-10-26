import { useState } from "react";
import { Button } from "@maxhub/max-ui";
import { chooseRole, startDemo } from "../App";
import { errorText, toast } from "../store";
import { Icon, Page } from "../ui";

const POINTS = [
  { icon: "chat" as const, title: "Родитель отвечает одной кнопкой", text: "Приглашение приходит в чат MAX — «Да, пойдёт» или «Нет»." },
  { icon: "users" as const, title: "Учитель видит, кто едет", text: "Список обновляется сам. Напомнить можно тем, кто не ответил." },
  { icon: "doc" as const, title: "Документы для директора готовы", text: "Приказ, список группы, реестр согласий и инструктаж — в один клик." },
];

export default function Welcome() {
  const [busy, setBusy] = useState(false);

  async function demo() {
    setBusy(true);
    try {
      await startDemo();
    } catch (e) {
      toast(errorText(e), "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Page>
      <div className="cg-welcome">
        <div className="cg-logo" aria-hidden="true">
          <Icon name="school" size={30} />
        </div>
        <h1 className="cg-display">Школьный выезд без бумажек и чата на 200 сообщений</h1>
        <p className="cg-lead">ClassGo собирает класс в музей или театр прямо в MAX.</p>

        <ul className="cg-points">
          {POINTS.map((p) => (
            <li key={p.title}>
              <span className="cg-point-icon">
                <Icon name={p.icon} size={22} />
              </span>
              <span>
                <b>{p.title}</b>
                <span className="cg-muted">{p.text}</span>
              </span>
            </li>
          ))}
        </ul>

        <div className="cg-stack">
          <Button size="large" stretched onClick={() => void chooseRole("teacher")}>
            Я классный руководитель
          </Button>
          <Button size="large" stretched variant="secondary" onClick={() => void chooseRole("parent")}>
            Я родитель
          </Button>
        </div>

        <button type="button" className="cg-demo-card" onClick={() => void demo()} disabled={busy}>
          <span className="cg-demo-icon">
            <Icon name="spark" size={22} />
          </span>
          <span className="cg-demo-text">
            <b>{busy ? "Готовим демо-класс…" : "Попробовать демо"}</b>
            <span>Вы станете учителем 7Б и родителем одного ученика — увидите обе стороны.</span>
          </span>
          <Icon name="chevron" size={20} />
        </button>

        <p className="cg-fineprint">
          Афиша — демо-данные по Казани. Билеты семьи покупают сами: в кассе или «Пушкинской картой».
        </p>
      </div>
    </Page>
  );
}
