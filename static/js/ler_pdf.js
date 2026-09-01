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

    const csrf = (document.querySelector('meta[name="csrf-token"]') || {}).content || "";
    fetch(botao.dataset.endpoint, { method: "POST", body: fd, headers: { "X-CSRFToken": csrf } })
      .then((r) => r.json())
      .then((res) => {
        const campos = (res && res.campos) || {};
        let n = 0;
        // estado precisa ser preenchido antes de cidade (o select de cidade é refeito no change)
        const prioridade = (k) => (k === "end_estado" ? 0 : k === "end_cidade" ? 1 : -1);
        const entradas = Object.entries(campos)
          .filter(([k, v]) => k !== "parcelas" && v != null && v !== "")
          .sort((a, b) => prioridade(a[0]) - prioridade(b[0]));
        for (const [nome, valor] of entradas) {
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
        mostrarTextoLido(res.texto);
      })
      .catch(() => dizer("Não consegui processar o PDF.", true))
      .finally(() => { botao.disabled = false; arquivo.value = ""; });
  });

  // alguns campos do PDF vêm por nome e o formulário guarda o id (FK)
  const ALIAS = {
    seguradora: "seguradora_id",
    tipo_seguro: "tipo_seguro_id",
    forma_pagamento: "forma_pagamento_id",
  };

  // link "ver texto lido" — ajuda a entender por que um campo não veio
  function mostrarTextoLido(texto) {
    if (!status || !texto) return;
    let cx = document.getElementById("ler-pdf-texto");
    if (!cx) {
      cx = document.createElement("div");
      cx.id = "ler-pdf-texto";
      const link = document.createElement("a");
      link.href = "#";
      link.textContent = "ver texto lido do PDF";
      link.style.cssText = "font-size:12px;text-decoration:underline";
      const pre = document.createElement("pre");
      pre.style.cssText =
        "display:none;white-space:pre-wrap;max-height:300px;overflow:auto;background:var(--fundo);" +
        "border:1px solid var(--linha);border-radius:8px;padding:10px;font-size:11px;margin-top:6px";
      link.addEventListener("click", (e) => {
        e.preventDefault();
        pre.style.display = pre.style.display === "none" ? "block" : "none";
      });
      cx.append(link, pre);
      status.after(cx);
    }
    cx.querySelector("pre").textContent = texto;
  }

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
      if (el.value === String(valor)) { el.dispatchEvent(new Event("change")); return true; }
      // casa pelo texto visível da opção (ex.: seguradora "Porto Seguro")
      const n = normal(valor);
      const opt = [...el.options].find((o) => {
        const to = normal(o.textContent);
        return to && (to === n || to.includes(n) || n.includes(to));
      });
      if (opt) { el.value = opt.value; el.dispatchEvent(new Event("change")); return true; }
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
