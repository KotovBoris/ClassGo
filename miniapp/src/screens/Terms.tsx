import { useState } from "react";
import { Button } from "@maxhub/max-ui";
import { api, type ParentChild } from "../api";
import { refreshMe } from "../App";
import { errorText, setState, toast, useAppState } from "../store";
import { Card, Confirm, Hero, Page } from "../ui";

/** Один раз перед первым ответом: соглашение о ПЭП (63-ФЗ) и отдельное согласие на ПДн (152-ФЗ). */
export function Terms({ children }: { children: ParentChild[] }) {
  const { me } = useAppState();
  const [step, setStep] = useState<1 | 2>(1);
  const [busy, setBusy] = useState(false);
  const [askPaper, setAskPaper] = useState(false);
  const school = children[0]?.school_name || "школа";
  const kids = children.map((c) => c.student_name).join(", ");

  function next() {
    setStep(2);
    window.scrollTo(0, 0);
  }

  async function accept() {
    setBusy(true);
    try {
      const next = await api.acceptTerms();
      setState({ me: next });
      toast("Спасибо! Теперь можно отвечать на приглашения.");
    } catch (e) {
      toast(errorText(e), "error");
    } finally {
      setBusy(false);
    }
  }

  async function paper() {
    setBusy(true);
    try {
      await api.revoke();
      await refreshMe("parent");
      setAskPaper(false);
      toast("Хорошо: бумажный бланк согласия передаст классный руководитель.", "info");
    } catch (e) {
      toast(errorText(e), "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Page
      bottom={
        <div className="cg-stack">
          <Button size="large" stretched loading={busy} onClick={() => (step === 1 ? next() : void accept())}>
            {step === 1 ? "Принимаю" : "Даю согласие"}
          </Button>
          <button type="button" className="cg-link cg-center-link" disabled={busy} onClick={() => setAskPaper(true)}>
            {step === 1 ? "Отвечать на бумаге" : "Не даю — отвечу на бумаге"}
          </button>
        </div>
      }
    >
      <Confirm open={askPaper} title="Отвечать на бумаге?" yes="Да, отвечу на бумаге" no="Вернуться" busy={busy}
        onYes={() => void paper()} onClose={() => setAskPaper(false)}>
        <p>Приглашения от школы в ClassGo приходить перестанут, ответ кнопкой будет недоступен.</p>
        <p>Бланк согласия даст классный руководитель — его нужно заполнить и вернуть до срока.</p>
        <p className="cg-muted">Передумаете — откройте ссылку класса ещё раз.</p>
      </Confirm>
      <Hero overline={`Шаг ${step} из 2 · один раз перед первым ответом`}
        title={step === 1 ? "Соглашение об электронной подписи" : "Согласие на обработку данных"} />
      {step === 1 ? (
        <Card className="cg-legalcard">
          <p>{school} и я, законный представитель ученика, договорились:</p>
          <ol>
            <li>Мой ответ кнопкой в ClassGo — простая электронная подпись (ст. 9 63-ФЗ); документ с ней равнозначен бумажному с моей подписью.</li>
            <li>Подписанта определяют по аккаунту MAX и его номеру телефона, совпадающему с номером у школы.</li>
            <li>Так подписываются только согласия и отказы на участие ребёнка в экскурсиях.</li>
            <li>Не передаю телефон и аккаунт MAX другим, об утрате сразу сообщаю классному руководителю; до этого ответы с аккаунта — мои.</li>
            <li>Могу отказаться в любой момент и отвечать на бумаге.</li>
          </ol>
          <p className="cg-muted cg-small">Редакция 1.0. Основание — Порядок получения согласий, утверждённый приказом школы.</p>
        </Card>
      ) : (
        <Card className="cg-legalcard">
          <p>
            Я, {me?.name || "законный представитель"}, свободно, своей волей и в своём интересе, в том числе как
            законный представитель ребёнка ({kids}), даю согласие оператору — {school} — на обработку: моих ФИО,
            телефона, ID в MAX, статуса (мать, отец, опекун); ФИО, класса и даты рождения ребёнка (если указана);
            моих ответов, их времени и причины отказа; отметок переклички в день выезда; присланных мной файлов
            билетов (удаляются через 7 дней после выезда).
          </p>
          <p><b>Цель:</b> участие ребёнка в экскурсиях школы — приглашения, согласия, списки, документы.</p>
          <p>
            <b>Действия:</b> сбор, запись, хранение, уточнение, использование, передача руководителю группы и
            администрации школы, удаление; автоматизированно. По поручению школы данные обрабатывает ClassGo,
            сообщения идут через MAX, хранение — в России.
          </p>
          <p>
            <b>Срок:</b> до конца учебного года или до отзыва. Отозвать — кнопкой «Отозвать согласие» внизу экрана
            или заявлением в школу; уже данные ответы школа хранит по номенклатуре дел.
          </p>
          <p className="cg-muted cg-small">Редакция 1.0. Оформлено отдельным документом (ст. 9 152-ФЗ).</p>
        </Card>
      )}
    </Page>
  );
}
