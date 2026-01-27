from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["Scanner"])

@router.get("/scan", response_class=HTMLResponse)
def scan_page():
    # HTML + JS: seleccionas doctor, abres cámara, escaneas, y hace check-in
    return """
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>Nexa Care Club - Scan</title>
  <style>
    body { font-family: Arial, sans-serif; padding: 16px; max-width: 520px; margin: 0 auto; }
    h2 { margin: 0 0 10px; }
    .card { border: 1px solid #ddd; border-radius: 14px; padding: 14px; margin: 12px 0; }
    select, button { width: 100%; padding: 12px; font-size: 16px; border-radius: 10px; border: 1px solid #ccc; }
    button { margin-top: 10px; cursor: pointer; }
    #reader { width: 100%; }
    .ok { color: #0a7; font-weight: 700; }
    .err { color: #c00; font-weight: 700; }
    .small { color: #666; font-size: 13px; }
    pre { white-space: pre-wrap; }
  </style>
</head>
<body>
  <h2>📲 Nexa Care Club — Escáner QR</h2>
  <div class="card">
    <label class="small">Selecciona el médico:</label>
    <select id="doctor">
      <option value="1">Dra. Yiria Collantes</option>
      <option value="2">Dr. Andrés Herrería</option>
    </select>
    <button id="start">Abrir cámara y escanear ✅</button>
    <button id="stop" style="display:none;">Detener cámara</button>
  </div>

  <div class="card">
    <div id="reader"></div>
    <div id="status" class="small">Listo para escanear.</div>
  </div>

  <div class="card">
    <div class="small">Resultado:</div>
    <pre id="result">—</pre>
  </div>

  <!-- Librería HTML5 QR Code (CDN) -->
  <script src="https://unpkg.com/html5-qrcode"></script>
  <script>
    const statusEl = document.getElementById("status");
    const resultEl = document.getElementById("result");
    const startBtn = document.getElementById("start");
    const stopBtn = document.getElementById("stop");
    const doctorSel = document.getElementById("doctor");

    let html5QrCode = null;

    function setStatus(msg, cls="") {
      statusEl.className = cls ? cls : "small";
      statusEl.textContent = msg;
    }

    async function doCheckin(qrText) {
      const stored = localStorage.getItem("doctor_id");
const doctorId = stored ? stored : doctorSel.value;
;
      setStatus("Registrando check-in...", "small");

      // Llama a tu endpoint: POST /checkin/{qr_code}?doctor_id=1
      const url = `/checkin/${encodeURIComponent(qrText)}?doctor_id=${encodeURIComponent(doctorId)}`;

      const res = await fetch(url, { method: "POST" });
      const data = await res.json();

      if (res.ok) {
        setStatus("✅ Check-in registrado", "ok");
      } else {
        setStatus("❌ Error en check-in", "err");
      }

      resultEl.textContent = JSON.stringify(data, null, 2);
    }

    startBtn.addEventListener("click", async () => {
      try {
        startBtn.style.display = "none";
        stopBtn.style.display = "block";
        setStatus("Abriendo cámara... permite el permiso ✅", "small");

        html5QrCode = new Html5Qrcode("reader");
        const config = { fps: 10, qrbox: { width: 260, height: 260 } };

        await html5QrCode.start(
          { facingMode: "environment" }, // cámara trasera
          config,
          async (decodedText) => {
            // Al primer scan: parar cámara y hacer check-in
            setStatus("QR detectado. Registrando...", "small");
            try {
              await html5QrCode.stop();
            } catch (e) {}
            await doCheckin(decodedText);
          }
        );

        setStatus("Cámara lista ✅ Escanea el QR del paciente", "ok");
      } catch (err) {
        startBtn.style.display = "block";
        stopBtn.style.display = "none";
        setStatus("No se pudo abrir cámara. Necesitas HTTPS o permisos.", "err");
        resultEl.textContent = String(err);
      }
    });

    stopBtn.addEventListener("click", async () => {
      try {
        if (html5QrCode) {
          await html5QrCode.stop();
          await html5QrCode.clear();
        }
      } catch (e) {}
      startBtn.style.display = "block";
      stopBtn.style.display = "none";
      setStatus("Cámara detenida.", "small");
    });
  </script>
</body>
</html>
"""
