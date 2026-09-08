/* Formulário de consórcio:
   - histórico do valor da parcela (adicionar / remover linha);
   - boletos (gerar / adicionar / remover / liberar edição), com trava quando
     já há data de pagamento, no mesmo padrão das parcelas da apólice;
   - contemplação: mostra "data" só quando há forma de contemplação. */
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

  // ---------- contemplação: data só com forma escolhida ----------
  const selForma = document.getElementById("forma_contemplacao");
  const campoDataContempl = document.getElementById("campo-data-contemplacao");
  function sincContempl() {
    if (!selForma || !campoDataContempl) return;
    campoDataContempl.hidden = !(selForma.value || "").trim();
  }
  if (selForma) selForma.addEventListener("change", sincContempl);
  sincContempl();

  // ---------- link do OneDrive: "abrir ↗" acompanha o valor digitado ----------
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

  // ---------- histórico do valor da parcela ----------
  (function historicoValores() {
    const corpo = document.getElementById("corpo-pv");
    const tpl = document.getElementById("tpl-pv");
    const btnAdd = document.getElementById("btn-add-pv");
    if (!corpo || !tpl) return;
    const linhas = () => Array.from(corpo.querySelectorAll("tr.pv-linha"));

    function marcarInicial() {
      linhas().forEach((tr, i) => {
        const rot = tr.querySelector("[data-pv-rotulo]");
        if (rot) rot.textContent = i === 0 ? "valor inicial" : "reajuste " + i;
      });
    }
    function novaLinha() {
      const tr = tpl.content.firstElementChild.cloneNode(true);
      corpo.appendChild(tr);
      marcarInicial();
      return tr;
    }
    corpo.addEventListener("click", (e) => {
      const b = e.target.closest("[data-remover-pv]");
      if (!b) return;
      b.closest("tr.pv-linha").remove();
      marcarInicial();
    });
    if (btnAdd) btnAdd.addEventListener("click", () => novaLinha());
    if (!linhas().length) novaLinha();
    marcarInicial();
  })();

  // ---------- boletos ----------
  (function boletos() {
    const corpo = document.getElementById("corpo-boletos");
    const tpl = document.getElementById("tpl-boleto");
    const resumo = document.getElementById("resumo-boletos");
    if (!corpo || !tpl) return;

    const linhas = () => Array.from(corpo.querySelectorAll("tr.boleto"));
    const editaveis = (tr) => Array.from(tr.querySelectorAll("input:not([type=hidden]), select"));

    function estaPago(tr) {
      const pago = (tr.querySelector('[name="boleto_pagamento"]').value || "").trim();
      const sel = tr.querySelector('[name="boleto_status"]');
      return !!pago || (sel && sel.value === "pago");
    }
    function statusLinha(tr) {
      const pago = (tr.querySelector('[name="boleto_pagamento"]').value || "").trim();
      const sel = tr.querySelector('[name="boleto_status"]');
      if (pago && sel) sel.value = "pago";
      const on = estaPago(tr);
      tr.classList.toggle("parcela--paga", on);
      // mesma formatação das parcelas pagas da apólice: linha verde + travada
      if (on && !tr.classList.contains("linha-liberada")) travar(tr);
      if (!on) destravar(tr);
    }
    function travar(tr) {
      tr.classList.remove("linha-liberada");
      tr.classList.add("linha-travada");
      editaveis(tr).forEach((el) => {
        if (el.tagName === "SELECT") el.setAttribute("tabindex", "-1");
        else el.setAttribute("readonly", "readonly");
      });
    }
    function destravar(tr) {
      tr.classList.remove("linha-travada");
      editaveis(tr).forEach((el) => { el.removeAttribute("readonly"); el.removeAttribute("tabindex"); });
    }
    function novaLinha(d) {
      const tr = tpl.content.firstElementChild.cloneNode(true);
      if (d) {
        const set = (n, v) => { const el = tr.querySelector('[name="' + n + '"]'); if (el && v != null) el.value = v; };
        set("boleto_identificacao", d.ident);
        set("boleto_valor", d.valor);
        set("boleto_emissao", d.emissao);
        set("boleto_vencimento", d.vencimento);
      }
      corpo.appendChild(tr);
      statusLinha(tr);
      return tr;
    }
    function atualizarResumo() {
      if (!resumo) return;
      const ls = linhas();
      if (!ls.length) { resumo.textContent = ""; return; }
      const soma = ls.reduce((s, tr) => s + num(tr.querySelector('[name="boleto_valor"]').value), 0);
      const pagos = ls.filter((tr) => tr.classList.contains("parcela--paga")).length;
      resumo.textContent = ls.length + " boleto(s) · soma R$ " + fmt(soma) + " · " + pagos + " pago(s)";
    }

    corpo.addEventListener("click", (e) => {
      const bEdit = e.target.closest("[data-editar]");
      if (bEdit) {
        const tr = bEdit.closest("tr.boleto");
        if (tr.classList.contains("linha-liberada")) {          // 2º clique = re-trava
          if (bEdit.dataset.iconeOriginal) bEdit.innerHTML = bEdit.dataset.iconeOriginal;
          bEdit.classList.replace("btn--primario", "btn--linha");
          bEdit.title = "Liberar edição";
          tr.classList.remove("linha-liberada");
          if (estaPago(tr)) travar(tr);
          atualizarResumo();
          return;
        }
        if (!bEdit.dataset.iconeOriginal) bEdit.dataset.iconeOriginal = bEdit.innerHTML;
        destravar(tr);
        tr.classList.add("linha-liberada");
        bEdit.classList.replace("btn--linha", "btn--primario");
        bEdit.textContent = "Salvar";
        bEdit.title = "Guardar esta linha";
        const alvo = editaveis(tr)[0];
        if (alvo) alvo.focus();
        return;
      }
      const bDel = e.target.closest("[data-remover]");
      if (!bDel) return;
      bDel.closest("tr.boleto").remove();
      atualizarResumo();
    });
    corpo.addEventListener("input", (e) => {
      if (e.target.name === "boleto_valor") atualizarResumo();
    });
    corpo.addEventListener("change", (e) => {
      if (e.target.name === "boleto_pagamento" || e.target.name === "boleto_status") {
        statusLinha(e.target.closest("tr.boleto"));
        atualizarResumo();
      }
    });

    function sugestaoProximo() {
      const ls = linhas();
      if (!ls.length) return null;
      const ult = ls[ls.length - 1];
      const g = (n) => (ult.querySelector('[name="' + n + '"]').value || "").trim();
      const ident = g("boleto_identificacao");
      const m = ident.match(/^(\d+)\s*\/\s*(\d+)$/);
      const emis = g("boleto_emissao");
      const venc = g("boleto_vencimento");
      return {
        ident: m ? (Number(m[1]) + 1) + "/" + m[2] : "",
        valor: g("boleto_valor"),
        emissao: emis ? addMeses(emis, 1) : "",
        vencimento: venc ? addMeses(venc, 1) : "",
      };
    }

    const btnAdd = document.getElementById("btn-add-boleto");
    if (btnAdd) btnAdd.addEventListener("click", () => { novaLinha(sugestaoProximo()); atualizarResumo(); });

    const btnGerar = document.getElementById("btn-gerar-boletos");
    if (btnGerar) {
      btnGerar.addEventListener("click", () => {
        const qtd = parseInt(document.getElementById("ger_bol_qtd").value, 10);
        const valor = num(document.getElementById("ger_bol_valor").value);
        const emis1 = document.getElementById("ger_bol_emissao").value;
        const venc1 = document.getElementById("ger_bol_vencimento").value;
        if (!qtd || qtd < 1) { alert("Informe a quantidade de boletos."); return; }
        if (linhas().length && !confirm("Substituir os boletos atuais?")) return;
        corpo.innerHTML = "";
        for (let i = 1; i <= qtd; i++) {
          novaLinha({
            ident: i + "/" + qtd,
            valor: valor ? fmt(valor) : "",
            emissao: emis1 ? addMeses(emis1, i - 1) : "",
            vencimento: venc1 ? addMeses(venc1, i - 1) : "",
          });
        }
        atualizarResumo();
      });
    }

    if (!linhas().length) novaLinha();
    linhas().forEach((tr) => statusLinha(tr));
    atualizarResumo();
  })();

  // ---------- comissão: botões "Calcular" do modo único ----------
  const set = (id, v) => { const el = document.getElementById(id); if (el) el.value = fmt(v); };
  const btnSeg = document.getElementById("btn-calc-seg-consorcio");
  if (btnSeg) btnSeg.addEventListener("click", () => {
    const base = num((document.getElementById("carta") || {}).value);
    const pct = num((document.getElementById("comissao_percentual") || {}).value);
    if (!base || !pct) { alert("Preencha o valor da carta e o percentual."); return; }
    const coco = document.getElementById("comissao_cocorretagem");
    const bruto = Math.round(base * pct) / 100;
    set("comissao_valor_seguralta_receber", coco && coco.checked ? Math.round(bruto * 25) / 100 : bruto);
  });
  const btnPle = document.getElementById("btn-calc-plenus-consorcio");
  if (btnPle) btnPle.addEventListener("click", () => {
    const coco = document.getElementById("comissao_cocorretagem");
    if (coco && coco.checked) {
      const base = num((document.getElementById("carta") || {}).value);
      const pct = num((document.getElementById("comissao_percentual") || {}).value);
      if (!base || !pct) { alert("Preencha o valor da carta e o percentual."); return; }
      set("comissao_valor_plenus_receber", Math.round(base * pct * 0.75) / 100);
      return;
    }
    const segReceb = num((document.getElementById("comissao_valor_seguralta_recebido") || {}).value);
    if (!segReceb) { alert("Preencha o valor recebido pela Seguralta."); return; }
    set("comissao_valor_plenus_receber", Math.round(segReceb * 75) / 100);
  });
})();
