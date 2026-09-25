/* Formulário de serviço: card "Apólice".
   Lista as apólices do cliente escolhido para ligar o serviço a uma delas; ao trocar o
   cliente, a lista é recarregada. Pagamento e comissão são os mesmos da apólice
   (apolice.js + comissao.js). */
(function () {
  "use strict";

  const selCliente = document.getElementById("cliente_id");
  const box = document.getElementById("apolices-cliente");
  const dica = document.getElementById("apolices-dica");
  if (!selCliente || !box || !dica) return;

  function montarOpcoes(apolices) {
    box.innerHTML = "";
    apolices.forEach((ap) => {
      const lbl = document.createElement("label");
      lbl.className = "ap-opcao";
      const r = document.createElement("input");
      r.type = "radio";
      r.name = "apolice_id";
      r.value = ap.id;
      const span = document.createElement("span");
      const b = document.createElement("strong");
      b.textContent = ap.numero_apolice || "sem número";
      span.appendChild(b);
      [ap.tipo_seguro_nome, ap.seguradora_nome].forEach((t) => { if (t) span.append(" · " + t); });
      [ap.vigencia ? "vigência " + ap.vigencia : "", ap.status_apolice_nome].forEach((t) => {
        if (!t) return;
        const sm = document.createElement("small");
        sm.className = "meta";
        sm.textContent = " · " + t;
        span.appendChild(sm);
      });
      const abrir = document.createElement("a");
      abrir.className = "link-abrir";
      abrir.href = "/apolices/" + ap.id;
      abrir.target = "_blank";
      abrir.rel = "noopener";
      abrir.textContent = "abrir";
      lbl.append(r, span, abrir);
      box.appendChild(lbl);
    });
    if (apolices.length === 1) box.querySelector("input").checked = true;
  }

  function atualizarDica(qtd) {
    dica.textContent = "";
    if (!selCliente.value) {
      dica.textContent = "Selecione o cliente para ver as apólices dele.";
    } else if (!qtd) {
      dica.append("Este cliente ainda não tem apólice cadastrada — ");
      const a = document.createElement("a");
      a.href = "/apolices/nova?cliente=" + encodeURIComponent(selCliente.value);
      a.target = "_blank";
      a.rel = "noopener";
      a.textContent = "cadastrar apólice";
      dica.append(a, ".");
    } else {
      dica.textContent = "Escolha a apólice à qual este serviço está ligado.";
    }
  }

  selCliente.addEventListener("change", () => {
    if (!selCliente.value) {
      montarOpcoes([]);
      atualizarDica(0);
      return;
    }
    const url = (selCliente.dataset.urlApolices || "").replace(/\/0$/, "/" + selCliente.value);
    fetch(url, { headers: { Accept: "application/json" }, credentials: "same-origin" })
      .then((r) => (r.ok ? r.json() : { apolices: [] }))
      .catch(() => ({ apolices: [] }))
      .then((j) => {
        const lista = j.apolices || [];
        montarOpcoes(lista);
        atualizarDica(lista.length);
      });
  });
})();
