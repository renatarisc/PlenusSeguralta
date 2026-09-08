/* Card "Comissão" do formulário de ENDOSSO — mesmo padrão/dinâmica da apólice
   (ver comissao.js): o checkbox alterna entre "repasse único" (valores
   achatados) e "repasse parcelado" (duas tabelas: Comissão e Repasses), que
   moram numa janela (dialog). Sem cocorretagem e sem "relatório da corretora".
   A validação que vale é a do servidor. */
(function () {
  "use strict";

  // ---------- helpers ----------
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
    const z = (n) => String(n).padStart(2, "0");
    return dt.getFullYear() + "-" + z(dt.getMonth() + 1) + "-" + z(dt.getDate());
  }

  // ---------- alterna único / parcelado + janela (dialog) ----------
  const chk = document.getElementById("comissao_parcelada");
  const boxUnico = document.getElementById("comissao-endosso-unico");
  const boxParc = document.getElementById("comissao-endosso-parcelado");
  const dlg = document.getElementById("dlg-comissao");
  if (!chk || !boxUnico || !boxParc) return;   // fora do form de endosso

  function abrirDlg() { if (dlg && !dlg.open) (dlg.showModal ? dlg.showModal() : dlg.show()); }
  function fecharDlg() { if (dlg && dlg.open) dlg.close(); }

  const btnAbrir = document.getElementById("btn-abrir-comissao");
  if (btnAbrir) btnAbrir.addEventListener("click", abrirDlg);
  document.querySelectorAll("[data-fechar-comissao]").forEach((b) =>
    b.addEventListener("click", fecharDlg));

  const sync = () => { boxUnico.hidden = chk.checked; boxParc.hidden = !chk.checked; };
  chk.addEventListener("change", () => {
    sync();
    if (chk.checked) abrirDlg(); else fecharDlg();
  });
  sync();

  // ---------- resumo no card (lançamentos × repasses) ----------
  const resumo = document.getElementById("resumo-comissao-parcelada");
  function atualizarResumo() {
    if (!resumo) return;
    const nc = document.querySelectorAll("#corpo-comissoes tr.fluxo-linha").length;
    const nr = document.querySelectorAll("#corpo-repasses tr.fluxo-linha").length;
    resumo.textContent = nc + " lançamento(s) de comissão · " + nr + " repasse(s)";
  }

  // ---------- controlador genérico de tabela (comissão / repasse) ----------
  function montarFluxo(cfg) {
    const corpo = document.getElementById(cfg.corpo);
    const tpl = document.getElementById(cfg.tpl);
    const total = document.getElementById(cfg.total);
    if (!corpo || !tpl) return;

    const linhas = () => Array.from(corpo.querySelectorAll("tr.fluxo-linha"));
    const campo = (tr, nome) => tr.querySelector('[name="' + nome + '"]');
    // o select "Conferido no banco" ([data-conf]) NÃO trava junto com a linha —
    // a conferência do depósito acontece depois que o "recebido" já foi lançado.
    const editaveis = (tr) =>
      Array.from(tr.querySelectorAll("input:not([type=hidden]), select"))
        .filter((el) => !el.hasAttribute("data-conf"));

    function ultimaPreenchida() {
      const ls = linhas();
      for (let i = ls.length - 1; i >= 0; i--) {
        if (campo(ls[i], cfg.campoData).value || campo(ls[i], cfg.campoValor).value) return ls[i];
      }
      return null;
    }
    function travar(tr) {
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
    function atualizarTotal() {
      const ls = linhas();
      let conferidas = 0;
      ls.forEach((tr) => {
        const sel = tr.querySelector("[data-conf]");
        const on = !!sel && sel.value === "1";
        if (on) conferidas++;
        tr.classList.toggle("linha-conferida", on);
      });
      const rows = ls.map((tr) => ({
        v1: num(campo(tr, cfg.campoValor).value),
        v2: cfg.campoValor2 ? num(campo(tr, cfg.campoValor2).value) : 0,
      }));
      total.textContent = cfg.textoTotal(rows, { conferidas });

      const elAviso = cfg.avisoEl && document.getElementById(cfg.avisoEl);
      if (elAviso) {                                // divergência × total do relatório
        const somaP = rows.reduce((s, r) => s + r.v1, 0);
        const somaR = rows.reduce((s, r) => s + r.v2, 0);
        const rp = num((document.getElementById(cfg.relPrevisto) || {}).value);
        const rr = num((document.getElementById(cfg.relRecebido) || {}).value);
        const dif = [];
        if (rp && Math.abs(rp - somaP) >= 0.01) dif.push("Previsto");
        if (rr && Math.abs(rr - somaR) >= 0.01) dif.push("Recebido");
        elAviso.textContent = dif.length ? "⚠ Divergência no valor " + dif.join(" e ") : "";
      }
      atualizarResumo();
    }
    function novaLinha(d) {
      const tr = tpl.content.firstElementChild.cloneNode(true);
      if (d) {
        if (d.parcela != null) campo(tr, cfg.campoParcela).value = d.parcela;
        if (d.data != null) campo(tr, cfg.campoData).value = d.data;
        if (d.valor != null) campo(tr, cfg.campoValor).value = d.valor;
      }
      corpo.appendChild(tr);
      return tr;
    }

    corpo.addEventListener("click", (e) => {
      const bEdit = e.target.closest("[data-editar]");
      if (bEdit) {
        const tr = bEdit.closest("tr.fluxo-linha");
        if (tr.classList.contains("linha-liberada")) {
          // 2º clique: só re-trava a linha (o Salvar de verdade é o do rodapé da janela)
          if (bEdit.dataset.iconeOriginal) bEdit.innerHTML = bEdit.dataset.iconeOriginal;
          bEdit.classList.replace("btn--primario", "btn--linha");
          bEdit.title = "Liberar edição";
          tr.classList.remove("linha-liberada");
          travar(tr);
          atualizarTotal();
          return;
        }
        if (!bEdit.dataset.iconeOriginal) bEdit.dataset.iconeOriginal = bEdit.innerHTML;
        destravar(tr);
        tr.classList.add("linha-liberada");
        bEdit.classList.replace("btn--linha", "btn--primario");
        bEdit.textContent = "Salvar";
        bEdit.title = "Guardar esta linha";
        const primeiro = editaveis(tr)[0];
        if (primeiro) primeiro.focus();
        return;
      }
      const bDel = e.target.closest("[data-remover]");
      if (!bDel) return;
      bDel.closest("tr.fluxo-linha").remove();
      atualizarTotal();
    });
    corpo.addEventListener("input", atualizarTotal);
    corpo.addEventListener("change", atualizarTotal);

    const btnAdd = document.getElementById(cfg.btnAdd);
    if (btnAdd) {
      btnAdd.addEventListener("click", () => {
        const base = ultimaPreenchida();
        let sug = null;
        if (base) {
          const d = campo(base, cfg.campoData).value;
          sug = { data: d ? addMeses(d, 1) : "", valor: campo(base, cfg.campoValor).value || "" };
        }
        novaLinha(sug);
        atualizarTotal();
      });
    }

    const btnGer = document.getElementById(cfg.btnGerar);
    if (btnGer) {
      btnGer.addEventListener("click", () => {
        const qtd = parseInt(document.getElementById(cfg.gerQtd).value, 10);
        const valor = num(document.getElementById(cfg.gerValor).value);
        const data1 = document.getElementById(cfg.gerData1).value;
        if (!qtd || qtd < 1) { alert("Informe a quantidade de meses."); return; }
        const temDados = linhas().some((tr) =>
          campo(tr, cfg.campoData).value || campo(tr, cfg.campoValor).value || campo(tr, cfg.campoParcela).value);
        if (temDados && !confirm("Substituir a tabela atual?")) return;
        corpo.innerHTML = "";
        for (let i = 1; i <= qtd; i++) {
          novaLinha({
            parcela: String(i),
            data: data1 ? addMeses(data1, i - 1) : "",
            valor: valor ? fmt(valor) : "",
          });
        }
        atualizarTotal();
      });
    }

    [cfg.relPrevisto, cfg.relRecebido].forEach((id) => {
      const el = id && document.getElementById(id);
      if (el) el.addEventListener("input", atualizarTotal);
    });

    if (!linhas().length) novaLinha();
    linhas().forEach((tr) => { if (cfg.ehTravada(tr, campo)) travar(tr); });
    atualizarTotal();
  }

  montarFluxo({
    corpo: "corpo-comissoes", tpl: "tpl-comissao", total: "total-comissoes",
    btnAdd: "btn-add-comissao", btnGerar: "btn-gerar-comissoes",
    gerQtd: "ger_com_qtd", gerValor: "ger_com_valor", gerData1: "ger_com_data1",
    campoParcela: "comissao_parcela", campoData: "comissao_data",
    campoValor: "comissao_previsto", campoValor2: "comissao_recebido",
    relPrevisto: "previsto_relatorio_seguralta", relRecebido: "recebido_relatorio_seguralta",
    avisoEl: "aviso-com",
    ehTravada: (tr, campo) => (campo(tr, "comissao_recebido").value || "").trim() !== "",
    textoTotal: (rows) => {
      if (!rows.length) return "";
      const prev = rows.reduce((s, r) => s + r.v1, 0);
      const receb = rows.reduce((s, r) => s + r.v2, 0);
      return rows.length + " linha(s) · previsto R$ " + fmt(prev) + " · recebido R$ " + fmt(receb);
    },
  });

  montarFluxo({
    corpo: "corpo-repasses", tpl: "tpl-repasse", total: "total-repasses",
    btnAdd: "btn-add-repasse", btnGerar: "btn-gerar-repasses",
    gerQtd: "ger_rep_qtd", gerValor: "ger_rep_valor", gerData1: "ger_rep_data1",
    campoParcela: "repasse_parcela", campoData: "repasse_data",
    campoValor: "repasse_previsto", campoValor2: "repasse_recebido",
    relPrevisto: "previsto_relatorio_plenus", relRecebido: "recebido_relatorio_plenus",
    avisoEl: "aviso-rep",
    ehTravada: (tr, campo) => (campo(tr, "repasse_recebido").value || "").trim() !== "",
    textoTotal: (rows, extra) => {
      if (!rows.length) return "";
      const prev = rows.reduce((s, r) => s + r.v1, 0);
      const receb = rows.reduce((s, r) => s + r.v2, 0);
      let t = rows.length + " linha(s) · pendente R$ " + fmt(prev) + " · pago R$ " + fmt(receb);
      if (extra && extra.conferidas) t += " · " + extra.conferidas + " conferida(s) no banco";
      return t;
    },
  });

  // ---------- conferência (uma no bloco Comissão, outra no bloco Repasses) ----------
  const FATOR_PLENUS = 0.75;
  const elConfCom = document.getElementById("conf-comissao");
  const elConfRep = document.getElementById("conf-repasse");

  function somaCampo(corpoId, nome) {
    const c = document.getElementById(corpoId);
    if (!c) return 0;
    return Array.from(c.querySelectorAll('[name="' + nome + '"]'))
      .reduce((s, el) => s + num(el.value), 0);
  }
  function selo(esp, lan) {
    const ok = Math.abs(esp - lan) < 0.01;
    return ' <span class="' + (ok ? "ok" : "ruim") + '">' +
      (ok ? "✓ confere" : "⚠ Diferença de R$ " + fmt(Math.abs(esp - lan))) + "</span>";
  }
  function conferir75() {
    const cR = somaCampo("corpo-comissoes", "comissao_recebido");
    const rR = somaCampo("corpo-repasses", "repasse_recebido");
    const pct = num((document.getElementById("comissao_percentual") || {}).value);
    const valor = num((document.getElementById("valor") || {}).value);
    const base = Math.round((pct / 100) * valor * 100) / 100;   // comissão = pct% × valor do endosso

    // bloco Comissão
    if (elConfCom) {
      if (!(pct && valor) && !cR) {
        elConfCom.hidden = true;
      } else {
        elConfCom.hidden = false;
        let l;
        if (!(pct && valor)) {
          l = '<span style="color:var(--texto-suave)">Informe Percentual (%) e Valor do endosso</span>';
        } else {
          const pctTxt = Number.isInteger(pct) ? String(pct) : fmt(pct);
          l = "Comissão de " + pctTxt + "% do valor do endosso = R$ " + fmt(base) +
            (cR ? selo(base, Math.round(cR * 100) / 100) : "");
        }
        elConfCom.innerHTML = "<strong>Conferência</strong><div>" + l + "</div>";
      }
    }

    // bloco Repasses / Plenus
    if (elConfRep) {
      if (!(cR || rR)) {
        elConfRep.hidden = true;
      } else {
        elConfRep.hidden = false;
        const esp = Math.round(FATOR_PLENUS * cR * 100) / 100;
        const l = "Repasse de 75% da comissão recebida = R$ " + fmt(esp) +
          selo(esp, Math.round(rR * 100) / 100);
        elConfRep.innerHTML = "<strong>Conferência</strong><div>" + l + "</div>";
      }
    }
  }

  const corpoDlg = document.querySelector("#dlg-comissao .dlg__corpo");
  if (corpoDlg) corpoDlg.addEventListener("input", conferir75);
  ["comissao_percentual", "valor"].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.addEventListener("input", conferir75);
  });
  conferir75();
  atualizarResumo();
})();
