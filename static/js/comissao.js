/* Card "Comissão" do formulário de apólice.
   Checkbox alterna entre o modo "repasse único" (4 valores achatados) e o
   "repasse parcelado" (duas tabelas: Comissão e Repasses), no mesmo padrão
   das parcelas / lançamentos. Validação que vale é a do servidor. */
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

  function enviarForm(el) {
    const f = el.form || el.closest("form");
    if (!f) return;
    if (f.requestSubmit) f.requestSubmit();
    else f.submit();
  }

  // ---------- alterna único / parcelado + janela (dialog) ----------
  const chk = document.getElementById("comissao_parcelada");
  const boxUnico = document.getElementById("comissao-unico");
  const boxParc = document.getElementById("comissao-parcelado");
  const dlg = document.getElementById("dlg-comissao");

  function abrirDlg() { if (dlg && !dlg.open) (dlg.showModal ? dlg.showModal() : dlg.show()); }
  function fecharDlg() { if (dlg && dlg.open) dlg.close(); }

  const btnAbrir = document.getElementById("btn-abrir-comissao");
  if (btnAbrir) btnAbrir.addEventListener("click", abrirDlg);
  document.querySelectorAll("[data-fechar-comissao]").forEach((b) =>
    b.addEventListener("click", fecharDlg));

  if (chk && boxUnico && boxParc) {
    const sync = () => { boxUnico.hidden = chk.checked; boxParc.hidden = !chk.checked; };
    chk.addEventListener("change", () => {
      sync();
      if (chk.checked) abrirDlg(); else fecharDlg();
    });
    sync();
  }

  // ---------- controlador genérico de tabela (comissão / repasse) ----------
  function montarFluxo(cfg) {
    const corpo = document.getElementById(cfg.corpo);
    const tpl = document.getElementById(cfg.tpl);
    const total = document.getElementById(cfg.total);
    if (!corpo || !tpl) return;

    const linhas = () => Array.from(corpo.querySelectorAll("tr.fluxo-linha"));
    const campo = (tr, nome) => tr.querySelector('[name="' + nome + '"]');
    const editaveis = (tr) => Array.from(tr.querySelectorAll("input:not([type=hidden]), select"));

    function preenchida(tr) {
      return editaveis(tr).some((el) => (el.value || "").trim());
    }
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
      total.textContent = cfg.textoTotal(linhas().map((tr) => ({
        v1: num(campo(tr, cfg.campoValor).value),
        v2: cfg.campoValor2 ? num(campo(tr, cfg.campoValor2).value) : 0,
        preenchida: preenchida(tr),
      })));
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
        if (tr.classList.contains("linha-liberada")) {   // 2º clique = já é "Salvar"
          enviarForm(bEdit);
          return;
        }
        destravar(tr);
        tr.classList.add("linha-liberada");
        bEdit.classList.replace("btn--linha", "btn--primario");
        bEdit.textContent = "Salvar";
        bEdit.title = "Salvar a apólice";
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
    ehTravada: (tr, campo) => (campo(tr, "repasse_recebido").value || "").trim() !== "",
    textoTotal: (rows) => {
      if (!rows.length) return "";
      const prev = rows.reduce((s, r) => s + r.v1, 0);
      const receb = rows.reduce((s, r) => s + r.v2, 0);
      return rows.length + " linha(s) · previsto R$ " + fmt(prev) + " · recebido R$ " + fmt(receb);
    },
  });
})();
