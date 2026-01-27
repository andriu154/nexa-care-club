from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["UI"])

@router.get("/app", response_class=HTMLResponse)
def app_home():
    return """
<!doctype html>
<html>
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>Nexa Care Club</title>
  <style>
    body{font-family:Arial,sans-serif;background:#fafafa;margin:0}
    .wrap{max-width:520px;margin:0 auto;padding:16px}
    .card{background:#fff;border:1px solid #e7e7e7;border-radius:16px;padding:16px;margin:12px 0;box-shadow:0 2px 8px rgba(0,0,0,.04)}
    h2{margin:0 0 10px}
    label{display:block;margin:10px 0 6px;color:#555;font-size:14px}
    select,input,button{width:100%;padding:14px;font-size:16px;border-radius:12px;border:1px solid #ccc}
    button{border:none;background:#111;color:#fff;font-weight:700;margin-top:12px;cursor:pointer}
    .small{color:#666;font-size:13px}
    .ok{color:#0a7;font-weight:700}
    .err{color:#c00;font-weight:700}
  </style>
</head>
<body>
<div class="wrap">
  <div class="card">
    <h2>🩺 Nexa Care Club</h2>
    <div class="small">Ingreso rápido para consulta (tablet/celular).</div>
  </div>

  <div class="card">
    <h2>🔐 Login Médico</h2>

    <label>Médico</label>
    <select id="doctor">
      <option value="1">Dra. Yiria Collantes</option>
      <option value="2">Dr. Andrés Herrería</option>
    </select>

    <label>PIN</label>
    <input id="pin" type="password" placeholder="Ej: 1234" inputmode="numeric"/>

    <button id="login">Ingresar ✅</button>
    <div id="status" class="small" style="margin-top:10px;">—</div>
  </div>

  <div class="card" id="scanCard" style="display:none;">
    <h2>📲 Escanear QR</h2>
    <div class="small">Cuando estés lista, abre la cámara y escanea el QR del paciente.</div>
    <button id="goScan">Abrir escáner</button>
  </div>
</div>

<script>
  const statusEl = document.getElementById("status");
  const scanCard = document.getElementById("scanCard");

  function setStatus(msg, cls="small") {
    statusEl.className = cls;
    statusEl.textContent = msg;
  }

  document.getElementById("login").addEventListener("click", async () => {
    const doctor_id = Number(document.getElementById("doctor").value);
    const pin = document.getElementById("pin").value.trim();

    if (!pin) {
      setStatus("Escribe tu PIN 🙏", "err");
      return;
    }

    setStatus("Validando...", "small");

    const res = await fetch("/auth/login", {
      method: "POST",
      headers: {"Content-Type":"application/json"},
      body: JSON.stringify({doctor_id, pin})
    });

    const data = await res.json();

    if (res.ok) {
      setStatus("✅ Login exitoso. Lista para escanear.", "ok");
      // Guardamos doctor_id en el navegador
      localStorage.setItem("doctor_id", String(doctor_id));
      scanCard.style.display = "block";
    } else {
      setStatus("❌ " + (data.detail || "No se pudo iniciar sesión"), "err");
      scanCard.style.display = "none";
    }
  });

  document.getElementById("goScan").addEventListener("click", () => {
    window.location.href = "/scan";
  });
</script>
</body>
</html>
"""
