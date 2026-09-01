"""Plenus SEGURALTA - sistema web (Flask). Roda em desktop e celular pelo navegador.

    python app.py    ->  http://localhost:5000  (no PC)
                          http://IP-DO-PC:5000   (no celular, mesma rede Wi-Fi)
"""

import os
import sqlite3
from datetime import timedelta

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from flask_wtf.csrf import CSRFProtect
from werkzeug.middleware.proxy_fix import ProxyFix

import db
import repo
import leitura_pdf
import seguranca
from validacao import (
    formatar_cpf, formatar_cep, formatar_telefone, validar_cliente,
    formatar_numero, formatar_moeda, formatar_data_br, dias_ate_data,
    validar_apolice, preparar_parcelas,
)

_HTTPS = os.environ.get("PLENUS_HTTPS") == "1"

app = Flask(__name__)
app.secret_key = seguranca.obter_secret_key()
app.config.update(
    MAX_CONTENT_LENGTH=20 * 1024 * 1024,          # PDF de apólice: teto de 20 MB
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=_HTTPS,                 # cookie só por HTTPS quando PLENUS_HTTPS=1
    PERMANENT_SESSION_LIFETIME=timedelta(days=7),
    WTF_CSRF_TIME_LIMIT=None,                     # token vale enquanto a sessão durar
)

# atrás de um proxy reverso (Caddy/nginx): confia nos cabeçalhos X-Forwarded-*
if os.environ.get("PLENUS_ATRAS_DE_PROXY") == "1":
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

csrf = CSRFProtect(app)


@app.after_request
def _cabecalhos_seguranca(resp):
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "same-origin")
    resp.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; img-src 'self' data:; "
        "style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; "
        "connect-src 'self' https://viacep.com.br; "
        "form-action 'self'; base-uri 'self'; frame-ancestors 'none'; object-src 'none'",
    )
    if _HTTPS:
        resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return resp


DIAS_ALERTA_VIGENCIA = 20  # <= N dias p/ vencer -> destaque vermelho + aviso no painel
DIAS_ALERTA_BOLETO = 15    # janela do card "Boletos a vencer" no painel

db.inicializar_db()

# slug na URL  <->  nome da tabela  (cadastros simples de "só nome")
_CADASTROS_SIMPLES = {
    "tipo-seguro": {"tabela": "tipo_seguro", "titulo": "Tipos de Seguro",
                    "singular": "tipo de seguro", "acao_novo": "Novo tipo de seguro"},
    "forma-pagamento": {"tabela": "forma_pagamento", "titulo": "Formas de Pagamento",
                        "singular": "forma de pagamento", "acao_novo": "Nova forma de pagamento"},
    "seguradora": {"tabela": "seguradora", "titulo": "Seguradoras",
                   "singular": "seguradora", "acao_novo": "Nova seguradora"},
}

# disponível em todo template (máscaras na exibição, itens do menu)
app.jinja_env.filters["cpf"] = formatar_cpf
app.jinja_env.filters["cep"] = formatar_cep
app.jinja_env.filters["numero"] = formatar_numero
app.jinja_env.filters["moeda"] = formatar_moeda
app.jinja_env.filters["data_br"] = formatar_data_br
app.jinja_env.globals["telefone"] = formatar_telefone
app.jinja_env.globals["dias_ate"] = dias_ate_data
app.jinja_env.globals["DIAS_ALERTA_VIGENCIA"] = DIAS_ALERTA_VIGENCIA
app.jinja_env.globals["DIAS_ALERTA_BOLETO"] = DIAS_ALERTA_BOLETO
app.jinja_env.globals["MENU"] = [
    {"rota": "dashboard", "texto": "Painel", "icone": "painel"},
    {"rota": "clientes_lista", "texto": "Clientes", "icone": "clientes"},
    {"rota": "apolices", "texto": "Apólices", "icone": "apolices"},
    {"rota": "cadastro_simples", "texto": "Seguradoras", "icone": "predio", "slug": "seguradora", "divisoria_antes": True},
    {"rota": "cadastro_simples", "texto": "Tipos de Seguro", "icone": "tag", "slug": "tipo-seguro"},
    {"rota": "cadastro_simples", "texto": "Formas de Pagamento", "icone": "pagamento", "slug": "forma-pagamento"},
    {"rota": "usuarios_lista", "texto": "Usuários", "icone": "cadeado", "divisoria_antes": True},
]


# ---------- autenticação ----------

_ENDPOINTS_LIVRES = {"login", "primeiro_acesso", "static"}


@app.before_request
def _exigir_login():
    if request.endpoint in _ENDPOINTS_LIVRES or request.endpoint is None:
        return
    if repo.contar_usuarios() == 0:
        return redirect(url_for("primeiro_acesso"))
    if not session.get("usuario_id"):
        return redirect(url_for("login", proxima=request.full_path if request.query_string else request.path))


@app.context_processor
def _injeta_usuario():
    uid = session.get("usuario_id")
    return {"usuario_atual": {"id": uid, "nome": session.get("usuario_nome")} if uid else None}


def _destino_seguro(valor):
    """Só permite caminho interno (evita open redirect)."""
    if valor and valor.startswith("/") and not valor.startswith("//"):
        return valor
    return url_for("dashboard")


def _erros_usuario(nome, login, senha, senha_obrigatoria):
    erros = []
    if not (nome or "").strip():
        erros.append("Informe o nome.")
    login = (login or "").strip()
    if len(login) < 3 or " " in login:
        erros.append("O login precisa ter 3+ caracteres e sem espaços.")
    if senha or senha_obrigatoria:
        p = seguranca.problemas_senha(senha)
        if p:
            erros.append(p)
    return erros


@app.route("/login", methods=["GET", "POST"])
def login():
    if repo.contar_usuarios() == 0:
        return redirect(url_for("primeiro_acesso"))
    if session.get("usuario_id"):
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        login_ = request.form.get("login", "").strip()
        senha = request.form.get("senha", "")
        chave = f"{request.remote_addr}|{login_.lower()}"
        if seguranca.bloqueado(chave):
            flash("Muitas tentativas. Aguarde alguns minutos e tente de novo.", "erro")
            return render_template("login.html", login=login_)
        usuario = repo.autenticar(login_, senha)
        if not usuario:
            seguranca.registrar_falha(chave)
            flash("Login ou senha inválidos.", "erro")
            return render_template("login.html", login=login_)
        seguranca.limpar_falhas(chave)
        session.clear()
        session["usuario_id"] = usuario["id"]
        session["usuario_nome"] = usuario["nome"]
        session.permanent = True
        return redirect(_destino_seguro(request.args.get("proxima")))
    return render_template("login.html", login="")


@app.route("/sair", methods=["POST"])
def sair():
    session.clear()
    flash("Sessão encerrada.", "ok")
    return redirect(url_for("login"))


@app.route("/primeiro-acesso", methods=["GET", "POST"])
def primeiro_acesso():
    if repo.contar_usuarios() > 0:
        return redirect(url_for("login"))
    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        login_ = request.form.get("login", "").strip()
        senha = request.form.get("senha", "")
        erros = _erros_usuario(nome, login_, senha, senha_obrigatoria=True)
        if erros:
            for e in erros:
                flash(e, "erro")
            return render_template("primeiro_acesso.html", nome=nome, login=login_)
        uid = repo.criar_usuario(nome, login_, senha)
        session.clear()
        session["usuario_id"] = uid
        session["usuario_nome"] = nome
        session.permanent = True
        flash("Usuário administrador criado. Bem-vindo(a)!", "ok")
        return redirect(url_for("dashboard"))
    return render_template("primeiro_acesso.html", nome="", login="")


# ---------- Usuários (admin) ----------

@app.route("/usuarios")
def usuarios_lista():
    return render_template("usuarios_lista.html", ativo="usuarios_lista",
                           usuarios=repo.listar_usuarios())


@app.route("/usuarios/novo", methods=["GET", "POST"])
@app.route("/usuarios/<int:uid>", methods=["GET", "POST"])
def usuario_form(uid=None):
    usuario = repo.obter_usuario(uid) if uid else None
    if uid and not usuario:
        flash("Usuário não encontrado.", "erro")
        return redirect(url_for("usuarios_lista"))

    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        login_ = request.form.get("login", "").strip()
        senha = request.form.get("senha", "")
        ativo = request.form.get("ativo", "1") == "1"
        erros = _erros_usuario(nome, login_, senha, senha_obrigatoria=(uid is None))
        if not erros and repo.login_em_uso(login_, ignorar_id=uid):
            erros.append("Já existe um usuário com esse login.")
        if erros:
            for e in erros:
                flash(e, "erro")
            return render_template("usuarios_form.html", ativo="usuarios_lista",
                                   usuario={"id": uid, "nome": nome, "login": login_, "ativo": ativo})
        try:
            if uid:
                repo.atualizar_usuario(uid, nome, login_, ativo, senha or None)
            else:
                repo.criar_usuario(nome, login_, senha)
        except sqlite3.IntegrityError:
            flash("Já existe um usuário com esse login.", "erro")
            return render_template("usuarios_form.html", ativo="usuarios_lista",
                                   usuario={"id": uid, "nome": nome, "login": login_, "ativo": ativo})
        flash("Usuário salvo.", "ok")
        return redirect(url_for("usuarios_lista"))

    return render_template("usuarios_form.html", ativo="usuarios_lista", usuario=usuario)


@app.route("/usuarios/<int:uid>/excluir", methods=["POST"])
def usuario_excluir(uid):
    if uid == session.get("usuario_id"):
        flash("Você não pode excluir o próprio usuário.", "erro")
    elif repo.contar_usuarios() <= 1:
        flash("Precisa existir ao menos um usuário.", "erro")
    else:
        repo.excluir_usuario(uid)
        flash("Usuário excluído.", "ok")
    return redirect(url_for("usuarios_lista"))


@app.context_processor
def _injeta_alertas():
    # contador de apólices vencendo, disponível em todo template (badge do menu)
    return {"qtd_vencendo": repo.contar_apolices_por_vencer(DIAS_ALERTA_VIGENCIA)}


@app.route("/")
def dashboard():
    return render_template("dashboard.html", ativo="dashboard",
                           resumo=repo.resumo_painel(),
                           por_tipo=repo.apolices_por_tipo(),
                           vencendo=repo.apolices_por_vencer(DIAS_ALERTA_VIGENCIA),
                           boletos=repo.parcelas_boleto_a_vencer(DIAS_ALERTA_BOLETO))


# ---------- Clientes ----------

@app.route("/clientes")
def clientes_lista():
    busca = request.args.get("busca", "").strip()
    uf = request.args.get("uf", "").strip().upper() or None
    return render_template("clientes_lista.html", ativo="clientes_lista",
                           clientes=repo.listar_clientes(busca or None, uf),
                           busca=busca, uf=uf, ufs=repo.ufs_dos_clientes())


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
    qtd_apolices = repo.contar_apolices_do_cliente(cliente_id) if cliente_id else 0
    return render_template("clientes_form.html", ativo="clientes_lista", cliente=cliente,
                           qtd_apolices=qtd_apolices)


@app.route("/clientes/<int:cliente_id>/excluir", methods=["POST"])
def cliente_excluir(cliente_id):
    repo.excluir_cliente(cliente_id)
    flash("Cliente excluído.", "ok")
    return redirect(url_for("clientes_lista"))


@app.route("/clientes/ler-pdf", methods=["POST"])
def cliente_ler_pdf():
    return _ler_pdf("cliente")


# ---------- Cadastros simples (Seguradoras / Tipos de Seguro / Formas de Pagamento) ----------

@app.route("/cadastros/<slug>")
def cadastro_simples(slug):
    cfg = _CADASTROS_SIMPLES.get(slug)
    if not cfg:
        flash("Cadastro não encontrado.", "erro")
        return redirect(url_for("dashboard"))
    return render_template("cadastro_simples_lista.html", ativo="cadastro_simples", slug=slug,
                           titulo=cfg["titulo"], singular=cfg["singular"], acao_novo=cfg["acao_novo"],
                           itens=repo.listar_simples(cfg["tabela"]))


@app.route("/cadastros/<slug>/novo", methods=["GET", "POST"])
@app.route("/cadastros/<slug>/<int:item_id>", methods=["GET", "POST"])
def cadastro_simples_form(slug, item_id=None):
    cfg = _CADASTROS_SIMPLES.get(slug)
    if not cfg:
        flash("Cadastro não encontrado.", "erro")
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        if not nome:
            flash("Informe o nome.", "erro")
            return render_template("cadastro_simples_form.html", ativo="cadastro_simples", slug=slug,
                                   singular=cfg["singular"], acao_novo=cfg["acao_novo"],
                                   item={"id": item_id, "nome": nome})
        if item_id:
            repo.renomear_simples(cfg["tabela"], item_id, nome)
            flash("Alteração salva.", "ok")
        else:
            repo.criar_simples(cfg["tabela"], nome)
            flash("Cadastrado.", "ok")
        return redirect(url_for("cadastro_simples", slug=slug))

    item = repo.obter_simples(cfg["tabela"], item_id) if item_id else None
    if item_id and not item:
        flash("Registro não encontrado.", "erro")
        return redirect(url_for("cadastro_simples", slug=slug))
    return render_template("cadastro_simples_form.html", ativo="cadastro_simples", slug=slug,
                           singular=cfg["singular"], acao_novo=cfg["acao_novo"], item=item)


@app.route("/cadastros/<slug>/<int:item_id>/excluir", methods=["POST"])
def cadastro_simples_excluir(slug, item_id):
    cfg = _CADASTROS_SIMPLES.get(slug)
    if cfg:
        repo.excluir_simples(cfg["tabela"], item_id)
        flash("Excluído.", "ok")
    return redirect(url_for("cadastro_simples", slug=slug))


# ---------- Apólices ----------

_CAMPOS_APOLICE = (
    "cliente_id", "seguradora_id", "tipo_seguro_id", "numero_apolice",
    "vigencia_inicio", "vigencia_fim",
    "premio_liquido", "iof", "premio_total",
    "forma_pagamento_id", "comissao_percentual", "comissao_valor",
    "lancado_quiver", "link_onedrive",
    "veiculo_placa", "veiculo_descricao",
    "aviso_vigencia_ok", "aviso_vigencia_ok_em",
    "apolice_enviada", "apolice_enviada_data", "cartao_enviado", "cartao_enviado_data",
)


def _apolice_para_form(ap, parcelas=None):
    """Deixa os números como texto pt-BR pros inputs (edição vinda do banco)."""
    if ap is None:
        return None
    ap = dict(ap)
    for campo in ("premio_liquido", "iof", "premio_total", "comissao_percentual", "comissao_valor"):
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


_MESES = ["", "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
          "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]


@app.route("/apolices")
def apolices():
    cliente_id = request.args.get("cliente", type=int)
    tipo_id = request.args.get("tipo", type=int)
    mes = request.args.get("mes", type=int)
    if mes not in range(1, 13):
        mes = None
    quiver_arg = request.args.get("quiver", "")
    quiver = 1 if quiver_arg == "1" else 0 if quiver_arg == "0" else None
    busca = request.args.get("busca", "").strip()
    cliente = repo.obter_cliente(cliente_id) if cliente_id else None
    return render_template(
        "apolices_lista.html", ativo="apolices",
        apolices=repo.listar_apolices(cliente_id=cliente_id, tipo_seguro_id=tipo_id,
                                      mes_inicio=mes, quiver=quiver, busca=busca or None),
        cliente_filtro=cliente, busca=busca, tipo_id=tipo_id, mes=mes, quiver=quiver_arg,
        tipos=repo.listar_simples("tipo_seguro"), MESES=_MESES)


@app.route("/apolices/nova", methods=["GET", "POST"])
@app.route("/apolices/<int:apolice_id>", methods=["GET", "POST"])
def apolice_form(apolice_id=None):
    if request.method == "POST":
        dados = {k: request.form.get(k, "") for k in _CAMPOS_APOLICE}
        parcelas, erros_parcelas = preparar_parcelas(
            request.form.getlist("parcela_identificacao"),
            request.form.getlist("parcela_data"),
            request.form.getlist("parcela_valor"),
            request.form.getlist("parcela_paga"),
            request.form.getlist("parcela_aviso"),
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
    if apolice is None:
        cliente_id = request.args.get("cliente", type=int)
        if cliente_id and repo.obter_cliente(cliente_id):
            apolice = {"cliente_id": cliente_id}
    return render_template("apolices_form.html", ativo="apolices",
                           apolice=_apolice_para_form(apolice), **_dados_form_apolice())


@app.route("/apolices/<int:apolice_id>/excluir", methods=["POST"])
def apolice_excluir(apolice_id):
    repo.excluir_apolice(apolice_id)
    flash("Apólice excluída.", "ok")
    return redirect(url_for("apolices"))


def _voltar_seguro(campo="voltar"):
    destino = request.form.get(campo)
    if destino and destino.startswith("/") and not destino.startswith("//"):
        return redirect(destino)
    return redirect(url_for("dashboard"))


@app.route("/parcelas/<int:parcela_id>/pagamento", methods=["POST"])
def parcela_pagamento(parcela_id):
    repo.marcar_parcela_paga(parcela_id, request.form.get("paga") == "1")
    flash("Parcela atualizada.", "ok")
    return _voltar_seguro()


@app.route("/parcelas/<int:parcela_id>/aviso-cliente", methods=["POST"])
def parcela_aviso(parcela_id):
    repo.marcar_aviso_parcela(parcela_id, request.form.get("aviso") == "1")
    flash("Aviso do boleto atualizado.", "ok")
    return _voltar_seguro()


@app.route("/apolices/<int:apolice_id>/aviso-cliente", methods=["POST"])
def apolice_aviso(apolice_id):
    repo.marcar_aviso_vigencia(apolice_id, request.form.get("aviso") == "1")
    flash("Aviso de renovação atualizado.", "ok")
    return _voltar_seguro()


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
