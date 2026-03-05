// app/static/app.js

function ncOpenModal() {
  const modal = document.getElementById("nc-modal");
  modal.classList.add("open");
  modal.setAttribute("aria-hidden", "false");
  document.body.classList.add("nc-modal-lock");
}

function ncCloseModal() {
  const modal = document.getElementById("nc-modal");
  modal.classList.remove("open");
  modal.setAttribute("aria-hidden", "true");
  document.body.classList.remove("nc-modal-lock");
}

async function ncLoadIntoModal(url) {
  ncOpenModal();

  const body = document.getElementById("nc-modal-body");
  body.innerHTML = `<div class="nc-spinner">Cargando...</div>`;

  const res = await fetch(url, {
    headers: { "X-Requested-With": "fetch" }
  });

  body.innerHTML = await res.text();

  // Si el contenido trae un form, lo interceptamos para enviarlo por fetch
  const form = body.querySelector("form");
  if (form) {
    form.addEventListener("submit", async (e) => {
      e.preventDefault();

      const fd = new FormData(form);
      const action = form.getAttribute("action") || url;
      const method = (form.getAttribute("method") || "POST").toUpperCase();

      const r = await fetch(action, {
        method,
        body: fd,
        headers: { "X-Requested-With": "fetch" }
      });

      // Si el backend redirige, vamos a esa URL (recargar agenda)
      if (r.redirected) {
        window.location.href = r.url;
        return;
      }

      // Si devuelve HTML (por ejemplo, vuelve a mostrar el formulario), lo reemplazamos
      body.innerHTML = await r.text();
    });
  }
}

document.addEventListener("click", (e) => {
  const open = e.target.closest("[data-nc-modal-open]");
  if (open) {
    e.preventDefault();
    const url = open.getAttribute("href");
    ncLoadIntoModal(url);
    return;
  }

  const close = e.target.closest("[data-nc-modal-close]");
  if (close) {
    e.preventDefault();
    ncCloseModal();
    return;
  }

  // Click fuera de la tarjeta cierra el modal
  if (e.target && e.target.id === "nc-modal") {
    ncCloseModal();
  }
});

// ESC para cerrar
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") ncCloseModal();
});