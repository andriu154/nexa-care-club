function ncOpenModal() {
  const modal = document.getElementById("nc-modal");
  if (!modal) return;
  modal.classList.add("open");
  modal.setAttribute("aria-hidden", "false");
}

function ncCloseModal() {
  const modal = document.getElementById("nc-modal");
  if (!modal) return;
  modal.classList.remove("open");
  modal.setAttribute("aria-hidden", "true");
  const body = document.getElementById("nc-modal-body");
  if (body) body.innerHTML = "";
}

async function ncLoadIntoModal(url) {
  const body = document.getElementById("nc-modal-body");
  if (!body) return;

  ncOpenModal();
  body.innerHTML = `<div style="padding:20px;font-weight:700;color:#6b7280;">Cargando...</div>`;

  const res = await fetch(url, {
    headers: { "X-Requested-With": "fetch" }
  });

  const html = await res.text();
  body.innerHTML = html;

  const forms = body.querySelectorAll("form");
  forms.forEach((form) => {
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

      if (r.redirected) {
        window.location.href = r.url;
        return;
      }

      const nextHtml = await r.text();
      body.innerHTML = nextHtml;

      const nestedForms = body.querySelectorAll("form");
      nestedForms.forEach((nestedForm) => {
        nestedForm.addEventListener("submit", async (ev) => {
          ev.preventDefault();
          const nestedFd = new FormData(nestedForm);
          const nestedAction = nestedForm.getAttribute("action") || url;
          const nestedMethod = (nestedForm.getAttribute("method") || "POST").toUpperCase();

          const nestedResp = await fetch(nestedAction, {
            method: nestedMethod,
            body: nestedFd,
            headers: { "X-Requested-With": "fetch" }
          });

          if (nestedResp.redirected) {
            window.location.href = nestedResp.url;
            return;
          }

          body.innerHTML = await nestedResp.text();
        });
      });
    });
  });
}

document.addEventListener("click", (e) => {
  const openTrigger = e.target.closest("[data-nc-modal-open]");
  if (openTrigger) {
    e.preventDefault();
    const url = openTrigger.getAttribute("href");
    if (url) ncLoadIntoModal(url);
    return;
  }

  const closeTrigger = e.target.closest("[data-nc-modal-close]");
  if (closeTrigger) {
    e.preventDefault();
    ncCloseModal();
    return;
  }

  if (e.target && e.target.id === "nc-modal") {
    ncCloseModal();
  }
});

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") ncCloseModal();
});