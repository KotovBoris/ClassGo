import { deviceTimeZone } from "./format";
import { initData, webDemoUserId } from "./max";

const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? "";

export type Light = "GREEN" | "YELLOW" | "GREY" | "RED";
export type Consent = "PENDING" | "APPROVED" | "REJECTED";
export type Ticket = "NOT_REQUIRED" | "WAITING_PAYMENT" | "PAID";

export interface Me {
  user_id: number | null;
  name: string;
  auth: "max" | "demo" | "anonymous";
  role: "teacher" | "parent" | null;
  is_teacher: boolean;
  is_parent: boolean;
  has_demo: boolean;
  classes_count: number;
  children_count: number;
  terms_accepted: boolean;
  bot_username: string;
}

export interface ParentInfo {
  id: number;
  full_name: string;
  phone_number: string;
  role: string;
  confirmed: boolean;
  bot_activated: boolean;
  notifications_enabled: boolean;
}

export interface Student {
  id: number;
  full_name: string;
  birth_date: string | null;
  parent_phones: string[];
  parents: ParentInfo[];
}

export interface SchoolClass {
  id: number;
  title: string;
  school_id: number | null;
  school_number: string;
  school_name: string;
  teacher_name: string;
  teacher_phone?: string;
  chat_id: number | null;
  owner_user_id: number | null;
  can_edit: boolean;
  is_demo: boolean;
  invite_code: string | null;
  parents_connected: number;
  /** Заявки родителей «добавьте моего ребёнка», ждут подтверждения учителя */
  join_requests: number;
  /** Сколько детей в классе по журналу (класс, собранный заявками родителей) */
  expected_size: number;
  students: Student[];
}

export interface CultureEvent {
  id: number;
  title: string;
  venue: string;
  city: string;
  age_rating: string;
  event_date: string | null;
  duration_min: number;
  price: number;
  pushkin_eligible: boolean;
  is_free: boolean;
  ticket_url: string;
  address: string;
  description: string;
  source: string;
}

export interface TripStats {
  total: number;
  answered: number;
  going: number;
  not_going: number;
  waiting: number;
  waiting_ticket: number;
}

export interface Excursion {
  id: number;
  class_id: number;
  timezone: string;
  title: string;
  location_name: string;
  address: string;
  event_date: string | null;
  gathering_time: string | null;
  return_time: string | null;
  deadline: string | null;
  ticket_price: number;
  ticket_sale_url: string;
  is_pushkin_card: boolean;
  status: string;
  school_name: string;
  responsible_teacher: string;
  meeting_point: string;
  escorts: string;
  transport: string;
  departed_at: string | null;
  returned_at: string | null;
  cancelled: boolean;
  class_title: string;
  is_demo: boolean;
  class_expected_size: number;
  stats: TripStats | null;
}

export interface ParticipantRow {
  student_id: number;
  full_name: string;
  traffic_light: Light;
  consent_status: Consent;
  ticket_status: Ticket;
  bot_activated: boolean;
  parent_status: "APPROVED" | "REJECTED" | "NO_ANSWER" | "BOT_INACTIVE";
  parent_name: string | null;
  parent_role: string | null;
  parent_phone: string | null;
  signed_by_name: string | null;
  signed_by_phone: string | null;
  signed_by_max_user_id: number | null;
  signed_source: string | null;
  signed_at: string | null;
  present: boolean | null;
  rejection_reason: string | null;
  ticket_number: string | null;
  ticket_file_id: number | null;
  ticket_uploaded_at: string | null;
}

export interface Dashboard {
  excursion: Excursion;
  summary: Record<Light, number>;
  progress_percent: number;
  participants: ParticipantRow[];
}

export interface ConsentResponse {
  student_id: number;
  consent_status: Consent;
  ticket_status: Ticket;
  changed: boolean;
  message: string;
  signed_by_name?: string | null;
  signed_at?: string | null;
}

export interface ParentTrip {
  excursion_id: number;
  timezone: string;
  title: string;
  location_name: string;
  address: string;
  meeting_point: string;
  responsible_teacher: string;
  event_date: string | null;
  gathering_time: string | null;
  return_time: string | null;
  deadline: string | null;
  ticket_price: number;
  ticket_sale_url: string;
  is_pushkin_card: boolean;
  status: string;
  traffic_light: Light;
  consent_status: Consent;
  ticket_status: Ticket;
  rejection_reason: string | null;
  signed_by_name: string | null;
  signed_at: string | null;
  /** true — можно «Пушкинской картой», false — нельзя, null — возраст неизвестен */
  pushkin_ok: boolean | null;
  can_change: boolean;
  started: boolean;
  cancelled: boolean;
  returned: boolean;
  ticket_file_id: number | null;
  ticket_uploaded_at: string | null;
}

export interface ParentChild {
  student_id: number;
  student_name: string;
  birth_date: string | null;
  class_title: string;
  school_name: string;
  teacher_name: string;
  teacher_phone: string;
  is_demo: boolean;
  parent_name: string;
  parent_role: string;
  confirmed: boolean;
  notifications_enabled: boolean;
  excursions: ParentTrip[];
}

export interface DemoInfo {
  created: boolean;
  class_id: number;
  class_title: string;
  child_student_id: number | null;
  child_name: string | null;
  excursion_ids: number[];
  invited: number;
}

export interface Invite {
  class_id: number;
  code: string;
  app_link: string;
  bot_link: string;
}

export interface JoinInfo {
  code: string;
  is_demo: boolean;
  class_title: string;
  school_name: string;
  teacher_name: string;
  students_count: number;
  phones_listed: number;
}

export interface JoinResult {
  status: "linked" | "not_found" | "no_phone" | "bad_code" | "requested";
  message: string;
  children: string[];
  class_title: string | null;
}

export interface TicketItem {
  id: number;
  student_id: number;
  student_name: string;
  content_type: string;
  filename: string;
  source: string;
  uploaded_at: string;
  /** Короткая подписанная ссылка (10 минут): картинку можно показать в <img> */
  url: string;
  is_image: boolean;
}

export interface TicketsInfo {
  going: number;
  with_ticket: number;
  missing: string[];
  items: TicketItem[];
}

export interface JoinRequestItem {
  id: number;
  class_id: number;
  class_title: string;
  child_name: string;
  child_birth_date: string | null;
  parent_name: string;
  parent_role: string;
  phone_number: string;
  status: string;
  created_at: string;
  match_name: string | null;
  match_has_parent: boolean;
  /** Ученик уже в списке, и у него есть родитель: подтверждать только кнопкой «Это второй родитель» */
  needs_check: boolean;
}

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

function withUser(path: string): string {
  const uid = webDemoUserId();
  if (!uid) return path;
  return path + (path.includes("?") ? "&" : "?") + `user_id=${uid}`;
}

function headers(json = true): Record<string, string> {
  const h: Record<string, string> = {};
  if (json) h["Content-Type"] = "application/json";
  const data = initData();
  if (data) h["X-Max-Init-Data"] = data;
  const tz = deviceTimeZone();
  if (tz) h["X-Timezone"] = tz; // тихие часы напоминаний — по часам телефона родителя
  return h;
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${BASE}${withUser(path)}`, { ...init, headers: { ...headers(), ...(init?.headers ?? {}) } });
  } catch {
    throw new ApiError("Нет связи с сервером. Проверьте интернет и попробуйте ещё раз.", 0);
  }
  if (!res.ok) {
    let detail = "Что-то пошло не так. Попробуйте ещё раз.";
    try {
      const body = await res.json();
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      /* тело без JSON */
    }
    throw new ApiError(detail, res.status);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

function qs(params: Record<string, unknown>): string {
  const q = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") q.set(k, String(v));
  });
  const s = q.toString();
  return s ? `?${s}` : "";
}

const post = <T>(path: string, body?: unknown) =>
  req<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

const PHOTO_MAX_SIDE = 2400;

/** Фото с телефона весит 3–6 МБ — уменьшаем до 2400 px перед отправкой. PDF и то, что браузер
 *  не открыл, отправляем как есть: сервер сам проверит файл. */
async function shrinkPhoto(file: File): Promise<Blob> {
  if (!/^image\/(jpeg|png|webp)$/.test(file.type) || typeof createImageBitmap !== "function") return file;
  try {
    // Поворот по EXIF явно: браузер, который так не умеет, бросит ошибку — тогда отправим оригинал.
    const bitmap = await createImageBitmap(file, { imageOrientation: "from-image" });
    const scale = Math.min(1, PHOTO_MAX_SIDE / Math.max(bitmap.width, bitmap.height));
    if (scale === 1 && file.size <= 2 * 1024 * 1024) {
      bitmap.close();
      return file;
    }
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(bitmap.width * scale);
    canvas.height = Math.round(bitmap.height * scale);
    const ctx = canvas.getContext("2d");
    if (!ctx) return file;
    ctx.fillStyle = "#fff"; // прозрачный фон скриншота — белым, а не чёрным
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    bitmap.close();
    const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.85));
    return blob && blob.size < file.size ? blob : file;
  } catch {
    return file;
  }
}

export const api = {
  me: () => req<Me>("/api/v1/me"),
  setRole: (role: "teacher" | "parent") => post<Me>("/api/v1/me/role", { role }),
  acceptTerms: () => post<Me>("/api/v1/me/accept-terms"),

  demoStart: () => post<DemoInfo>("/api/v1/demo/start"),
  demoReset: () => post<DemoInfo>("/api/v1/demo/reset"),

  myClasses: () => req<SchoolClass[]>("/api/v1/classes?mine=true"),
  createClass: (payload: Record<string, unknown>) => post<SchoolClass>("/api/v1/classes", payload),
  addStudent: (classId: number, payload: Record<string, unknown>) =>
    post<Student>(`/api/v1/classes/${classId}/students`, payload),
  removeStudent: (classId: number, studentId: number) =>
    req<{ ok: boolean }>(`/api/v1/classes/${classId}/students/${studentId}`, { method: "DELETE" }),
  importClass: async (file: File, params: Record<string, unknown>) => {
    const fd = new FormData();
    fd.append("file", file);
    const res = await fetch(`${BASE}${withUser(`/api/v1/classes/import${qs(params)}`)}`, {
      method: "POST",
      body: fd,
      headers: headers(false),
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new ApiError(body.detail || "Не удалось загрузить файл", res.status);
    }
    return (await res.json()) as { class_id: number; title: string; students_created: number; skipped_rows: string[] };
  },
  invite: (classId: number) => post<Invite>(`/api/v1/classes/${classId}/invite`),

  events: () => req<CultureEvent[]>("/api/v1/culture-events"),

  myTrips: () => req<Excursion[]>("/api/v1/excursions?mine=true"),
  createTrip: (payload: Record<string, unknown>) => post<Excursion>("/api/v1/excursions", payload),
  dashboard: (id: number) => req<Dashboard>(`/api/v1/excursions/${id}/dashboard`),
  remind: (id: number) =>
    post<{ targeted: number; delivered: number; recipients: string[]; skipped_quiet: number; skipped_recent: number }>(
      `/api/v1/excursions/${id}/remind-unconfirmed`,
    ),
  sendDocuments: (id: number) => post<{ delivered: boolean; message: string }>(`/api/v1/excursions/${id}/send-documents`),
  /** Короткие подписанные ссылки на PDF/DOCX: MAX скачивает файл без заголовков авторизации. */
  orderLinks: (id: number) =>
    post<{ pdf_url: string; docx_url: string }>(`/api/v1/excursions/${id}/export-order`),

  consent: (excursionId: number, payload: Record<string, unknown>) =>
    post<ConsentResponse>(`/api/v1/excursions/${excursionId}/consent`, payload),
  resetConsent: (excursionId: number, studentId: number, asTeacher = false) =>
    post<ConsentResponse>(`/api/v1/excursions/${excursionId}/consent/reset`, {
      student_id: studentId,
      as_teacher: asTeacher,
    }),
  ticket: (excursionId: number, studentId: number) =>
    post<ConsentResponse>(`/api/v1/excursions/${excursionId}/ticket-confirm`, {
      student_id: studentId,
      source: "miniapp",
    }),

  parentContext: (userId: number) =>
    req<{ children: ParentChild[]; found: boolean }>(`/api/v1/parent/context?max_user_id=${userId}`),
  joinInfo: (code: string) => req<JoinInfo>(`/api/v1/join/${encodeURIComponent(code)}`),
  join: (payload: { code?: string | null; phone: string; auth_date?: string; hash?: string }) =>
    post<JoinResult>("/api/v1/parent/join", payload),
  setNotifications: (userId: number, enabled: boolean) =>
    post<{ ok: boolean }>("/api/v1/parent/notifications", { max_user_id: userId, enabled }),
  revoke: () => post<{ ok: boolean; unlinked: number }>("/api/v1/parent/revoke"),
  secondInvite: (studentId: number) =>
    post<{ code: string; app_link: string; bot_link: string; student_name: string }>(
      "/api/v1/parent/second-invite",
      { student_id: studentId },
    ),
  pairInfo: (code: string) =>
    req<{ code: string; student_name: string; class_title: string; invited_by: string }>(
      `/api/v1/parent/pair/${encodeURIComponent(code)}`,
    ),
  pair: (code: string) => post<JoinResult>("/api/v1/parent/pair", { code }),

  attendance: (excursionId: number, studentId: number, present: boolean | null) =>
    post<{ ok: boolean }>(`/api/v1/excursions/${excursionId}/attendance`, { student_id: studentId, present }),
  milestone: (excursionId: number, kind: "departed" | "returned") =>
    post<{ kind: string; at: string; notified: number; absent: string[] }>(
      `/api/v1/excursions/${excursionId}/milestone`,
      { kind },
    ),
  cancelTrip: (excursionId: number) => post<{ ok: boolean; notified: number }>(`/api/v1/excursions/${excursionId}/cancel`),

  uploadTicket: async (excursionId: number, studentId: number, file: File) => {
    const fd = new FormData();
    fd.append("student_id", String(studentId));
    const body = await shrinkPhoto(file);
    fd.append("file", body, body === file ? file.name : file.name.replace(/\.\w+$/, "") + ".jpg");
    let res: Response;
    try {
      res = await fetch(`${BASE}${withUser(`/api/v1/excursions/${excursionId}/tickets`)}`, {
        method: "POST",
        body: fd,
        headers: headers(false),
      });
    } catch {
      throw new ApiError("Нет связи с сервером. Проверьте интернет и попробуйте ещё раз.", 0);
    }
    if (res.status === 413) {
      throw new ApiError("Файл слишком большой — пришлите скриншот билета или PDF до 10 МБ.", 413);
    }
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new ApiError(err.detail || "Не удалось загрузить билет", res.status);
    }
    return (await res.json()) as TicketItem;
  },
  tickets: (excursionId: number) => req<TicketsInfo>(`/api/v1/excursions/${excursionId}/tickets`),
  ticketsPdf: (excursionId: number) => post<{ url: string }>(`/api/v1/excursions/${excursionId}/tickets-pdf`),
  deleteTicket: (fileId: number) => req<{ ok: boolean }>(`/api/v1/tickets/${fileId}`, { method: "DELETE" }),

  joinRequest: (payload: {
    code: string;
    child_name: string;
    birth_date?: string | null;
    role: string;
    parent_name: string;
    phone: string;
    auth_date?: string;
    hash?: string;
  }) => post<JoinResult>("/api/v1/parent/join-request", payload),
  myJoinRequests: () => req<JoinRequestItem[]>("/api/v1/parent/join-requests"),
  classJoinRequests: (classId: number) => req<JoinRequestItem[]>(`/api/v1/classes/${classId}/join-requests`),
  decideJoin: (requestId: number, approve: boolean, childName?: string, linkExisting = false) =>
    post<JoinRequestItem>(`/api/v1/join-requests/${requestId}/decide`, {
      approve,
      child_name: childName || null,
      link_existing: linkExisting,
    }),
  approveAllJoins: (classId: number) => post<JoinRequestItem[]>(`/api/v1/classes/${classId}/join-requests/approve-all`),
  sendTickets: (excursionId: number) =>
    post<{ delivered: boolean; message: string }>(`/api/v1/excursions/${excursionId}/send-tickets`),
  updateChild: (studentId: number, payload: { full_name?: string; birth_date?: string | null }) =>
    req<{ ok: boolean; changed: string[] }>(`/api/v1/parent/children/${studentId}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
};
