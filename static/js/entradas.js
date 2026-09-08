/* Menu Entradas — grade editável das comissões por apólice.
   Um <section.ent-bloco> por apólice, cada um com seu <form> independente.
   Espelha o essencial de comissao.js/saida.js: trava a linha com "Pago Plenus"
   preenchido (lápis libera; 2º clique salva), adiciona/remove linha, e mantém
   a coluna "Situação" e os rótulos de parcela ocultos em sincronia.
   A validação que vale é a do servidor. */
(function () {
  "use strict";

  function hasVal(el) {
    return !!el && ("" + (el.value == null ? "" : el.value)).trim() !== "";
  }

  // número pt-BR <-> float (igual apolice.js)
  function num(v) {
    v = (v == null ? "" : "" + v).trim().replace(/\s|R\$/g, "");
    if (!v) return 0;
    if (v.indexOf(",") > -1) v = v.replace(/\./g, "").replace(",", ".");
    const n = parseFloat(v);
    return isNaN(n) ? 0 : n;
  }
  const fmt = (n) =>
    (Number(n) || 0).toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  // soma da entrada REAL: Seguralta = Recebido; Plenus = Pago
  function recomputarSoma(sec) {
    const alvo = sec.querySelector("[data-soma]");
    const corpo = sec.querySelector("[data-corpo]");
    if (!alvo || !corpo) return;
    const somar = (sel) =>
      Array.from(corpo.querySelectorAll(sel)).reduce((t, el) => t + num(el.value), 0);
    const seg = somar('input[name="comissao_recebido"], input[name="comissao_valor_seguralta_recebido"]');
    const ple = somar('input[name="repasse_recebido"], input[name="comissao_valor_plenus_recebido"]');
    alvo.textContent = "Seguralta R$ " + fmt(seg) + " | Plenus R$ " + fmt(ple);
  }
  function addMeses(iso, k) {
    const p = (iso || "").split("-").map(Number);
    if (p.length !== 3 || p.some(isNaN)) return "";
    const [y, m, d] = p;
    const dt = new Date(y, m - 1 + k, d);
    if (dt.getDate() < d) dt.setDate(0);
    const z = (n) => String(n).padStart(2, "0");
    return dt.getFullYear() + "-" + z(dt.getMonth() + 1) + "-" + z(dt.getDate());
  }

  // "Conferido no banco" (data-conf) segue editável mesmo com a linha travada.
  function editaveis(tr) {
    return Array.from(tr.querySelectorAll("input:not([type=hidden]), select"))
      .filter((el) => !el.hasAttribute("data-conf"));
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
    editaveis(tr).forEach((el) => {
      el.removeAttribute("readonly");
      el.removeAttribute("tabindex");
    });
  }

  function atualizarSituacao(tr) {
    const cel = tr.querySelector("[data-situacao]");
    if (!cel) return;
    const paga = hasVal(tr.querySelector("[data-ple-receb]"));
    cel.innerHTML = paga
      ? '<span class="selo-pago">Paga</span>'
      : '<span class="selo-apagar">A receber</span>';
  }

  // Um só campo visível "Parcela"; os hidden comissao_parcela / repasse_parcela
  // só recebem o rótulo quando aquele lado tem algum valor — senão o servidor
  // criaria linhas fantasmas (parcela sem valor) em apolice_comissao/repasse.
  function sincronizarParcela(tr) {
    const vis = tr.querySelector("[data-parcela]");
    if (!vis) return; // linha "única" não tem rótulo editável
    const rotulo = (vis.value || "").trim();
    const temLado = (nomes) =>
      nomes.some((n) => hasVal(tr.querySelector('[name="' + n + '"]')));
    const com = tr.querySelector("[data-com-parcela]");
    const rep = tr.querySelector("[data-rep-parcela]");
    if (com) com.value = temLado(["comissao_previsto", "comissao_recebido", "comissao_data"]) ? rotulo : "";
    if (rep) rep.value = temLado(["repasse_previsto", "repasse_recebido", "repasse_data"]) ? rotulo : "";
  }

  function initBloco(sec) {
    const corpo = sec.querySelector("[data-corpo]");
    const form = sec.querySelector("form");
    const tpl = document.getElementById("tpl-ent-linha");
    if (!corpo || !form) return;

    const sincTodas = () => corpo.querySelectorAll("tr").forEach(sincronizarParcela);

    corpo.querySelectorAll("tr").forEach((tr) => {
      sincronizarParcela(tr);
      if (hasVal(tr.querySelector("[data-ple-receb]"))) travar(tr);
    });
    recomputarSoma(sec);

    sec.addEventListener("input", (e) => {
      const tr = e.target.closest("tr");
      if (!tr) return;
      sincronizarParcela(tr);
      if (e.target.hasAttribute("data-ple-receb")) atualizarSituacao(tr);
      recomputarSoma(sec);
    });

    sec.addEventListener("click", (e) => {
      const bEdit = e.target.closest("[data-editar]");
      const bDel = e.target.closest("[data-remover]");
      const bAdd = e.target.closest("[data-add-linha]");

      if (bEdit) {
        const tr = bEdit.closest("tr");
        if (tr.classList.contains("linha-liberada")) {
          sincTodas();
          if (form.requestSubmit) form.requestSubmit();
          else form.submit();
          return;
        }
        destravar(tr);
        tr.classList.add("linha-liberada");
        bEdit.classList.replace("btn--linha", "btn--primario");
        bEdit.textContent = "Salvar";
        const alvo = editaveis(tr)[0];
        if (alvo) alvo.focus();
      } else if (bDel) {
        bDel.closest("tr").remove();
        recomputarSoma(sec);
      } else if (bAdd) {
        const nova = tpl.content.firstElementChild.cloneNode(true);
        const linhas = corpo.querySelectorAll("tr");
        const ult = linhas[linhas.length - 1];
        if (ult) {
          const d = ult.querySelector('[name="comissao_data"]');
          const v = ult.querySelector('[name="comissao_previsto"]');
          const p = ult.querySelector("[data-parcela]");
          if (d && d.value) nova.querySelector('[name="comissao_data"]').value = addMeses(d.value, 1);
          if (v && v.value) nova.querySelector('[name="comissao_previsto"]').value = v.value;
          if (p && /^\d+$/.test((p.value || "").trim()))
            nova.querySelector("[data-parcela]").value = String(parseInt(p.value, 10) + 1);
        }
        corpo.appendChild(nova);
        recomputarSoma(sec);
        const foco = nova.querySelector("input:not([type=hidden])");
        if (foco) foco.focus();
      }
    });

    form.addEventListener("submit", sincTodas);
  }

  document.querySelectorAll(".ent-bloco").forEach(initBloco);
})();
