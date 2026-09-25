/* Formulário de nota fiscal: o campo Valor é sugerido pela soma do valor líquido dos
   recibos marcados, enquanto o usuário não editar o valor à mão (mesmo padrão do
   premio_total da apólice). Quem define o valor é a Seguralta (ela informa quanto vai
   pagar); a diferença de centavos para a soma dos recibos é arredondamento dela e fica
   só mostrada. A validação que vale continua sendo a do servidor. */
(function () {
  "use strict";

  const caixas = Array.from(document.querySelectorAll('input[name="recibo_ids"]'));
  const campoValor = document.getElementById("valor");
  const conf = document.getElementById("nf-conferencia");
  if (!campoValor) return;

  function num(v) {
    v = (v == null ? "" : "" + v).trim().replace(/\s|R\$/g, "");
    if (!v) return 0;
    if (v.indexOf(",") > -1) v = v.replace(/\./g, "").replace(",", ".");
    const n = parseFloat(v);
    return isNaN(n) ? 0 : n;
  }
  const fmt = (n) =>
    (Number(n) || 0).toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const cent = (n) => Math.round(n * 100);
  const somaMarcados = () =>
    caixas.reduce((s, c) => s + (c.checked ? cent(num(c.dataset.valorLiquido)) : 0), 0);

  // nota já com valor (o que a Seguralta informou): marcar/desmarcar recibo não sobrescreve
  let valorManual = !!campoValor.value.trim();
  campoValor.addEventListener("input", () => { valorManual = true; conferir(); });

  function conferir() {
    if (!conf) return;
    const soma = somaMarcados();
    const valor = cent(num(campoValor.value));
    if (!soma || !campoValor.value.trim()) { conf.innerHTML = ""; return; }
    const dif = valor - soma;
    if (dif === 0) {
      conf.innerHTML = '<span class="selo-ok">✓ igual à soma dos recibos</span>';
    } else if (Math.abs(dif) <= 5) {
      conf.textContent = "Soma dos recibos R$ " + fmt(soma / 100) + " · diferença de R$ " +
        fmt(Math.abs(dif) / 100) + " = arredondamento da Seguralta (vale o valor da nota)";
    } else {
      conf.innerHTML = '<span class="selo-ruim">⚠ difere da soma dos recibos (R$ ' +
        fmt(soma / 100) + ") em R$ " + fmt(Math.abs(dif) / 100) + "</span>";
    }
  }

  function recalcValor() {
    if (!valorManual) {
      const soma = somaMarcados();
      campoValor.value = soma ? fmt(soma / 100) : "";
    }
    conferir();
  }
  caixas.forEach((c) => c.addEventListener("change", recalcValor));
  conferir();
})();
