import { useCallback, useEffect, useState } from "react";
import { api, type Me } from "./api";
import { isInsideMax, ready, setBackButton, startParam } from "./max";
import { back, errorText, getState, resetTo, setState, toast, useAppState, type Role, type Route } from "./store";
import { Icon, Loader, Notice, Segmented, Toaster } from "./ui";
import Welcome from "./screens/Welcome";
import TeacherHome from "./screens/TeacherHome";
import TripScreen from "./screens/TripScreen";
import NewTrip from "./screens/NewTrip";
import ClassScreen from "./screens/ClassScreen";
import NewClass from "./screens/NewClass";
import ParentHome from "./screens/ParentHome";
import ParentTrip from "./screens/ParentTrip";
import JoinScreen from "./screens/JoinScreen";
import PairScreen from "./screens/PairScreen";

function pickRole(me: Me): Role | null {
  if (me.role === "teacher" && me.is_teacher) return "teacher";
  if (me.role === "parent" && (me.is_parent || !me.is_teacher)) return "parent";
  if (me.is_teacher) return "teacher";
  if (me.is_parent) return "parent";
  return me.role;
}

/** Обновить профиль (после демо, привязки, создания класса). */
export async function refreshMe(nextRole?: Role): Promise<Me> {
  const me = await api.me();
  setState({ me, role: nextRole ?? getState().role ?? pickRole(me) });
  return me;
}

export async function chooseRole(role: Role): Promise<void> {
  setState({ role });
  resetTo({ name: "home" });
  try {
    const me = await api.setRole(role);
    setState({ me });
  } catch {
    /* роль сохранится при следующем входе */
  }
}

export async function startDemo(): Promise<void> {
  const info = await api.demoStart();
  await refreshMe("teacher");
  try {
    await api.setRole("teacher");
  } catch {
    /* не критично */
  }
  resetTo({ name: "home" });
  if (info.created) {
    toast(
      info.invited
        ? "Демо-класс готов. Приглашение на выезд уже пришло вам в чат с ботом."
        : "Демо-класс 7Б готов: вы в нём учитель и родитель ученика.",
    );
  }
}

async function routeFromStartParam(me: Me): Promise<{ role: Role | null; stack: Route[] } | null> {
  const param = startParam();
  if (!param) return null;
  if (param === "demo") {
    await startDemo();
    return { role: "teacher", stack: [{ name: "home" }] };
  }
  if (param.startsWith("pair_")) {
    return { role: "parent", stack: [{ name: "home" }, { name: "pair", code: param.slice(5) }] };
  }
  if (param.startsWith("join_")) {
    return { role: "parent", stack: [{ name: "home" }, { name: "join", code: param.slice(5) }] };
  }
  if (param.startsWith("trip_")) {
    const tripId = Number(param.slice(5));
    if (!tripId) return null;
    if (me.user_id && me.is_parent) {
      const ctx = await api.parentContext(me.user_id).catch(() => null);
      const child = ctx?.children.find((c) => c.excursions.some((e) => e.excursion_id === tripId));
      if (child) {
        return {
          role: "parent",
          stack: [{ name: "home" }, { name: "parent-trip", excursionId: tripId, studentId: child.student_id }],
        };
      }
    }
    if (me.is_teacher) return { role: "teacher", stack: [{ name: "home" }, { name: "trip", id: tripId }] };
  }
  return null;
}

export default function App() {
  const state = useAppState();
  const [booting, setBooting] = useState(true);
  const [bootError, setBootError] = useState<string | null>(null);

  const boot = useCallback(async () => {
    setBootError(null);
    setBooting(true);
    // Сразу говорим MAX, что приложение готово: он убирает свой экран загрузки,
    // и пользователь видит наш индикатор вместо пустого окна.
    ready();
    try {
      const me = await api.me();
      setState({ me, role: pickRole(me) });
      const routed = await routeFromStartParam(me);
      if (routed) setState({ role: routed.role ?? getState().role, stack: routed.stack });
    } catch (e) {
      setBootError(errorText(e));
    } finally {
      setBooting(false);
    }
  }, []);

  useEffect(() => {
    void boot();
  }, [boot]);

  const depth = state.stack.length;
  useEffect(() => {
    setBackButton(depth > 1 ? back : null);
  }, [depth]);

  if (booting) {
    return (
      <div className="cg-app">
        <Loader label="Открываем ClassGo…" />
      </div>
    );
  }

  if (bootError) {
    return (
      <div className="cg-app">
        <div className="cg-page">
          <Notice
            tone="error"
            icon="info"
            title="Не получилось открыть ClassGo"
            action={
              <button type="button" className="cg-link" onClick={() => void boot()}>
                Попробовать ещё раз
              </button>
            }
          >
            {bootError}
          </Notice>
        </div>
      </div>
    );
  }

  const route = state.stack[depth - 1];
  const me = state.me;
  const bothRoles = Boolean(me && me.is_teacher && me.is_parent);

  // На боевом стенде без подписи MAX сервер не знает, кто вы: работаем только внутри MAX.
  if (me && !me.user_id && !isInsideMax()) {
    return (
      <div className="cg-app">
        <div className="cg-page">
          <Notice tone="info" icon="info" title="Откройте ClassGo в MAX">
            ClassGo работает внутри мессенджера MAX: там мы знаем, что это вы, и никто не ответит за вашего ребёнка.
          </Notice>
          <a className="cg-callbtn cg-mt" href={`https://max.ru/${me.bot_username}`}>
            Открыть в MAX
          </a>
        </div>
      </div>
    );
  }

  return (
    <div className="cg-app">
      {depth > 1 && !isInsideMax() && (
        <button type="button" className="cg-webback" onClick={back}>
          <Icon name="chevron" size={18} className="flip" />
          Назад
        </button>
      )}
      {bothRoles && depth === 1 && state.role && (
        <div className="cg-rolebar">
          <Segmented
            label="Роль"
            value={state.role}
            onChange={(r) => void chooseRole(r)}
            options={[
              { value: "teacher", label: "Я учитель" },
              { value: "parent", label: "Я родитель" },
            ]}
          />
        </div>
      )}
      <Screen route={route} role={state.role} />
      <Toaster />
    </div>
  );
}

function Screen({ route, role }: { route: Route; role: Role | null }) {
  switch (route.name) {
    case "trip":
      return <TripScreen id={route.id} />;
    case "new-trip":
      return <NewTrip classId={route.classId} />;
    case "class":
      return <ClassScreen id={route.id} />;
    case "new-class":
      return <NewClass />;
    case "parent-trip":
      return <ParentTrip excursionId={route.excursionId} studentId={route.studentId} />;
    case "join":
      return <JoinScreen code={route.code} />;
    case "pair":
      return <PairScreen code={route.code} />;
    default:
      if (role === "teacher") return <TeacherHome />;
      if (role === "parent") return <ParentHome />;
      return <Welcome />;
  }
}
