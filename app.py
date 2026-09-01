"""Plenus SEGURALTA - sistema web (Flask). Roda em desktop e celular pelo navegador.

    python app.py    ->  http://localhost:5000  (no PC)
                          http://IP-DO-PC:5000   (no celular, mesma rede Wi-Fi)
"""

from flask import Flask, render_template, request, redirect, url_for, flash

import db
import repo
from validacao import formatar_cpf, formatar_cep, formatar_telefone, validar_cliente

app = Flask(__name__)
app.secret_key = "plenus-seguralta-dev"  # trocar por algo secreto quando for pra valer

db.inicializar_db()

# slug na URL  <->  nome da tabela  (cadastros simples de "só nome")
_CADASTROS_SIMPLES = {
    "tipo-seguro": {"tabela": "tipo_seguro", "titulo": "Tipos de Seguro", "singular": "tipo de seguro"},
    "forma-pagamento": {"tabela": "forma_pagamento", "titulo": "Formas de Pagamento", "singular": "forma de pagamento"},
}

# disponível em todo template (máscaras na exibição, itens do menu)
app.jinja_env.filters["cpf"] = formatar_cpf
app.jinja_env.filters["cep"] = formatar_cep
app.jinja_env.globals["telefone"] = formatar_telefone
app.jinja_env.globals["MENU"] = [
    {"rota": "dashboard", "texto": "Painel", "icone": "painel"},
    {"rota": "clientes_lista", "texto": "Clientes", "icone": "clientes"},
    {"rota": "apolices", "texto": "Apólices", "icone": "apolices"},
    {"rota": "cadastro_simples", "texto": "Tipos de Seguro", "icone": "tag", "slug": "tipo-seguro"},
    {"rota": "cadastro_simples", "texto": "Formas de Pagamento", "icone": "pagamento", "slug": "forma-pagamento"},
]


@app.route("/")
def dashboard():
    return render_template("dashboard.html", ativo="dashboard")


# ---------- Clientes ----------

@app.route("/clientes")
def clientes_lista():
    busca = request.args.get("busca", "").strip()
    return render_template("clientes_lista.html", ativo="clientes_lista",
                           clientes=repo.listar_clientes(busca or None), busca=busca)


@app.route("/clientes/novo", methods=["GET", "POST"])
@app.route("/clientes/<int:cliente_id>", methods=["GET", "POST"])
def cliente_form(cliente_id=None):
    if request.method == "POST":
        dados = {k: request.form.get(k, "") for k in (
            "nome", "data_nascimento", "sexo", "cpf",
            "end_rua", "end_numero", "end_complemento", "end_bairro",
            "end_cep", "end_cidade", "end_estado", "tel_ddd", "tel_numero", "email",
        )}
        erros = validar_cliente(dados)
        if erros:
            for e in erros:
                flash(e, "erro")
            return render_template("clientes_form.html", ativo="clientes_lista",
                                   cliente={**dados, "id": cliente_id})
        if cliente_id:
            repo.atualizar_cliente(cliente_id, dados)
            flash("Cliente atualizado.", "ok")
        else:
            cliente_id = repo.criar_cliente(dados)
            flash("Cliente cadastrado.", "ok")
        return redirect(url_for("clientes_lista"))

    cliente = repo.obter_cliente(cliente_id) if cliente_id else None
    if cliente_id and not cliente:
        flash("Cliente não encontrado.", "erro")
        return redirect(url_for("clientes_lista"))
    return render_template("clientes_form.html", ativo="clientes_lista", cliente=cliente)


@app.route("/clientes/<int:cliente_id>/excluir", methods=["POST"])
def cliente_excluir(cliente_id):
    repo.excluir_cliente(cliente_id)
    flash("Cliente excluído.", "ok")
    return redirect(url_for("clientes_lista"))


# ---------- Cadastros simples (Tipos de Seguro / Formas de Pagamento) ----------

@app.route("/cadastros/<slug>")
def cadastro_simples(slug):
    cfg = _CADASTROS_SIMPLES.get(slug)
    if not cfg:
        flash("Cadastro não encontrado.", "erro")
        return redirect(url_for("dashboard"))
    return render_template("cadastro_simples.html", ativo="cadastro_simples", slug=slug,
                           titulo=cfg["titulo"], singular=cfg["singular"],
                           itens=repo.listar_simples(cfg["tabela"]))


@app.route("/cadastros/<slug>/salvar", methods=["POST"])
def cadastro_simples_salvar(slug):
    cfg = _CADASTROS_SIMPLES.get(slug)
    if cfg:
        item_id = request.form.get("id")
        nome = request.form.get("nome", "")
        if item_id:
            repo.renomear_simples(cfg["tabela"], int(item_id), nome)
        elif nome.strip():
            repo.criar_simples(cfg["tabela"], nome)
    return redirect(url_for("cadastro_simples", slug=slug))


@app.route("/cadastros/<slug>/<int:item_id>/excluir", methods=["POST"])
def cadastro_simples_excluir(slug, item_id):
    cfg = _CADASTROS_SIMPLES.get(slug)
    if cfg:
        repo.excluir_simples(cfg["tabela"], item_id)
    return redirect(url_for("cadastro_simples", slug=slug))


# ---------- Apólices (em construção) ----------

@app.route("/apolices")
def apolices():
    return render_template("apolices.html", ativo="apolices")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
