/* Formulário de serviço: card "Veículo".
   Mostra os carros que o cliente já tem cadastrados (apólices, endossos, outros serviços)
   para confirmar que é o mesmo, ou "Cadastrar outro carro" (libera placa/descrição).
   Pagamento e comissão são os mesmos da apólice (apolice.js + comissao.js). */
(function () {
  "use strict";

  const selCliente = document.getElementById("cliente_id");
  const box = document.getElementById("veiculos-cliente");
  const campos = document.getElementById("veiculo-campos");
  const dica = document.getElementById("veiculos-dica");
  const inPlaca = document.getElementById("veiculo_placa");
  const inDesc = document.getElementById("veiculo_descricao");
  if (!selCliente || !box || !campos || !inPlaca || !inDesc) return;

  const norm = (s) => (s || "").trim().toUpperCase();
  const radios = () => Array.from(box.querySelectorAll('input[name="veiculo_escolha"]'));
  const radioNovo = () => box.querySelector('input[name="veiculo_escolha"][value="novo"]');
  const qtdVeiculos = () => radios().length - 1;

  function travarCampos(travar) {
    [inPlaca, inDesc].forEach((el) => {
      if (travar) el.setAttribute("readonly", "readonly");
      else el.removeAttribute("readonly");
    });
  }

  function aplicar(radio, focar) {
    if (!radio) {                       // nada escolhido ainda: esconde os campos
      campos.hidden = true;
      return;
    }
    campos.hidden = false;
    if (radio.value === "novo") {
      // vindo de um carro da lista: limpa pra digitar o novo
      if (inPlaca.hasAttribute("readonly")) { inPlaca.value = ""; inDesc.value = ""; }
      travarCampos(false);
      if (focar) inPlaca.focus();
    } else {
      inPlaca.value = radio.dataset.placa || "";
      inDesc.value = radio.dataset.descricao || "";
      travarCampos(true);
    }
  }

  function atualizarDica() {
    const n = qtdVeiculos();
    dica.textContent = !selCliente.value
      ? "Selecione o cliente para ver os veículos dele."
      : n === 0
        ? "Este cliente ainda não tem veículo cadastrado — informe o carro abaixo."
        : "Confirme se é um destes carros do cliente ou cadastre outro.";
  }

  // escolha inicial: o carro gravado no serviço, se estiver na lista; senão "outro carro"
  function selecionarInicial(placa, descricao) {
    const alvo = radios().find((r) => r.value !== "novo" && (
      norm(placa) ? norm(r.dataset.placa) === norm(placa)
                  : norm(descricao) && norm(r.dataset.descricao) === norm(descricao)));
    let escolhido = alvo || null;
    if (!escolhido && (norm(placa) || norm(descricao) || qtdVeiculos() === 0)) escolhido = radioNovo();
    radios().forEach((r) => { r.checked = r === escolhido; });
    if (escolhido && escolhido.value === "novo") {
      travarCampos(false);
      campos.hidden = false;
    } else {
      aplicar(escolhido, false);
    }
  }

  function montarOpcoes(veiculos) {
    box.innerHTML = "";
    const opcao = (valor, montarTexto, dados) => {
      const lbl = document.createElement("label");
      lbl.className = "veic-opcao";
      const r = document.createElement("input");
      r.type = "radio";
      r.name = "veiculo_escolha";
      r.value = valor;
      if (dados) { r.dataset.placa = dados.placa || ""; r.dataset.descricao = dados.descricao || ""; }
      const span = document.createElement("span");
      montarTexto(span);
      lbl.append(r, span);
      box.appendChild(lbl);
    };
    veiculos.forEach((v, i) => opcao(String(i), (span) => {
      const b = document.createElement("strong");
      b.textContent = v.placa || "sem placa";
      const sm = document.createElement("small");
      sm.className = "meta";
      sm.textContent = "— " + (v.origem || "");
      span.append(b, " " + (v.descricao || "") + " ", sm);
    }, v));
    opcao("novo", (span) => { span.textContent = "Cadastrar outro carro"; });
  }

  box.addEventListener("change", (e) => {
    if (e.target.name === "veiculo_escolha") aplicar(e.target, true);
  });

  selCliente.addEventListener("change", () => {
    inPlaca.value = "";
    inDesc.value = "";
    travarCampos(false);
    if (!selCliente.value) {
      montarOpcoes([]);
      selecionarInicial("", "");
      atualizarDica();
      return;
    }
    const url = (selCliente.dataset.urlVeiculos || "").replace(/\/0$/, "/" + selCliente.value);
    fetch(url, { headers: { Accept: "application/json" }, credentials: "same-origin" })
      .then((r) => (r.ok ? r.json() : { veiculos: [] }))
      .catch(() => ({ veiculos: [] }))
      .then((j) => {
        montarOpcoes(j.veiculos || []);
        selecionarInicial("", "");
        atualizarDica();
      });
  });

  selecionarInicial(box.dataset.placa, box.dataset.descricao);
  atualizarDica();
})();
