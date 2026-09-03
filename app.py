"""Plenus SEGURALTA - sistema web (Flask). Roda em desktop e celular pelo navegador.

    python app.py    ->  http://localhost:5000  (no PC)
                          http://IP-DO-PC:5000   (no celular, mesma rede Wi-Fi)
"""

import os
import sqlite3
from datetime import date, timedelta

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
    validar_apolice, preparar_parcelas, preparar_comissoes, preparar_repasses,
    validar_saida, preparar_lancamentos_saida,
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
DIAS_ALERTA_SAIDA = 15     # janela do card "Contas a pagar" no painel

db.inicializar_db()

# slug na URL  <->  nome da tabela  (cadastros simples de "só nome")
_CADASTROS_SIMPLES = {
    "tipo-seguro": {"tabela": "tipo_seguro", "titulo": "Tipos de Seguro",
                    "singular": "tipo de seguro", "acao_novo": "Novo tipo de seguro"},
    "forma-pagamento": {"tabela": "forma_pagamento", "titulo": "Formas de Pagamento",
                        "singular": "forma de pagamento", "acao_novo": "Nova forma de pagamento"},
    "seguradora": {"tabela": "seguradora", "titulo": "Seguradoras",
                   "singular": "seguradora", "acao_novo": "Nova seguradora"},
    "categoria-saida": {"tabela": "categoria_saida", "titulo": "Categorias de Saída",
                        "singular": "categoria de saída", "acao_novo": "Nova categoria de saída"},
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
app.jinja_env.globals["DIAS_ALERTA_SAIDA"] = DIAS_ALERTA_SAIDA
app.jinja_env.globals["MENU"] = [
    {"rota": "dashboard", "texto": "Painel", "icone": "painel"},
    {"rota": "clientes_lista", "texto": "Clientes", "icone": "clientes"},
    {"rota": "apolices", "texto": "Apólices", "icone": "apolices"},
    {"grupo": "Fluxo de caixa", "icone": "fluxo", "divisoria_antes": True, "filhos": [
        {"rota": "saidas_lista", "texto": "Saídas", "icone": "saida"},
        {"rota": "entradas_lista", "texto": "Entradas", "icone": "entrada"},
        {"rota": "fluxo_relatorios", "slug": "saidas", "texto": "Relatório de saídas", "icone": "relatorio"},
        {"rota": "fluxo_relatorios", "slug": "entradas", "texto": "Relatório de entradas", "icone": "relatorio"},
    ]},
    {"grupo": "Cadastros auxiliares", "icone": "pasta", "divisoria_antes": True, "filhos": [
        {"rota": "cadastro_simples", "texto": "Formas de Pagamento", "icone": "pagamento", "slug": "forma-pagamento"},
        {"rota": "cadastro_simples", "texto": "Tipos de Seguro", "icone": "tag", "slug": "tipo-seguro"},
        {"rota": "cadastro_simples", "texto": "Seguradoras", "icone": "predio", "slug": "seguradora"},
        {"rota": "cadastro_simples", "texto": "Categorias de Saída", "icone": "tag", "slug": "categoria-saida"},
    ]},
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
                           boletos=repo.parcelas_boleto_a_vencer(DIAS_ALERTA_BOLETO),
                           contas_pagar=repo.saidas_a_pagar(DIAS_ALERTA_SAIDA))


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
        erro = None
        if not nome:
            erro = "Informe o nome."
        elif repo.nome_simples_existe(cfg["tabela"], nome, ignorar_id=item_id):
            erro = f"Já existe {cfg['singular']} com esse nome."
        if erro:
            flash(erro, "erro")
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
    "forma_pagamento_id", "comissao_percentual",
    "comissao_valor_seguralta_receber", "comissao_valor_plenus_receber",
    "comissao_valor_seguralta_recebido", "comissao_valor_plenus_recebido",
    "data_plenus_recebido", "plenus_conferido_banco",
    "comissao_parcelada", "comissao_cocorretagem",
    "previsto_relatorio_seguralta", "recebido_relatorio_seguralta",
    "previsto_relatorio_plenus", "recebido_relatorio_plenus",
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
    for campo in ("premio_liquido", "iof", "premio_total", "comissao_percentual",
                  "comissao_valor_seguralta_receber", "comissao_valor_plenus_receber",
                  "comissao_valor_seguralta_recebido", "comissao_valor_plenus_recebido",
                  "previsto_relatorio_seguralta", "recebido_relatorio_seguralta",
                  "previsto_relatorio_plenus", "recebido_relatorio_plenus"):
        ap[campo] = formatar_numero(ap.get(campo))
    # flag 0/1 vinda ora do banco (int), ora do form re-renderizado após erro (str "0"/"1"):
    # normaliza p/ o template não tratar a string "0" como verdadeira
    ap["plenus_conferido_banco"] = 1 if str(ap.get("plenus_conferido_banco") or "").strip() in ("1", "sim", "on", "true") else 0
    fonte = parcelas if parcelas is not None else ap.get("parcelas", [])
    ap["parcelas"] = [{**p, "valor": formatar_numero(p.get("valor"))} for p in fonte]
    ap["comissoes"] = [{**c, "valor_previsto": formatar_numero(c.get("valor_previsto")),
                        "valor_recebido": formatar_numero(c.get("valor_recebido"))}
                       for c in (ap.get("comissoes") or [])]
    ap["repasses"] = [{**r, "valor_previsto": formatar_numero(r.get("valor_previsto")),
                       "valor_recebido": formatar_numero(r.get("valor_recebido"))}
                      for r in (ap.get("repasses") or [])]
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
    parcela = request.args.get("parcela", "")
    if parcela not in ("vencida", "proxima", "sem"):
        parcela = ""
    cliente = repo.obter_cliente(cliente_id) if cliente_id else None
    return render_template(
        "apolices_lista.html", ativo="apolices",
        apolices=repo.listar_apolices(cliente_id=cliente_id, tipo_seguro_id=tipo_id,
                                      mes_inicio=mes, quiver=quiver, busca=busca or None,
                                      parcela_status=parcela or None),
        cliente_filtro=cliente, busca=busca, tipo_id=tipo_id, mes=mes, quiver=quiver_arg,
        parcela=parcela, tipos=repo.listar_simples("tipo_seguro"), MESES=_MESES)


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
        comissoes, erros_com = preparar_comissoes(
            request.form.getlist("comissao_parcela"),
            request.form.getlist("comissao_previsto"),
            request.form.getlist("comissao_recebido"),
            request.form.getlist("comissao_data"),
        )
        repasses, erros_rep = preparar_repasses(
            request.form.getlist("repasse_parcela"),
            request.form.getlist("repasse_previsto"),
            request.form.getlist("repasse_recebido"),
            request.form.getlist("repasse_data"),
            request.form.getlist("repasse_conferido"),
        )
        if not dados.get("comissao_parcelada"):  # modo "único": ignora as tabelas
            comissoes, repasses = [], []
        erros = validar_apolice(dados) + erros_parcelas
        if dados.get("comissao_parcelada"):
            erros += erros_com + erros_rep
        if erros:
            for e in erros:
                flash(e, "erro")
            apolice = _apolice_para_form(
                {**dados, "id": apolice_id, "comissoes": comissoes, "repasses": repasses},
                parcelas=parcelas)
            return render_template("apolices_form.html", ativo="apolices",
                                   apolice=apolice, **_dados_form_apolice())
        if apolice_id:
            repo.atualizar_apolice(apolice_id, dados, parcelas, comissoes, repasses)
            flash("Apólice atualizada.", "ok")
        else:
            apolice_id = repo.criar_apolice(dados, parcelas, comissoes, repasses)
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


# ---------- Financeiro: Saídas (fluxo de caixa) ----------

@app.route("/financeiro/saidas")
def saidas_lista():
    # sem o parâmetro "mes" na URL (navegação normal) → mostra só o mês corrente;
    # "mes" vazio ("Qualquer mês" escolhido no filtro) → todos os meses.
    mes_arg = request.args.get("mes")
    if mes_arg is None:
        mes = date.today().month
    elif mes_arg.isdigit() and int(mes_arg) in range(1, 13):
        mes = int(mes_arg)
    else:
        mes = None
    status = request.args.get("status", "")
    categoria_id = request.args.get("categoria_id", type=int)
    forma_id = request.args.get("forma_pagamento_id", type=int)
    fixo = request.args.get("fixo", "")
    if fixo not in ("0", "1"):
        fixo = ""
    busca = request.args.get("busca", "").strip()
    saidas = repo.listar_saidas(mes=mes, status=status or None,
                                categoria_id=categoria_id or None, busca=busca or None,
                                forma_pagamento_id=forma_id or None, fixo=fixo or None)
    total = sum(s["valor"] or 0 for s in saidas)
    tem_filtro = bool(busca or status or categoria_id or forma_id or fixo) or mes != date.today().month
    return render_template("saidas_lista.html", ativo="saidas_lista",
                           saidas=saidas, total=total, resumo=repo.resumo_saidas(),
                           mes=mes, status=status, categoria_id=categoria_id, busca=busca,
                           forma_id=forma_id, fixo=fixo,
                           tem_filtro=tem_filtro, mes_atual=date.today().month,
                           categorias=repo.categorias_saida(),
                           formas=repo.listar_simples("forma_pagamento"),
                           descricoes=repo.descricoes_saida(), MESES=_MESES)


def _selects_saida():
    return {"categorias": repo.categorias_saida(),
            "formas": repo.listar_simples("forma_pagamento")}


@app.route("/financeiro/saidas/nova", methods=["GET", "POST"])
@app.route("/financeiro/saidas/<int:saida_id>", methods=["GET", "POST"])
def saida_form(saida_id=None):
    # "voltar" (caminho interno) leva de volta pra lista com a busca/filtros ativos
    voltar = request.form.get("voltar") or request.args.get("voltar") or ""
    if not (voltar.startswith("/") and not voltar.startswith("//")):
        voltar = ""
    grupo = repo.obter_grupo_saida(saida_id) if saida_id else None
    if saida_id and not grupo:
        flash("Saída não encontrada.", "erro")
        return redirect(voltar or url_for("saidas_lista"))

    if request.method == "POST":
        comum = {
            "descricao": request.form.get("descricao", ""),
            "categoria_id": request.form.get("categoria_id", ""),
            "forma_pagamento_id": request.form.get("forma_pagamento_id", ""),
            "fixo_mensal": "1" if request.form.get("fixo_mensal") else "0",
        }
        linhas, erros = preparar_lancamentos_saida(
            request.form.getlist("saida_id"),
            request.form.getlist("saida_data"),
            request.form.getlist("saida_valor"),
            request.form.getlist("saida_parcela"),
            request.form.getlist("saida_pago_em"))
        erros = validar_saida(comum) + erros
        if not linhas:
            erros.append("Deixe ao menos um lançamento.")
        if erros:
            for e in erros:
                flash(e, "erro")
            return render_template("saidas_form.html", ativo="saidas_lista",
                                   saida={**comum, "id": saida_id,
                                          "serie_id": grupo["serie_id"] if grupo else None,
                                          "lancamentos": linhas},
                                   voltar=voltar, **_selects_saida())
        repo.salvar_grupo_saida(saida_id, comum, linhas)
        flash("Saída salva.", "ok")
        return redirect(voltar or url_for("saidas_lista"))

    return render_template("saidas_form.html", ativo="saidas_lista",
                           saida=grupo, voltar=voltar, **_selects_saida())


@app.route("/financeiro/saidas/<int:saida_id>/excluir", methods=["POST"])
def saida_excluir(saida_id):
    repo.excluir_saida(saida_id)
    flash("Lançamento excluído.", "ok")
    return _voltar_seguro() if request.form.get("voltar") else redirect(url_for("saidas_lista"))


@app.route("/financeiro/saidas/<int:saida_id>/pagamento", methods=["POST"])
def saida_pagamento(saida_id):
    repo.marcar_saida_paga(saida_id, request.form.get("paga") == "1",
                           request.form.get("data_pagamento"))
    flash("Saída atualizada.", "ok")
    return _voltar_seguro()


@app.route("/financeiro/entradas")
def entradas_lista():
    return render_template("em_breve.html", ativo="entradas_lista",
                           titulo="Fluxo de caixa — Entradas",
                           mensagem="O controle de entradas (contas a receber) ainda será construído.")


# ---- relatório de fluxo de caixa (dinâmico: filtros + agrupamento em 2 níveis) ----

_GRUPO_OPCOES = [("", "—"), ("descricao", "Descrição da saída"), ("categoria", "Categoria"),
                 ("forma", "Forma de pagamento"), ("situacao", "Situação"),
                 ("mes", "Mês do vencimento"), ("fixo", "Fixa mensal")]
_ORDEM_OPCOES = [("vencimento", "Vencimento"), ("pagamento", "Pagamento"),
                 ("valor", "Valor"), ("descricao", "Descrição")]


def _rotulo_mes_iso(iso):
    if not iso or len(iso) < 7:
        return ("zzzz", "Sem data")
    return (iso[:7], f"{_MESES[int(iso[5:7])]}/{iso[:4]}")


# cada função devolve (chave_de_ordenação, rótulo_exibido)
_GRUPOS_SAIDA = {
    "descricao": ("Descrição", lambda s: (
        repo._sem_acento_minusculo(s.get("descricao") or "") or "zzz",
        s.get("descricao") or "Sem descrição")),
    "categoria": ("Categoria", lambda s: (
        repo._sem_acento_minusculo(s.get("categoria") or "") or "zzz",
        s.get("categoria") or "Sem categoria")),
    "forma": ("Forma de pagamento", lambda s: (
        repo._sem_acento_minusculo(s.get("forma_pagamento") or "") or "zzz",
        s.get("forma_pagamento") or "Sem forma")),
    "situacao": ("Situação", lambda s: {
        "vencido": (0, "Vencida"), "a_pagar": (1, "A pagar"), "pago": (2, "Paga"),
    }.get(s["status"], (3, s["status"]))),
    "mes": ("Mês do vencimento", lambda s: _rotulo_mes_iso(s.get("data_vencimento"))),
    "fixo": ("Fixa mensal", lambda s: (0, "Fixa mensal") if s.get("fixo_mensal") else (1, "Avulsa")),
}


def _soma_valor(itens):
    return sum(x.get("valor") or 0 for x in itens)


def _agrupar_saidas(linhas, chaves):
    """chaves = lista de 0..2 nomes de _GRUPOS_SAIDA. Devolve {campo, grupos:[...]} ou None."""
    if not chaves:
        return None
    campo_rotulo, fn = _GRUPOS_SAIDA[chaves[0]]
    baldes = {}
    for s in linhas:
        ordk, rot = fn(s)
        baldes.setdefault((ordk, rot), []).append(s)
    grupos = []
    for chave in sorted(baldes):
        itens = baldes[chave]
        total = _soma_valor(itens)
        pago = _soma_valor([x for x in itens if x["status"] == "pago"])
        grupos.append({
            "rotulo": chave[1], "qtd": len(itens), "soma": total,
            "soma_paga": pago, "soma_aberto": total - pago,
            "itens": itens if len(chaves) == 1 else None,
            "sub": _agrupar_saidas(itens, chaves[1:]) if len(chaves) > 1 else None,
        })
    return {"campo": campo_rotulo, "chave": chaves[0], "grupos": grupos}


@app.route("/financeiro/relatorios")
def fluxo_relatorios_raiz():
    return redirect(url_for("fluxo_relatorios", slug="saidas"))


@app.route("/financeiro/relatorios/<slug>")
def fluxo_relatorios(slug):
    # a escolha saídas × entradas vem do MENU (URL), não mais de um filtro na tela
    tipo = slug if slug in ("saidas", "entradas") else None
    if tipo is None:
        return redirect(url_for("fluxo_relatorios", slug="saidas"))

    hoje = date.today()
    ini_mes = hoje.replace(day=1).isoformat()
    fim_mes_passado = hoje.replace(day=1) - timedelta(days=1)
    prox_mes_1 = (date(hoje.year + 1, 1, 1) if hoje.month == 12
                  else date(hoje.year, hoje.month + 1, 1))
    fim_mes = (prox_mes_1 - timedelta(days=1)).isoformat()
    # atalhos cobrem o PERÍODO INTEIRO (não param no dia de hoje), pra pegar
    # também as parcelas ainda a vencer no mês / ano
    presets = {
        "mes": (ini_mes, fim_mes),
        "mes_passado": (fim_mes_passado.replace(day=1).isoformat(), fim_mes_passado.isoformat()),
        "ano": (hoje.replace(month=1, day=1).isoformat(), hoje.replace(month=12, day=31).isoformat()),
    }
    # os campos De/Até nascem VAZIOS (sem período = todos os lançamentos);
    # a usuária usa os atalhos ou digita as datas
    data_ini = request.args.get("data_ini", "").strip()
    data_fim = request.args.get("data_fim", "").strip()
    base_data = request.args.get("base_data", "")
    if base_data not in ("vencimento", "pagamento"):
        base_data = ""  # nenhum → recorta por vencimento OU pagamento
    status = request.args.get("status", "")
    categoria_id = request.args.get("categoria_id", type=int)
    forma_id = request.args.get("forma_pagamento_id", type=int)
    fixo = request.args.get("fixo", "")
    if fixo not in ("0", "1"):
        fixo = ""
    busca = request.args.get("busca", "").strip()
    validos = set(_GRUPOS_SAIDA)
    g1 = request.args.get("g1", "")
    g1 = g1 if g1 in validos else ""
    g2 = request.args.get("g2", "")
    g2 = g2 if (g2 in validos and g2 != g1) else ""
    ordem = request.args.get("ordem", "vencimento")
    if ordem not in {k for k, _ in _ORDEM_OPCOES}:
        ordem = "vencimento"
    ordem_dir = "desc" if request.args.get("ordem_dir") == "desc" else "asc"

    linhas, arvore, resumo = [], None, None
    if tipo == "saidas":
        linhas = repo.listar_saidas(
            status=status or None, categoria_id=categoria_id or None,
            forma_pagamento_id=forma_id or None, fixo=fixo or None, busca=busca or None,
            data_ini=data_ini or None, data_fim=data_fim or None, base_data=base_data)
        ordkey = {
            "vencimento": lambda s: s.get("data_vencimento") or "",
            "pagamento": lambda s: s.get("data_pagamento") or "",
            "valor": lambda s: s.get("valor") or 0,
            "descricao": lambda s: repo._sem_acento_minusculo(s.get("descricao") or ""),
        }[ordem]
        linhas.sort(key=ordkey, reverse=(ordem_dir == "desc"))
        chaves = [c for c in (g1, g2) if c]
        arvore = _agrupar_saidas(linhas, chaves)
        total = _soma_valor(linhas)
        pago = _soma_valor([s for s in linhas if s["status"] == "pago"])
        resumo = {
            "qtd": len(linhas), "soma": total, "soma_paga": pago, "soma_aberto": total - pago,
            "qtd_paga": sum(1 for s in linhas if s["status"] == "pago"),
            "qtd_aberto": sum(1 for s in linhas if s["status"] != "pago"),
        }

    tem_filtro = bool(status or categoria_id or forma_id or fixo or busca
                      or data_ini or data_fim or g1 or base_data)
    titulo = "Fluxo de caixa — Relatório de " + ("saídas" if tipo == "saidas" else "entradas")
    return render_template(
        "relatorios.html", ativo="fluxo_relatorios", titulo=titulo,
        tipo=tipo, data_ini=data_ini, data_fim=data_fim, base_data=base_data, status=status,
        categoria_id=categoria_id, forma_id=forma_id, fixo=fixo, busca=busca,
        g1=g1, g2=g2, ordem=ordem, ordem_dir=ordem_dir, tem_filtro=tem_filtro,
        linhas=linhas, arvore=arvore, resumo=resumo, presets=presets,
        categorias=repo.categorias_saida(), formas=repo.listar_simples("forma_pagamento"),
        descricoes=repo.descricoes_saida(), grupo_opcoes=_GRUPO_OPCOES,
        ordem_opcoes=_ORDEM_OPCOES, MESES=_MESES)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
