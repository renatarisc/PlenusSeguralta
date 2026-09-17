/* Formulário de nota fiscal: o campo Valor é sugerido pela soma do valor líquido dos
   recibos marcados, enquanto o usuário não editar o valor à mão (mesmo padrão do
   premio_total da apólice). A validação que vale continua sendo a do servidor. */
(function () {
  "use strict";

  const caixas = Array.from(document.querySelectorAll('input[name="recibo_ids"]'));
  const campoValor = document.getElementById("valor");
  if (!caixas.length || !campoValor) return;

  function num(v) {
    v = (v == null ? "" : "" + v).trim().replace(/\s|R\$/g, "");
    if (!v) return 0;
    if (v.indexOf(",") > -1) v = v.replace(/\./g, "").replace(",", ".");
    const n = parseFloat(v);
    return isNaN(n) ? 0 : n;
  }
  const fmt = (n) =>
    (Number(n) || 0).toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  let valorManual = false;
  campoValor.addEventListener("input", () => { valorManual = true; });

  function recalcValor() {
    if (valorManual) return;
    const soma = caixas.reduce((s, c) => s + (c.checked ? num(c.dataset.valorLiquido) : 0), 0);
    campoValor.value = soma ? fmt(soma) : "";
  }
  caixas.forEach((c) => c.addEventListener("change", recalcValor));
})();
