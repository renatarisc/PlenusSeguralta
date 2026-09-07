/* Cadastro de campo de cotação: mostra a lista de opções só quando o tipo é
   "Seleção" e permite adicionar/remover opções na própria página. */
(function () {
  "use strict";

  const tipo = document.getElementById("tipo");
  const bloco = document.getElementById("bloco-opcoes");
  const lista = document.getElementById("lista-opcoes");
  const tpl = document.getElementById("tpl-opcao");
  const add = document.getElementById("add-opcao");
  if (!tipo || !bloco || !lista || !tpl || !add) return;

  function sincronizar() {
    const eSelecao = tipo.value === "selecao";
    bloco.hidden = !eSelecao;
    // começa com uma linha em branco para não abrir vazio
    if (eSelecao && !lista.querySelector(".opcao-linha")) novaLinha();
  }

  function novaLinha() {
    lista.appendChild(tpl.content.cloneNode(true));
  }

  tipo.addEventListener("change", sincronizar);
  add.addEventListener("click", () => {
    novaLinha();
    const ult = lista.querySelector(".opcao-linha:last-child input");
    if (ult) ult.focus();
  });
  lista.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-remover-opcao]");
    if (btn) btn.closest(".opcao-linha").remove();
  });

  sincronizar();
})();
