import { useEffect, useMemo, useState } from "react";
import { Button } from "@maxhub/max-ui";
import { api } from "../api";
import { refreshMe } from "../App";
import { deviceTimeZone, plural } from "../format";
import { haptic, setClosingConfirmation } from "../max";
import { errorText, replace, toast, useAppState } from "../store";
import { Card, Field, Hero, Icon, Notice, Page, Section, Segmented } from "../ui";

type Mode = "self" | "paste" | "file";

const EXAMPLE = "Иванов Иван Иванович; +7 900 123-45-67; Иванова Анна Петровна\nПетрова Мария Олеговна; +7 900 765-43-21; Петров Олег Игоревич";

function parseLines(text: string) {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const [name, phone, parent] = line.split(/[;\t]/).map((s) => s?.trim() ?? "");
      return { full_name: name, parent_phone: phone || "", parent_name: parent || "", parent_role: "Родитель" };
    })
    .filter((s) => s.full_name);
}

export default function NewClass() {
  const { me } = useAppState();
  const [mode, setMode] = useState<Mode>("self");
  const [grade, setGrade] = useState("");
  const [letter, setLetter] = useState("");
  const [school, setSchool] = useState("");
  const [teacher, setTeacher] = useState(me?.name ?? "");
  const [phone, setPhone] = useState("");
  const [text, setText] = useState("");
  const [size, setSize] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const students = useMemo(() => parseLines(text), [text]);
  const withPhone = students.filter((s) => s.parent_phone).length;
  const dirty = Boolean(grade || text || file);
  const phoneOk = phone.replace(/\D/g, "").length >= 10;
  const sizeOk = Number(size) > 0 && Number(size) <= 60;
  const ready = grade.trim() && phoneOk && (mode === "self" ? sizeOk : mode === "paste" ? students.length > 0 : file);

  useEffect(() => {
    setClosingConfirmation(dirty);
    return () => setClosingConfirmation(false);
  }, [dirty]);

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      let classId: number;
      let count: number;
      if (mode === "file" && file) {
        const r = await api.importClass(file, {
          grade: grade.trim(),
          letter: letter.trim().toUpperCase(),
          school_name: school.trim(),
          teacher_name: teacher.trim(),
          teacher_phone: phone.trim(),
          timezone: deviceTimeZone(),
        });
        classId = r.class_id;
        count = r.students_created;
      } else {
        const r = await api.createClass({
          grade: grade.trim(),
          letter: letter.trim().toUpperCase(),
          school_name: school.trim(),
          teacher_name: teacher.trim(),
          teacher_phone: phone.trim(),
          timezone: deviceTimeZone(),
          expected_size: mode === "self" ? Number(size) : 0,
          students: mode === "self" ? [] : students,
        });
        classId = r.id;
        count = r.students.length;
      }
      setClosingConfirmation(false);
      haptic.ok();
      await refreshMe("teacher");
      toast(`Класс создан: ${count} ${plural(count, "ученик", "ученика", "учеников")}. Теперь пригласите родителей.`);
      replace({ name: "class", id: classId });
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Page
      bottom={
        <Button size="large" stretched disabled={!ready} loading={busy} onClick={() => void submit()}>
          Создать класс
        </Button>
      }
    >
      <Hero overline="Новый класс" title="Список класса" subtitle="Нужен один раз в год: ФИО ученика и телефон родителя." />

      {error && <Notice tone="error" icon="info" title="Не получилось создать класс">{error}</Notice>}

      <Section>
        <div className="cg-form">
          <div className="cg-form-row">
            <Field label="Класс">
              <input className="cg-input" inputMode="numeric" value={grade} placeholder="7" maxLength={2}
                onChange={(e) => setGrade(e.target.value.replace(/\D/g, ""))} />
            </Field>
            <Field label="Буква">
              <input className="cg-input" value={letter} placeholder="Б" maxLength={2} onChange={(e) => setLetter(e.target.value)} />
            </Field>
          </div>
          <Field label="Школа">
            <input className="cg-input" value={school} placeholder="МБОУ «Школа № …» г. Казани" onChange={(e) => setSchool(e.target.value)} />
          </Field>
          <Field label="Классный руководитель" hint="Попадёт в приказ как ответственный за группу.">
            <input className="cg-input" value={teacher} placeholder="Фамилия Имя Отчество" onChange={(e) => setTeacher(e.target.value)} />
          </Field>
          <Field label="Ваш телефон для родителей"
            hint="Покажем в приглашении. Если ребёнок не пришёл на сбор, родитель сразу сможет позвонить.">
            <input className="cg-input" type="tel" inputMode="tel" autoComplete="tel" value={phone} placeholder="+7 900 000-00-00"
              onChange={(e) => setPhone(e.target.value)} />
          </Field>
        </div>
      </Section>

      <Section title="Ученики">
        <Segmented<Mode>
          label="Способ"
          value={mode}
          onChange={setMode}
          options={[
            { value: "self", label: "Родители сами" },
            { value: "paste", label: "Вставить список" },
            { value: "file", label: "Файл Excel" },
          ]}
        />
        {mode === "self" ? (
          <Card className="cg-form-card">
            <p>
              Создайте класс без списка и отправьте ссылку в чат родителей. Каждый подтвердит номер в MAX и впишет
              ребёнка, а вы подтвердите заявку одной кнопкой — в боте или здесь.
            </p>
            <Field label="Сколько детей в классе" hint="По журналу. Пока не все семьи прислали заявку, ClassGo покажет, сколько ещё ждём.">
              <input className="cg-input" type="number" inputMode="numeric" min={1} max={60} value={size}
                placeholder="28" onChange={(e) => setSize(e.target.value)} />
            </Field>
            <p className="cg-muted cg-small">Учеников можно добавить и вручную на экране класса.</p>
          </Card>
        ) : mode === "paste" ? (
          <Card className="cg-form-card">
            <p className="cg-muted cg-small">
              По одному ученику в строке: <b>ФИО ученика; телефон родителя; ФИО родителя</b>. Можно скопировать
              столбцы прямо из Excel.
            </p>
            <textarea className="cg-input cg-textarea" rows={7} value={text} placeholder={EXAMPLE}
              onChange={(e) => setText(e.target.value)} />
            {students.length > 0 && (
              <p className="cg-muted cg-small">
                Распознано: {students.length} {plural(students.length, "ученик", "ученика", "учеников")}, с телефоном
                родителя — {withPhone}.
              </p>
            )}
          </Card>
        ) : (
          <Card className="cg-form-card">
            <p className="cg-muted cg-small">
              Файл .xlsx или .csv с колонками «ФИО», «Телефон родителя», «ФИО родителя». «Дата рождения» — по желанию.
              Первая строка — заголовки.
            </p>
            <label className="cg-file">
              <Icon name="upload" size={20} />
              <span>{file ? file.name : "Выбрать файл"}</span>
              <input type="file" accept=".xlsx,.xlsm,.csv" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
            </label>
          </Card>
        )}
      </Section>

      <Notice tone="info" icon="shield">
        По телефону родитель подключится сам: MAX подтвердит номер, ClassGo найдёт ребёнка. Данные хранятся в
        России и нужны только для выездов класса.
      </Notice>
    </Page>
  );
}
