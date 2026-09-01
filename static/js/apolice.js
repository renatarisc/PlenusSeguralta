/* Formulário de apólice: parcelas dinâmicas, gerador de parcelas e cálculo da comissão.
   (A validação que vale continua sendo a do servidor.) */
(function () {
  "use strict";

  const corpo = document.getElementById("corpo-parcelas");
  const tpl = document.getElementById("tpl-parcela");
  const resumo = document.getElementById("resumo-parcelas");
  if (!corpo || !tpl) return;

  // ---- número pt-BR <-> float ----
  function num(v) {
    v = (v == null ? "" : "" + v).trim().replace(/\s|R\$/g, "");
    if (!v) return 0;
    if (v.indexOf(",") > -1) v = v.replace(/\./g, "").replace(",", ".");
    const n = parseFloat(v);
    return isNaN(n) ? 0 : n;
  }
  const fmt = (n) => n.toFixed(2).replace(".", ",");

  function addMeses(iso, k) {
    const p = iso.split("-").map(Number);
    if (p.length !== 3) return "";
    const [y, m, d] = p;
    const dt = new Date(y, m - 1 + k, d);
    if (dt.getDate() < d) dt.setDate(0); // estoura mês curto -> último dia
    const z = (n) => String(n).padStart(2, "0");
    return dt.getFullYear() + "-" + z(dt.getMonth() + 1) + "-" + z(dt.getDate());
  }

  // ---- linhas de parcela ----
  function linhas() {
    return Array.from(corpo.querySelectorAll("tr.parcela"));
  }

  function atualizarResumo() {
    const ls = linhas();
    let soma = 0;
    ls.forEach((tr) => (soma += num(tr.querySelector('[name="parcela_valor"]').value)));
    resumo.textContent = ls.length
      ? ls.length + " parcela(s) · soma R$ " + fmt(soma)
      : "";
  }

  function novaLinha(dados) {
    const tr = tpl.content.firstElementChild.cloneNode(true);
    if (dados) {
      tr.querySelector('[name="parcela_identificacao"]').value = dados.ident || "";
      tr.querySelector('[name="parcela_data"]').value = dados.data || "";
      tr.querySelector('[name="parcela_valor"]').value = dados.valor || "";
    }
    corpo.appendChild(tr);
    return tr;
  }

  corpo.addEventListener("click", (e) => {
    const b = e.target.closest("[data-remover-parcela]");
    if (!b) return;
    b.closest("tr.parcela").remove();
    atualizarResumo();
  });
  corpo.addEventListener("input", (e) => {
    if (e.target.name === "parcela_valor") atualizarResumo();
  });

  const btnAdd = document.getElementById("btn-add-parcela");
  if (btnAdd) btnAdd.addEventListener("click", () => { novaLinha(); atualizarResumo(); });

  // ---- gerador ----
  const btnGerar = document.getElementById("btn-gerar-parcelas");
  if (btnGerar) {
    btnGerar.addEventListener("click", () => {
      const qtd = parseInt(document.getElementById("ger_qtd").value, 10);
      const total = num(document.getElementById("ger_total").value);
      const data1 = document.getElementById("ger_data1").value;
      if (!qtd || qtd < 1) { alert("Informe a quantidade de parcelas."); return; }
      if (linhas().length && !confirm("Substituir as parcelas atuais?")) return;

      corpo.innerHTML = "";
      const base = total ? Math.floor((total / qtd) * 100) / 100 : 0;
      let acumulado = 0;
      for (let i = 1; i <= qtd; i++) {
        let valor = base;
        acumulado += base;
        if (i === qtd && total) valor = Math.round((total - (acumulado - base)) * 100) / 100;
        novaLinha({
          ident: i + "/" + qtd,
          data: data1 ? addMeses(data1, i - 1) : "",
          valor: total ? fmt(valor) : "",
        });
      }
      atualizarResumo();
    });
  }

  // ---- preenchimento vindo do "Ler apólice" (ler_pdf.js) ----
  window.plenusSetParcelas = function (lista) {
    if (!Array.isArray(lista)) return;
    corpo.innerHTML = "";
    lista.forEach((p) =>
      novaLinha({ ident: p.identificacao || "", data: p.data || "", valor: p.valor || "" }));
    atualizarResumo();
  };

  // ---- link do OneDrive: mantém o "abrir ↗" apontando pro valor digitado ----
  const linkIn = document.getElementById("link_onedrive");
  const linkAbrir = document.getElementById("link_onedrive_abrir");
  if (linkIn && linkAbrir) {
    const syncLink = () => {
      const v = linkIn.value.trim();
      linkAbrir.hidden = !v;
      if (v) linkAbrir.href = v;
    };
    linkIn.addEventListener("input", syncLink);
    syncLink();
  }

  // ---- "enviada = Sim" preenche a data com hoje, se estiver vazia ----
  document.querySelectorAll("[data-par-data]").forEach((sel) => {
    sel.addEventListener("change", () => {
      const campoData = document.getElementById(sel.dataset.parData);
      if (sel.value === "1" && campoData && !campoData.value) {
        campoData.value = new Date().toISOString().slice(0, 10);
      }
    });
  });

  // ---- comissão: valor = prêmio * % / 100 ----
  const btnCalc = document.getElementById("btn-calc-comissao");
  if (btnCalc) {
    btnCalc.addEventListener("click", () => {
      const premio = num(document.getElementById("premio_liquido").value);
      const pct = num(document.getElementById("comissao_percentual").value);
      if (!premio || !pct) { alert("Preencha o prêmio líquido e o percentual."); return; }
      document.getElementById("comissao_valor").value = fmt(Math.round(premio * pct) / 100);
    });
  }

  atualizarResumo();
})();
