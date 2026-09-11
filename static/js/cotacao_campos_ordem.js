/* Cotação → Cadastrar Campo: arrastar as linhas da tabela pra reordenar (drag and
   drop nativo, sem lib). Ao soltar, manda a sequência inteira de ids pro servidor,
   que renumera a "ordem" de 1 em diante nessa sequência. */
(function () {
  "use strict";

  const corpo = document.getElementById("corpo-campos-cotacao");
  if (!corpo) return;

  let arrastando = null;

  corpo.addEventListener("dragstart", (e) => {
    const tr = e.target.closest("tr[draggable='true']");
    if (!tr) return;
    arrastando = tr;
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", tr.dataset.campoId || "");
    setTimeout(() => tr.classList.add("arrastando"), 0);
  });

  corpo.addEventListener("dragend", () => {
    if (arrastando) arrastando.classList.remove("arrastando");
    limparIndicadores();
    arrastando = null;
  });

  corpo.addEventListener("dragover", (e) => {
    if (!arrastando) return;
    const alvo = e.target.closest("tr");
    if (!alvo || alvo === arrastando) return;
    e.preventDefault();
    limparIndicadores();
    const antes = ehMetadeSuperior(e, alvo);
    alvo.classList.add(antes ? "arrasta-antes" : "arrasta-depois");
  });

  corpo.addEventListener("drop", (e) => {
    if (!arrastando) return;
    e.preventDefault();
    const alvo = e.target.closest("tr");
    limparIndicadores();
    if (!alvo || alvo === arrastando) return;
    const antes = ehMetadeSuperior(e, alvo);
    alvo.parentNode.insertBefore(arrastando, antes ? alvo : alvo.nextSibling);
    salvarOrdem();
  });

  function ehMetadeSuperior(e, alvo) {
    const rect = alvo.getBoundingClientRect();
    return (e.clientY - rect.top) < rect.height / 2;
  }

  function limparIndicadores() {
    corpo.querySelectorAll(".arrasta-antes, .arrasta-depois")
      .forEach((el) => el.classList.remove("arrasta-antes", "arrasta-depois"));
  }

  function salvarOrdem() {
    const linhas = [...corpo.querySelectorAll("tr[data-campo-id]")];
    const ids = linhas.map((tr) => tr.dataset.campoId);
    linhas.forEach((tr, i) => {
      const input = tr.querySelector("input.input-ordem");
      if (input) input.value = i + 1;
    });
    const csrf = (document.querySelector('meta[name="csrf-token"]') || {}).content || "";
    fetch(corpo.dataset.endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrf },
      body: JSON.stringify({ ids }),
    }).catch(() => {});
  }
})();
