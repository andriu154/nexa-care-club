from datetime import datetime, timedelta
import os
from pathlib import Path
from zoneinfo import ZoneInfo
import re
import unicodedata
import json

import pandas as pd
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
CIE10_FILE = Path("app/assets/cie10.xlsx")

DOCTOR_CANONICAL = {
    "1750785220": {
        "key": "andres",
        "name": "Dr. Andrés Herrería",
        "color": "#0B4DBB",
    },
    "1312059627": {
        "key": "yiria",
        "name": "Dra. Yiria Collantes",
        "color": "#7C3AED",
    },
}

CIE10_SMART_ALIASES = {
    "itu": [
        "infeccion del tracto urinario",
        "infeccion urinaria",
        "infeccion de vias urinarias",
        "infeccion de las vias urinarias",
        "cistitis",
    ],
    "ivu": [
        "infeccion urinaria",
        "infeccion de vias urinarias",
        "infeccion del tracto urinario",
        "cistitis",
    ],
    "hta": [
        "hipertension",
        "hipertension arterial",
        "crisis hipertensiva",
    ],
    "dm": [
        "diabetes",
        "diabetes mellitus",
    ],
    "dm2": [
        "diabetes mellitus tipo 2",
        "diabetes tipo 2",
        "diabetes mellitus",
    ],
    "dm1": [
        "diabetes mellitus tipo 1",
        "diabetes tipo 1",
        "diabetes mellitus",
    ],
    "eda": [
        "diarrea",
        "gastroenteritis",
        "enfermedad diarreica aguda",
    ],
    "ira": [
        "infeccion respiratoria aguda",
        "faringitis",
        "amigdalitis",
        "resfriado comun",
    ],
    "ivrs": [
        "infeccion de vias respiratorias superiores",
        "resfriado comun",
        "faringitis",
    ],
    "lumbalgia": [
        "dolor lumbar",
        "lumbago",
    ],
    "cefalea": [
        "dolor de cabeza",
        "migraña",
        "migraña sin aura",
        "migraña con aura",
    ],
    "otitis": [
        "otitis media",
        "otitis externa",
    ],
    "faringoamigdalitis": [
        "faringitis",
        "amigdalitis",
        "infeccion de vias respiratorias superiores",
    ],
    "gripe": [
        "influenza",
        "resfriado comun",
        "infeccion respiratoria aguda",
    ],
    "neumonia": [
        "neumonia",
        "bronconeumonia",
    ],
    "asma": [
        "asma",
        "crisis asmatica",
        "broncoespasmo",
    ],
    "eca": [
        "enfermedad cerebrovascular",
        "accidente cerebrovascular",
        "ictus",
    ],
    "acv": [
        "accidente cerebrovascular",
        "ictus",
        "enfermedad cerebrovascular",
    ],
    "iam": [
        "infarto agudo de miocardio",
        "infarto",
        "sindrome coronario agudo",
    ],
    "sca": [
        "sindrome coronario agudo",
        "angina inestable",
        "infarto agudo de miocardio",
    ],
    "its": [
        "infeccion de transmision sexual",
        "uretritis",
        "gonorrea",
        "sifilis",
    ],
    "dengue": [
        "dengue",
        "fiebre por dengue",
    ],
    "covid": [
        "covid",
        "covid 19",
        "infeccion por coronavirus",
    ],
}


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


def _canonical_doctor_info(doctor: Doctor | None):
    registration = (getattr(doctor, "registration", None) or "").strip()
    name = (getattr(doctor, "name", None) or "").strip()

    if registration in DOCTOR_CANONICAL:
        item = DOCTOR_CANONICAL[registration]
        return {
            "key": item["key"],
            "name": item["name"],
            "color": item["color"],
            "registration": registration,
            "doctor_ids": [getattr(doctor, "id", None)] if doctor else [],
        }

    lowered = name.lower()
    if "miguel" in lowered or "andres" in lowered or "herrer" in lowered:
        return {
            "key": "andres",
            "name": "Dr. Andrés Herrería",
            "color": "#0B4DBB",
            "registration": registration,
            "doctor_ids": [getattr(doctor, "id", None)] if doctor else [],
        }

    if "yiria" in lowered or "collantes" in lowered:
        return {
            "key": "yiria",
            "name": "Dra. Yiria Collantes",
            "color": "#7C3AED",
            "registration": registration,
            "doctor_ids": [getattr(doctor, "id", None)] if doctor else [],
        }

    fallback_id = getattr(doctor, "id", 0) if doctor else 0
    return {
        "key": f"doctor_{fallback_id}",
        "name": name or f"Doctor #{fallback_id}",
        "color": "#0F766E",
        "registration": registration,
        "doctor_ids": [fallback_id] if fallback_id else [],
    }


def _build_dashboard_doctors(doctors: list[Doctor]):
    merged = {}

    for doctor in doctors:
        item = _canonical_doctor_info(doctor)
        key = item["key"]

        if key not in merged:
            merged[key] = {
                "key": item["key"],
                "name": item["name"],
                "color": item["color"],
                "doctor_ids": [],
                "registrations": [],
            }

        doc_id = getattr(doctor, "id", None)
        reg = (getattr(doctor, "registration", None) or "").strip()

        if doc_id and doc_id not in merged[key]["doctor_ids"]:
            merged[key]["doctor_ids"].append(doc_id)

        if reg and reg not in merged[key]["registrations"]:
            merged[key]["registrations"].append(reg)

    ordered_keys = ["andres", "yiria"]
    ordered = []

    for k in ordered_keys:
        if k in merged:
            ordered.append(merged[k])

    for k in sorted(merged.keys()):
        if k not in ordered_keys:
            ordered.append(merged[k])

    return ordered


def _appointment_matches_filter(appt: Appointment, selected_doctor_key: str | None) -> bool:
    if not selected_doctor_key:
        return True

    doctor = getattr(appt, "doctor", None)
    info = _canonical_doctor_info(doctor)
    return info["key"] == selected_doctor_key


def _is_editable(enc: Encounter) -> bool:
    if enc.ended_at is None:
        return True
    return datetime.utcnow() <= (enc.ended_at + timedelta(minutes=20))


def _norm_text(value) -> str:
    if value is None:
        return ""
    if pd.isna(value):
        return ""
    return str(value).strip()


def _strip_accents(value: str) -> str:
    value = unicodedata.normalize("NFD", value or "")
    return "".join(ch for ch in value if unicodedata.category(ch) != "Mn")


def _normalize_search_text(value: str) -> str:
    value = _norm_text(value).lower()
    value = _strip_accents(value)
    value = re.sub(r"[^a-z0-9\s\.]", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def _normalize_cie_code(value: str) -> str:
    raw = _norm_text(value).upper().replace(" ", "")
    if not raw:
        return ""

    raw_no_dot = raw.replace(".", "")

    if len(raw_no_dot) >= 4:
        return raw_no_dot[:3] + "." + raw_no_dot[3:]

    return raw


def _normalize_prescription_json(raw_value) -> str:
    if raw_value is None:
        return "[]"

    if isinstance(raw_value, str):
        raw_value = raw_value.strip()
        if not raw_value:
            return "[]"
        try:
            parsed = json.loads(raw_value)
        except Exception:
            return "[]"
    elif isinstance(raw_value, list):
        parsed = raw_value
    else:
        return "[]"

    cleaned = []
    if isinstance(parsed, list):
        for item in parsed:
            if not isinstance(item, dict):
                continue

            prescription = str(item.get("prescription") or "").strip()
            indication = str(item.get("indication") or "").strip()

            if prescription or indication:
                cleaned.append(
                    {
                        "prescription": prescription,
                        "indication": indication,
                    }
                )

    return json.dumps(cleaned, ensure_ascii=False)


def _load_cie10_data():
    items = []
    seen = set()

    if not CIE10_FILE.exists():
        print(f"⚠️ Archivo CIE-10 no encontrado: {CIE10_FILE}")
        return items

    try:
        xls = pd.ExcelFile(CIE10_FILE)

        sheet_configs = [
            ("Catálogo CIE-10 principal", "CIE PRINCIPAL", "DESCRIPCION"),
            ("Catálogo CIE-10 causa externa", "CIE CAUSA EXTERNA", "DESCRIPCION"),
        ]

        for sheet_name, code_col, desc_col in sheet_configs:
            if sheet_name not in xls.sheet_names:
                print(f"⚠️ Hoja no encontrada en CIE-10: {sheet_name}")
                continue

            df = pd.read_excel(CIE10_FILE, sheet_name=sheet_name)

            if code_col not in df.columns or desc_col not in df.columns:
                print(f"⚠️ Columnas no encontradas en hoja {sheet_name}")
                continue

            for _, row in df.iterrows():
                code_raw = _norm_text(row.get(code_col))
                desc_raw = _norm_text(row.get(desc_col))

                if not code_raw or not desc_raw:
                    continue

                code = _normalize_cie_code(code_raw)
                description = desc_raw

                key = (code.upper(), description.lower())
                if key in seen:
                    continue

                seen.add(key)
                items.append({
                    "code": code.upper(),
                    "description": description,
                })

        print(f"✅ CIE-10 cargado desde Excel: {len(items)} registros")
        return items

    except Exception as e:
        print("⚠️ Error cargando archivo CIE-10:", repr(e))
        return []


CIE10_DATA = _load_cie10_data()


def _expand_smart_query(query: str) -> list[str]:
    base = _normalize_search_text(query)
    if not base:
        return []

    variants = [base]

    compact = base.replace(" ", "")
    if compact and compact != base:
        variants.append(compact)

    alias_values = CIE10_SMART_ALIASES.get(base, [])
    for item in alias_values:
        normalized = _normalize_search_text(item)
        if normalized and normalized not in variants:
            variants.append(normalized)

    return variants


def _tokenize_query(value: str) -> list[str]:
    normalized = _normalize_search_text(value)
    if not normalized:
        return []
    return [tok for tok in normalized.split(" ") if tok]


def _search_local_cie10(query: str, limit: int = 15):
    q_raw = _norm_text(query)
    q = q_raw.upper()
    if len(q) < 2:
        return []

    q_clean_code = q.replace(".", "").replace(" ", "")
    q_text = _normalize_search_text(q_raw)
    q_tokens = _tokenize_query(q_raw)
    q_variants = _expand_smart_query(q_raw)

    scored = []
    seen = set()

    for item in CIE10_DATA:
        code = item["code"]
        desc = item["description"]

        code_clean = code.replace(".", "").replace(" ", "").upper()
        desc_norm = _normalize_search_text(desc)
        desc_tokens = set(desc_norm.split())

        score = None

        if code_clean == q_clean_code:
            score = 100
        elif code == q:
            score = 99
        elif code.startswith(q):
            score = 96
        elif code_clean.startswith(q_clean_code):
            score = 95
        elif q_text and desc_norm == q_text:
            score = 92
        elif q_text and desc_norm.startswith(q_text):
            score = 86
        else:
            best_variant_score = None

            for variant in q_variants:
                if not variant:
                    continue

                variant_tokens = [tok for tok in variant.split(" ") if tok]

                if desc_norm == variant:
                    best_variant_score = max(best_variant_score or 0, 90)
                elif desc_norm.startswith(variant):
                    best_variant_score = max(best_variant_score or 0, 84)
                elif variant in desc_norm:
                    best_variant_score = max(best_variant_score or 0, 78)
                elif variant_tokens and all(tok in desc_tokens for tok in variant_tokens):
                    best_variant_score = max(best_variant_score or 0, 72)
                elif variant_tokens:
                    overlap = sum(1 for tok in variant_tokens if tok in desc_tokens)
                    if overlap >= 2:
                        best_variant_score = max(best_variant_score or 0, 60 + overlap)

            if best_variant_score is not None:
                score = best_variant_score

        if score is None and q_tokens:
            overlap = sum(1 for tok in q_tokens if tok in desc_tokens)
            if overlap == len(q_tokens) and overlap > 0:
                score = 68
            elif overlap >= 2:
                score = 58 + overlap
            elif overlap == 1 and len(q_tokens) == 1:
                score = 52

        if score is None:
            continue

        key = (code, desc.lower())
        if key in seen:
            continue
        seen.add(key)

        scored.append((
            score,
            len(code),
            code,
            {
                "code": code,
                "description": desc,
            }
        ))

    scored.sort(key=lambda x: (-x[0], x[1], x[2]))
    return [x[3] for x in scored[:limit]]


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

    results = _search_local_cie10(query, limit=15)
    return JSONResponse({"ok": True, "results": results})


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
def ui_dashboard(
    request: Request,
    db: Session = Depends(get_db),
    date: str | None = None,
    doctor_key: str | None = None,
):
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
        .options(joinedload(Appointment.patient), joinedload(Appointment.doctor))
        .filter(Appointment.start_at >= start_dt)
        .filter(Appointment.start_at <= end_dt)
        .order_by(Appointment.start_at.asc())
        .all()
    )

    doctors_raw = db.query(Doctor).order_by(Doctor.name.asc()).all()
    doctors = _build_dashboard_doctors(doctors_raw)

    selected_doctor_key = (doctor_key or "").strip() or None
    if selected_doctor_key:
        appts = [a for a in appts if _appointment_matches_filter(a, selected_doctor_key)]

    for a in appts:
        a.can_start_now = _can_start_now(a)
        a.ui_badge = _compute_ui_badge(a)

        info = _canonical_doctor_info(getattr(a, "doctor", None))
        a.doctor_color = info["color"]
        a.doctor_name = info["name"]
        a.doctor_key = info["key"]

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
        "doctors": doctors,
        "selected_doctor_key": selected_doctor_key,
    }

    html = templates.get_template("dashboard.html").render(**ctx)
    return HTMLResponse(html)


@router.post("/appointments/{appointment_id}/start")
def ui_start_appointment(appointment_id: int, request: Request, db: Session = Depends(get_db)):
    current_doctor = _require_login(request, db)
    if not current_doctor:
        return _redirect_login()

    appt = (
        db.query(Appointment)
        .filter(Appointment.id == appointment_id)
        .filter(Appointment.doctor_id == current_doctor.id)
        .first()
    )
    if not appt:
        raise HTTPException(status_code=404, detail="Cita no encontrada")

    if appt.status in ["canceled", "no_show", "completed"]:
        raise HTTPException(status_code=400, detail="La cita no puede iniciarse")

    if appt.encounter_id:
        existing_enc = db.query(Encounter).filter(Encounter.id == appt.encounter_id).first()
        if existing_enc:
            return RedirectResponse(url=f"/app/encounters/{existing_enc.id}", status_code=302)
        appt.encounter_id = None
        db.commit()

    patient = db.query(Patient).filter(Patient.id == appt.patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Paciente no encontrado")

    enc = Encounter(
        patient_id=appt.patient_id,
        doctor_id=current_doctor.id,
        visit_type="Ambulatorio",
        chief_complaint_short=(appt.reason or "").strip()[:120],
        created_at=datetime.utcnow(),
        ended_at=None,
        is_signed=False,
        prescription_json="[]",
    )
    db.add(enc)
    db.commit()
    db.refresh(enc)

    appt.encounter_id = enc.id
    db.commit()

    return RedirectResponse(url=f"/app/encounters/{enc.id}", status_code=302)


@router.get("/patients", response_class=HTMLResponse)
def ui_patients(
    request: Request,
    db: Session = Depends(get_db),
    q: str | None = None,
):
    current_doctor = _require_login(request, db)
    if not current_doctor:
        return _redirect_login()

    search = (q or "").strip()

    query = db.query(Patient)

    if search:
        like = f"%{search}%"
        query = query.filter(
            (Patient.full_name.ilike(like)) |
            (Patient.cedula.ilike(like)) |
            (Patient.phone.ilike(like)) |
            (Patient.qr_code.ilike(like))
        )

    patients = query.order_by(Patient.id.desc()).all()

    total_patients = db.query(Patient).count()
    active_patients = db.query(Patient).filter(Patient.status == "Activo").count()

    return templates.TemplateResponse(
        "patients.html",
        {
            "request": request,
            "current_doctor": current_doctor,
            "patients": patients,
            "search": search,
            "total_patients": total_patients,
            "active_patients": active_patients,
            "result_count": len(patients),
        },
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
        prescription_json="[]",
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
    enc.prescription_json = _normalize_prescription_json(form.get("prescription_items_json"))

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