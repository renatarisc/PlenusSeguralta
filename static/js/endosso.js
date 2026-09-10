/* Formulário de endosso: card Veículo condicional + parcelas de pagamento
   (adicionar / remover / gerar), no mesmo padrão da apólice. */
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

  function addMeses(iso, k) {
    const p = (iso || "").split("-").map(Number);
    if (p.length !== 3 || p.some(isNaN)) return "";
    const [y, m, d] = p;
    const dt = new Date(y, m - 1 + k, d);
    if (dt.getDate() < d) dt.setDate(0);
    const z = (x) => String(x).padStart(2, "0");
    return dt.getFullYear() + "-" + z(dt.getMonth() + 1) + "-" + z(dt.getDate());
  }

  // ---------- card Veículo: aparece p/ apólice de automóvel / moto ----------
  const selApolice = document.getElementById("apolice_id");
  const cardVeiculo = document.getElementById("card-endosso-veiculo");
  const RE_AUTO = /autom[óo]vel|ve[íi]culo|autom[óo]tiv|carro|moto\b|frota/i;

  function temDadosVeiculo() {
    return ["veiculo_placa", "veiculo_descricao"].some((n) => {
      const el = document.getElementById(n);
      return el && el.value.trim() !== "";
    });
  }
  function sincVeiculo() {
    if (!selApolice || !cardVeiculo) return;
    const opt = selApolice.selectedOptions[0];
    const tipo = opt ? (opt.dataset.tipo || "") : "";
    cardVeiculo.hidden = !(RE_AUTO.test(tipo) || temDadosVeiculo());
  }
  if (selApolice) selApolice.addEventListener("change", sincVeiculo);
  sincVeiculo();

  // ---------- cards Pagamento e Comissão: só com ônus ou devolução ----------
  const selSit = document.getElementById("situacao");
  const cardPag = document.getElementById("card-endosso-pagamento");
  const cardCom = document.getElementById("card-endosso-comissao");
  function sincFinanceiro() {
    if (!selSit) return;
    const fin = selSit.value === "onus" || selSit.value === "devolucao";
    if (cardPag) cardPag.hidden = !fin;
    if (cardCom) cardCom.hidden = !fin;
  }
  if (selSit) selSit.addEventListener("change", sincFinanceiro);
  sincFinanceiro();

  // ---------- parcelas ----------
  const corpo = document.getElementById("corpo-parcelas");
  const tpl = document.getElementById("tpl-parcela");
  const resumo = document.getElementById("resumo-parcelas");
  if (!corpo || !tpl) return;

  function linhas() {
    return Array.from(corpo.querySelectorAll("tr.parcela"));
  }

  // ---- status da parcela: "a enviar / enviado / pago" p/ boleto; "a pagar / pago" p/ o resto ----
  const selForma = document.getElementById("forma_pagamento_id");
  function ehBoleto() {
    const t = selForma ? (selForma.options[selForma.selectedIndex] || {}).text || "" : "";
    return /boleto/i.test(t);
  }
  const OPC_STATUS = {
    boleto: [["a_enviar", "A enviar"], ["enviado", "Enviado"], ["pago", "Pago"]],
    normal: [["a_pagar", "A pagar"], ["pago", "Pago"]],
  };
  function statusInicial(tr, boleto) {
    const paga = tr.querySelector('[name="parcela_paga"]').value === "1";
    const env = (tr.querySelector('[name="parcela_enviado"]') || {}).value === "1";
    if (paga) return "pago";
    if (boleto) return env ? "enviado" : "a_enviar";
    return "a_pagar";
  }
  function remapStatus(val, boleto) {
    if (val === "pago") return "pago";
    if (boleto) return val === "enviado" ? "enviado" : "a_enviar";
    return "a_pagar";
  }
  function sincOcultosStatus(tr, val, boleto) {
    const hp = tr.querySelector('[name="parcela_paga"]');
    const he = tr.querySelector('[name="parcela_enviado"]');
    if (hp) hp.value = val === "pago" ? "1" : "0";
    if (he) he.value = (val === "enviado" || (val === "pago" && boleto)) ? "1" : "0";
  }
  function aplicarStatus(tr) {
    const sel = tr.querySelector("[data-parcela-status]");
    if (!sel) return;
    const boleto = ehBoleto();
    const alvo = remapStatus(sel.dataset.val || statusInicial(tr, boleto), boleto);
    sel.innerHTML = OPC_STATUS[boleto ? "boleto" : "normal"]
      .map(([v, t]) => '<option value="' + v + '">' + t + "</option>").join("");
    sel.value = alvo;
    sel.dataset.val = alvo;
    sincOcultosStatus(tr, alvo, boleto);
    tr.classList.toggle("parcela--paga", alvo === "pago");
  }
  function aplicarStatusTodas() { linhas().forEach(aplicarStatus); }
  if (selForma) selForma.addEventListener("change", aplicarStatusTodas);

  // ---- parcela já paga abre travada; o lápis libera (igual à apólice) ----
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

  function novaLinha(dados) {
    const tr = tpl.content.firstElementChild.cloneNode(true);
    if (dados) {
      tr.querySelector('[name="parcela_identificacao"]').value = dados.ident || "";
      tr.querySelector('[name="parcela_data"]').value = dados.data || "";
      tr.querySelector('[name="parcela_valor"]').value = dados.valor || "";
    }
    corpo.appendChild(tr);
    aplicarStatus(tr);
    return tr;
  }
  function atualizarResumo() {
    const ls = linhas();
    if (!ls.length) { if (resumo) resumo.textContent = ""; return; }
    let soma = 0;
    ls.forEach((tr) => { soma += num(tr.querySelector('[name="parcela_valor"]').value); });
    let txt = ls.length + " parcela(s) · soma R$ " + fmt(soma);
    const elValor = document.getElementById("valor");
    const total = elValor ? num(elValor.value) : 0;
    if (total) {
      const dif = Math.round((soma - total) * 100) / 100;
      txt += Math.abs(dif) < 0.01
        ? ' <span class="selo-ok">✓ confere com o valor do endosso</span>'
        : ' <span class="selo-ruim">⚠ difere do valor do endosso em R$ ' + fmt(Math.abs(dif)) + "</span>";
    }
    if (resumo) resumo.innerHTML = txt;
  }

  corpo.addEventListener("click", (e) => {
    const bEdit = e.target.closest("[data-editar-parcela]");
    if (bEdit) {
      const tr = bEdit.closest("tr.parcela");
      if (tr.classList.contains("linha-liberada")) {          // 2º clique = "Salvar"
        const f = bEdit.form || bEdit.closest("form");
        if (f) {
          const fica = f.querySelector('input[name="permanecer"]');
          if (fica) fica.value = "1";                          // salva e volta pro form
          f.requestSubmit ? f.requestSubmit() : f.submit();
        }
        return;
      }
      destravar(tr);
      tr.classList.add("linha-liberada");
      bEdit.classList.replace("btn--linha", "btn--primario");
      bEdit.textContent = "Salvar";
      const alvo = editaveis(tr)[0];
      if (alvo) alvo.focus();
      return;
    }
    const b = e.target.closest("[data-remover-parcela]");
    if (!b) return;
    b.closest("tr.parcela").remove();
    atualizarResumo();
  });
  corpo.addEventListener("input", (e) => {
    if (e.target.name === "parcela_valor") atualizarResumo();
  });
  corpo.addEventListener("change", (e) => {
    if (e.target.matches("[data-parcela-status]")) {
      const tr = e.target.closest("tr.parcela");
      e.target.dataset.val = e.target.value;
      sincOcultosStatus(tr, e.target.value, ehBoleto());
      tr.classList.toggle("parcela--paga", e.target.value === "pago");
    }
  });

  const btnAdd = document.getElementById("btn-add-parcela");
  if (btnAdd) btnAdd.addEventListener("click", () => { novaLinha(); atualizarResumo(); });

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

  const elValor = document.getElementById("valor");
  if (elValor) elValor.addEventListener("input", atualizarResumo);

  // na carga: monta os selects de status e trava as parcelas já pagas
  aplicarStatusTodas();
  linhas().forEach((tr) => {
    const st = tr.querySelector('[name="parcela_paga"]');
    if (st && st.value === "1") travar(tr);
  });
  atualizarResumo();

  // ---------- comissão: botões "Calcular" ----------
  const set = (id, v) => { const el = document.getElementById(id); if (el) el.value = fmt(v); };

  const btnSeg = document.getElementById("btn-calc-seg-endosso");
  if (btnSeg) btnSeg.addEventListener("click", () => {
    const base = num((document.getElementById("valor") || {}).value);
    const pct = num((document.getElementById("comissao_percentual") || {}).value);
    if (!base || !pct) { alert("Preencha o valor do endosso e o percentual."); return; }
    set("comissao_valor_seguralta_receber", Math.round(base * pct) / 100);
  });

  const btnPle = document.getElementById("btn-calc-plenus-endosso");
  if (btnPle) btnPle.addEventListener("click", () => {
    const segReceb = num((document.getElementById("comissao_valor_seguralta_recebido") || {}).value);
    if (!segReceb) { alert("Preencha o valor recebido pela Seguralta."); return; }
    set("comissao_valor_plenus_receber", Math.round(segReceb * 75) / 100);
  });
  // a alternância único × parcelado e as duas tabelas ficam em endosso_comissao.js

  // ---- link do OneDrive: "abrir ↗" acompanha o valor digitado ----
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
})();
