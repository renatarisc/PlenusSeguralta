/* Máscaras, validações e selects UF <-> Cidade do formulário de cliente.
   (A validação que VALE é a do servidor - aqui é só ajuda visual.) */
(function () {
  "use strict";

  const soDig = (s) => (s || "").replace(/\D/g, "");

  // ---------- máscaras ----------
  const MASCARAS = {
    cpf: (v) => {
      v = soDig(v).slice(0, 11);
      return v
        .replace(/^(\d{3})(\d)/, "$1.$2")
        .replace(/^(\d{3})\.(\d{3})(\d)/, "$1.$2.$3")
        .replace(/\.(\d{3})(\d)/, ".$1-$2");
    },
    cnpj: (v) => {
      v = soDig(v).slice(0, 14);
      return v
        .replace(/^(\d{2})(\d)/, "$1.$2")
        .replace(/^(\d{2})\.(\d{3})(\d)/, "$1.$2.$3")
        .replace(/\.(\d{3})(\d)/, ".$1/$2")
        .replace(/(\d{4})(\d)/, "$1-$2");
    },
    cep: (v) => soDig(v).slice(0, 8).replace(/^(\d{5})(\d)/, "$1-$2"),
    ddd: (v) => soDig(v).slice(0, 2),
    telefone: (v) => {
      v = soDig(v).slice(0, 9);
      if (v.length > 5) return v.replace(/^(\d{5})(\d{0,4}).*/, "$1-$2");
      return v.replace(/^(\d{4})(\d{0,4}).*/, "$1-$2").replace(/-$/, "");
    },
  };

  document.querySelectorAll("[data-mask]").forEach((el) => {
    // lê data-mask a cada input: o campo CPF/CNPJ troca de máscara em runtime
    const aplica = () => {
      const fn = MASCARAS[el.dataset.mask];
      if (fn) el.value = fn(el.value);
    };
    aplica();
    el.addEventListener("input", aplica);
  });

  // ---------- validações leves ----------
  function cpfValido(cpf) {
    const d = soDig(cpf);
    if (d.length !== 11 || /^(\d)\1{10}$/.test(d)) return false;
    for (const tam of [9, 10]) {
      let soma = 0;
      for (let i = 0; i < tam; i++) soma += +d[i] * (tam + 1 - i);
      let dig = (soma * 10) % 11;
      if (dig === 10) dig = 0;
      if (dig !== +d[tam]) return false;
    }
    return true;
  }
  function cnpjValido(cnpj) {
    const d = soDig(cnpj);
    if (d.length !== 14 || /^(\d)\1{13}$/.test(d)) return false;
    for (const tam of [12, 13]) {
      const pesos = [];
      for (let p = tam - 7; p > 1; p--) pesos.push(p);
      for (let p = 9; p > 1; p--) pesos.push(p);
      let soma = 0;
      for (let i = 0; i < tam; i++) soma += +d[i] * pesos[i];
      let dig = soma % 11;
      dig = dig < 2 ? 0 : 11 - dig;
      if (dig !== +d[tam]) return false;
    }
    return true;
  }
  const emailValido = (v) => /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test((v || "").trim());

  function marcar(el, ok, msgErro, chave) {
    const dica = document.querySelector(`[data-dica="${chave || el.dataset.valida}"]`);
    const vazio = !el.value.trim();
    el.setAttribute("aria-invalid", vazio || ok ? "false" : "true");
    if (dica) {
      dica.textContent = vazio || ok ? "" : msgErro;
      dica.className = "dica" + (vazio || ok ? "" : " dica--erro");
    }
  }

  document.querySelectorAll('[data-valida="cpf"]').forEach((el) =>
    el.addEventListener("blur", () => marcar(el, cpfValido(el.value), "CPF inválido")));

  // campo único CPF/CNPJ: máscara, rótulo e validação seguem o select "Tipo"
  const selTipoPessoa = document.getElementById("tipo_pessoa");
  const campoDoc = document.querySelector("[data-doc]");
  if (selTipoPessoa && campoDoc) {
    const lblDoc = document.getElementById("lbl-doc");
    const lblNome = document.getElementById("lbl-nome");
    const ehPJ = () => selTipoPessoa.value === "J";
    const validaDoc = () => marcar(
      campoDoc,
      ehPJ() ? cnpjValido(campoDoc.value) : cpfValido(campoDoc.value),
      ehPJ() ? "CNPJ inválido" : "CPF inválido",
      "doc",
    );
    const sync = () => {
      campoDoc.dataset.mask = ehPJ() ? "cnpj" : "cpf";
      campoDoc.placeholder = ehPJ() ? "00.000.000/0000-00" : "000.000.000-00";
      if (lblDoc) lblDoc.textContent = ehPJ() ? "CNPJ *" : "CPF *";
      if (lblNome) lblNome.textContent = ehPJ() ? "Razão social *" : "Nome *";
      const fn = MASCARAS[campoDoc.dataset.mask];
      if (fn) campoDoc.value = fn(campoDoc.value);
      // nascimento e sexo não fazem sentido p/ pessoa jurídica: esconde e limpa
      ["data_nascimento", "sexo"].forEach((id) => {
        const el = document.getElementById(id);
        if (!el) return;
        const campo = el.closest(".campo");
        if (campo) campo.hidden = ehPJ();
        if (ehPJ()) el.value = "";
      });
      validaDoc();
    };
    selTipoPessoa.addEventListener("change", sync);
    campoDoc.addEventListener("blur", validaDoc);
    sync();
  }

  document.querySelectorAll('[data-valida="cep"]').forEach((el) =>
    el.addEventListener("blur", () => marcar(el, soDig(el.value).length === 8, "CEP deve ter 8 dígitos")));
  document.querySelectorAll('[data-valida="email"]').forEach((el) =>
    el.addEventListener("blur", () => marcar(el, emailValido(el.value), "E-mail em formato inválido")));

  // ---------- UF <-> Cidade ----------
  const selUF = document.querySelector("[data-uf]");
  const selCidade = document.querySelector("[data-cidade]");

  function preencherCidades(sigla, selecionar) {
    if (!selCidade) return;
    const est = (window.__ESTADOS || []).find((e) => e.sigla === sigla);
    selCidade.innerHTML = '<option value="">—</option>';
    if (est) {
      for (const nome of est.cidades) {
        const o = document.createElement("option");
        o.value = o.textContent = nome;
        if (nome === selecionar) o.selected = true;
        selCidade.appendChild(o);
      }
    }
    selCidade.disabled = !est;
  }

  if (selUF) {
    fetch("/static/dados/municipios.json")
      .then((r) => r.json())
      .then((estados) => {
        window.__ESTADOS = estados;
        for (const e of estados) {
          const o = document.createElement("option");
          o.value = e.sigla;
          o.textContent = `${e.sigla} — ${e.nome}`;
          if (e.sigla === selUF.dataset.valor) o.selected = true;
          selUF.appendChild(o);
        }
        preencherCidades(selUF.value, selCidade && selCidade.dataset.valor);
        selUF.addEventListener("change", () => preencherCidades(selUF.value, null));
      })
      .catch(() => { selUF.innerHTML = '<option value="">(erro ao carregar UFs)</option>'; });
  }

  // ---------- CEP -> ViaCEP (preenche rua/bairro/cidade/UF) ----------
  const campoCep = document.querySelector("[data-cep]");
  if (campoCep) {
    campoCep.addEventListener("blur", () => {
      const d = soDig(campoCep.value);
      if (d.length !== 8) return;
      fetch(`https://viacep.com.br/ws/${d}/json/`)
        .then((r) => r.json())
        .then((j) => {
          if (j.erro) return;
          const set = (id, v) => { const el = document.getElementById(id); if (el && v && !el.value) el.value = v; };
          set("end_rua", j.logradouro);
          set("end_bairro", j.bairro);
          // complemento: não preencher — o do ViaCEP é a faixa de numeração do CEP, não o do cliente
          if (selUF && j.uf) {
            selUF.value = j.uf;
            preencherCidades(j.uf, j.localidade);
          }
        })
        .catch(() => {});
    });
  }
})();
