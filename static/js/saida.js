/* Formulário de saída (novo): tabela de lançamentos + gerador, no mesmo modelo
   das parcelas da apólice. A validação que vale é a do servidor. */
(function () {
  "use strict";

  const corpo = document.getElementById("corpo-lancamentos");
  const tpl = document.getElementById("tpl-lancamento");
  const resumo = document.getElementById("resumo-lancamentos");
  if (!corpo || !tpl) return;

  // ---- número pt-BR <-> float ----
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
    const p = iso.split("-").map(Number);
    if (p.length !== 3) return "";
    const [y, m, d] = p;
    const dt = new Date(y, m - 1 + k, d);
    if (dt.getDate() < d) dt.setDate(0); // estoura mês curto -> último dia
    const z = (n) => String(n).padStart(2, "0");
    return dt.getFullYear() + "-" + z(dt.getMonth() + 1) + "-" + z(dt.getDate());
  }

  function hojeISO() {
    const d = new Date();
    const z = (n) => String(n).padStart(2, "0");
    return d.getFullYear() + "-" + z(d.getMonth() + 1) + "-" + z(d.getDate());
  }
  function diasEntre(a, b) {
    const t = (s) => new Date(s + "T00:00:00Z").getTime();
    return Math.round((t(b) - t(a)) / 86400000);
  }
  const DIAS_PERTO = 10;

  function linhas() {
    return Array.from(corpo.querySelectorAll("tr.lancamento"));
  }

  function campo(tr, nome) {
    return tr.querySelector('[name="' + nome + '"]');
  }
  function preenchida(tr) {
    return ["saida_data", "saida_valor", "saida_parcela", "saida_pago_em"]
      .some((n) => campo(tr, n).value.trim());
  }
  function ultimaPreenchida() {
    const ls = linhas();
    for (let i = ls.length - 1; i >= 0; i--) {
      if (campo(ls[i], "saida_data").value || campo(ls[i], "saida_valor").value) return ls[i];
    }
    return null;
  }

  function atualizarPintura(tr) {
    const data = tr.querySelector('[name="saida_data"]').value;
    const pago = !!tr.querySelector('[name="saida_pago_em"]').value;
    const dias = data ? diasEntre(hojeISO(), data) : null;
    tr.classList.toggle("parcela--paga", pago);
    tr.classList.toggle("parcela--atrasada", !pago && dias !== null && dias < 0);
    tr.classList.toggle("parcela--perto", !pago && dias !== null && dias >= 0 && dias <= DIAS_PERTO);
  }

  function atualizarResumo() {
    let soma = 0;
    let n = 0;
    linhas().forEach((tr) => {
      soma += num(campo(tr, "saida_valor").value);
      atualizarPintura(tr);
      if (preenchida(tr)) n++;
    });
    resumo.textContent = n ? n + " lançamento(s) · soma R$ " + fmt(soma) : "";
  }

  function novaLinha(d) {
    const tr = tpl.content.firstElementChild.cloneNode(true);
    if (d) {
      tr.querySelector('[name="saida_data"]').value = d.data || "";
      tr.querySelector('[name="saida_valor"]').value = d.valor || "";
      tr.querySelector('[name="saida_parcela"]').value = d.parcela || "";
      tr.querySelector('[name="saida_pago_em"]').value = d.pago || "";
    }
    corpo.appendChild(tr);
    return tr;
  }

  // ---- linhas já pagas abrem travadas; o lápis libera ----
  function editaveis(tr) {
    return Array.from(tr.querySelectorAll("input:not([type=hidden])"));
  }
  function travar(tr) {
    tr.classList.add("lancamento--travada");
    editaveis(tr).forEach((i) => i.setAttribute("readonly", "readonly"));
  }
  function destravar(tr) {
    tr.classList.remove("lancamento--travada");
    editaveis(tr).forEach((i) => i.removeAttribute("readonly"));
  }

  corpo.addEventListener("click", (e) => {
    const bEdit = e.target.closest("[data-editar-lancamento]");
    if (bEdit) {
      const tr = bEdit.closest("tr.lancamento");
      destravar(tr);
      const primeiro = editaveis(tr)[0];
      if (primeiro) primeiro.focus();
      return;
    }
    const b = e.target.closest("[data-remover-lancamento]");
    if (!b) return;
    b.closest("tr.lancamento").remove();
    if (!linhas().length) novaLinha();
    atualizarResumo();
  });
  corpo.addEventListener("input", (e) => {
    if (["saida_valor", "saida_data", "saida_pago_em", "saida_parcela"].indexOf(e.target.name) > -1) atualizarResumo();
  });

  // sugestão a partir da última linha preenchida: mesmo dia do mês seguinte + mesmo valor
  function sugestao(k) {
    const base = ultimaPreenchida();
    if (!base) return null;
    const d = campo(base, "saida_data").value;
    return { data: d ? addMeses(d, k) : "", valor: campo(base, "saida_valor").value || "" };
  }

  const btnAdd = document.getElementById("btn-add-lancamento");
  if (btnAdd) {
    btnAdd.addEventListener("click", () => {
      novaLinha(sugestao(1));
      atualizarResumo();
    });
  }

  const btnGerar = document.getElementById("btn-gerar-lancamentos");
  if (btnGerar) {
    btnGerar.addEventListener("click", () => {
      const qtd = parseInt(document.getElementById("ger_qtd").value, 10);
      const valorInf = num(document.getElementById("ger_valor").value);
      const data1 = document.getElementById("ger_data1").value;
      const modo = (document.getElementById("ger_modo") || {}).value || "cada";
      if (!qtd || qtd < 1) { alert("Informe a quantidade de lançamentos."); return; }

      const temDados = linhas().some((tr) =>
        tr.querySelector('[name="saida_data"]').value ||
        tr.querySelector('[name="saida_valor"]').value ||
        tr.querySelector('[name="saida_parcela"]').value);
      if (temDados && !confirm("Substituir os lançamentos atuais?")) return;

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
          parcela: qtd > 1 ? i + "/" + qtd : "",
          data: data1 ? addMeses(data1, i - 1) : "",
          valor: valorInf ? fmt(valor) : "",
        });
      }
      atualizarResumo();
    });
  }

  if (!linhas().length) novaLinha();
  // ao abrir: trava as linhas que já vieram pagas do servidor
  linhas().forEach((tr) => {
    if (campo(tr, "saida_pago_em").value) travar(tr);
  });
  atualizarResumo();
})();
