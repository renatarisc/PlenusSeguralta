/* Formulário de recibo: valor líquido = valor bruto - alíquota(%), enquanto o
   usuário não editar o líquido à mão. (A validação que vale continua sendo a do servidor.) */
(function () {
  "use strict";

  function num(v) {
    v = (v == null ? "" : "" + v).trim().replace(/\s|R\$/g, "");
    if (!v) return 0;
    if (v.indexOf(",") > -1) v = v.replace(/\./g, "").replace(",", ".");
    const n = parseFloat(v);
    return isNaN(n) ? 0 : n;
  }
  const fmt = (n) =>
    (Number(n) || 0).toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  const bruto = document.getElementById("valor_bruto");
  const aliquota = document.getElementById("aliquota");
  const liquido = document.getElementById("valor_liquido");
  let recalcLiquido = () => {};
  if (bruto && aliquota && liquido) {
    let liquidoManual = false;
    liquido.addEventListener("input", () => { liquidoManual = true; });

    recalcLiquido = () => {
      if (liquidoManual) return;
      if (!bruto.value.trim() && !aliquota.value.trim()) { liquido.value = ""; return; }
      liquido.value = fmt(num(bruto.value) * (1 - num(aliquota.value) / 100));
    };
    bruto.addEventListener("input", recalcLiquido);
    aliquota.addEventListener("input", recalcLiquido);
  }

  // ---- "Buscar parcelas dessa data": reenvia o form (sem perder o que já foi
  // digitado) marcando acao=buscar, pro servidor recalcular o checklist ----
  const btnBuscar = document.getElementById("btn-buscar-parcelas");
  const campoAcao = document.getElementById("recibo-acao");
  if (btnBuscar && campoAcao) {
    btnBuscar.addEventListener("click", () => {
      campoAcao.value = "buscar";
      const form = btnBuscar.closest("form");
      if (form) { form.requestSubmit ? form.requestSubmit() : form.submit(); }
    });
  }

  // ---- resumo ao vivo + valor bruto sugerido pelas parcelas marcadas menos os
  //      descontos marcados. O resumo abaixo da tabela de parcelas mostra só a soma
  //      das PARCELAS (o desconto não é parcela); o desconto entra apenas no valor
  //      bruto lá em cima. ----
  const caixasParc = document.querySelectorAll('input[name="parcela_refs"]');
  const caixasDesconto = document.querySelectorAll('input[name="desconto_refs"]');
  const resumoParc = document.getElementById("resumo-parcelas-recibo");
  if (caixasParc.length || caixasDesconto.length) {
    let brutoManual = false;
    if (bruto) bruto.addEventListener("input", () => { brutoManual = true; });

    const atualizarResumo = () => {
      let n = 0, somaParcelas = 0;
      caixasParc.forEach((c) => { if (c.checked) { n++; somaParcelas += num(c.dataset.valor); } });
      let somaDescontos = 0;
      caixasDesconto.forEach((c) => { if (c.checked) { somaDescontos += num(c.dataset.valor); } });
      if (resumoParc) resumoParc.textContent = n ? n + " parcela(s) marcada(s) · soma R$ " + fmt(somaParcelas) : "";
      if (bruto && !brutoManual && (n || somaDescontos)) {
        bruto.value = fmt(somaParcelas - somaDescontos);
        recalcLiquido();
      }
    };
    caixasParc.forEach((c) => c.addEventListener("change", atualizarResumo));
    caixasDesconto.forEach((c) => c.addEventListener("change", atualizarResumo));
    atualizarResumo();
  }
})();
