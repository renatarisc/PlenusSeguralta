/* "Gerar cotação": adiciona/remove blocos de cotação (uma seguradora por bloco).
   Os campos de cada bloco têm o mesmo name em todos os blocos -> o servidor lê
   com request.form.getlist(), alinhado por índice. */
(function () {
  "use strict";

  const cont = document.getElementById("cotacoes");
  const btnAdd = document.getElementById("add-cotacao");
  if (!cont || !btnAdd) return;

  function limpar(bloco) {
    bloco.querySelectorAll("input").forEach((el) => { el.value = ""; });
    bloco.querySelectorAll("select").forEach((el) => { el.selectedIndex = 0; });
  }

  function renumerar() {
    const blocos = cont.querySelectorAll(".cot-bloco");
    blocos.forEach((b, i) => {
      const n = b.querySelector(".cot-num");
      if (n) n.textContent = i + 1;
      const rem = b.querySelector(".cot-remover");
      if (rem) rem.hidden = blocos.length <= 1;
    });
  }

  btnAdd.addEventListener("click", () => {
    const base = cont.querySelector(".cot-bloco");
    const novo = base.cloneNode(true);
    limpar(novo);
    cont.appendChild(novo);
    renumerar();
    const sel = novo.querySelector('select[name="cot_seguradora"]');
    if (sel) sel.focus();
    novo.scrollIntoView({ behavior: "smooth", block: "nearest" });
  });

  cont.addEventListener("click", (e) => {
    const rem = e.target.closest(".cot-remover");
    if (!rem) return;
    if (cont.querySelectorAll(".cot-bloco").length <= 1) return;
    rem.closest(".cot-bloco").remove();
    renumerar();
  });

  renumerar();
})();
