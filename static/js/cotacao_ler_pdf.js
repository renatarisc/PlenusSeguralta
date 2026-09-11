/* "Ler PDF" em Cotação → Gerar: envia um PDF de comparativo ao servidor, que já
   devolve os valores casados com os campos cadastrados (por id) — aqui só preenche
   o formulário (uma cotação por oferta encontrada, sem sobrescrever o que já foi
   digitado) pro usuário conferir antes de finalizar. */
(function () {
  "use strict";

  const botao = document.querySelector("[data-ler-pdf]");
  const arquivo = document.getElementById("cotacao-arquivo-pdf");
  const status = document.getElementById("cotacao-ler-pdf-status");
  const form = document.getElementById("form-cotacao");
  const cont = document.getElementById("cotacoes");
  const btnAdd = document.getElementById("add-cotacao");
  if (!botao || !arquivo || !form || !cont) return;

  const dizer = (msg, erro) => {
    if (!status) return;
    status.textContent = msg;
    status.className = "dica" + (erro ? " dica--erro" : "");
  };

  botao.addEventListener("click", () => arquivo.click());

  arquivo.addEventListener("change", () => {
    const f = arquivo.files && arquivo.files[0];
    if (!f) return;
    if (!/\.pdf$/i.test(f.name)) { dizer("Escolha um arquivo PDF.", true); return; }

    dizer("Lendo " + f.name + "…");
    botao.disabled = true;
    const fd = new FormData();
    fd.append("arquivo", f);

    const csrf = (document.querySelector('meta[name="csrf-token"]') || {}).content || "";
    fetch(botao.dataset.endpoint, { method: "POST", body: fd, headers: { "X-CSRFToken": csrf } })
      .then((r) => r.json())
      .then((res) => {
        const n = preencherTudo(res);
        const nOfertas = Array.isArray(res.cotacoes) ? res.cotacoes.length : 0;
        const origem = res.origem === "ocr" ? " (via OCR)" : "";
        let msg;
        if (n) {
          msg = "Atenção: " + nOfertas + " oferta(s) reconhecida(s) e " + n +
                " campo(s) preenchido(s) a partir do PDF" + origem + ". Confira antes de Finalizar.";
        } else {
          msg = "Nenhum campo reconhecido nesse PDF.";
          if (res.aviso) msg += " " + res.aviso;
        }
        dizer(msg, !n);
      })
      .catch(() => dizer("Não consegui processar o PDF.", true))
      .finally(() => { botao.disabled = false; arquivo.value = ""; });
  });

  function preencherTudo(res) {
    let n = 0;

    const cliente = form.querySelector('[name="cliente"]');
    if (cliente && !cliente.value.trim() && res.cliente) {
      cliente.value = res.cliente;
      n++;
    }

    const cotacoes = Array.isArray(res.cotacoes) ? res.cotacoes : [];
    for (let i = 0; i < cotacoes.length; i++) {
      garantirBloco(i);
      const bloco = cont.querySelectorAll(".cot-bloco")[i];
      if (!bloco) continue;
      n += preencherBloco(bloco, cotacoes[i]);
    }
    return n;
  }

  // garante que existe pelo menos `indice + 1` blocos de cotação (clona clicando
  // no mesmo botão "Adicionar cotação" que a usuária usaria manualmente)
  function garantirBloco(indice) {
    while (cont.querySelectorAll(".cot-bloco").length <= indice) {
      if (!btnAdd) break;
      btnAdd.click();
    }
  }

  function preencherBloco(bloco, cotacao) {
    let n = 0;
    const sel = bloco.querySelector('select[name="cot_seguradora"]');
    if (sel && !sel.value && cotacao.seguradora) {
      if (selecionarOpcao(sel, cotacao.seguradora)) n++;
    }
    const valores = cotacao.valores || {};
    for (const [campoId, valor] of Object.entries(valores)) {
      const el = bloco.querySelector('[name="campo_' + campoId + '"]');
      if (!el || valor == null || valor === "") continue;
      if (el.tagName === "SELECT") {
        if (!el.value && selecionarOpcao(el, valor)) n++;
      } else if (!el.value || !el.value.trim()) {
        el.value = valor;
        realce(el);
        n++;
      }
    }
    return n;
  }

  // seleciona pelo texto visível entre as opções JÁ cadastradas; na dúvida (nenhuma
  // opção bate) deixa em branco -- NUNCA cria uma opção nova no <select>
  function selecionarOpcao(select, texto) {
    const n = normal(texto);
    let opt = [...select.options].find((o) => normal(o.textContent) === n);
    if (!opt) opt = [...select.options].find((o) => {
      const t = normal(o.textContent);
      return t && (t.includes(n) || n.includes(t));
    });
    // seguradora: o nome do plano no PDF quase nunca é igual ao nome cadastrado
    // (ex.: "Pier Personalizado" vs "PIER SEGURADORA") -- casa se pelo menos uma
    // palavra "forte" (4+ letras) for comum aos dois textos.
    if (!opt && select.name === "cot_seguradora") {
      const palavras = n.split(/\s+/).filter((p) => p.length >= 4);
      opt = [...select.options].find((o) => {
        const palavrasOpt = normal(o.textContent).split(/\s+/).filter((p) => p.length >= 4);
        return palavrasOpt.some((p) => palavras.includes(p));
      });
    }
    if (!opt) return false;
    select.value = opt.value;
    realce(select);
    return true;
  }

  function normal(s) {
    return (s == null ? "" : "" + s).trim().toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");
  }

  function realce(el) {
    el.classList.add("foi-preenchido");
    setTimeout(() => el.classList.remove("foi-preenchido"), 2500);
  }
})();
