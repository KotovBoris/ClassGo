import { useEffect, useState } from "react";
import { Button } from "@maxhub/max-ui";
import { api } from "../api";
import { refreshMe } from "../App";
import { haptic } from "../max";
import { errorText, resetTo, toast } from "../store";
import { Card, Hero, Icon, Loader, Notice, Page } from "../ui";

/** Второй родитель открыл ссылку от первого: подключаем его к ребёнку одной кнопкой. */
export default function PairScreen({ code }: { code: string }) {
  const [info, setInfo] = useState<{ student_name: string; class_title: string; invited_by: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.pairInfo(code).then(setInfo).catch((e) => setError(errorText(e)));
  }, [code]);

  async function accept() {
    setBusy(true);
    try {
      const r = await api.pair(code);
      if (r.status !== "linked" && r.status !== "requested") {
        setError(r.message);
        return;
      }
      haptic.ok();
      await refreshMe("parent");
      toast(r.message);
      resetTo({ name: "home" });
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  if (error) {
    return (
      <Page>
        <Notice tone="error" icon="info" title="Ссылка не сработала">
          {error}
        </Notice>
      </Page>
    );
  }
  if (!info) return <Page><Loader /></Page>;

  return (
    <Page
      bottom={
        <Button size="large" stretched loading={busy} onClick={() => void accept()} iconBefore={<Icon name="check" size={20} />}>
          Подключиться
        </Button>
      }
    >
      <Hero overline="Приглашение для второго родителя" title={info.student_name} subtitle={`Класс ${info.class_title}`} />
      <Card className="cg-join">
        <span className="cg-join-icon"><Icon name="users" size={26} /></span>
        <p>
          {info.invited_by ? <b>{info.invited_by}</b> : "Родитель"} зовёт вас тоже получать приглашения на выезды
          и отвечать на них.
        </p>
        <p className="cg-muted">
          Достаточно ответа одного из родителей. Второму придёт сообщение, кто и как ответил.
        </p>
      </Card>
    </Page>
  );
}
