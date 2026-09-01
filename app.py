"""Plenus SEGURALTA - sistema web (Flask). Roda em desktop e celular pelo navegador.

    python app.py    ->  http://localhost:5000  (no PC)
                          http://IP-DO-PC:5000   (no celular, mesma rede Wi-Fi)
"""

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify

import db
import repo
import leitura_pdf
from validacao import (
    formatar_cpf, formatar_cep, formatar_telefone, validar_cliente,
    formatar_numero, formatar_moeda, formatar_data_br, validar_apolice, preparar_parcelas,
)

app = Flask(__name__)
app.secret_key = "plenus-seguralta-dev"  # trocar por algo secreto quando for pra valer
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024  # PDF de apólice: teto de 20 MB

db.inicializar_db()

# slug na URL  <->  nome da tabela  (cadastros simples de "só nome")
_CADASTROS_SIMPLES = {
    "tipo-seguro": {"tabela": "tipo_seguro", "titulo": "Tipos de Seguro", "singular": "tipo de seguro"},
    "forma-pagamento": {"tabela": "forma_pagamento", "titulo": "Formas de Pagamento", "singular": "forma de pagamento"},
    "seguradora": {"tabela": "seguradora", "titulo": "Seguradoras", "singular": "seguradora"},
}

# disponível em todo template (máscaras na exibição, itens do menu)
app.jinja_env.filters["cpf"] = formatar_cpf
app.jinja_env.filters["cep"] = formatar_cep
app.jinja_env.filters["numero"] = formatar_numero
app.jinja_env.filters["moeda"] = formatar_moeda
app.jinja_env.filters["data_br"] = formatar_data_br
app.jinja_env.globals["telefone"] = formatar_telefone
app.jinja_env.globals["MENU"] = [
    {"rota": "dashboard", "texto": "Painel", "icone": "painel"},
    {"rota": "clientes_lista", "texto": "Clientes", "icone": "clientes"},
    {"rota": "apolices", "texto": "Apólices", "icone": "apolices"},
    {"rota": "cadastro_simples", "texto": "Seguradoras", "icone": "predio", "slug": "seguradora"},
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


@app.route("/clientes/ler-pdf", methods=["POST"])
def cliente_ler_pdf():
    return _ler_pdf("cliente")


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


# ---------- Apólices ----------

_CAMPOS_APOLICE = (
    "cliente_id", "seguradora_id", "tipo_seguro_id", "numero_apolice",
    "vigencia_inicio", "vigencia_fim",
    "premio_liquido", "forma_pagamento_id", "comissao_percentual", "comissao_valor",
    "lancado_quiver", "link_onedrive",
)


def _apolice_para_form(ap, parcelas=None):
    """Deixa os números como texto pt-BR pros inputs (edição vinda do banco)."""
    if ap is None:
        return None
    ap = dict(ap)
    for campo in ("premio_liquido", "comissao_percentual", "comissao_valor"):
        ap[campo] = formatar_numero(ap.get(campo))
    fonte = parcelas if parcelas is not None else ap.get("parcelas", [])
    ap["parcelas"] = [{**p, "valor": formatar_numero(p.get("valor"))} for p in fonte]
    return ap


def _dados_form_apolice():
    return dict(
        clientes=repo.listar_clientes(),
        seguradoras=repo.listar_simples("seguradora"),
        tipos=repo.listar_simples("tipo_seguro"),
        formas=repo.listar_simples("forma_pagamento"),
    )


@app.route("/apolices")
def apolices():
    return render_template("apolices_lista.html", ativo="apolices",
                           apolices=repo.listar_apolices())


@app.route("/apolices/nova", methods=["GET", "POST"])
@app.route("/apolices/<int:apolice_id>", methods=["GET", "POST"])
def apolice_form(apolice_id=None):
    if request.method == "POST":
        dados = {k: request.form.get(k, "") for k in _CAMPOS_APOLICE}
        parcelas, erros_parcelas = preparar_parcelas(
            request.form.getlist("parcela_identificacao"),
            request.form.getlist("parcela_data"),
            request.form.getlist("parcela_valor"),
        )
        erros = validar_apolice(dados) + erros_parcelas
        if erros:
            for e in erros:
                flash(e, "erro")
            apolice = _apolice_para_form({**dados, "id": apolice_id}, parcelas=parcelas)
            return render_template("apolices_form.html", ativo="apolices",
                                   apolice=apolice, **_dados_form_apolice())
        if apolice_id:
            repo.atualizar_apolice(apolice_id, dados, parcelas)
            flash("Apólice atualizada.", "ok")
        else:
            apolice_id = repo.criar_apolice(dados, parcelas)
            flash("Apólice cadastrada.", "ok")
        return redirect(url_for("apolices"))

    apolice = repo.obter_apolice(apolice_id) if apolice_id else None
    if apolice_id and not apolice:
        flash("Apólice não encontrada.", "erro")
        return redirect(url_for("apolices"))
    return render_template("apolices_form.html", ativo="apolices",
                           apolice=_apolice_para_form(apolice), **_dados_form_apolice())


@app.route("/apolices/<int:apolice_id>/excluir", methods=["POST"])
def apolice_excluir(apolice_id):
    repo.excluir_apolice(apolice_id)
    flash("Apólice excluída.", "ok")
    return redirect(url_for("apolices"))


@app.route("/apolices/ler-pdf", methods=["POST"])
def apolice_ler_pdf():
    return _ler_pdf("apolice")


# ---------- Ler apólice em PDF (usado pelos dois formulários) ----------

def _ler_pdf(alvo):
    arquivo = request.files.get("arquivo")
    if not arquivo or not arquivo.filename:
        return jsonify(ok=False, campos={}, origem="vazio", aviso="Nenhum arquivo enviado."), 400
    if not arquivo.filename.lower().endswith(".pdf"):
        return jsonify(ok=False, campos={}, origem="vazio", aviso="Envie um arquivo PDF."), 400
    dados = arquivo.read()
    if not dados:
        return jsonify(ok=False, campos={}, origem="vazio", aviso="Arquivo vazio."), 400
    try:
        return jsonify(leitura_pdf.ler_pdf(dados, alvo))
    except Exception as e:  # noqa: BLE001 - devolve o erro pro front em vez de 500 seco
        app.logger.exception("falha ao ler PDF")
        return jsonify(ok=False, campos={}, origem="erro", aviso=f"Erro ao ler o PDF: {e}"), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
