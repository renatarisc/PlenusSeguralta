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
  // 3048.16 -> "3.048,16" (ponto no milhar, vírgula no decimal)
  const fmt = (n) =>
    (Number(n) || 0).toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

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

  // hoje, no formato do <input type=date> (yyyy-mm-dd), em fuso local
  function hojeISO() {
    const d = new Date();
    const z = (n) => String(n).padStart(2, "0");
    return d.getFullYear() + "-" + z(d.getMonth() + 1) + "-" + z(d.getDate());
  }

  // diferença em dias (b - a), ambos "yyyy-mm-dd", sem depender do fuso local
  function diasEntre(a, b) {
    const t = (s) => new Date(s + "T00:00:00Z").getTime();
    return Math.round((t(b) - t(a)) / 86400000);
  }

  const DIAS_PERTO_VENCER = 10; // mesma janela do 1º marco de aviso de boleto

  // vermelho: vencida e não paga. amarelo: perto de vencer (<= 10 dias) e não paga.
  function atualizarAtraso(tr) {
    const data = tr.querySelector('[name="parcela_data"]').value;
    const paga = tr.querySelector('[name="parcela_paga"]').value === "1";
    const dias = data ? diasEntre(hojeISO(), data) : null;
    tr.classList.toggle("parcela--paga", paga);
    tr.classList.toggle("parcela--atrasada", !paga && dias !== null && dias < 0);
    tr.classList.toggle("parcela--perto", !paga && dias !== null && dias >= 0 && dias <= DIAS_PERTO_VENCER);
  }

  // ---- parcela já paga abre travada; o lápis libera (igual à saída) ----
  function editaveis(tr) {
    return Array.from(tr.querySelectorAll("input:not([type=hidden]), select"));
  }
  function travar(tr) {
    tr.classList.add("parcela--travada");
    editaveis(tr).forEach((el) => {
      if (el.tagName === "SELECT") el.setAttribute("tabindex", "-1");
      else el.setAttribute("readonly", "readonly");
    });
  }
  function destravar(tr) {
    tr.classList.remove("parcela--travada");
    editaveis(tr).forEach((el) => { el.removeAttribute("readonly"); el.removeAttribute("tabindex"); });
  }

  function atualizarResumo() {
    const ls = linhas();
    let soma = 0;
    ls.forEach((tr) => {
      soma += num(tr.querySelector('[name="parcela_valor"]').value);
      atualizarAtraso(tr);
    });
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
    const bEdit = e.target.closest("[data-editar-parcela]");
    if (bEdit) {
      const tr = bEdit.closest("tr.parcela");
      destravar(tr);
      const primeiro = editaveis(tr)[0];
      if (primeiro) primeiro.focus();
      return;
    }
    const b = e.target.closest("[data-remover-parcela]");
    if (!b) return;
    b.closest("tr.parcela").remove();
    atualizarResumo();
  });
  corpo.addEventListener("input", (e) => {
    if (e.target.name === "parcela_valor" || e.target.name === "parcela_data") atualizarResumo();
  });
  corpo.addEventListener("change", (e) => {
    if (e.target.name === "parcela_paga" || e.target.name === "parcela_data") atualizarResumo();
  });

  const btnAdd = document.getElementById("btn-add-parcela");
  if (btnAdd) btnAdd.addEventListener("click", () => { novaLinha(); atualizarResumo(); });

  // ---- gerador ----
  const btnGerar = document.getElementById("btn-gerar-parcelas");
  if (btnGerar) {
    btnGerar.addEventListener("click", () => {
      const qtd = parseInt(document.getElementById("ger_qtd").value, 10);
      const valorInf = num(document.getElementById("ger_total").value);
      const data1 = document.getElementById("ger_data1").value;
      const modo = (document.getElementById("ger_modo") || {}).value || "parcela";
      if (!qtd || qtd < 1) { alert("Informe a quantidade de parcelas."); return; }
      if (linhas().length && !confirm("Substituir as parcelas atuais?")) return;

      corpo.innerHTML = "";
      // "por parcela": mesmo valor em todas. "total": divide, última absorve o arredondamento.
      const base = modo === "total" && valorInf ? Math.floor((valorInf / qtd) * 100) / 100 : valorInf;
      let acumulado = 0;
      for (let i = 1; i <= qtd; i++) {
        let valor = base;
        if (modo === "total" && valorInf) {
          acumulado += base;
          if (i === qtd) valor = Math.round((valorInf - (acumulado - base)) * 100) / 100;
        }
        novaLinha({
          ident: i + "/" + qtd,
          data: data1 ? addMeses(data1, i - 1) : "",
          valor: valorInf ? fmt(valor) : "",
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

  // ---- card "Veículo" só aparece para seguro de automóvel ----
  const selTipo = document.getElementById("tipo_seguro_id");
  const cardVeiculo = document.getElementById("card-veiculo");
  if (selTipo && cardVeiculo) {
    const ehAuto = () => {
      const txt = (selTipo.options[selTipo.selectedIndex] || {}).text || "";
      return /autom[óo]vel|ve[íi]culo|autom[óo]tiv|carro|moto\b|frota/i.test(txt);
    };
    const jaTemDados = ["veiculo_placa", "veiculo_descricao"].some((n) => {
      const el = document.getElementById(n);
      return el && el.value.trim();
    });
    const sync = () => { cardVeiculo.hidden = !(ehAuto() || jaTemDados); };
    selTipo.addEventListener("change", sync);
    sync();
  }

  // ---- coluna "Cliente avisado" das parcelas: só para pagamento em boleto ----
  const selForma = document.getElementById("forma_pagamento_id");
  const tabParcelas = document.getElementById("tab-parcelas");
  if (selForma && tabParcelas) {
    const ehBoleto = () => {
      const txt = (selForma.options[selForma.selectedIndex] || {}).text || "";
      return /boleto/i.test(txt);
    };
    const syncAviso = () => { tabParcelas.classList.toggle("sem-aviso", !ehBoleto()); };
    selForma.addEventListener("change", syncAviso);
    syncAviso();
  }

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

  // ---- prêmio total = líquido + IOF (enquanto o usuário não editar o total à mão) ----
  const pl = document.getElementById("premio_liquido");
  const iof = document.getElementById("iof");
  const pt = document.getElementById("premio_total");
  if (pl && iof && pt) {
    let totalManual = false;
    pt.addEventListener("input", () => { totalManual = true; });
    const recalcTotal = () => {
      if (totalManual) return;
      if (!pl.value.trim() && !iof.value.trim()) { pt.value = ""; return; }
      pt.value = fmt(num(pl.value) + num(iof.value));
    };
    pl.addEventListener("input", recalcTotal);
    iof.addEventListener("input", recalcTotal);
  }

  // ---- comissão: SEGURALTA a receber = prêmio líq. * % ; Plenus a receber = 75% do recebido pela SEGURALTA ----
  const btnCalc = document.getElementById("btn-calc-comissao");
  if (btnCalc) {
    btnCalc.addEventListener("click", () => {
      const premio = num(document.getElementById("premio_liquido").value);
      const pct = num(document.getElementById("comissao_percentual").value);
      if (!premio || !pct) { alert("Preencha o prêmio líquido e o percentual."); return; }
      document.getElementById("comissao_valor_seguralta_receber").value =
        fmt(Math.round(premio * pct) / 100);
      const segRecebido = num(document.getElementById("comissao_valor_seguralta_recebido").value);
      document.getElementById("comissao_valor_plenus_receber").value =
        fmt(Math.round(segRecebido * 75) / 100);
    });
  }

  // ao abrir: trava as parcelas que já vieram pagas
  linhas().forEach((tr) => {
    if (tr.querySelector('[name="parcela_paga"]').value === "1") travar(tr);
  });
  atualizarResumo();
})();
