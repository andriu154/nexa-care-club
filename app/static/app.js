function ncOpenModal() {
  const modal = document.getElementById("nc-modal");
  if (!modal) return;
  modal.classList.add("open");
  modal.setAttribute("aria-hidden", "false");
  document.body.style.overflow = "hidden";
}

function ncCloseModal() {
  const modal = document.getElementById("nc-modal");
  const body = document.getElementById("nc-modal-body");
  if (!modal || !body) return;
  modal.classList.remove("open");
  modal.setAttribute("aria-hidden", "true");
  body.innerHTML = "";
  document.body.style.overflow = "";
}

function ncBindModalForms(container) {
  const forms = container.querySelectorAll("form");

  forms.forEach((form) => {
    form.addEventListener("submit", async (e) => {
      e.preventDefault();

      const body = document.getElementById("nc-modal-body");
      if (!body) return;

      const formData = new FormData(form);
      const action = form.getAttribute("action") || window.location.href;
      const method = (form.getAttribute("method") || "POST").toUpperCase();

      body.style.opacity = "0.7";

      try {
        const response = await fetch(action, {
          method,
          body: formData,
          headers: {
            "X-Requested-With": "fetch"
          },
          redirect: "follow"
        });

        const finalUrl = response.url || "";

        // Si redirige a /app o a otra página real -> navegar normal
        if (finalUrl.includes("/app?") || finalUrl.endsWith("/app") || finalUrl.includes("/app/encounters/")) {
          window.location.href = finalUrl;
          return;
        }

        // Si la respuesta sigue siendo una vista modal (= contiene modal=1), cargarla dentro del modal
        const html = await response.text();
        body.innerHTML = html;
        body.style.opacity = "1";
        ncBindModalForms(body);
      } catch (error) {
        body.style.opacity = "1";
        body.innerHTML = `
          <div style="padding:20px; color:#b91c1c; font-weight:700;">
            Ocurrió un error cargando el formulario.
          </div>
        `;
      }
    });
  });
}

async function ncLoadIntoModal(url) {
  const body = document.getElementById("nc-modal-body");
  if (!body) return;

  ncOpenModal();
  body.innerHTML = `
    <div style="padding:24px; font-weight:700; color:#6b7280;">
      Cargando...
    </div>
  `;

  try {
    const response = await fetch(url, {
      headers: {
        "X-Requested-With": "fetch"
      }
    });

    const html = await response.text();
    body.innerHTML = html;
    ncBindModalForms(body);
  } catch (error) {
    body.innerHTML = `
      <div style="padding:24px; color:#b91c1c; font-weight:700;">
        No se pudo abrir la ventana.
      </div>
    `;
  }
}

document.addEventListener("click", (e) => {
  const openBtn = e.target.closest("[data-nc-modal-open]");
  if (openBtn) {
    e.preventDefault();
    const url = openBtn.getAttribute("href");
    if (url) ncLoadIntoModal(url);
    return;
  }

  const closeBtn = e.target.closest("[data-nc-modal-close]");
  if (closeBtn) {
    e.preventDefault();
    ncCloseModal();
    return;
  }

  if (e.target && e.target.id === "nc-modal") {
    ncCloseModal();
  }
});

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    ncCloseModal();
  }
});