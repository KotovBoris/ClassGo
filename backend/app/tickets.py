"""Билеты от родителей: подтверждение покупки на пилоте и «все билеты класса» на входе в музей.

Родитель присылает фото, скриншот чека или PDF билета (в чат бота или из мини-приложения).
Учитель видит, у кого билет уже есть, листает билеты подряд и скачивает их одним PDF.
"""
from __future__ import annotations

import hashlib
import hmac
import io
import logging
import time as time_mod
import uuid
from datetime import datetime
from pathlib import Path

from reportlab import rl_config
from sqlmodel import Session, select

from . import services
from .config import get_settings
from .models import (
    ConsentAudit,
    ConsentStatus,
    Excursion,
    SchoolClass,
    Student,
    TicketFile,
    TicketStatus,
)

log = logging.getLogger("classgo.tickets")

# Потоки PDF — двоичные, без ASCII85: без C-ускорителя reportlab кодирует ASCII85 на чистом Python,
# и на 30 фото это ~7 из 10 секунд сборки билетов класса (а файл на 20% больше).
rl_config.useA85 = 0

MAX_TICKET_BYTES = 10 * 1024 * 1024
# Билету не нужно больше 40 Мпикс, а распаковка такой картинки съедает гигабайты памяти.
MAX_PIXELS = 40_000_000
# По длинной стороне: и на экране учителя, и на листе A4 этого хватает с запасом.
MAX_SIDE = 2400
MAX_PDF_PAGES = 10
EXTENSIONS = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "application/pdf": ".pdf"}
SOURCE_LABEL = {"bot": "в чате MAX", "miniapp": "в ClassGo", "teacher": "добавил учитель", "demo": "демо-данные"}

_FONT_PATHS = [
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ("/usr/share/fonts/dejavu/DejaVuSans.ttf", "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf"),
    ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
]


def files_dir() -> Path:
    path = Path(get_settings().FILES_DIR) / "tickets"
    path.mkdir(parents=True, exist_ok=True)
    return path


def sniff_type(content: bytes) -> str | None:
    """Тип по содержимому, а не по имени файла: расширению из чата доверять нельзя."""
    if content.startswith(b"%PDF"):
        return "application/pdf"
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp"
    return None


def normalize(content: bytes) -> tuple[bytes, str]:
    """Открываем файл целиком, а не верим первым байтам: битый или огромный файл не должен ломать PDF класса.

    Фото: поворот по EXIF, белый фон вместо прозрачного, не больше MAX_SIDE по стороне, JPEG
    (заодно пропадают EXIF с геометкой). PDF: открывается, без пароля, 1–10 страниц.
    """
    ctype = sniff_type(content)
    if ctype == "application/pdf":
        return _check_pdf(content), ctype
    if ctype in ("image/jpeg", "image/png", "image/webp"):
        return _flatten_image(content), "image/jpeg"
    raise ValueError("Нужна фотография (JPG, PNG) или PDF билета")


def _flatten_image(content: bytes) -> bytes:
    from PIL import Image, ImageOps

    try:
        with Image.open(io.BytesIO(content)) as probe:
            if probe.width * probe.height > MAX_PIXELS:
                raise Image.DecompressionBombError(f"{probe.width}x{probe.height}")
            probe.draft("RGB", (MAX_SIDE, MAX_SIDE))  # JPEG сразу читается уменьшенным
            img = ImageOps.exif_transpose(probe)
            img.load()
        if img.mode in ("RGBA", "LA", "P", "PA") or "transparency" in img.info:
            # Прозрачный фон (QR на PNG) без этого становится чёрным.
            rgba = img.convert("RGBA")
            img = Image.new("RGB", rgba.size, "white")
            img.paste(rgba, mask=rgba.getchannel("A"))
        img = img.convert("RGB")
        img.thumbnail((MAX_SIDE, MAX_SIDE))
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=85)
        return out.getvalue()
    except Image.DecompressionBombError as err:
        raise ValueError("Слишком большое изображение — пришлите скриншот билета") from err
    except Exception as err:  # noqa: BLE001
        raise ValueError("Фото не открывается — пришлите его ещё раз или скриншот билета") from err


def _check_pdf(content: bytes) -> bytes:
    """PDF без пароля и не длиннее MAX_PDF_PAGES. Защищённый только от правки (пустой пароль) — сохраняем
    расшифрованным, иначе в общий PDF класса он не встанет."""
    from pypdf import PdfReader, PdfWriter

    try:
        reader = PdfReader(io.BytesIO(content))
        locked = False
        if reader.is_encrypted:
            try:
                locked = not reader.decrypt("")
            except Exception:  # noqa: BLE001 — например, AES без библиотеки шифрования
                locked = True
        pages = 0 if locked else len(reader.pages)
        if not locked and 1 <= pages <= MAX_PDF_PAGES:
            for page in reader.pages:
                _ = page.mediabox
            if reader.is_encrypted:
                out = io.BytesIO()
                PdfWriter(clone_from=reader).write(out)
                content = out.getvalue()
    except Exception as err:  # noqa: BLE001
        raise ValueError("PDF не открывается — пришлите его ещё раз или скриншот билета") from err
    if locked:
        raise ValueError("PDF защищён паролем — пришлите без пароля или скриншот билета")
    if not 1 <= pages <= MAX_PDF_PAGES:
        raise ValueError(f"В PDF {pages} стр. — пришлите только сам билет (до {MAX_PDF_PAGES} страниц)")
    return content


def tickets_for(session: Session, excursion_id: int, student_id: int | None = None) -> list[TicketFile]:
    stmt = select(TicketFile).where(TicketFile.excursion_id == excursion_id)
    if student_id is not None:
        stmt = stmt.where(TicketFile.student_id == student_id)
    return list(session.exec(stmt.order_by(TicketFile.created_at)).all())


def save_ticket(session: Session, excursion: Excursion, student_id: int, *, content: bytes, filename: str,
                uploaded_by: int | None, source: str) -> TicketFile:
    """Сохраняет билет ребёнка (новый заменяет прежний) и отмечает, что билет куплен."""
    participant = services.get_participant(session, excursion.id, student_id)
    if participant is None:
        raise ValueError("Ученик не найден в этом выезде")
    if excursion.cancelled:
        raise ValueError("Выезд отменён — билет не нужен")
    if participant.consent_status != ConsentStatus.APPROVED:
        raise ValueError("Сначала ответьте «Да» на приглашение, потом пришлите билет")
    if not content:
        raise ValueError("Файл пустой — пришлите фото или PDF ещё раз")
    if len(content) > MAX_TICKET_BYTES:
        raise ValueError("Файл больше 10 МБ — пришлите фото или скриншот поменьше")
    content, ctype = normalize(content)

    for old in tickets_for(session, excursion.id, student_id):
        _remove_file(old)
        session.delete(old)
    stored = f"{excursion.id}/{student_id}_{uuid.uuid4().hex}{EXTENSIONS[ctype]}"
    path = files_dir() / stored
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    row = TicketFile(excursion_id=excursion.id, student_id=student_id, uploaded_by_max_user_id=uploaded_by,
                     filename=(filename or Path(stored).name)[:120], content_type=ctype, size=len(content),
                     stored_name=stored, source=source)
    session.add(row)
    participant.ticket_status = TicketStatus.PAID
    session.add(participant)
    session.add(ConsentAudit(excursion_id=excursion.id, student_id=student_id, action="TICKET_FILE",
                             source=source, parent_name=participant.signed_by_name or ""))
    session.commit()
    session.refresh(row)
    return row


def delete_uploaded_by(session: Session, user_id: int) -> int:
    """Родитель отозвал согласие: удаляем присланные им файлы билетов."""
    rows = session.exec(select(TicketFile).where(TicketFile.uploaded_by_max_user_id == user_id)).all()
    for row in rows:
        _remove_file(row)
        session.delete(row)
    if rows:
        session.commit()
    return len(rows)


def delete_where(session: Session, *conditions) -> int:
    """Билеты вместе с файлами на диске — когда удаляют ученика или демо-класс. Без commit."""
    rows = session.exec(select(TicketFile).where(*conditions)).all()
    for row in rows:
        _remove_file(row)
        session.delete(row)
    return len(rows)


def delete_ticket(session: Session, row: TicketFile, source: str = "api") -> None:
    """Удаление файла. Если покупку отметили отдельно (номер билета или «билет куплен»),
    отметка остаётся: файл был лишь подтверждением."""
    excursion = session.get(Excursion, row.excursion_id)
    _remove_file(row)
    session.delete(row)
    participant = services.get_participant(session, row.excursion_id, row.student_id)
    if participant and excursion and not tickets_for(session, row.excursion_id, row.student_id):
        marked = participant.ticket_number or session.exec(select(ConsentAudit).where(
            ConsentAudit.excursion_id == row.excursion_id, ConsentAudit.student_id == row.student_id,
            ConsentAudit.action == "TICKET_CONFIRM")).first()
        if not marked:
            participant.ticket_status = (TicketStatus.WAITING_PAYMENT if (excursion.ticket_price or 0) > 0
                                         else TicketStatus.NOT_REQUIRED)
            session.add(participant)
    session.add(ConsentAudit(excursion_id=row.excursion_id, student_id=row.student_id,
                             action="TICKET_FILE_DELETED", source=source))
    session.commit()


def read_ticket(row: TicketFile) -> bytes:
    return (files_dir() / row.stored_name).read_bytes()


def _remove_file(row: TicketFile) -> None:
    try:
        (files_dir() / row.stored_name).unlink(missing_ok=True)
    except OSError:
        log.warning("Не удалось удалить файл билета %s", row.stored_name)


# ---------------------------------------------------------------------- короткие ссылки
def _key() -> bytes:
    s = get_settings()
    return (s.DOWNLOAD_SECRET or f"classgo-download:{s.MAX_BOT_TOKEN}").encode()


def file_sig(kind: str, object_id: int, expires: int, salt: str = "") -> str:
    """salt привязывает ссылку к содержимому: номер удалённого билета может достаться чужому,
    а имя файла на диске (uuid) — нет."""
    return hmac.new(_key(), f"ticket:{kind}:{object_id}:{salt}:{expires}".encode(), hashlib.sha256).hexdigest()[:32]


def signed_ok(kind: str, object_id: int, exp: int | None, sig: str | None, salt: str = "") -> bool:
    return bool(exp and sig and sig.isascii() and exp >= time_mod.time()
                and hmac.compare_digest(sig, file_sig(kind, object_id, exp, salt)))


def pack_salt(session: Session, excursion: Excursion) -> str:
    """Ссылка на PDF класса живёт, пока не изменился набор билетов выезда, и не подходит
    к другому выезду, если номер выезда достанется заново (демо-классы удаляются)."""
    last = max((r.id for r in tickets_for(session, excursion.id)), default=0)
    return f"{excursion.created_at or ''}:{last}"


def purge_old(session: Session, days: int = 7) -> int:
    """Билеты не храним дольше недели после выезда: удаляем файлы, отметка «билет был» остаётся."""
    from datetime import date, timedelta

    edge = date.today() - timedelta(days=days)
    removed = 0
    for row in session.exec(select(TicketFile)).all():
        exc = session.get(Excursion, row.excursion_id)
        if exc and exc.event_date and exc.event_date < edge:
            _remove_file(row)
            session.delete(row)
            removed += 1
    if removed:
        session.commit()
    return removed


def pack_filename(session: Session, excursion: Excursion) -> str:
    klass = session.get(SchoolClass, excursion.class_id)
    when = excursion.event_date.strftime("%d.%m") if excursion.event_date else ""
    return "_".join(p for p in ("Билеты", klass.title if klass else "", when) if p) + ".pdf"


def signed_url(kind: str, object_id: int, ttl: int = 600, salt: str = "") -> str:
    """kind: file — один билет (salt — stored_name), pack — все билеты выезда одним PDF (salt — pack_salt)."""
    expires = int(time_mod.time()) + ttl
    base = get_settings().PUBLIC_BASE_URL.rstrip("/")
    path = f"/api/v1/tickets/{object_id}" if kind == "file" else f"/api/v1/excursions/{object_id}/tickets.pdf"
    return f"{base}{path}?exp={expires}&sig={file_sig(kind, object_id, expires, salt)}"


# ---------------------------------------------------------------------- один PDF на класс
def build_tickets_pdf(session: Session, excursion: Excursion) -> bytes:
    """Обложка, билеты по алфавиту (на каждом — чей он) и в конце лист «для учителя»:
    у кого билета нет и чей файл не открылся.

    Файл — учителю: на входе он показывает страницы с билетами. Вместо билета семья могла прислать
    чек, поэтому везде, где просим чек, напоминаем закрыть номер карты. Один битый файл не ломает
    весь PDF — он попадает в список «не открылся».
    """
    from pypdf import PdfReader, PdfWriter
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    from .documents import _fonts

    font, bold = _fonts()
    klass = session.get(SchoolClass, excursion.class_id)
    rows = tickets_for(session, excursion.id)
    by_student = {r.student_id: r for r in rows}
    going = []
    for part in excursion.participants:
        if part.consent_status != ConsentStatus.APPROVED:
            continue
        student = session.get(Student, part.student_id)
        if student:
            going.append(student)
    going.sort(key=lambda s: s.full_name)
    width, height = A4

    def caption_page(student: Student, row: TicketFile, image: bytes | None) -> bytes:
        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=A4)
        c.setFont(bold, 15)
        c.drawString(40, height - 50, student.full_name)
        c.setFont(font, 10)
        when = services.local_stamp(row.created_at, excursion.timezone) or ""
        c.drawString(40, height - 68, f"{klass.title if klass else ''} · {excursion.title} · прислан {when}, "
                                      f"{SOURCE_LABEL.get(row.source, row.source)}")
        if image is not None:
            img = ImageReader(io.BytesIO(image))
            iw, ih = img.getSize()
            box_w, box_h = width - 80, height - 120
            scale = min(box_w / iw, box_h / ih)
            c.drawImage(img, 40, height - 90 - ih * scale, iw * scale, ih * scale)
        c.showPage()
        c.save()
        return buf.getvalue()

    def ticket_pages(student: Student, row: TicketFile) -> list:
        content = read_ticket(row)
        if row.content_type == "application/pdf":
            reader = PdfReader(io.BytesIO(content))
            if reader.is_encrypted:
                reader.decrypt("")
            pages = list(reader.pages[:MAX_PDF_PAGES])
            for page in pages:
                _ = page.mediabox
            return [PdfReader(io.BytesIO(caption_page(student, row, None))).pages[0], *pages]
        return [PdfReader(io.BytesIO(caption_page(student, row, _pdf_image(content)))).pages[0]]

    included: list = []
    missing: list[str] = []
    unreadable: list[str] = []
    for student in going:
        row = by_student.get(student.id)
        if not row:
            missing.append(student.full_name)
            continue
        try:
            included.extend(ticket_pages(student, row))
        except Exception:  # noqa: BLE001 — один файл не должен ломать PDF всего класса
            log.warning("Билет %s не открылся", row.stored_name, exc_info=True)
            unreadable.append(student.full_name)
    sent = len(going) - len(missing) - len(unreadable)

    cover = io.BytesIO()
    c = canvas.Canvas(cover, pagesize=A4)
    c.setFont(bold, 18)
    c.drawString(40, height - 60, f"Билеты класса {klass.title if klass else ''}")
    c.setFont(font, 11)
    y = height - 86
    for line in (excursion.title, f"{services.local_stamp(datetime.utcnow(), excursion.timezone)} — сформировано в ClassGo",
                 f"Билетов в файле: {sent}", "Файл для учителя: на входе покажите страницы с билетами."):
        c.drawString(40, y, line)
        y -= 18
    c.showPage()
    c.save()

    tail = io.BytesIO()
    if missing or unreadable:
        t = canvas.Canvas(tail, pagesize=A4)
        t.setFont(bold, 13)
        t.drawString(40, height - 60, "Для учителя — не показывать на входе")
        t.setFont(font, 11)
        y = height - 86
        t.drawString(40, y, f"Идут: {len(going)}, билетов в файле: {sent}.")
        for title, names in (("Нет билета:", missing),
                             ("Файл не открылся — попросите прислать ещё раз:", unreadable)):
            if not names:
                continue
            y -= 26
            t.drawString(40, y, title)
            for name in names:
                y -= 16
                if y < 50:
                    t.showPage()
                    t.setFont(font, 11)
                    y = height - 50
                t.drawString(56, y, f"— {name}")
        t.showPage()
        t.save()

    writer = PdfWriter()
    for page in PdfReader(io.BytesIO(cover.getvalue())).pages:
        writer.add_page(page)
    for page in included:
        writer.add_page(page)
    if missing or unreadable:
        for page in PdfReader(io.BytesIO(tail.getvalue())).pages:
            writer.add_page(page)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def _pdf_image(content: bytes) -> bytes:
    """Картинка для страницы PDF. Новые билеты уже нормализованы при загрузке, их берём как есть;
    файлы, сохранённые раньше, приводим к тому же виду (поворот, белый фон, размер)."""
    from PIL import Image

    with Image.open(io.BytesIO(content)) as probe:
        if probe.format == "JPEG" and max(probe.size) <= MAX_SIDE and probe.getexif().get(0x0112, 1) == 1:
            return content
    return _flatten_image(content)


# ---------------------------------------------------------------------- демо
def demo_ticket_image(excursion: Excursion, student: Student) -> bytes:
    """Скриншот электронного билета, который «присылает» виртуальный родитель демо-класса.

    Устроен как настоящий мобильный билет: у спектакля и концерта — зал, ряд и место, у музея
    и экскурсии — входной билет на сеанс. Цена, посетитель, QR-код и штрихкод для однократного
    прохода. Помечен как образец: это демо-данные ClassGo.
    """
    from PIL import Image, ImageDraw, ImageFont
    from reportlab.graphics.barcode import qrencoder
    from reportlab.graphics.barcode.code128 import Code128

    def font(size: int, bold: bool = False) -> ImageFont.ImageFont:
        for regular, heavy in _FONT_PATHS:
            try:
                return ImageFont.truetype(heavy if bold else regular, size)
            except OSError:
                continue
        return ImageFont.load_default()

    sid = student.id or 0
    seed = (excursion.id or 0) * 7919 + sid * 104729
    number = f"{(excursion.id or 0) % 10000:04d} {seed % 10000:04d} {sid * 37 % 10000:04d}"
    seat = 3 + sid % 14
    row = 4 + (sid // 14) % 3
    W, H = 1080, 1860
    img = Image.new("RGB", (W, H), "#F2F3F5")
    d = ImageDraw.Draw(img)
    ink, muted, line = "#111318", "#5F6672", "#D9DCE1"

    # Карточка билета
    d.rounded_rectangle([40, 40, W - 40, H - 40], radius=36, fill="#FFFFFF")
    d.rounded_rectangle([40, 40, W - 40, 300], radius=36, fill="#1F1B3A")
    d.rectangle([40, 250, W - 40, 300], fill="#1F1B3A")
    d.text((92, 92), "ЭЛЕКТРОННЫЙ БИЛЕТ", font=font(30, True), fill="#BFB8FF")
    full_title = excursion.title or ""
    venue = (full_title.split("(", 1)[1].rstrip(")").strip() if "(" in full_title
             else (excursion.location_name or "Театр"))
    vfont = font(40, True) if d.textlength(venue, font=font(40, True)) < W - 184 else font(32, True)
    d.text((92, 140), venue, font=vfont, fill="#FFFFFF")

    title = excursion.title or "Спектакль"
    if "(" in title:
        title = title.split("(")[0].strip()
    # Зал и места бывают у спектакля и концерта; в музей и на экскурсию — входной билет на сеанс.
    seated = any(w in (full_title + " " + (excursion.location_name or "")).lower()
                 for w in ("спектакл", "концерт", "театр", "шоу", "планетари"))
    d.text((92, 200), "Большой зал" if seated else "Входной билет", font=font(28), fill="#D7D3F5")
    y = 350
    tfont, max_w = font(52, True), W - 184 - (120 if seated else 0)
    words, lines = title.split(), [""]
    for word in words:
        probe = f"{lines[-1]} {word}".strip()
        if d.textlength(probe, font=tfont) <= max_w or not lines[-1]:
            lines[-1] = probe
        else:
            lines.append(word)
    if len(lines) > 2:
        tfont, lines = font(40, True), [" ".join(words[: len(words) // 2]), " ".join(words[len(words) // 2:])]
    for i, text in enumerate(lines[:2]):
        d.text((92, y + i * 62), text, font=tfont, fill=ink)
    if seated:
        d.rounded_rectangle([W - 190, y + 6, W - 92, y + 58], radius=12, outline=ink, width=3)
        d.text((W - 141, y + 32), "6+", font=font(32, True), fill=ink, anchor="mm")
    y += 62 * (min(len(lines), 2) - 1)
    when = excursion.event_date.strftime("%d.%m.%Y") if excursion.event_date else ""
    start = "10:00"
    if getattr(excursion, "gathering_time", None):
        start = f"{(excursion.gathering_time.hour + 1) % 24:02d}:{excursion.gathering_time.minute:02d}"
    d.text((92, y + 84), f"{when} · {'начало' if seated else 'сеанс'} в {start}", font=font(34), fill=muted)

    # Сетка реквизитов
    y += 170
    d.line([92, y, W - 92, y], fill=line, width=2)
    price = f"{excursion.ticket_price or 450:.0f} ₽"
    cells = ([("Ряд", str(row)), ("Место", str(seat)), ("Цена", price), ("Категория", "Детский")] if seated
             else [("Сеанс", start), ("Посетителей", "1"), ("Цена", price), ("Категория", "Школьный")])
    col = (W - 184) // 4
    for i, (label, value) in enumerate(cells):
        x = 92 + i * col
        d.text((x, y + 28), label, font=font(26), fill=muted)
        d.text((x, y + 66), value, font=font(44, True), fill=ink)
    y += 160
    d.line([92, y, W - 92, y], fill=line, width=2)
    d.text((92, y + 28), "Посетитель", font=font(26), fill=muted)
    d.text((92, y + 66), student.full_name[:40], font=font(36, True), fill=ink)

    # QR-код (настоящий, но кодирует номер образца)
    qr = qrencoder.QRCode(4, qrencoder.QRErrorCorrectLevel.M)
    qr.addData(f"CLASSGO-DEMO-{number.replace(' ', '')}")
    qr.make()
    n = qr.getModuleCount()
    cell = 12
    size = n * cell
    qx, qy = (W - size) // 2, y + 170
    d.rounded_rectangle([qx - 36, qy - 36, qx + size + 36, qy + size + 36], radius=24, fill="#FFFFFF",
                        outline=line, width=2)
    for r in range(n):
        for c in range(n):
            if qr.isDark(r, c):
                d.rectangle([qx + c * cell, qy + r * cell, qx + (c + 1) * cell - 1, qy + (r + 1) * cell - 1], fill=ink)
    y = qy + size + 70
    num_font = font(34, True)
    tw = d.textlength(f"№ {number}", font=num_font)
    d.text(((W - tw) / 2, y), f"№ {number}", font=num_font, fill=ink)

    # Штрихкод Code128 того же номера
    bars = Code128(number.replace(" ", ""))
    bars.validate()
    bars.encode()
    pattern = bars.decompose()
    unit = 6
    total = sum(ord(ch.upper()) - 64 for ch in pattern) * unit
    bx = (W - total) // 2
    by = y + 70
    for ch in pattern:
        w = (ord(ch.upper()) - 64) * unit
        if ch.isupper():
            d.rectangle([bx, by, bx + w - 1, by + 120], fill=ink)
        bx += w

    # Правила прохода и пометка образца
    y = by + 160
    rules = ["Билет действителен для однократного прохода одного посетителя.",
             "Покажите QR-код на входе с экрана телефона или распечатайте."]
    for text in rules:
        d.text((92, y), text, font=font(26), fill=muted)
        y += 40
    mark = "ОБРАЗЕЦ · демо-данные ClassGo · для входа недействителен"
    mw = d.textlength(mark, font=font(26, True))
    d.rounded_rectangle([(W - mw) / 2 - 24, y + 24, (W + mw) / 2 + 24, y + 78], radius=27, fill="#FFF1E6")
    d.text(((W - mw) / 2, y + 32), mark, font=font(26, True), fill="#B4530B")

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
