from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from .models import AccessRole, ConsentStatus, ExcursionStatus, TicketStatus, TrafficLight


class CultureEventOut(BaseModel):
    id: int
    title: str
    venue: str
    city: str
    age_rating: str
    event_date: date | None
    duration_min: int
    price: float
    pushkin_eligible: bool
    is_free: bool
    ticket_url: str
    address: str
    description: str
    source: str


class SchoolOut(BaseModel):
    id: int
    name: str
    city: str
    number: str
    owner_user_id: int | None = None
    classes_count: int = 0


class SchoolCreate(BaseModel):
    name: str
    city: str = ""
    number: str = ""
    user_id: int | None = None


class ShareRequest(BaseModel):
    user_id: int
    role: Literal["EDIT", "READ"] = "READ"


class ShareOut(BaseModel):
    user_id: int
    role: AccessRole


class ParentOut(BaseModel):
    id: int
    full_name: str
    phone_number: str
    role: str
    confirmed: bool
    bot_activated: bool
    notifications_enabled: bool


class StudentOut(BaseModel):
    id: int
    full_name: str
    birth_date: date | None
    parent_phones: list[str] = Field(default_factory=list)
    parents: list[ParentOut] = Field(default_factory=list)


class StudentCreate(BaseModel):
    full_name: str
    birth_date: date | None = None
    parent_phone: str = ""
    parent_name: str = ""
    parent_role: str = "Законный представитель"


class ClassOut(BaseModel):
    id: int
    title: str
    school_id: int | None = None
    school_number: str
    school_name: str
    teacher_name: str
    teacher_phone: str = ""
    chat_id: int | None = None
    owner_user_id: int | None = None
    can_edit: bool = True
    is_demo: bool = False
    invite_code: str | None = None
    parents_connected: int = 0
    join_requests: int = 0
    expected_size: int = 0
    students: list[StudentOut] = Field(default_factory=list)


class ClassCreate(BaseModel):
    grade: str
    letter: str = ""
    school_id: int | None = None
    school_name: str = ""
    school_number: str = ""
    teacher_name: str = ""
    teacher_phone: str = ""
    timezone: str | None = None
    chat_id: int | None = None
    user_id: int | None = None
    expected_size: int = 0
    students: list[StudentCreate] = Field(default_factory=list)


class ClassUpdate(BaseModel):
    grade: str | None = None
    letter: str | None = None
    school_id: int | None = None
    teacher_name: str | None = None
    chat_id: int | None = None
    user_id: int | None = None


class ImportResult(BaseModel):
    class_id: int
    title: str
    students_created: int
    parents_created: int
    skipped_rows: list[str] = Field(default_factory=list)


class ExcursionCreate(BaseModel):
    class_id: int
    culture_event_id: int | None = None
    title: str | None = None
    location_name: str | None = None
    address: str | None = None
    event_date: date | None = None
    gathering_time: str | None = None
    return_time: str | None = None
    deadline: datetime | None = None
    ticket_price: float | None = None
    ticket_sale_url: str | None = None
    is_pushkin_card: bool | None = None
    order_basis: str | None = None
    meeting_point: str | None = None
    escorts: str | None = None
    transport: str | None = None
    notify_parents: bool = True


class ParticipantRow(BaseModel):
    student_id: int
    full_name: str
    traffic_light: TrafficLight
    consent_status: ConsentStatus
    ticket_status: TicketStatus
    bot_activated: bool = False
    parent_status: Literal["APPROVED", "REJECTED", "NO_ANSWER", "BOT_INACTIVE"] = "NO_ANSWER"
    parent_name: str | None = None
    parent_role: str | None = None
    parent_phone: str | None = None
    signed_by_name: str | None = None
    signed_by_phone: str | None = None
    signed_by_max_user_id: int | None = None
    signed_source: str | None = None
    signed_at: datetime | None = None
    present: bool | None = None
    rejection_reason: str | None = None
    ticket_number: str | None = None
    ticket_file_id: int | None = None
    ticket_uploaded_at: datetime | None = None


class ExcursionStats(BaseModel):
    total: int
    answered: int
    going: int
    not_going: int
    waiting: int
    waiting_ticket: int


class ExcursionOut(BaseModel):
    id: int
    class_id: int
    timezone: str = "Europe/Moscow"
    title: str
    location_name: str
    address: str
    event_date: date | None
    gathering_time: str | None
    return_time: str | None
    deadline: datetime | None
    ticket_price: float
    ticket_sale_url: str
    is_pushkin_card: bool
    status: ExcursionStatus
    school_name: str
    responsible_teacher: str
    meeting_point: str = ""
    escorts: str = ""
    transport: str = ""
    departed_at: datetime | None = None
    returned_at: datetime | None = None
    cancelled: bool = False
    class_title: str = ""
    is_demo: bool = False
    class_expected_size: int = 0
    stats: ExcursionStats | None = None


class DashboardOut(BaseModel):
    excursion: ExcursionOut
    summary: dict[str, int]
    progress_percent: int
    participants: list[ParticipantRow]


class ConsentRequest(BaseModel):
    student_id: int
    status: Literal["APPROVED", "REJECTED"]
    parent_phone: str = ""
    parent_name: str = ""
    reason: str | None = None
    source: str = "miniapp"
    max_user_id: int | None = None
    init_data: str | None = None


class ConsentResponse(BaseModel):
    student_id: int
    consent_status: ConsentStatus
    ticket_status: TicketStatus
    changed: bool
    message: str
    signed_by_name: str | None = None
    signed_at: datetime | None = None


class ConsentResetRequest(BaseModel):
    student_id: int
    as_teacher: bool = False


class TicketConfirmRequest(BaseModel):
    student_id: int
    ticket_number: str | None = None
    source: str = "miniapp"
    init_data: str | None = None


class RemindResponse(BaseModel):
    targeted: int
    delivered: int
    recipients: list[str] = Field(default_factory=list)
    skipped_quiet: int = 0   # у родителя ночь (21:00–08:00 по его времени)
    skipped_recent: int = 0  # напоминали меньше 12 часов назад


class LinkCodeOut(BaseModel):
    code: str
    deep_link: str
    student_id: int
    expires_in_min: int = 60


class DocumentOut(BaseModel):
    excursion_id: int
    docx_url: str
    pdf_url: str
    version: int
    generated_at: datetime


class ParentLinkAction(BaseModel):
    student_id: int
    max_user_id: int
    accept: bool = True


class ParentSearchRow(BaseModel):
    parent_id: int
    parent_name: str
    role: str
    phone: str
    student_id: int
    student_name: str
    class_title: str
    claimed: bool


class ParentClaimRequest(BaseModel):
    parent_id: int
    max_user_id: int


class NotificationsRequest(BaseModel):
    max_user_id: int
    enabled: bool


class MeOut(BaseModel):
    user_id: int | None
    name: str = ""
    auth: Literal["max", "demo", "anonymous"] = "anonymous"
    role: Literal["teacher", "parent"] | None = None
    is_teacher: bool = False
    is_parent: bool = False
    has_demo: bool = False
    classes_count: int = 0
    children_count: int = 0
    terms_accepted: bool = False
    bot_username: str = ""


class RoleRequest(BaseModel):
    role: Literal["teacher", "parent"]


class DemoOut(BaseModel):
    created: bool
    class_id: int
    class_title: str
    child_student_id: int | None = None
    child_name: str | None = None
    excursion_ids: list[int] = Field(default_factory=list)
    invited: int = 0


class InviteOut(BaseModel):
    class_id: int
    code: str
    app_link: str
    bot_link: str


class JoinRequest(BaseModel):
    code: str | None = None
    phone: str = ""
    # Подпись номера из WebApp.requestContact(): {phone, authDate, hash}
    auth_date: str | None = None
    hash: str | None = None


class JoinInfoOut(BaseModel):
    code: str
    is_demo: bool = False
    class_title: str
    school_name: str
    teacher_name: str
    students_count: int
    # Сколько родителей в списке класса с номером: 0 — сверять не с чем, родитель сразу вписывает ребёнка.
    phones_listed: int = 0


class JoinOut(BaseModel):
    status: Literal["linked", "not_found", "no_phone", "bad_code", "requested"]
    message: str
    children: list[str] = Field(default_factory=list)
    class_title: str | None = None


class SendDocumentsOut(BaseModel):
    delivered: bool
    message: str


class SecondParentInviteRequest(BaseModel):
    student_id: int


class SecondParentInviteOut(BaseModel):
    code: str
    app_link: str
    bot_link: str
    student_name: str


class PairRequest(BaseModel):
    code: str


class PairInfoOut(BaseModel):
    code: str
    student_name: str
    class_title: str
    invited_by: str


class AttendanceRequest(BaseModel):
    student_id: int
    present: bool | None


class MilestoneRequest(BaseModel):
    kind: Literal["departed", "returned"]


class MilestoneOut(BaseModel):
    kind: str
    at: datetime
    notified: int
    absent: list[str] = Field(default_factory=list)


class TicketOut(BaseModel):
    id: int
    student_id: int
    student_name: str
    content_type: str
    filename: str
    source: str
    uploaded_at: datetime
    url: str
    is_image: bool


class TicketsOut(BaseModel):
    going: int
    with_ticket: int
    missing: list[str] = Field(default_factory=list)
    items: list[TicketOut] = Field(default_factory=list)


class LinkOut(BaseModel):
    url: str


class ChildJoinRequestIn(BaseModel):
    code: str
    child_name: str
    birth_date: date | None = None
    role: str = "Родитель"
    parent_name: str = ""
    phone: str = ""
    auth_date: str | None = None
    hash: str | None = None


class ChildJoinRequestOut(BaseModel):
    id: int
    class_id: int
    class_title: str = ""
    child_name: str
    child_birth_date: date | None = None
    parent_name: str
    parent_role: str
    phone_number: str
    status: str
    created_at: datetime
    # Ученик из списка, на которого похожа заявка: учитель видит, к кому привяжется родитель
    match_name: str | None = None
    match_has_parent: bool = False
    # Ученик уже в списке и у него есть родитель, а заявка не по ссылке от этого родителя:
    # подтверждать только отдельно, кнопкой «Это второй родитель»
    needs_check: bool = False


class JoinDecision(BaseModel):
    approve: bool
    child_name: str | None = None
    # Учитель явно подтвердил: заявитель — второй родитель ученика, который уже есть в списке
    link_existing: bool = False


class ChildUpdate(BaseModel):
    full_name: str | None = None
    birth_date: date | None = None
