// Zoom con la rueda en los mapas del trabajo (lo usa basemap.py para el reporte y el análisis exploratorio).
//
// Plotly acerca con la rueda si la configuración tiene scrollZoom, pero en una página larga eso atrapa el
// desplazamiento: al bajar leyendo, el mapa se agranda en vez de moverse la página. Por eso la rueda
// acerca recién después de hacer clic en el mapa y deja de hacerlo al sacar el mouse; mientras tanto
// la página se desplaza como siempre y un cartel avisa cómo activarla. Los botones andan siempre.
function enableMapZoom(gd) {
  // La barra de Plotly viene en inglés y la página no carga sus traducciones.
  const TITLES = {"Zoom in": "Acercar", "Zoom out": "Alejar", "Reset axes": "Volver al encuadre inicial"};
  const translate = () => gd.querySelectorAll(".modebar-btn").forEach(button => {
    const title = TITLES[button.getAttribute("data-title")];
    if (title) button.setAttribute("data-title", title);
  });

  const hint = document.createElement("div");
  hint.textContent = "Hacé clic en el mapa para acercar con la rueda";
  Object.assign(hint.style, {
    position: "absolute", left: "50%", top: "50%", transform: "translate(-50%, -50%)", zIndex: 10,
    padding: "8px 14px", borderRadius: "6px", background: "rgba(30, 30, 28, 0.8)", color: "white",
    font: '15px system-ui, -apple-system, "Segoe UI", Roboto, sans-serif', pointerEvents: "none",
    opacity: 0, transition: "opacity 0.2s",
  });
  if (getComputedStyle(gd).position === "static") gd.style.position = "relative";
  gd.appendChild(hint);

  let active = false;
  let timer;
  // En la fase de captura, antes de que el evento llegue a Plotly: sin activar, Plotly no se entera
  // de la rueda y el navegador desplaza la página.
  gd.addEventListener("wheel", event => {
    if (active || !event.target.closest(".draglayer")) return;
    event.stopPropagation();
    hint.style.opacity = 1;
    clearTimeout(timer);
    timer = setTimeout(() => { hint.style.opacity = 0; }, 1500);
  }, {capture: true});
  gd.addEventListener("pointerdown", () => { active = true; hint.style.opacity = 0; }, {capture: true});
  // Se mira la posición y no solo el evento de salida: al apretar el botón Plotly tapa la página con
  // una capa para seguir el arrastre, y eso cuenta como salir del mapa aunque el mouse no se mueva.
  const leave = event => {
    const box = gd.getBoundingClientRect();
    const inside = event.clientX >= box.left && event.clientX <= box.right &&
      event.clientY >= box.top && event.clientY <= box.bottom;
    if (!inside) active = false;
  };
  gd.addEventListener("pointerleave", leave);
  document.addEventListener("pointerup", leave, {capture: true});

  // Plotly pone la barra en la esquina del gráfico, que puede quedar lejos del mapa porque el mapa se
  // angosta para no deformarse, y encima del título. Se la pone junto a la esquina superior derecha del mapa.
  const place = () => {
    const container = gd.querySelector(".modebar-container");
    const bar = gd.querySelector(".modebar");
    const map = gd.querySelector(".draglayer .nsewdrag");
    if (!container || !bar || !map) return;
    const figure = gd.getBoundingClientRect();
    const plot = map.getBoundingClientRect();
    container.style.right = Math.max(0, figure.right - plot.right - bar.getBoundingClientRect().width - 6) + "px";
    container.style.top = Math.max(0, plot.top - figure.top) + "px";
  };
  const arrange = () => { translate(); place(); };
  arrange();
  gd.on("plotly_afterplot", arrange);
}
