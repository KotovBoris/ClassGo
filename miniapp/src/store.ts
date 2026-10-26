import { useEffect, useState } from "react";
import type { Me } from "./api";

export type Route =
  | { name: "home" }
  | { name: "trip"; id: number }
  | { name: "new-trip"; classId?: number }
  | { name: "class"; id: number }
  | { name: "new-class" }
  | { name: "parent-trip"; excursionId: number; studentId: number }
  | { name: "join"; code: string }
  | { name: "pair"; code: string };

export type Role = "teacher" | "parent";

export interface Toast {
  id: number;
  text: string;
  tone: "ok" | "info" | "error";
}

interface State {
  me: Me | null;
  role: Role | null;
  stack: Route[];
  toast: Toast | null;
}

let state: State = { me: null, role: null, stack: [{ name: "home" }], toast: null };
const listeners = new Set<() => void>();

function emit(): void {
  listeners.forEach((fn) => fn());
}

export function getState(): State {
  return state;
}

export function setState(patch: Partial<State>): void {
  state = { ...state, ...patch };
  emit();
}

export function useAppState(): State {
  const [, force] = useState(0);
  useEffect(() => {
    const fn = () => force((n) => n + 1);
    listeners.add(fn);
    return () => void listeners.delete(fn);
  }, []);
  return state;
}

export function push(route: Route): void {
  setState({ stack: [...state.stack, route] });
  window.scrollTo({ top: 0 });
}

export function back(): void {
  if (state.stack.length > 1) {
    setState({ stack: state.stack.slice(0, -1) });
  }
}

export function resetTo(route: Route): void {
  setState({ stack: [route] });
  window.scrollTo({ top: 0 });
}

/** Заменить текущий экран (после создания выезда — сразу на его страницу). */
export function replace(route: Route): void {
  setState({ stack: [...state.stack.slice(0, -1), route] });
  window.scrollTo({ top: 0 });
}

let toastSeq = 0;
let toastTimer: number | undefined;

export function toast(text: string, tone: Toast["tone"] = "ok"): void {
  toastSeq += 1;
  setState({ toast: { id: toastSeq, text, tone } });
  window.clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => setState({ toast: null }), tone === "error" ? 5000 : 3200);
}

export function errorText(e: unknown): string {
  return e instanceof Error ? e.message : "Что-то пошло не так. Попробуйте ещё раз.";
}
