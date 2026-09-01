/* Botão "Ler apólice": envia um PDF ao servidor, que extrai os campos e devolve JSON;
   aqui a gente só preenche o formulário (campos vazios de preferência) pro usuário conferir. */
(function () {
  "use strict";

  const botao = document.querySelector("[data-ler-pdf]");
  const arquivo = document.getElementById("arquivo-pdf");
  const status = document.getElementById("ler-pdf-status");
  if (!botao || !arquivo) return;

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

    fetch(botao.dataset.endpoint, { method: "POST", body: fd })
      .then((r) => r.json())
      .then((res) => {
        const campos = (res && res.campos) || {};
        let n = 0;
        for (const [nome, valor] of Object.entries(campos)) {
          if (nome === "parcelas" || valor == null || valor === "") continue;
          if (preencher(nome, valor)) n++;
        }
        if (Array.isArray(campos.parcelas) && campos.parcelas.length && window.plenusSetParcelas) {
          window.plenusSetParcelas(campos.parcelas);
          n++;
        }
        const origem = res.origem === "ocr" ? " (via OCR)" : "";
        let msg = n
          ? n + " campo(s) preenchido(s) a partir do PDF" + origem + ". Confira antes de salvar."
          : "Nenhum campo reconhecido nesse PDF.";
        if (res.aviso) msg += " " + res.aviso;
        dizer(msg, !n);
      })
      .catch(() => dizer("Não consegui processar o PDF.", true))
      .finally(() => { botao.disabled = false; arquivo.value = ""; });
  });

  // alguns campos do PDF vêm por nome e o formulário guarda o id (FK)
  const ALIAS = { seguradora: "seguradora_id" };

  const normal = (s) =>
    (s == null ? "" : "" + s).trim().toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");

  // preenche um campo pelo name; devolve true se conseguiu pôr algo
  function preencher(nome, valor) {
    const alvo = ALIAS[nome] || nome;
    const el = document.querySelector('[name="' + alvo + '"]');
    if (!el) return false;

    if (el.tagName === "SELECT") {
      if (alvo === "end_estado") {
        el.value = valor;
        el.dispatchEvent(new Event("change"));
        return el.value === valor;
      }
      if (alvo === "end_cidade") {
        if (![...el.options].some((o) => o.value === valor)) el.add(new Option(valor, valor));
        el.value = valor;
        return true;
      }
      el.value = valor;
      if (el.value === String(valor)) return true;
      // casa pelo texto visível da opção (ex.: seguradora "Porto Seguro")
      const n = normal(valor);
      const opt = [...el.options].find((o) => {
        const to = normal(o.textContent);
        return to && (to === n || to.includes(n) || n.includes(to));
      });
      if (opt) { el.value = opt.value; return true; }
      return false;
    }

    if (el.value && el.value.trim()) return false; // não sobrescreve o que já foi digitado
    el.value = valor;
    realce(el);
    return true;
  }

  function realce(el) {
    el.classList.add("foi-preenchido");
    setTimeout(() => el.classList.remove("foi-preenchido"), 2500);
  }
})();
