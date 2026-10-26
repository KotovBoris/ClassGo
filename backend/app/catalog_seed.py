from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlmodel import Session, select

from .models import (
    CultureEvent,
    Excursion,
    ExcursionParticipant,
    ExcursionStatus,
    ParentContact,
    School,
    SchoolClass,
    Student,
    TicketStatus,
)

SOURCE = "PRO.Культура.РФ / «Пушкинская карта» — модельные данные (снапшот каталога, г. Казань)"

_EVENTS: list[dict] = [
    dict(title="Экскурсия «Казанский Кремль: сквозь века»", venue="Музей-заповедник «Казанский Кремль»",
         age_rating="6+", days=7, duration_min=90, price=0.0, pushkin=False, free=True,
         address="г. Казань, Кремль, 1", ticket_url="https://kazan-kremlin.ru/",
         description="Обзорная экскурсия по объекту Всемирного наследия ЮНЕСКО."),
    dict(title="Выставка «Сокровища Национального музея РТ»", venue="Национальный музей Республики Татарстан",
         age_rating="12+", days=10, duration_min=75, price=0.0, pushkin=True, free=True,
         address="г. Казань, ул. Кремлёвская, 2", ticket_url="https://tatmuseum.ru/",
         description="Постоянная экспозиция истории и культуры Татарстана. Вход по «Пушкинской карте»."),
    dict(title="Спектакль «Гөлбакча» (Театр кукол «Экият»)", venue="Татарский государственный театр кукол «Экият»",
         age_rating="6+", days=5, duration_min=70, price=450.0, pushkin=True, free=False,
         address="г. Казань, ул. Петербургская, 57", ticket_url="https://ekiyat.ru/",
         description="Музыкальная сказка для школьников."),
    dict(title="Планетарий: программа «Космос для школьников»", venue="Планетарий КФУ",
         age_rating="6+", days=4, duration_min=60, price=300.0, pushkin=True, free=False,
         address="г. Казань, ул. Кремлёвская, 18", ticket_url="https://planetarium.kpfu.ru/",
         description="Полнокупольная научно-познавательная программа."),
    dict(title="Экскурсия в Центр «Эрмитаж-Казань»", venue="Центр «Эрмитаж-Казань»",
         age_rating="12+", days=12, duration_min=80, price=500.0, pushkin=True, free=False,
         address="г. Казань, Кремль, 6", ticket_url="https://ermitage-kazan.ru/",
         description="Выставка западноевропейского искусства из собрания Эрмитажа."),
    dict(title="Литературный музей Г. Тукая", venue="Литературный музей Габдуллы Тукая",
         age_rating="12+", days=9, duration_min=60, price=250.0, pushkin=True, free=False,
         address="г. Казань, ул. Тукая, 74", ticket_url="https://tatmuseum.ru/",
         description="Экскурсия по жизни и творчеству поэта."),
    dict(title="Спектакль Татарского театра им. Г. Камала", venue="Татарский академический театр им. Г. Камала",
         age_rating="12+", days=14, duration_min=150, price=700.0, pushkin=True, free=False,
         address="г. Казань, ул. Татарстан, 1", ticket_url="https://kamalteatr.ru/",
         description="Классическая постановка национального репертуара."),
    dict(title="Дом-музей В. И. Ленина", venue="Дом-музей В. И. Ленина",
         age_rating="12+", days=6, duration_min=50, price=200.0, pushkin=True, free=False,
         address="г. Казань, ул. Ульянова-Ленина, 58", ticket_url="https://tatmuseum.ru/",
         description="Мемориальный музей, связанный с казанским периодом жизни."),
    dict(title="Научное шоу «Физика вокруг нас»", venue="Музей естественной истории Татарстана",
         age_rating="6+", days=3, duration_min=60, price=350.0, pushkin=True, free=False,
         address="г. Казань, Кремль, 5", ticket_url="https://tatmuseum.ru/",
         description="Интерактивное занятие по естественным наукам."),
    dict(title="Экскурсия «Старо-Татарская слобода»", venue="Пешеходная экскурсия по историческому центру",
         age_rating="0+", days=8, duration_min=120, price=0.0, pushkin=False, free=True,
         address="г. Казань, ул. Марджани", ticket_url="https://kazan-kremlin.ru/",
         description="Бесплатная городская пешая экскурсия (в сопровождении педагога)."),
    dict(title="Выставка «Искусство Татарстана XX века»", venue="Государственный музей изобразительных искусств РТ",
         age_rating="12+", days=11, duration_min=70, price=300.0, pushkin=True, free=False,
         address="г. Казань, ул. Карла Маркса, 64", ticket_url="https://izo-museum.ru/",
         description="Живопись и графика мастеров республики."),
    dict(title="Концерт органной музыки", venue="Государственный большой концертный зал им. С. Сайдашева",
         age_rating="12+", days=13, duration_min=90, price=400.0, pushkin=True, free=False,
         address="г. Казань, ул. Пушкина, 66", ticket_url="https://gbsk.ru/",
         description="Просветительский концерт для школьной аудитории."),
    dict(title="Экскурсия в Национальную библиотеку РТ", venue="Национальная библиотека Республики Татарстан",
         age_rating="12+", days=15, duration_min=60, price=0.0, pushkin=False, free=True,
         address="г. Казань, ул. Пушкина, 86", ticket_url="https://kitaphane.tatarstan.ru/",
         description="Знакомство с современным библиотечным пространством."),
    dict(title="Мастер-класс «Живопись для начинающих»", venue="Детская художественная школа №1",
         age_rating="6+", days=16, duration_min=90, price=600.0, pushkin=True, free=False,
         address="г. Казань, ул. Достоевского, 10", ticket_url="https://dmsh-kazan.ru/",
         description="Практическое занятие по живописи."),
    dict(title="Театрализованная программа «В гостях у сказки»", venue="Дом актёра им. М. Салимжанова",
         age_rating="6+", days=18, duration_min=60, price=350.0, pushkin=True, free=False,
         address="г. Казань, ул. Щапова, 37", ticket_url="https://domaktera.ru/",
         description="Интерактивный спектакль для младших классов."),
    dict(title="Экскурсия «Мир профессий: музей связи»", venue="Музей связи Республики Татарстан",
         age_rating="12+", days=17, duration_min=70, price=250.0, pushkin=True, free=False,
         address="г. Казань, ул. Право-Булачная, 26", ticket_url="https://tatmuseum.ru/",
         description="Профориентационная экскурсия."),
]

_DEMO_STUDENTS: list[dict] = [
    {
        "name": "Абдуллина Алия Ильдаровна",
        "birth": "2010-03-12",
        "parents": [
            {"name": "Абдуллина Гульнара Рамилевна", "phone": "+79001234501", "role": "Мама",
             "max_user_id": 1001, "confirmed": True},
            {"name": "Абдуллин Ильдар Наилевич", "phone": "+79001234502", "role": "Папа",
             "max_user_id": 1002, "confirmed": True},
        ],
    },
    {
        "name": "Абдуллин Тимур Ильдарович",
        "birth": "2012-05-04",
        "parents": [
            {"name": "Абдуллина Гульнара Рамилевна", "phone": "+79001234501", "role": "Мама",
             "max_user_id": 1001, "confirmed": True},
        ],
    },
    {
        "name": "Бикмуллин Марат Ринатович",
        "birth": "2010-01-22",
        "parents": [
            {"name": "Бикмуллин Ринат Айратович", "phone": "+79001234503", "role": "Папа",
             "max_user_id": 1003, "confirmed": False},
        ],
    },
    {
        "name": "Валеева Дина Артуровна",
        "birth": "2010-07-16",
        "parents": [
            {"name": "Валеева Эльвира Маратовна", "phone": "+79001234504", "role": "Мама"},
        ],
    },
    {
        "name": "Гайнуллин Артём Русланович",
        "birth": "2010-09-09",
        "parents": [
            {"name": "Гайнуллина Алсу Фаридовна", "phone": "+79001234505", "role": "Мама",
             "max_user_id": 1004, "confirmed": True},
        ],
    },
    {
        "name": "Егорова София Сергеевна",
        "birth": "2010-02-28",
        "parents": [
            {"name": "Егоров Сергей Николаевич", "phone": "+79001234506", "role": "Папа",
             "max_user_id": 1005, "confirmed": True},
        ],
    },
    {
        "name": "Журавлёва Мария Андреевна",
        "birth": "2010-11-11",
        "parents": [
            {"name": "Журавлёва Ольга Викторовна", "phone": "+79001234507", "role": "Мама",
             "max_user_id": 1006, "confirmed": True},
        ],
    },
    {
        "name": "Зарипов Ильназ Ленарович",
        "birth": "2010-04-19",
        "parents": [
            {"name": "Зарипова Лейсан Рустемовна", "phone": "+79001234508", "role": "Мама"},
        ],
    },
]


def seed_catalog(session: Session) -> int:
    existing = session.exec(select(CultureEvent)).first()
    if existing:
        return 0
    today = date.today()
    created = 0
    for i, e in enumerate(_EVENTS):
        session.add(
            CultureEvent(
                external_id=f"prokultura-kzn-{i + 1:03d}",
                title=e["title"],
                venue=e["venue"],
                city="Казань",
                age_rating=e["age_rating"],
                event_date=today + timedelta(days=e["days"]),
                duration_min=e["duration_min"],
                price=e["price"],
                pushkin_eligible=e["pushkin"],
                is_free=e["free"],
                ticket_url=e["ticket_url"],
                address=e["address"],
                description=e["description"],
                source=SOURCE,
            )
        )
        created += 1
    session.commit()
    return created


_DEMO_STUDENTS_5A: list[dict] = [
    {"name": "Ахметова Лия Наилевна", "birth": "2015-04-02",
     "parents": [{"name": "Ахметова Розалия Ильгизовна", "phone": "+79001234601", "role": "Мама",
                  "max_user_id": 1007, "confirmed": True}]},
    {"name": "Борисов Глеб Андреевич", "birth": "2015-08-14",
     "parents": [{"name": "Борисова Анна Павловна", "phone": "+79001234602", "role": "Мама"}]},
    {"name": "Гиниятуллина Аделя Маратовна", "birth": "2015-02-27",
     "parents": [{"name": "Гиниятуллин Марат Рафисович", "phone": "+79001234603", "role": "Папа"}]},
    {"name": "Дмитриев Лев Игоревич", "birth": "2015-06-09",
     "parents": [{"name": "Дмитриева Ксения Олеговна", "phone": "+79001234604", "role": "Мама"}]},
    {"name": "Исмагилова Ясмина Айратовна", "birth": "2015-10-21",
     "parents": [{"name": "Исмагилова Гузель Фанисовна", "phone": "+79001234605", "role": "Мама"}]},
    {"name": "Козлов Матвей Денисович", "birth": "2015-12-03",
     "parents": [{"name": "Козлов Денис Викторович", "phone": "+79001234606", "role": "Папа"}]},
]

_DEMO_STUDENTS_7V: list[dict] = [
    {"name": "Латыпова Карина Булатовна", "birth": "2013-01-17",
     "parents": [{"name": "Латыпов Булат Ирекович", "phone": "+79001234701", "role": "Папа",
                  "max_user_id": 1008, "confirmed": False}]},
    {"name": "Морозов Даниил Сергеевич", "birth": "2013-05-29",
     "parents": [{"name": "Морозова Татьяна Юрьевна", "phone": "+79001234702", "role": "Мама"}]},
    {"name": "Насырова Диляра Рамилевна", "birth": "2013-09-11",
     "parents": [{"name": "Насырова Лилия Фаритовна", "phone": "+79001234703", "role": "Мама"}]},
    {"name": "Осипов Тимофей Максимович", "birth": "2013-03-23",
     "parents": [{"name": "Осипова Марина Андреевна", "phone": "+79001234704", "role": "Мама"}]},
    {"name": "Сабирова Амелия Ленаровна", "birth": "2013-07-05",
     "parents": [{"name": "Сабиров Ленар Азатович", "phone": "+79001234705", "role": "Папа"}]},
    {"name": "Тихонов Марк Владимирович", "birth": "2013-11-16",
     "parents": [{"name": "Тихонова Елена Валерьевна", "phone": "+79001234706", "role": "Мама"}]},
]


def _get_or_create_school(session: Session, name: str, number: str) -> int:
    existing = session.exec(select(School).where(School.name == name)).first()
    if existing:
        return existing.id
    school = School(name=name, city="Казань", number=number)
    session.add(school)
    session.commit()
    session.refresh(school)
    return school.id


def _create_class(session: Session, grade: str, letter: str, school_id: int,
                  school_number: str, school_name: str, teacher_name: str,
                  teacher_phone: str, chat_id: int | None, students: list[dict]) -> int:
    klass = SchoolClass(
        grade=grade,
        letter=letter,
        school_id=school_id,
        school_number=school_number,
        school_name=school_name,
        teacher_name=teacher_name,
        teacher_phone=teacher_phone,
        chat_id=chat_id,
    )
    session.add(klass)
    session.commit()
    session.refresh(klass)
    for item in students:
        student = Student(class_id=klass.id, full_name=item["name"], birth_date=date.fromisoformat(item["birth"]))
        session.add(student)
        session.commit()
        session.refresh(student)
        for parent in item["parents"]:
            session.add(
                ParentContact(
                    student_id=student.id,
                    full_name=parent["name"],
                    phone_number=parent["phone"],
                    role=parent["role"],
                    max_user_id=parent.get("max_user_id"),
                    confirmed=parent.get("confirmed", False),
                )
            )
    session.commit()
    return klass.id


def seed_demo_class(session: Session) -> int:
    existing = session.exec(select(SchoolClass)).first()
    if existing:
        return existing.id
    gym7 = _get_or_create_school(session, "Гимназия «Демо» г. Казань (демо-данные)", "7")
    school33 = _get_or_create_school(session, "Школа №33 «Демо» г. Казань (демо-данные)", "33")
    class_8b = _create_class(
        session, "8", "Б", gym7, "7", "Гимназия «Демо» г. Казань (демо-данные)",
        "Салимова Гульнара Рифкатовна", "+79001230000", -100200300, _DEMO_STUDENTS,
    )
    _create_class(
        session, "5", "А", gym7, "7", "Гимназия «Демо» г. Казань (демо-данные)",
        "Иванова Елена Петровна", "+79001230001", None, _DEMO_STUDENTS_5A,
    )
    _create_class(
        session, "7", "В", school33, "33", "Школа №33 «Демо» г. Казань (демо-данные)",
        "Хабибуллин Марат Айратович", "+79001230002", None, _DEMO_STUDENTS_7V,
    )
    return class_8b


def seed_demo_excursion(session: Session) -> int:
    existing = session.exec(select(Excursion)).first()
    if existing:
        return existing.id
    klass = session.exec(select(SchoolClass)).first()
    if not klass:
        return 0
    event = session.exec(
        select(CultureEvent).where(CultureEvent.pushkin_eligible == True, CultureEvent.price > 0)  # noqa: E712
    ).first()
    if not event:
        event = session.exec(select(CultureEvent).where(CultureEvent.pushkin_eligible == True)).first()  # noqa: E712
    if not event:
        event = session.exec(select(CultureEvent)).first()

    today = date.today()
    excursion = Excursion(
        class_id=klass.id,
        culture_event_id=event.id if event else None,
        title=event.title if event else "Экскурсия",
        location_name=event.venue if event else "Музей",
        address=event.address if event else "г. Казань",
        event_date=today + timedelta(days=7),
        deadline=datetime.now() + timedelta(days=3),
        ticket_price=event.price if event else 0.0,
        ticket_sale_url=event.ticket_url if event else "",
        is_pushkin_card=bool(event.pushkin_eligible) if event else False,
        status=ExcursionStatus.VOTING,
        school_name=klass.school_name,
        responsible_teacher=klass.teacher_name,
        order_basis="план воспитательной работы на 2026/2027 учебный год",
    )
    session.add(excursion)
    session.commit()
    session.refresh(excursion)

    pattern = ["PAID", "WAIT", "REJECT", "PENDING", "PAID", "PENDING", "WAIT", "PAID"]
    students = session.exec(select(Student).where(Student.class_id == klass.id)).all()
    for idx, student in enumerate(students):
        parent = session.exec(
            select(ParentContact).where(ParentContact.student_id == student.id)
        ).first()
        kind = pattern[idx % len(pattern)]
        status_consent = "PENDING"
        ticket = TicketStatus.NOT_REQUIRED
        if kind == "PAID":
            status_consent = "APPROVED"
            ticket = TicketStatus.PAID if excursion.ticket_price > 0 else TicketStatus.NOT_REQUIRED
        elif kind == "WAIT":
            status_consent = "APPROVED"
            ticket = TicketStatus.WAITING_PAYMENT if excursion.ticket_price > 0 else TicketStatus.NOT_REQUIRED
        elif kind == "REJECT":
            status_consent = "REJECTED"
        part = ExcursionParticipant(
            excursion_id=excursion.id,
            student_id=student.id,
            consent_status=status_consent,
            ticket_status=ticket,
            signed_by_name=parent.full_name if status_consent != "PENDING" else None,
            signed_by_phone=parent.phone_number if status_consent != "PENDING" else None,
            signed_at=datetime.now() if status_consent != "PENDING" else None,
            rejection_reason="Личные причины" if status_consent == "REJECTED" else None,
        )
        session.add(part)
    session.commit()

    klass_5a = session.exec(
        select(SchoolClass).where(SchoolClass.grade == "5", SchoolClass.letter == "А")
    ).first()
    free_event = session.exec(
        select(CultureEvent).where(CultureEvent.is_free == True)  # noqa: E712
    ).first()
    if klass_5a and free_event:
        second = Excursion(
            class_id=klass_5a.id,
            culture_event_id=free_event.id,
            title=free_event.title,
            location_name=free_event.venue,
            address=free_event.address,
            event_date=today + timedelta(days=10),
            deadline=datetime.now() + timedelta(days=5),
            ticket_price=0.0,
            ticket_sale_url=free_event.ticket_url,
            is_pushkin_card=False,
            status=ExcursionStatus.VOTING,
            school_name=klass_5a.school_name,
            responsible_teacher=klass_5a.teacher_name,
            order_basis="план воспитательной работы на 2026/2027 учебный год",
        )
        session.add(second)
        session.commit()
        session.refresh(second)
        for st in session.exec(select(Student).where(Student.class_id == klass_5a.id)).all():
            session.add(ExcursionParticipant(
                excursion_id=second.id,
                student_id=st.id,
                consent_status="PENDING",
                ticket_status=TicketStatus.NOT_REQUIRED,
            ))
        session.commit()
    return excursion.id


def refresh_catalog_dates(session: Session, min_days_ahead: int = 3) -> int:
    """Сдвигает прошедшие события каталога вперёд, чтобы демо не устаревало.

    Каталог — модельный снапшот: даты генерируются относительно дня первого запуска.
    Чтобы через неделю в каталоге не оказались одни прошедшие события, переносим их
    на ближайшие недели, сохраняя порядок.
    """
    horizon = date.today() + timedelta(days=min_days_ahead)
    moved = 0
    for event in session.exec(select(CultureEvent)).all():
        if event.event_date and event.event_date < horizon:
            while event.event_date < horizon:
                event.event_date += timedelta(days=14)
            session.add(event)
            moved += 1
    if moved:
        session.commit()
    return moved


def seed_all(session: Session) -> dict[str, int]:
    events = seed_catalog(session)
    class_id = seed_demo_class(session)
    excursion_id = seed_demo_excursion(session)
    return {"events": events, "class_id": class_id, "excursion_id": excursion_id}
