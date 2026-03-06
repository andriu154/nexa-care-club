from datetime import datetime, timedelta
import os
from zoneinfo import ZoneInfo
import json
import re
from html import unescape
from urllib.parse import urlencode
from urllib.request import Request as UrlRequest, urlopen

from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, joinedload

from ..database import get_db
from ..models import Appointment, Patient, Encounter, Doctor, ClinicalNote, EncounterEvolution
from .auth import get_logged_doctor

router = APIRouter(prefix="/app", tags=["UI"])
templates = Jinja2Templates(directory="app/templates")

APP_TZ = ZoneInfo(os.getenv("APP_TIMEZONE", "America/Guayaquil"))
CPOCKETS_CIE10_ROUTE = "https://cpockets.com/ajaxsearch10"


def _redirect_login():
    return RedirectResponse(url="/login", status_code=302)


def _require_login(request: Request, db: Session):
    doctor = get_logged_doctor(request, db)
    if not doctor:
        return None
    return doctor


def _parse_date(s: str | None):
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None


def _now_local_naive() -> datetime:
    return datetime.now(APP_TZ).replace(tzinfo=None)


def _can_start_now(appt: Appointment) -> bool:
    now = _now_local_naive()
    start_window = appt.start_at - timedelta(minutes=15)
    end_window = appt.end_at + timedelta(minutes=30)
    return start_window <= now <= end_window


def _compute_ui_badge(appt: Appointment) -> str:
    if appt.status == "canceled":
        return "cancelado"
    if appt.status == "no_show":
        return "cancelado_auto"
    if appt.status == "completed":
        return "completado"
    if appt.encounter_id:
        return "en_atencion"

    now = _now_local_naive()

    if now < (appt.start_at - timedelta(minutes=15)):
        return "pendiente"

    if now <= appt.end_at:
        return "a_tiempo"

    return "atrasado"


def _is_editable(enc: Encounter) -> bool:
    if enc.ended_at is None:
        return True
    return datetime.utcnow() <= (enc.ended_at + timedelta(minutes=20))


def _http_fetch_text(url: str, method: str = "GET", data: bytes | None = None) -> str:
    req = UrlRequest(
        url,
        data=data,
        method=method,
        headers={
            "User-Agent": "Mozilla/5.0 NexaCenter/1.0",
            "Accept": "application/json, text/html, */*",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        },
    )
    with urlopen(req, timeout=12) as resp:
        raw = resp.read()
        return raw.decode("utf-8", errors="ignore")


def _flatten_json_strings(obj):
    items = []

    if isinstance(obj, dict):
        for _, v in obj.items():
            items.extend(_flatten_json_strings(v))
    elif isinstance(obj, list):
        for v in obj:
            items.extend(_flatten_json_strings(v))
    elif isinstance(obj, str):
        items.append(obj)

    return items


def _extract_code_desc_from_line(line: str):
    line = " ".join((line or "").split()).strip()
    if not line:
        return None

    m = re.search(r"\b([A-TV-Z][0-9]{2}(?:\.[0-9A-Z]{1,4})?)\b", line)
    if not m:
        return None

    code = m.group(1).strip()
    desc = (line.replace(code, "", 1)).strip(" -:|•;,.")
    if len(desc) < 3:
        return None

    return {"code": code, "description": desc}


def _parse_cpockets_payload(text: str):
    results = []
    seen = set()

    def add_item(code: str, description: str):
        key = (code.strip().upper(), description.strip().lower())
        if key in seen:
            return
        seen.add(key)
        results.append({"code": code.strip().upper(), "description": description.strip()})

    try:
        obj = json.loads(text)
        strings = _flatten_json_strings(obj)
        for s in strings:
            parsed = _extract_code_desc_from_line(s)
            if parsed:
                add_item(parsed["code"], parsed["description"])
        if results:
            return results[:15]
    except Exception:
        pass

    plain = unescape(text)
    plain = re.sub(r"<br\s*/?>", "\n", plain, flags=re.I)
    plain = re.sub(r"</(p|div|li|tr|td|span|a|h[1-6])>", "\n", plain, flags=re.I)
    plain = re.sub(r"<[^>]+>", " ", plain)
    plain = re.sub(r"[ \t\r\f\v]+", " ", plain)

    for raw_line in plain.split("\n"):
        line = raw_line.strip()
        parsed = _extract_code_desc_from_line(line)
        if parsed:
            add_item(parsed["code"], parsed["description"])

    if not results:
        chunks = re.split(r"[;\n]+", plain)
        for ch in chunks:
            parsed = _extract_code_desc_from_line(ch)
            if parsed:
                add_item(parsed["code"], parsed["description"])

    return results[:15]


def _cpockets_search_cie10(query: str):
    q = (query or "").strip()
    if not q:
        return []

    param_names = ["query", "q", "term", "search", "keyword"]

    for pname in param_names:
        try:
            qs = urlencode({pname: q})
            body = _http_fetch_text(f"{CPOCKETS_CIE10_ROUTE}?{qs}", method="GET")
            parsed = _parse_cpockets_payload(body)
            if parsed:
                return parsed
        except Exception:
            pass

        try:
            data = urlencode({pname: q}).encode("utf-8")
            body = _http_fetch_text(CPOCKETS_CIE10_ROUTE, method="POST", data=data)
            parsed = _parse_cpockets_payload(body)
            if parsed:
                return parsed
        except Exception:
            pass

    return []


@router.get("/cie10/search")
def ui_cie10_search(
    request: Request,
    q: str = "",
    db: Session = Depends(get_db),
):
    current_doctor = _require_login(request, db)
    if not current_doctor:
        return JSONResponse({"ok": False, "error": "Sesión expirada"}, status_code=401)

    query = (q or "").strip()
    if len(query) < 2:
        return JSONResponse({"ok": True, "results": []})

    results = _cpockets_search_cie10(query)
    return JSONResponse({"ok": True, "results": results})


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
def ui_dashboard(request: Request, db: Session = Depends(get_db), date: str | None = None):
    current_doctor = _require_login(request, db)
    if not current_doctor:
        return _redirect_login()

    base_date = _parse_date(date) or datetime.now(APP_TZ).date()
    start_date = base_date - timedelta(days=1)
    end_date = base_date + timedelta(days=7)

    prev_date = (base_date - timedelta(days=1)).isoformat()
    next_date = (base_date + timedelta(days=1)).isoformat()

    start_dt = datetime(start_date.year, start_date.month, start_date.day, 0, 0, 0)
    end_dt = datetime(end_date.year, end_date.month, end_date.day, 23, 59, 59)

    appts = (
        db.query(Appointment)
        .options(joinedload(Appointment.patient))
        .filter(Appointment.doctor_id == current_doctor.id)
        .filter(Appointment.start_at >= start_dt)
        .filter(Appointment.start_at <= end_dt)
        .order_by(Appointment.start_at.asc())
        .all()
    )

    for a in appts:
        a.can_start_now = _can_start_now(a)
        a.ui_badge = _compute_ui_badge(a)

    days = {}
    for a in appts:
        k = a.start_at.date().isoformat()
        days.setdefault(k, []).append(a)

    ordered_days = []
    d = start_date
    while d <= end_date:
        ordered_days.append(d.isoformat())
        d += timedelta(days=1)

    ctx = {
        "request": request,
        "current_doctor": current_doctor,
        "base_date": base_date,
        "start_date": start_date,
        "end_date": end_date,
        "prev_date": prev_date,
        "next_date": next_date,
        "ordered_days": ordered_days,
        "days": days,
    }

    html = templates.get_template("dashboard.html").render(**ctx)
    return HTMLResponse(html)


@router.get("/patients", response_class=HTMLResponse)
def ui_patients(request: Request, db: Session = Depends(get_db)):
    current_doctor = _require_login(request, db)
    if not current_doctor:
        return _redirect_login()

    patients = db.query(Patient).order_by(Patient.id.desc()).all()
    return templates.TemplateResponse(
        "patients.html",
        {"request": request, "current_doctor": current_doctor, "patients": patients},
    )


@router.get("/patients/{patient_id}", response_class=HTMLResponse)
def ui_patient_detail(patient_id: int, request: Request, db: Session = Depends(get_db)):
    current_doctor = _require_login(request, db)
    if not current_doctor:
        return _redirect_login()

    patient = db.query(Patient).filter(Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Paciente no encontrado")

    encounters = (
        db.query(Encounter)
        .filter(Encounter.patient_id == patient_id)
        .order_by(Encounter.created_at.desc(), Encounter.id.desc())
        .all()
    )

    items = []
    for enc in encounters:
        doc = db.query(Doctor).filter(Doctor.id == enc.doctor_id).first()
        items.append({"enc": enc, "doc": doc, "pdf_url": f"/encounters/{enc.id}/pdf"})

    return templates.TemplateResponse(
        "patient_detail.html",
        {
            "request": request,
            "current_doctor": current_doctor,
            "patient": patient,
            "items": items,
            "pdf_consolidated_url": f"/patients/{patient.id}/history/pdf",
        },
    )


@router.post("/patients/{patient_id}/new-encounter")
def ui_new_encounter(patient_id: int, request: Request, db: Session = Depends(get_db)):
    current_doctor = _require_login(request, db)
    if not current_doctor:
        return _redirect_login()

    patient = db.query(Patient).filter(Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Paciente no encontrado")

    enc = Encounter(
        patient_id=patient.id,
        doctor_id=current_doctor.id,
        visit_type="Ambulatorio",
        chief_complaint_short="",
        created_at=datetime.utcnow(),
        ended_at=None,
        is_signed=False,
    )
    db.add(enc)
    db.commit()
    db.refresh(enc)

    return RedirectResponse(url=f"/app/encounters/{enc.id}", status_code=302)


@router.get("/encounters/{encounter_id}", response_class=HTMLResponse)
def ui_encounter(encounter_id: int, request: Request, db: Session = Depends(get_db)):
    current_doctor = _require_login(request, db)
    if not current_doctor:
        return _redirect_login()

    enc = db.query(Encounter).filter(Encounter.id == encounter_id).first()
    if not enc:
        raise HTTPException(status_code=404, detail="Consulta no encontrada")

    patient = db.query(Patient).filter(Patient.id == enc.patient_id).first()
    doc = db.query(Doctor).filter(Doctor.id == enc.doctor_id).first()

    note = db.query(ClinicalNote).filter(ClinicalNote.encounter_id == encounter_id).first()
    evols = (
        db.query(EncounterEvolution)
        .filter(EncounterEvolution.encounter_id == encounter_id)
        .order_by(EncounterEvolution.created_at.asc())
        .all()
    )

    editable_window = _is_editable(enc)
    is_owner = (enc.doctor_id == current_doctor.id)
    can_edit_note = is_owner and editable_window

    return templates.TemplateResponse(
        "encounter.html",
        {
            "request": request,
            "current_doctor": current_doctor,
            "enc": enc,
            "patient": patient,
            "doc": doc,
            "note": note,
            "evols": evols,
            "editable": editable_window,
            "is_owner": is_owner,
            "can_edit_note": can_edit_note,
            "pdf_url": f"/encounters/{enc.id}/pdf",
        },
    )


@router.post("/encounters/{encounter_id}/save-note")
async def ui_save_note(encounter_id: int, request: Request, db: Session = Depends(get_db)):
    current_doctor = _require_login(request, db)
    if not current_doctor:
        if (request.headers.get("X-Requested-With") or "").lower() == "fetch":
            return JSONResponse({"ok": False, "error": "Sesión expirada"}, status_code=401)
        return _redirect_login()

    enc = db.query(Encounter).filter(Encounter.id == encounter_id).first()
    if not enc:
        raise HTTPException(status_code=404, detail="Consulta no encontrada")

    if enc.doctor_id != current_doctor.id:
        raise HTTPException(status_code=403, detail="No autorizado")

    if not _is_editable(enc):
        raise HTTPException(
            status_code=403,
            detail="Ventana de edición cerrada (20 min). Usa Evolución/Addendum para correcciones."
        )

    form = await request.form()

    enc.chief_complaint_short = (form.get("chief_complaint_short") or "").strip()[:120]
    enc.visit_type = (form.get("visit_type") or enc.visit_type or "Ambulatorio").strip()[:50]

    note = db.query(ClinicalNote).filter(ClinicalNote.encounter_id == encounter_id).first()
    if not note:
        note = ClinicalNote(encounter_id=encounter_id)
        db.add(note)

    note.chief_complaint = (form.get("chief_complaint") or "").strip()
    note.hpi = (form.get("hpi") or "").strip()
    note.physical_exam = (form.get("physical_exam") or "").strip()
    note.complementary_tests = (form.get("complementary_tests") or "").strip()
    note.assessment_dx = (form.get("assessment_dx") or "").strip()
    note.plan_treatment = (form.get("plan_treatment") or "").strip()
    note.indications_alarm_signs = (form.get("indications_alarm_signs") or "").strip()
    note.follow_up = (form.get("follow_up") or "").strip()

    def to_int(v):
        v = (v or "").strip()
        if v == "":
            return None
        try:
            return int(v)
        except Exception:
            return None

    note.ta_sys = to_int(form.get("ta_sys"))
    note.ta_dia = to_int(form.get("ta_dia"))
    note.hr = to_int(form.get("hr"))
    note.rr = to_int(form.get("rr"))
    note.spo2 = to_int(form.get("spo2"))

    temp = (form.get("temp") or "").strip()
    note.temp = temp if temp else None

    db.commit()

    if (request.headers.get("X-Requested-With") or "").lower() == "fetch":
        return JSONResponse(
            {
                "ok": True,
                "message": "Guardado",
                "saved_at": datetime.now().strftime("%H:%M:%S"),
            }
        )

    return RedirectResponse(url=f"/app/encounters/{encounter_id}", status_code=302)


@router.post("/encounters/{encounter_id}/end")
def ui_end_encounter(encounter_id: int, request: Request, db: Session = Depends(get_db)):
    current_doctor = _require_login(request, db)
    if not current_doctor:
        return _redirect_login()

    enc = db.query(Encounter).filter(Encounter.id == encounter_id).first()
    if not enc:
        raise HTTPException(status_code=404, detail="Consulta no encontrada")

    if enc.doctor_id != current_doctor.id:
        raise HTTPException(status_code=403, detail="No autorizado")

    if enc.ended_at is None:
        enc.ended_at = datetime.utcnow()
        db.commit()

    return RedirectResponse(url=f"/app/encounters/{encounter_id}", status_code=302)


@router.post("/encounters/{encounter_id}/add-evolution")
async def ui_add_evolution(encounter_id: int, request: Request, db: Session = Depends(get_db)):
    current_doctor = _require_login(request, db)
    if not current_doctor:
        return _redirect_login()

    enc = db.query(Encounter).filter(Encounter.id == encounter_id).first()
    if not enc:
        raise HTTPException(status_code=404, detail="Consulta no encontrada")

    form = await request.form()
    content = (form.get("content") or "").strip()
    if not content:
        return RedirectResponse(url=f"/app/encounters/{encounter_id}", status_code=302)

    ev = EncounterEvolution(
        encounter_id=encounter_id,
        author_doctor_id=current_doctor.id,
        content=content,
    )
    db.add(ev)
    db.commit()

    return RedirectResponse(url=f"/app/encounters/{encounter_id}", status_code=302)