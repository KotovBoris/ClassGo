"""Пакет документов по экскурсии — с учётом рекомендаций Минпросвещения России (письмо от 16.06.2022 № 06-836).

Состав (PDF для печати и DOCX для правки под бланк школы):
  • проект приказа об организации экскурсии (по полям прил. 1 к 06-836);
  • приложение 1 — список группы (без контактов: приказ хранится по номенклатуре дел);
  • рабочий список группы с телефонами законных представителей — для руководителя группы;
  • приложение 2 — реестр согласий: кто, когда, каким способом и на какой текст ответил;
  • приложение 3 — ведомость инструктажа (форма прил. 3) и памятка (по прил. 2);
  • бумажные бланки согласия для тех, кто ещё не ответил или не пользуется MAX;
  • образец Порядка получения согласий для администрации школы.
Документ — проект: решение принимает и подписывает директор.
"""
from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.shared import Pt
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlmodel import Session, select

from . import timeutil
from .models import (
    ConsentAudit,
    ConsentStatus,
    Excursion,
    ExcursionParticipant,
    ParentContact,
    SchoolClass,
    Student,
)

MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа",
          "сентября", "октября", "ноября", "декабря"]

# Способы ответа. Только ПЭП и бумага дают письменное согласие (прил. 2 к 06-836, п. 2.3).
METHOD = {
    "bot": "ПЭП — кнопка в чате MAX",
    "demo": "ПЭП — кнопка в чате MAX (демо)",
    "miniapp": "ПЭП — мини-приложение ClassGo",
    "api": "ПЭП — ClassGo",
    "paper": "Бумага — отметку внёс учитель",
    "call": "Устно — нужно письменное подтверждение",
    "person": "Устно — нужно письменное подтверждение",
}
WRITTEN = {"bot", "demo", "miniapp", "api", "paper", None}
AUDIT_LABEL = {"APPROVE": "Согласие", "REJECT": "Отказ", "RESET": "ответ изменён"}

MEMO = [
    "Слушай руководителя группы и сопровождающих, выполняй их указания.",
    "Не отходи от группы и не покидай место экскурсии без разрешения руководителя.",
    "Переходи дорогу только по команде руководителя, по пешеходному переходу и вместе с группой.",
    "В транспорте держись за поручни, не стой у дверей; садись и выходи только по команде руководителя.",
    "В музее и театре соблюдай правила учреждения: не трогай экспонаты без разрешения, не шуми.",
    "Одевайся по погоде, возьми воду. При плохом самочувствии сразу скажи руководителю.",
    "Не трогай бесхозные вещи и сообщи о них руководителю.",
    "При эвакуации слушай руководителя и сотрудников учреждения, сразу возвращайся к группе.",
    "Если отстал от группы — оставайся на месте и позвони руководителю (если у тебя есть телефон, "
    "заряди его и запиши номер руководителя).",
]


@dataclass
class Row:
    name: str
    birth: str
    age: str
    parent: str
    status_label: str
    phone: str
    phone_masked: str
    consent: ConsentStatus
    reason: str = ""
    signer: str = ""
    method: str = ""
    method_key: str | None = None
    signed_at: str = ""
    max_id: str = ""
    history: str = ""


@dataclass
class Pack:
    school: str
    class_title: str
    title: str
    venue: str
    address: str
    place: str
    date_long: str
    date_short: str
    weekday: bool
    gathering: str
    returning: str
    meeting_point: str
    teacher: str
    escorts: str
    transport: str
    bus: bool
    basis: str
    deadline: str
    generated: str
    tz_label: str
    doc_no: str
    invite_hash: str
    going: list[Row] = field(default_factory=list)
    oral: list[Row] = field(default_factory=list)
    not_going: list[Row] = field(default_factory=list)
    waiting: list[Row] = field(default_factory=list)


def _quoted(title: str) -> str:
    return title if "«" in title else f"«{title}»"


def _basis(text: str, class_title: str) -> str:
    """«план воспитательной работы» → «планом воспитательной работы 7Б класса» для преамбулы."""
    text = (text or "план воспитательной работы").strip()
    if text.lower().startswith("план "):
        text = "планом " + text[5:]
    return text


def _msk(value: datetime | None, seconds: bool = False, tz: str | None = None) -> str:
    """Время по часам школы (в БД — UTC)."""
    if not value:
        return "—"
    return timeutil.to_local(value, tz).strftime("%d.%m.%Y %H:%M:%S" if seconds else "%d.%m.%Y %H:%M")


def _mask(phone: str) -> str:
    digits = "".join(c for c in phone or "" if c.isdigit())
    if len(digits) < 6:
        return "—"
    return f"+{digits[0]} {digits[1]}** ***-**-{digits[-2:]}"


def _age(birth, on) -> str:
    if not birth or not on:
        return "—"
    years = on.year - birth.year - ((on.month, on.day) < (birth.month, birth.day))
    return str(years)


def invitation_hash(excursion: Excursion) -> str:
    """Хеш условий, на которые соглашается родитель: если учитель их поменяет, хеш изменится."""
    parts = [
        excursion.title, str(excursion.event_date), str(excursion.gathering_time), str(excursion.return_time),
        excursion.meeting_point or "", excursion.location_name or "", excursion.address or "",
        f"{excursion.ticket_price:.2f}", excursion.responsible_teacher or "", excursion.transport or "",
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _collect(session: Session, excursion: Excursion) -> Pack:
    klass = session.get(SchoolClass, excursion.class_id)
    parts = session.exec(
        select(ExcursionParticipant).where(ExcursionParticipant.excursion_id == excursion.id)
    ).all()
    audits = session.exec(select(ConsentAudit).where(ConsentAudit.excursion_id == excursion.id)
                          .order_by(ConsentAudit.created_at)).all()
    class_title = klass.title if klass else ""
    transport = excursion.transport or "пешком и на общественном транспорте"
    event_date = excursion.event_date
    pack = Pack(
        school=excursion.school_name or (klass.school_name if klass else "") or "Образовательная организация",
        class_title=class_title,
        title=_quoted(excursion.title),
        venue=excursion.location_name or "",
        address=excursion.address or "",
        place=", ".join(p for p in (excursion.location_name, excursion.address) if p),
        date_long=f"{event_date.day} {MONTHS[event_date.month - 1]} {event_date.year} г." if event_date else "__.__.____",
        date_short=event_date.strftime("%d.%m.%Y") if event_date else "__.__.____",
        weekday=bool(event_date and event_date.weekday() < 5),
        gathering=excursion.gathering_time.strftime("%H:%M") if excursion.gathering_time else "__:__",
        returning=excursion.return_time.strftime("%H:%M") if excursion.return_time else "__:__",
        meeting_point=excursion.meeting_point or "у главного входа школы",
        teacher=excursion.responsible_teacher or (klass.teacher_name if klass else "") or "",
        escorts=excursion.escorts or "",
        transport=transport,
        bus="автобус" in transport.lower(),
        basis=_basis(excursion.order_basis, class_title),
        deadline=_msk(excursion.deadline, tz=excursion.timezone),
        generated=_msk(datetime.utcnow(), seconds=True, tz=excursion.timezone),
        tz_label=timeutil.label(excursion.timezone),
        doc_no=f"CG-{class_title}-{event_date:%Y%m%d}-{excursion.id:03d}" if event_date else f"CG-{excursion.id:03d}",
        invite_hash=invitation_hash(excursion),
    )
    for p in parts:
        student = session.get(Student, p.student_id)
        parents = session.exec(select(ParentContact).where(ParentContact.student_id == p.student_id)).all()
        parent = next((x for x in parents if x.max_user_id), parents[0] if parents else None)
        role = (parent.role if parent else "") or "законный представитель"
        history = " → ".join(
            f"{AUDIT_LABEL.get(a.action, a.action)} {_msk(a.created_at, seconds=True, tz=excursion.timezone)[11:]}"
            for a in audits if a.student_id == p.student_id and a.action in AUDIT_LABEL
        )
        row = Row(
            name=student.full_name if student else f"#{p.student_id}",
            birth=student.birth_date.strftime("%d.%m.%Y") if student and student.birth_date else "—",
            age=_age(student.birth_date if student else None, event_date),
            parent=parent.full_name if parent and parent.full_name else "—",
            status_label=role.lower(),
            phone=parent.phone_number if parent and parent.phone_number else "—",
            phone_masked=_mask(parent.phone_number if parent else ""),
            consent=p.consent_status,
            reason=p.rejection_reason or "",
            signer=p.signed_by_name or "",
            method=METHOD.get(p.signed_source or "", "ПЭП — ClassGo"),
            method_key=p.signed_source,
            signed_at=_msk(p.signed_at, seconds=True, tz=excursion.timezone),
            max_id=str(p.signed_by_max_user_id) if p.signed_by_max_user_id else "—",
            history=history or "изменений нет",
        )
        if p.consent_status == ConsentStatus.APPROVED:
            (pack.going if p.signed_source in WRITTEN else pack.oral).append(row)
        elif p.consent_status == ConsentStatus.REJECTED:
            pack.not_going.append(row)
        else:
            pack.waiting.append(row)
    for lst in (pack.going, pack.oral, pack.not_going, pack.waiting):
        lst.sort(key=lambda r: r.name)
    return pack


def _title(pack: Pack) -> str:
    return f"Об организации экскурсии обучающихся {pack.class_title} класса в {pack.venue or 'учреждение культуры'} {pack.date_short}"


def _preamble(pack: Pack) -> str:
    return (
        "В соответствии с п. 2 ч. 6 и ч. 7 ст. 28 Федерального закона от 29.12.2012 № 273-ФЗ «Об образовании "
        "в Российской Федерации», Положением об организации экскурсий обучающихся, утверждённым приказом "
        f"от ________ № ____, {pack.basis}, с учётом методических рекомендаций Минпросвещения России "
        "(письмо от 16.06.2022 № 06-836), в целях развития познавательного интереса обучающихся"
    )


def _order_points(pack: Pack) -> list[str]:
    n = len(pack.going)
    adults = 1 + (1 if pack.escorts else 0)
    points = [
        f"Организовать {pack.date_short} с {pack.gathering} до {pack.returning} экскурсию в {pack.place} "
        f"для {n} обучающихся {pack.class_title} класса (приложение 1) в сопровождении {adults} "
        f"{'работника' if adults == 1 else 'работников'} школы. Маршрут: школа — {pack.venue or 'место экскурсии'} — школа. "
        f"Передвижение: {pack.transport}.",
        f"Руководителем группы назначить: {pack.teacher or '________________________'}, классный руководитель "
        f"{pack.class_title} класса. Возложить на руководителя группы ответственность за сохранение жизни и "
        f"здоровья обучающихся с {pack.gathering} до {pack.returning} {pack.date_short}.",
        f"Помощником руководителя группы назначить: {pack.escorts or '________________________ (ФИО, должность)'}.",
        f"Время сбора — {pack.gathering} {pack.meeting_point}; контрольное время возвращения — {pack.returning}. "
        "О прибытии к месту экскурсии и о возвращении в школу руководителю группы сообщить дежурному "
        "администратору ____________________ по телефону ____________. При задержке более 15 минут — "
        "сразу сообщить причину и новое время.",
        f"Руководителю группы: до {pack.date_short} ознакомиться с Инструкцией по охране труда при проведении "
        "экскурсий и провести с обучающимися инструктаж под подпись (приложение 3); иметь при себе копию "
        "приказа, рабочий список группы с телефонами законных представителей, аптечку первой помощи, "
        "мобильный телефон; пересчитывать обучающихся при выходе из школы, в пути, по прибытии и перед "
        "возвращением.",
        "Включить в список группы только обучающихся, на участие которых получены письменные согласия "
        "законных представителей — на бумаге или в форме электронного документа, подписанного простой "
        "электронной подписью по Порядку, утверждённому приказом от ________ № ____. Сведения о согласиях — "
        "приложение 2.",
    ]
    if pack.weekday:
        points.append(
            f"Заместителю директора по учебно-воспитательной работе ____________________ организовать "
            f"{pack.date_short} замену уроков руководителя и помощника руководителя группы, а также учебные "
            f"занятия по расписанию для обучающихся {pack.class_title} класса, не участвующих в экскурсии."
        )
    if pack.bus:
        points.append(
            "Организованную перевозку группы детей осуществить в соответствии с Правилами, утверждёнными "
            "постановлением Правительства РФ от 02.06.2026 № 680: уведомление в Госавтоинспекцию подать не "
            "позднее чем за 24 часа до начала перевозки, список по п. 13 Правил — рабочий список группы."
        )
    points.append(
        "Контроль за исполнением приказа возложить на заместителя директора по воспитательной работе "
        "____________________."
    )
    return points


AGREEMENT_TEMPLATE = [
    "Согласия законных представителей на участие обучающихся в экскурсиях принимаются на бумаге или в форме "
    "электронного документа, подписанного простой электронной подписью (ч. 2 ст. 6, ст. 9 Федерального закона "
    "от 06.04.2011 № 63-ФЗ).",
    "Электронный ответ даётся кнопкой в чат-боте или мини-приложении ClassGo в мессенджере MAX после принятия "
    "законным представителем соглашения об электронной подписи. Подписант определяется по аккаунту MAX и его "
    "номеру телефона, совпадающему с номером в данных школы.",
    "Сведения о согласиях (время, способ, идентификатор аккаунта, текст приглашения) хранятся в журнале "
    "ClassGo, в который можно только дописывать; выписка прилагается к приказу об экскурсии.",
    "Законный представитель вправе в любой момент до начала экскурсии изменить ответ, отказаться от "
    "электронной подписи и отвечать на бумаге, отозвать согласие на обработку персональных данных.",
    "Оператор персональных данных — школа; ClassGo обрабатывает данные по поручению школы на основании "
    "договора, хранение — на территории Российской Федерации.",
]


# ---------------------------------------------------------------------------- PDF
_FONTS: tuple[str, str] | None = None


def _fonts() -> tuple[str, str]:
    global _FONTS
    if _FONTS:
        return _FONTS
    pairs = [
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        ("/usr/share/fonts/dejavu/DejaVuSans.ttf", "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf"),
        ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
        ("/System/Library/Fonts/Supplemental/Arial.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
    ]
    for regular, bold in pairs:
        try:
            pdfmetrics.registerFont(TTFont("CG", regular))
            try:
                pdfmetrics.registerFont(TTFont("CG-Bold", bold))
            except Exception:  # noqa: BLE001
                pdfmetrics.registerFont(TTFont("CG-Bold", regular))
            # Семейство нужно, чтобы <b> в абзацах переключался на жирное начертание.
            pdfmetrics.registerFontFamily("CG", normal="CG", bold="CG-Bold", italic="CG", boldItalic="CG-Bold")
            _FONTS = ("CG", "CG-Bold")
            return _FONTS
        except Exception:  # noqa: BLE001
            continue
    _FONTS = ("Helvetica", "Helvetica-Bold")
    return _FONTS


def _styles() -> dict[str, ParagraphStyle]:
    font, bold = _fonts()
    base = ParagraphStyle("base", fontName=font, fontSize=11, leading=15)
    return {
        "school": ParagraphStyle("school", parent=base, fontName=bold, alignment=TA_CENTER, fontSize=11.5),
        "draft": ParagraphStyle("draft", parent=base, alignment=TA_RIGHT, fontName=bold, fontSize=10,
                                textColor=colors.HexColor("#9a2a2a")),
        "h1": ParagraphStyle("h1", parent=base, fontName=bold, fontSize=14, leading=18, alignment=TA_CENTER,
                             spaceBefore=6, spaceAfter=2),
        "h2": ParagraphStyle("h2", parent=base, fontName=bold, fontSize=12, leading=16, spaceBefore=4, spaceAfter=6),
        "center": ParagraphStyle("center", parent=base, alignment=TA_CENTER),
        "body": ParagraphStyle("body", parent=base, alignment=TA_JUSTIFY, firstLineIndent=10 * mm),
        "item": ParagraphStyle("item", parent=base, alignment=TA_LEFT, spaceBefore=3),
        "small": ParagraphStyle("small", parent=base, fontSize=9, leading=12, textColor=colors.HexColor("#444444")),
        "cell": ParagraphStyle("cell", parent=base, fontSize=9, leading=11.5),
        "cellb": ParagraphStyle("cellb", parent=base, fontName=bold, fontSize=9, leading=11.5),
        "appx": ParagraphStyle("appx", parent=base, fontSize=9.5, leading=12, alignment=TA_RIGHT),
    }


def _table(data: list[list], widths: list[float], s: dict[str, ParagraphStyle]) -> Table:
    rows = [[Paragraph(str(c), s["cellb"] if i == 0 else s["cell"]) for c in row] for i, row in enumerate(data)]
    t = Table(rows, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#9aa1ab")),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef1f5")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return t


def _appx(n: int | str, s) -> Paragraph:
    return Paragraph(f"Приложение {n} к приказу от «___» ________ 20__ г. № ____", s["appx"])


def build_order_pdf(session: Session, excursion: Excursion) -> bytes:
    pack = _collect(session, excursion)
    s = _styles()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=25 * mm, rightMargin=15 * mm,
                            topMargin=15 * mm, bottomMargin=16 * mm,
                            title=f"Проект приказа об экскурсии {pack.class_title} {pack.date_short}", author="")
    story: list = []

    # --- Проект приказа
    story += [
        Paragraph("ПРОЕКТ", s["draft"]),
        Paragraph(pack.school, s["school"]),
        Spacer(1, 6 * mm),
        Paragraph("ПРИКАЗ", s["h1"]),
        Paragraph("«___» ____________ 20__ г. &nbsp;&nbsp;&nbsp;&nbsp; г. Казань &nbsp;&nbsp;&nbsp;&nbsp; № ________",
                  s["center"]),
        Spacer(1, 4 * mm),
        Paragraph(f"<b>{_title(pack)}</b>", s["center"]),
        Spacer(1, 5 * mm),
        Paragraph(_preamble(pack) + "", s["body"]),
        Spacer(1, 2 * mm),
        Paragraph("<b>ПРИКАЗЫВАЮ:</b>", s["item"]),
    ]
    for i, text in enumerate(_order_points(pack), 1):
        story.append(Paragraph(f"{i}. {text}", s["item"]))
    story += [
        Spacer(1, 9 * mm),
        Paragraph("Директор &nbsp; ______________ &nbsp; И. О. Фамилия", s["item"]),
        Spacer(1, 6 * mm),
        Paragraph("С приказом ознакомлены:", s["item"]),
        Paragraph(f"______________ {pack.teacher or '________________'} &nbsp; «___» ________ 20__ г.", s["item"]),
        Paragraph(f"______________ {pack.escorts or '________________'} &nbsp; «___» ________ 20__ г.", s["item"]),
        Paragraph("______________ ________________ (зам. директора по ВР) &nbsp; «___» ________ 20__ г.", s["item"]),
        Spacer(1, 6 * mm),
        Paragraph(f"Исп.: {pack.teacher or '________________'}", s["small"]),
        PageBreak(),
    ]

    # --- Приложение 1. Список группы (без контактов)
    story += [
        _appx(1, s),
        Paragraph(f"Список обучающихся {pack.class_title} класса — участников экскурсии", s["h2"]),
        Paragraph(f"Экскурсия {pack.title}, {pack.date_short}, {pack.place}.", s["small"]),
        Spacer(1, 3 * mm),
    ]
    data = [["№", "ФИО обучающегося", "Класс"]]
    for i, r in enumerate(pack.going, 1):
        data.append([i, r.name, pack.class_title])
    if not pack.going:
        data.append(["", "Пока нет письменных согласий", ""])
    story.append(_table(data, [12 * mm, 120 * mm, 30 * mm], s))
    story += [
        Spacer(1, 4 * mm),
        Paragraph(f"Всего: {len(pack.going)} обучающихся. Руководитель группы: {pack.teacher or '________'}. "
                  f"Помощник руководителя: {pack.escorts or '________'}.", s["item"]),
    ]
    if pack.oral:
        story.append(Paragraph("Не включены — согласие получено устно, нужно письменное подтверждение: "
                               + ", ".join(r.name for r in pack.oral) + ".", s["small"]))
    story.append(PageBreak())

    # --- Рабочий список группы с контактами
    story += [
        Paragraph("Рабочий список группы с контактами законных представителей", s["h2"]),
        Paragraph("Для руководителя группы на время экскурсии. Не приобщается к приказу; после экскурсии "
                  "уничтожить" + (" (при автобусной перевозке — хранить 90 дней, п. 24 Правил, утв. ПП РФ № 680)."
                                  if pack.bus else "."), s["small"]),
        Spacer(1, 3 * mm),
    ]
    header = ["№", "ФИО обучающегося"] + (["Возраст"] if pack.bus else []) + ["Законный представитель", "Телефон"]
    widths = [9 * mm, 52 * mm] + ([16 * mm] if pack.bus else []) + ([60 * mm, 33 * mm] if pack.bus else [70 * mm, 39 * mm])
    data = [header]
    for i, r in enumerate(pack.going, 1):
        data.append([i, r.name] + ([r.age] if pack.bus else []) + [f"{r.parent} ({r.status_label})", r.phone])
    story.append(_table(data, widths, s))
    story += [
        Spacer(1, 3 * mm),
        Paragraph(f"Руководитель группы: {pack.teacher or '________'}, тел. ____________. "
                  f"Помощник: {pack.escorts or '________'}, тел. ____________.", s["item"]),
        PageBreak(),
    ]

    # --- Приложение 2. Реестр согласий
    story += [
        _appx(2, s),
        Paragraph("Реестр согласий законных представителей", s["h2"]),
        Paragraph(f"Сведения по состоянию на {pack.generated} (срок приёма ответов — до {pack.deadline}). "
                  f"Документ {pack.doc_no}. Текст приглашения: SHA-256 {pack.invite_hash[:16]}… "
                  "(полный хеш — в журнале ClassGo). Время — по часам школы ({pack.tz_label}).", s["small"]),
        Spacer(1, 3 * mm),
    ]
    data = [["№", "Обучающийся", "Ответ", "Подписант", "Способ", "Время ответа", "История"]]
    rows = ([(r, "Согласие") for r in pack.going + pack.oral]
            + [(r, f"Отказ: {r.reason or 'без причины'}") for r in pack.not_going])
    for i, (r, verdict) in enumerate(rows, 1):
        signer = f"{r.signer or '—'}<br/>MAX ID {r.max_id}<br/>тел. {r.phone_masked}" if r.max_id != "—" \
            else f"{r.signer or '—'}"
        data.append([i, r.name, verdict, signer, r.method, r.signed_at, r.history])
    if not rows:
        data.append(["", "Ответов пока нет", "", "", "", "", ""])
    story.append(_table(data, [9 * mm, 28 * mm, 21 * mm, 33 * mm, 27 * mm, 21 * mm, 29 * mm], s))
    if pack.waiting:
        story += [Spacer(1, 3 * mm),
                  Paragraph("Ещё не ответили: " + ", ".join(r.name for r in pack.waiting)
                            + ". Для них в пакет добавлены бумажные бланки согласия.", s["small"])]
    story += [
        Spacer(1, 3 * mm),
        Paragraph("Электронные согласия подписаны простой электронной подписью законных представителей (п. 1 "
                  "ст. 160 ГК РФ; ч. 2 ст. 6, ст. 9 Федерального закона № 63-ФЗ) в соответствии с Порядком, "
                  "утверждённым приказом от ________ № ____, и соглашением об электронной подписи (ред. 1.0). "
                  "Подписант определяется по аккаунту MAX и его номеру телефона, совпадающему с номером в данных "
                  "школы. Устные отметки учителя не являются письменным согласием.", s["small"]),
        Spacer(1, 4 * mm),
        Paragraph(f"Классный руководитель &nbsp; ______________ &nbsp; {pack.teacher or '________________'}", s["item"]),
        PageBreak(),
    ]

    # --- Приложение 3. Ведомость инструктажа + памятка
    story += [
        _appx(3, s),
        Paragraph("Ведомость проведения инструктажа по правилам поведения обучающихся на экскурсии", s["h2"]),
        Paragraph(f"Экскурсия {pack.title}, {pack.date_short}, {pack.place}. Инструктаж по Инструкции № ____, "
                  "утв. приказом от ________ № ____.", s["small"]),
        Spacer(1, 3 * mm),
    ]
    data = [["№ п/п", "ФИО инструктируемого", "Класс", "С инструкцией ознакомлен(а), подпись"]]
    for i, r in enumerate(pack.going, 1):
        data.append([i, r.name, pack.class_title, ""])
    for _ in range(max(0, 3 - len(pack.going))):
        data.append(["", "", "", ""])
    story.append(_table(data, [14 * mm, 78 * mm, 18 * mm, 58 * mm], s))
    story += [
        Spacer(1, 4 * mm),
        Paragraph(f"Присутствовало: ______ обучающихся. Дата: ________. Инструктаж провёл(а): классный "
                  f"руководитель {pack.teacher or '________________'} ______________ (подпись).", s["item"]),
        Spacer(1, 6 * mm),
        Paragraph("Памятка обучающемуся", s["h2"]),
    ]
    for i, line in enumerate(MEMO, 1):
        story.append(Paragraph(f"{i}. {line}", s["item"]))

    # --- Бумажные бланки
    if pack.waiting:
        story.append(PageBreak())
        story.append(Paragraph("Бланки согласия — для тех, кто ещё не ответил или отвечает на бумаге", s["h2"]))
        story.append(Paragraph("После возврата бланка откройте ученика в ClassGo и нажмите «Бланк: отпускают» "
                               "или «Бланк: не пойдёт». Оригинал храните вместе с приказом.", s["small"]))
        for r in pack.waiting:
            story.append(KeepTogether([
                Spacer(1, 6 * mm),
                Paragraph("<b>Согласие на участие обучающегося в экскурсии</b>", s["item"]),
                Paragraph(f"Я, ______________________________________ (ФИО), □ мать □ отец □ опекун (попечитель) "
                          f"обучающегося {pack.class_title} класса <b>{r.name}</b>, даю согласие на участие в "
                          f"экскурсии {pack.title} {pack.date_short} с {pack.gathering} до {pack.returning} "
                          f"(сбор {pack.meeting_point}; передвижение: {pack.transport}; руководитель — "
                          f"{pack.teacher or '________________'}).", s["item"]),
                Paragraph("Билет семья при желании покупает сама; школа деньги не собирает. После возвращения "
                          "в школу ребёнок □ идёт домой самостоятельно □ его встретит ____________________. "
                          "С правилами поведения на экскурсии ознакомлен(а).", s["item"]),
                Paragraph("Телефон ____________ &nbsp; Подпись __________ / ____________ &nbsp; "
                          "Дата ________", s["item"]),
                Paragraph("- - - - - - - - - - - - - - - - линия отреза - - - - - - - - - - - - - - - -", s["center"]),
            ]))

    # --- Образец Порядка для администрации
    story.append(PageBreak())
    story.append(Paragraph("Для администрации школы: образец пунктов Порядка получения согласий", s["h2"]))
    story.append(Paragraph("Включается в Положение об организации экскурсий или утверждается отдельным "
                           "приказом. Без такого Порядка ответ кнопкой не признаётся равнозначным подписи "
                           "(ч. 2 ст. 6 63-ФЗ).", s["small"]))
    for i, line in enumerate(AGREEMENT_TEMPLATE, 1):
        story.append(Paragraph(f"{i}. {line}", s["item"]))

    def footer(canvas, doc_):
        font, _ = _fonts()
        canvas.saveState()
        canvas.setFont(font, 7.5)
        canvas.setFillColor(colors.grey)
        canvas.drawString(25 * mm, 8 * mm, "Содержит персональные данные. Не пересылать в общие чаты.")
        canvas.drawRightString(A4[0] - 15 * mm, 8 * mm, f"{pack.doc_no} · стр. {doc_.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()


# ---------------------------------------------------------------------------- DOCX
def _docx_table(doc, header: list[str], rows: list[list]) -> None:
    t = doc.add_table(rows=1, cols=len(header))
    t.style = "Table Grid"
    for i, h in enumerate(header):
        cell = t.rows[0].cells[i]
        cell.text = ""
        cell.paragraphs[0].add_run(h).bold = True
    for row in rows:
        cells = t.add_row().cells
        for i, value in enumerate(row):
            cells[i].text = str(value)


def _page_break(doc) -> None:
    doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)


def build_order_docx(session: Session, excursion: Excursion) -> bytes:
    pack = _collect(session, excursion)
    doc = Document()
    normal = doc.styles["Normal"]
    normal.font.name = "Times New Roman"
    normal.font.size = Pt(12)

    def para(text: str, *, bold: bool = False, align=None, size: int | None = None):
        p = doc.add_paragraph()
        if align is not None:
            p.alignment = align
        run = p.add_run(text)
        run.bold = bold
        if size:
            run.font.size = Pt(size)
        return p

    para("ПРОЕКТ", bold=True, align=WD_ALIGN_PARAGRAPH.RIGHT)
    para(pack.school, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER)
    para("ПРИКАЗ", bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, size=14)
    para("«___» ____________ 20__ г.        г. Казань        № ________", align=WD_ALIGN_PARAGRAPH.CENTER)
    para(_title(pack), bold=True, align=WD_ALIGN_PARAGRAPH.CENTER)
    para(_preamble(pack), align=WD_ALIGN_PARAGRAPH.JUSTIFY)
    para("ПРИКАЗЫВАЮ:", bold=True)
    for i, text in enumerate(_order_points(pack), 1):
        para(f"{i}. {text}", align=WD_ALIGN_PARAGRAPH.JUSTIFY)
    para("\nДиректор ______________ И. О. Фамилия")
    para("С приказом ознакомлены:")
    para(f"______________ {pack.teacher or '________________'}  «___» ________ 20__ г.")
    para(f"______________ {pack.escorts or '________________'}  «___» ________ 20__ г.")
    para("______________ ________________ (зам. директора по ВР)  «___» ________ 20__ г.")
    para(f"Исп.: {pack.teacher}")

    _page_break(doc)
    para("Приложение 1 к приказу от «___» ________ 20__ г. № ____", align=WD_ALIGN_PARAGRAPH.RIGHT)
    para(f"Список обучающихся {pack.class_title} класса — участников экскурсии", bold=True)
    _docx_table(doc, ["№", "ФИО обучающегося", "Класс"],
                [[i, r.name, pack.class_title] for i, r in enumerate(pack.going, 1)])
    para(f"Всего: {len(pack.going)} обучающихся. Руководитель группы: {pack.teacher}. "
         f"Помощник руководителя: {pack.escorts or '________'}.")

    _page_break(doc)
    para("Рабочий список группы с контактами законных представителей", bold=True)
    para("Для руководителя группы на время экскурсии. Не приобщается к приказу; после экскурсии уничтожить.")
    _docx_table(doc, ["№", "ФИО обучающегося", "Законный представитель", "Телефон"],
                [[i, r.name, f"{r.parent} ({r.status_label})", r.phone] for i, r in enumerate(pack.going, 1)])

    _page_break(doc)
    para("Приложение 2 к приказу от «___» ________ 20__ г. № ____", align=WD_ALIGN_PARAGRAPH.RIGHT)
    para("Реестр согласий законных представителей", bold=True)
    para(f"Сведения по состоянию на {pack.generated} (срок приёма ответов — до {pack.deadline}). "
         f"Документ {pack.doc_no}. Текст приглашения: SHA-256 {pack.invite_hash}.")
    rows = ([(r, "Согласие") for r in pack.going + pack.oral]
            + [(r, f"Отказ: {r.reason or 'без причины'}") for r in pack.not_going])
    _docx_table(doc, ["№", "Обучающийся", "Ответ", "Подписант", "MAX ID", "Способ", "Время ответа", "История"],
                [[i, r.name, verdict, r.signer or "—", r.max_id, r.method, r.signed_at, r.history]
                 for i, (r, verdict) in enumerate(rows, 1)])
    if pack.waiting:
        para("Ещё не ответили: " + ", ".join(r.name for r in pack.waiting) + ".")
    para("Электронные согласия подписаны простой электронной подписью законных представителей (п. 1 ст. 160 "
         "ГК РФ; ч. 2 ст. 6, ст. 9 Федерального закона № 63-ФЗ) в соответствии с Порядком, утверждённым "
         "приказом от ________ № ____. Устные отметки учителя не являются письменным согласием.")

    _page_break(doc)
    para("Приложение 3 к приказу от «___» ________ 20__ г. № ____", align=WD_ALIGN_PARAGRAPH.RIGHT)
    para("Ведомость проведения инструктажа по правилам поведения обучающихся на экскурсии", bold=True)
    _docx_table(doc, ["№ п/п", "ФИО инструктируемого", "Класс", "С инструкцией ознакомлен(а), подпись"],
                [[i, r.name, pack.class_title, ""] for i, r in enumerate(pack.going, 1)])
    para(f"Присутствовало: ______ обучающихся. Дата: ________. Инструктаж провёл(а): {pack.teacher} ________")
    para("Памятка обучающемуся", bold=True)
    for i, line in enumerate(MEMO, 1):
        para(f"{i}. {line}")

    if pack.waiting:
        _page_break(doc)
        para("Бланки согласия — для тех, кто ещё не ответил или отвечает на бумаге", bold=True)
        for r in pack.waiting:
            para("Согласие на участие обучающегося в экскурсии", bold=True)
            para(f"Я, ______________________________ (ФИО), □ мать □ отец □ опекун (попечитель) обучающегося "
                 f"{pack.class_title} класса {r.name}, даю согласие на участие в экскурсии {pack.title} "
                 f"{pack.date_short} с {pack.gathering} до {pack.returning} (сбор {pack.meeting_point}; "
                 f"передвижение: {pack.transport}; руководитель — {pack.teacher}).")
            para("Билет семья при желании покупает сама; школа деньги не собирает. После возвращения ребёнок "
                 "□ идёт домой самостоятельно □ его встретит ______________.")
            para("Телефон ______________  Подпись ______________ / ______________  Дата ____________\n")

    _page_break(doc)
    para("Для администрации школы: образец пунктов Порядка получения согласий", bold=True)
    for i, line in enumerate(AGREEMENT_TEMPLATE, 1):
        para(f"{i}. {line}")

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
