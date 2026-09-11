"""Plenus SEGURALTA - sistema web (Flask). Roda em desktop e celular pelo navegador.

    python app.py    ->  http://localhost:5000  (no PC)
                          http://IP-DO-PC:5000   (no celular, mesma rede Wi-Fi)
"""

import os
import re
from datetime import date, datetime, timedelta

from pymysql.err import IntegrityError

from flask import (Flask, render_template, request, redirect, url_for, flash, jsonify,
                   session, Response, abort)
from flask_wtf.csrf import CSRFProtect
from werkzeug.middleware.proxy_fix import ProxyFix

import db
import repo
import leitura_pdf
import cotacao_leitura_pdf
import seguranca
from validacao import (
    formatar_cpf, formatar_cnpj, formatar_documento, formatar_cep, formatar_telefone, validar_cliente,
    formatar_numero, formatar_moeda, formatar_data_br, dias_ate_data,
    validar_apolice, preparar_parcelas, preparar_comissoes, preparar_repasses,
    gerar_repasses_cocorretagem, para_decimal,
    validar_saida, preparar_lancamentos_saida, validar_endosso,
    validar_consorcio, preparar_parcela_valores, preparar_boletos,
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
    "tipo-consorcio": {"tabela": "tipo_consorcio", "titulo": "Tipos de Consórcio",
                       "singular": "tipo de consórcio", "acao_novo": "Novo tipo de consórcio"},
}

# disponível em todo template (máscaras na exibição, itens do menu)
app.jinja_env.filters["cpf"] = formatar_cpf
app.jinja_env.filters["cnpj"] = formatar_cnpj
app.jinja_env.filters["documento"] = formatar_documento
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
    {"rota": "endossos_lista", "texto": "Endossos", "icone": "endosso"},
    {"rota": "consorcios_lista", "texto": "Consórcios", "icone": "consorcio"},
    {"grupo": "Cotação", "icone": "cotacao", "divisoria_antes": True, "filhos": [
        {"rota": "cotacao_campos", "texto": "Cadastrar Campo", "icone": "lapis"},
        {"rota": "cotacao_gerar", "texto": "Gerar", "icone": "relatorio"},
    ]},
    {"grupo": "Fluxo de caixa", "icone": "fluxo", "divisoria_antes": True, "filhos": [
        {"rota": "saidas_lista", "texto": "Saídas", "icone": "saida"},
        {"rota": "entradas_lista", "texto": "Entradas (Comissões)", "icone": "entrada"},
        {"rota": "fluxo_relatorios", "slug": "saidas", "texto": "Relatório de saídas", "icone": "relatorio"},
        {"rota": "fluxo_relatorios", "slug": "entradas", "texto": "Relatório de entradas", "icone": "relatorio"},
        {"rota": "entradas_panorama", "texto": "Comissões recebidas", "icone": "relatorio"},
    ]},
    {"grupo": "Cadastros auxiliares", "icone": "pasta", "divisoria_antes": True, "filhos": [
        {"rota": "cadastro_simples", "texto": "Seguradoras", "icone": "predio", "slug": "seguradora"},
        {"rota": "cadastro_simples", "texto": "Tipos de Seguro", "icone": "tag", "slug": "tipo-seguro"},
        {"rota": "cadastro_simples", "texto": "Formas de Pagamento", "icone": "pagamento", "slug": "forma-pagamento"},
        {"rota": "cadastro_simples", "texto": "Categorias de Saída", "icone": "tag", "slug": "categoria-saida"},
        {"rota": "cadastro_simples", "texto": "Tipos de Consórcio", "icone": "tag", "slug": "tipo-consorcio"},
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
        except IntegrityError:
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
                           boletos_enviar=repo.boletos_a_enviar(DIAS_ALERTA_BOLETO),
                           contas_pagar=repo.saidas_a_pagar(DIAS_ALERTA_SAIDA))


@app.route("/consorcios/boleto/<int:boleto_id>/enviado", methods=["POST"])
def consorcio_boleto_enviado(boleto_id):
    repo.marcar_boleto_consorcio_enviado(boleto_id, request.form.get("enviado") == "1")
    flash("Status do boleto atualizado.", "ok")
    return _voltar_seguro()


# ---------- Clientes ----------

@app.route("/clientes")
def clientes_lista():
    busca = request.args.get("busca", "").strip()
    uf = request.args.get("uf", "").strip().upper() or None
    cidade = request.args.get("cidade", "").strip() or None
    agrupar = request.args.get("g", "")
    if agrupar not in ("cidade", "uf", "seguradora", "tipo_seguro"):
        agrupar = ""
    clientes = repo.listar_clientes(busca or None, uf, cidade)

    grupos = None
    if agrupar:
        baldes = {}
        if agrupar in ("tipo_seguro", "seguradora"):
            # cliente com apólices de vários tipos/seguradoras aparece em vários grupos;
            # sem apólice mas com consórcio → grupo "Só consórcio"
            por_cli = (repo.tipos_seguro_por_cliente() if agrupar == "tipo_seguro"
                       else repo.seguradoras_por_cliente())
            com_cons = repo.clientes_com_consorcio()
            for c in clientes:
                chaves = por_cli.get(c["id"])
                if chaves:
                    for ch in chaves:
                        baldes.setdefault(ch, []).append(c)
                elif c["id"] in com_cons:
                    baldes.setdefault("Só consórcio", []).append(c)
                else:
                    baldes.setdefault("Sem apólice", []).append(c)
        else:
            def _chave(c):
                if agrupar == "uf":
                    return (c.get("end_estado") or "").strip().upper() or "Sem estado"
                cid = (c.get("end_cidade") or "").strip()
                est = (c.get("end_estado") or "").strip().upper()
                return f"{cid} / {est}" if cid and est else (cid or est or "Sem cidade")
            for c in clientes:
                baldes.setdefault(_chave(c), []).append(c)

        def _ordem_grupo(rot):
            if rot == "Sem apólice":
                return (3, "")
            if rot == "Só consórcio":
                return (2, "")
            if rot.startswith("Sem "):
                return (1, repo._sem_acento_minusculo(rot))
            return (0, repo._sem_acento_minusculo(rot))
        grupos = [{"rotulo": k, "itens": v}
                  for k, v in sorted(baldes.items(), key=lambda kv: _ordem_grupo(kv[0]))]

    return render_template("clientes_lista.html", ativo="clientes_lista",
                           clientes=clientes, grupos=grupos, agrupar=agrupar,
                           busca=busca, uf=uf, cidade=cidade,
                           ufs=repo.ufs_dos_clientes(), cidades=repo.cidades_dos_clientes(uf))


@app.route("/clientes/novo", methods=["GET", "POST"])
@app.route("/clientes/<int:cliente_id>", methods=["GET", "POST"])
def cliente_form(cliente_id=None):
    if request.method == "POST":
        dados = {k: request.form.get(k, "") for k in (
            "nome", "tipo_pessoa", "data_nascimento", "sexo", "cpf",
            "end_rua", "end_numero", "end_complemento", "end_bairro",
            "end_cep", "end_cidade", "end_estado", "tel_ddd", "tel_numero", "email",
        )}
        ehpj = (dados.get("tipo_pessoa") or "").upper() == "J"
        rotulo_doc = "CNPJ" if ehpj else "CPF"
        if ehpj:  # pessoa jurídica não tem nascimento nem sexo
            dados["data_nascimento"] = dados["sexo"] = ""
        erros = validar_cliente(dados)
        if not erros:
            dup = repo.cliente_por_documento(dados.get("cpf"), ignorar_id=cliente_id)
            if dup:
                erros.append(f"Já existe um cliente com esse {rotulo_doc}: {dup['nome']}.")
        if erros:
            for e in erros:
                flash(e, "erro")
            return render_template("clientes_form.html", ativo="clientes_lista",
                                   cliente={**dados, "id": cliente_id})
        try:
            if cliente_id:
                repo.atualizar_cliente(cliente_id, dados)
                flash("Cliente atualizado.", "ok")
            else:
                cliente_id = repo.criar_cliente(dados)
                flash("Cliente cadastrado.", "ok")
        except IntegrityError:
            flash(f"Já existe um cliente com esse {rotulo_doc}.", "erro")
            return render_template("clientes_form.html", ativo="clientes_lista",
                                   cliente={**dados, "id": cliente_id})
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
    busca = request.args.get("busca", "").strip()
    return render_template("cadastro_simples_lista.html", ativo="cadastro_simples", slug=slug,
                           titulo=cfg["titulo"], singular=cfg["singular"], acao_novo=cfg["acao_novo"],
                           busca=busca, itens=repo.listar_simples(cfg["tabela"], busca or None))


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
        try:
            if item_id:
                repo.renomear_simples(cfg["tabela"], item_id, nome)
                flash("Alteração salva.", "ok")
            else:
                repo.criar_simples(cfg["tabela"], nome)
                flash("Cadastrado.", "ok")
        except IntegrityError:
            flash(f"Já existe {cfg['singular']} com esse nome.", "erro")
            return render_template("cadastro_simples_form.html", ativo="cadastro_simples", slug=slug,
                                   singular=cfg["singular"], acao_novo=cfg["acao_novo"],
                                   item={"id": item_id, "nome": nome})
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
    "data_seguralta_recebido", "data_plenus_recebido", "plenus_conferido_banco",
    "comissao_parcelada", "comissao_cocorretagem",
    "previsto_relatorio_seguralta", "recebido_relatorio_seguralta",
    "previsto_relatorio_plenus", "recebido_relatorio_plenus",
    "lancado_quiver", "link_onedrive",
    "veiculo_placa", "veiculo_descricao",
    "aviso_vigencia_ok", "aviso_vigencia_ok_em",
    "apolice_enviada", "apolice_enviada_data", "cartao_enviado", "cartao_enviado_data",
    "observacao",
)


def _apolice_para_form(ap, parcelas=None):
    """Deixa os números como texto pt-BR pros inputs (edição vinda do banco)."""
    if ap is None:
        return None
    ap = dict(ap)
    for campo in ("premio_liquido", "iof", "premio_total",
                  "comissao_valor_seguralta_receber", "comissao_valor_plenus_receber",
                  "comissao_valor_seguralta_recebido", "comissao_valor_plenus_recebido",
                  "previsto_relatorio_seguralta", "recebido_relatorio_seguralta",
                  "previsto_relatorio_plenus", "recebido_relatorio_plenus"):
        ap[campo] = formatar_numero(ap.get(campo))
    # percentual: sem forçar as 2 casas — "15" e não "15,00"; mantém "15,5" quando há
    ap["comissao_percentual"] = formatar_numero(ap.get("comissao_percentual")).rstrip("0").rstrip(",")
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
    seguradora_id = request.args.get("seguradora", type=int)
    forma_id = request.args.get("forma", type=int)
    mes = request.args.get("mes", type=int)
    if mes not in range(1, 13):
        mes = None
    mes_fim = request.args.get("mes_fim", type=int)
    if mes_fim not in range(1, 13):
        mes_fim = None
    quiver_arg = request.args.get("quiver", "")
    quiver = 1 if quiver_arg == "1" else 0 if quiver_arg == "0" else None
    busca = request.args.get("busca", "").strip()
    parcela = request.args.get("parcela", "")
    if parcela not in ("vencida", "proxima", "sem"):
        parcela = ""
    ordem = request.args.get("ord", "")
    if ordem not in ("cliente", "cliente_desc"):
        ordem = ""
    cliente = repo.obter_cliente(cliente_id) if cliente_id else None
    return render_template(
        "apolices_lista.html", ativo="apolices",
        apolices=repo.listar_apolices(cliente_id=cliente_id, tipo_seguro_id=tipo_id,
                                      seguradora_id=seguradora_id, forma_pagamento_id=forma_id,
                                      mes_inicio=mes, mes_fim=mes_fim, quiver=quiver,
                                      busca=busca or None, parcela_status=parcela or None,
                                      ordem=ordem or None),
        cliente_filtro=cliente, busca=busca, tipo_id=tipo_id, seguradora_id=seguradora_id,
        forma_id=forma_id,
        mes=mes, mes_fim=mes_fim, quiver=quiver_arg, parcela=parcela, ord=ordem,
        tipos=repo.listar_simples("tipo_seguro"), seguradoras=repo.listar_simples("seguradora"),
        formas=repo.listar_simples("forma_pagamento"), MESES=_MESES)


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
            request.form.getlist("parcela_enviado"),
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
        # cocorretagem: se o repasse veio vazio, o sistema o gera dos 75% da
        # comissão (fica editável — ver comissao.js). Só no salvar e só se vazio.
        if (dados.get("comissao_parcelada") and dados.get("comissao_cocorretagem")
                and comissoes and not repasses):
            repasses = gerar_repasses_cocorretagem(
                comissoes, dados.get("premio_liquido"), dados.get("comissao_percentual"))
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
                                   apolice=apolice, **_dados_form_apolice(),
                                   qtd_endossos=repo.contar_endossos_por_apolice(apolice_id) if apolice_id else 0)
        if apolice_id:
            repo.atualizar_apolice(apolice_id, dados, parcelas, comissoes, repasses)
            flash("Apólice atualizada.", "ok")
        else:
            apolice_id = repo.criar_apolice(dados, parcelas, comissoes, repasses)
            flash("Apólice cadastrada.", "ok")
        # "Salvar" de uma linha de parcela: fica no próprio formulário (não vai pra lista)
        if request.form.get("permanecer") == "1":
            return redirect(url_for("apolice_form", apolice_id=apolice_id))
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
                           apolice=_apolice_para_form(apolice), **_dados_form_apolice(),
                           qtd_endossos=repo.contar_endossos_por_apolice(apolice_id) if apolice_id else 0)


@app.route("/apolices/<int:apolice_id>/excluir", methods=["POST"])
def apolice_excluir(apolice_id):
    repo.excluir_apolice(apolice_id)
    flash("Apólice excluída.", "ok")
    return redirect(url_for("apolices"))


# ---------- Endossos ----------

_ENDOSSO_SITUACOES = [("onus", "Com ônus"), ("devolucao", "Com devolução"),
                      ("sem_alteracao", "Sem alteração financeira")]
_CAMPOS_ENDOSSO = (
    "apolice_id", "numero", "vigencia_inicio", "vigencia_fim", "motivacao",
    "situacao", "valor", "forma_pagamento_id", "veiculo_placa", "veiculo_descricao",
    "comissao_parcelada", "comissao_percentual",
    "comissao_valor_seguralta_receber", "comissao_valor_seguralta_recebido",
    "comissao_valor_plenus_receber", "comissao_valor_plenus_recebido",
    "data_seguralta_recebido", "data_plenus_recebido", "plenus_conferido_banco",
    "previsto_relatorio_seguralta", "recebido_relatorio_seguralta",
    "previsto_relatorio_plenus", "recebido_relatorio_plenus",
    "lancado_quiver", "link_onedrive",
)


def _dados_form_endosso():
    return {"apolices_opcoes": repo.listar_apolices_select(),
            "formas": repo.listar_simples("forma_pagamento"),
            "situacoes": _ENDOSSO_SITUACOES}


def _endosso_para_form(e, parcelas=None, comissoes=None, repasses=None):
    if e is None:
        return {"situacao": "sem_alteracao", "parcelas": parcelas or [],
                "comissoes": comissoes or [], "repasses": repasses or []}
    e = dict(e)
    for campo in ("valor", "comissao_percentual",
                  "comissao_valor_seguralta_receber", "comissao_valor_seguralta_recebido",
                  "comissao_valor_plenus_receber", "comissao_valor_plenus_recebido",
                  "previsto_relatorio_seguralta", "recebido_relatorio_seguralta",
                  "previsto_relatorio_plenus", "recebido_relatorio_plenus"):
        e[campo] = formatar_numero(e.get(campo))
    e["plenus_conferido_banco"] = 1 if str(e.get("plenus_conferido_banco") or "").strip() in ("1", "sim", "on", "true") else 0
    e["comissao_parcelada"] = 1 if str(e.get("comissao_parcelada") or "").strip() in ("1", "sim", "on", "true") else 0
    e["lancado_quiver"] = 1 if str(e.get("lancado_quiver") or "").strip() in ("1", "sim", "on", "true") else 0
    fonte = parcelas if parcelas is not None else e.get("parcelas", [])
    e["parcelas"] = [{**p, "valor": formatar_numero(p.get("valor"))} for p in fonte]
    fc = comissoes if comissoes is not None else e.get("comissoes", [])
    e["comissoes"] = [{**c, "valor_previsto": formatar_numero(c.get("valor_previsto")),
                       "valor_recebido": formatar_numero(c.get("valor_recebido"))} for c in fc]
    fr = repasses if repasses is not None else e.get("repasses", [])
    e["repasses"] = [{**r, "valor_previsto": formatar_numero(r.get("valor_previsto")),
                      "valor_recebido": formatar_numero(r.get("valor_recebido"))} for r in fr]
    return e


@app.route("/endossos")
def endossos_lista():
    apolice_id = request.args.get("apolice", type=int)
    busca = request.args.get("busca", "").strip()
    return render_template(
        "endossos_lista.html", ativo="endossos_lista",
        endossos=repo.listar_endossos(apolice_id or None, busca or None),
        busca=busca, apolice_id=apolice_id,
        apolice_filtro=repo.obter_apolice_basico(apolice_id) if apolice_id else None,
        tem_filtro=bool(busca or apolice_id),
        situacoes=dict(_ENDOSSO_SITUACOES))


@app.route("/endossos/novo", methods=["GET", "POST"])
@app.route("/endossos/<int:endosso_id>", methods=["GET", "POST"])
def endosso_form(endosso_id=None):
    voltar = request.form.get("voltar") or request.args.get("voltar") or ""
    if not (voltar.startswith("/") and not voltar.startswith("//")):
        voltar = ""
    endosso = repo.obter_endosso(endosso_id) if endosso_id else None
    if endosso_id and not endosso:
        flash("Endosso não encontrado.", "erro")
        return redirect(url_for("endossos_lista"))

    if request.method == "POST":
        dados = {k: request.form.get(k, "") for k in _CAMPOS_ENDOSSO}
        parcelas, erros_parc = preparar_parcelas(
            request.form.getlist("parcela_identificacao"),
            request.form.getlist("parcela_data"),
            request.form.getlist("parcela_valor"),
            request.form.getlist("parcela_paga"),
            request.form.getlist("parcela_aviso"),
            request.form.getlist("parcela_enviado"))
        comissoes, erros_com = preparar_comissoes(
            request.form.getlist("comissao_parcela"),
            request.form.getlist("comissao_previsto"),
            request.form.getlist("comissao_recebido"),
            request.form.getlist("comissao_data"))
        repasses, erros_rep = preparar_repasses(
            request.form.getlist("repasse_parcela"),
            request.form.getlist("repasse_previsto"),
            request.form.getlist("repasse_recebido"),
            request.form.getlist("repasse_data"),
            request.form.getlist("repasse_conferido"))
        if dados.get("comissao_parcelada") == "1":
            # comissão em parcelas: zera os campos planos de comissão
            for k in ("comissao_valor_seguralta_receber", "comissao_valor_seguralta_recebido",
                      "comissao_valor_plenus_receber", "comissao_valor_plenus_recebido",
                      "data_seguralta_recebido", "data_plenus_recebido", "plenus_conferido_banco"):
                dados[k] = ""
        else:
            comissoes, repasses, erros_com, erros_rep = [], [], [], []
            for k in ("previsto_relatorio_seguralta", "recebido_relatorio_seguralta",
                      "previsto_relatorio_plenus", "recebido_relatorio_plenus"):
                dados[k] = ""
        if dados.get("situacao") == "sem_alteracao":
            # sem alteração financeira: nada de pagamento nem comissão
            parcelas, erros_parc = [], []
            comissoes, repasses, erros_com, erros_rep = [], [], [], []
            dados["comissao_parcelada"] = ""
            for k in ("valor", "forma_pagamento_id", "comissao_percentual",
                      "comissao_valor_seguralta_receber", "comissao_valor_seguralta_recebido",
                      "comissao_valor_plenus_receber", "comissao_valor_plenus_recebido",
                      "data_seguralta_recebido", "data_plenus_recebido", "plenus_conferido_banco",
                      "previsto_relatorio_seguralta", "recebido_relatorio_seguralta",
                      "previsto_relatorio_plenus", "recebido_relatorio_plenus"):
                dados[k] = ""
        erros = validar_endosso(dados) + erros_parc + erros_com + erros_rep
        if erros:
            for e in erros:
                flash(e, "erro")
            return render_template("endossos_form.html", ativo="endossos_lista",
                                   endosso=_endosso_para_form({**dados, "id": endosso_id}, parcelas=parcelas,
                                                              comissoes=comissoes, repasses=repasses),
                                   voltar=voltar, **_dados_form_endosso())
        if endosso_id:
            repo.atualizar_endosso(endosso_id, dados, parcelas, comissoes, repasses)
            flash("Endosso atualizado.", "ok")
        else:
            endosso_id = repo.criar_endosso(dados, parcelas, comissoes, repasses)
            flash("Endosso cadastrado.", "ok")
        if request.form.get("permanecer") == "1":
            return redirect(url_for("endosso_form", endosso_id=endosso_id, voltar=voltar))
        return redirect(voltar or url_for("endossos_lista"))

    dados = _endosso_para_form(endosso)
    if endosso is None:
        ap = request.args.get("apolice", type=int)
        if ap and repo.obter_apolice(ap):
            dados["apolice_id"] = ap
    return render_template("endossos_form.html", ativo="endossos_lista",
                           endosso=dados, voltar=voltar, **_dados_form_endosso())


@app.route("/endossos/<int:endosso_id>/excluir", methods=["POST"])
def endosso_excluir(endosso_id):
    repo.excluir_endosso(endosso_id)
    flash("Endosso excluído.", "ok")
    return redirect(url_for("endossos_lista"))


# ---------- Consórcios ----------

_CONSORCIO_SITUACOES = [("ativo", "Ativo"), ("contemplado", "Contemplado"),
                        ("quitado", "Quitado"), ("cancelado", "Cancelado"),
                        ("desistente", "Desistente")]
_CONSORCIO_CONTEMPLACOES = [("", "—"), ("sorteio", "Sorteio"), ("lance", "Lance")]
_CAMPOS_CONSORCIO = (
    "cliente_id", "seguradora_id", "tipo_consorcio_id", "carta",
    "numero_grupo", "numero_cota", "forma_pagamento_id", "quantidade_parcelas",
    "parcela_dia_vencimento", "situacao", "forma_contemplacao", "data_contemplacao",
    "comissao_percentual",
    "comissao_valor_seguralta_receber", "comissao_valor_plenus_receber",
    "comissao_valor_seguralta_recebido", "comissao_valor_plenus_recebido",
    "data_seguralta_recebido", "data_plenus_recebido", "plenus_conferido_banco",
    "comissao_parcelada", "comissao_cocorretagem",
    "previsto_relatorio_seguralta", "recebido_relatorio_seguralta",
    "previsto_relatorio_plenus", "recebido_relatorio_plenus",
    "lancado_quiver", "link_onedrive", "observacao",
)
_COMISSAO_FLAT_CONSORCIO = ("comissao_valor_seguralta_receber", "comissao_valor_seguralta_recebido",
                            "comissao_valor_plenus_receber", "comissao_valor_plenus_recebido",
                            "data_seguralta_recebido", "data_plenus_recebido", "plenus_conferido_banco")
_COMISSAO_REL_CONSORCIO = ("previsto_relatorio_seguralta", "recebido_relatorio_seguralta",
                           "previsto_relatorio_plenus", "recebido_relatorio_plenus")


def _dados_form_consorcio():
    return {"clientes": repo.listar_clientes(),
            "seguradoras": repo.listar_simples("seguradora"),
            "tipos_consorcio": repo.listar_simples("tipo_consorcio"),
            "formas": repo.listar_simples("forma_pagamento"),
            "situacoes": _CONSORCIO_SITUACOES,
            "contemplacoes": _CONSORCIO_CONTEMPLACOES}


def _consorcio_para_form(co, parcela_valores=None, comissoes=None, repasses=None, boletos=None):
    if co is None:
        return {"situacao": "ativo", "parcela_valores": parcela_valores or [],
                "comissoes": comissoes or [], "repasses": repasses or [],
                "boletos": boletos or []}
    co = dict(co)
    for campo in ("carta", "comissao_percentual",
                  "comissao_valor_seguralta_receber", "comissao_valor_seguralta_recebido",
                  "comissao_valor_plenus_receber", "comissao_valor_plenus_recebido",
                  "previsto_relatorio_seguralta", "recebido_relatorio_seguralta",
                  "previsto_relatorio_plenus", "recebido_relatorio_plenus"):
        co[campo] = formatar_numero(co.get(campo))
    for campo in ("plenus_conferido_banco", "comissao_parcelada", "comissao_cocorretagem", "lancado_quiver"):
        co[campo] = 1 if str(co.get(campo) or "").strip() in ("1", "sim", "on", "true") else 0
    fpv = parcela_valores if parcela_valores is not None else co.get("parcela_valores", [])
    co["parcela_valores"] = [{**v, "valor": formatar_numero(v.get("valor"))} for v in fpv]
    fc = comissoes if comissoes is not None else co.get("comissoes", [])
    co["comissoes"] = [{**c, "valor_previsto": formatar_numero(c.get("valor_previsto")),
                        "valor_recebido": formatar_numero(c.get("valor_recebido"))} for c in fc]
    fr = repasses if repasses is not None else co.get("repasses", [])
    co["repasses"] = [{**r, "valor_previsto": formatar_numero(r.get("valor_previsto")),
                       "valor_recebido": formatar_numero(r.get("valor_recebido"))} for r in fr]
    fb = boletos if boletos is not None else co.get("boletos", [])
    co["boletos"] = [{**b, "valor": formatar_numero(b.get("valor"))} for b in fb]
    return co


@app.route("/consorcios")
def consorcios_lista():
    busca = request.args.get("busca", "").strip()
    return render_template(
        "consorcios_lista.html", ativo="consorcios_lista",
        consorcios=repo.listar_consorcios(busca or None),
        busca=busca, tem_filtro=bool(busca),
        situacoes=dict(_CONSORCIO_SITUACOES))


@app.route("/consorcios/novo", methods=["GET", "POST"])
@app.route("/consorcios/<int:consorcio_id>", methods=["GET", "POST"])
def consorcio_form(consorcio_id=None):
    voltar = request.form.get("voltar") or request.args.get("voltar") or ""
    if not (voltar.startswith("/") and not voltar.startswith("//")):
        voltar = ""
    consorcio = repo.obter_consorcio(consorcio_id) if consorcio_id else None
    if consorcio_id and not consorcio:
        flash("Consórcio não encontrado.", "erro")
        return redirect(url_for("consorcios_lista"))

    if request.method == "POST":
        dados = {k: request.form.get(k, "") for k in _CAMPOS_CONSORCIO}
        parcela_valores, erros_pv = preparar_parcela_valores(
            request.form.getlist("pv_valor"), request.form.getlist("pv_data"))
        comissoes, erros_com = preparar_comissoes(
            request.form.getlist("comissao_parcela"),
            request.form.getlist("comissao_previsto"),
            request.form.getlist("comissao_recebido"),
            request.form.getlist("comissao_data"))
        repasses, erros_rep = preparar_repasses(
            request.form.getlist("repasse_parcela"),
            request.form.getlist("repasse_previsto"),
            request.form.getlist("repasse_recebido"),
            request.form.getlist("repasse_data"),
            request.form.getlist("repasse_conferido"))
        boletos, erros_bol = preparar_boletos(
            request.form.getlist("boleto_identificacao"),
            request.form.getlist("boleto_valor"),
            request.form.getlist("boleto_emissao"),
            request.form.getlist("boleto_vencimento"),
            request.form.getlist("boleto_pagamento"),
            request.form.getlist("boleto_status"),
            request.form.getlist("boleto_aviso"))
        if (dados.get("comissao_parcelada") == "1" and dados.get("comissao_cocorretagem") == "1"
                and comissoes and not repasses):
            repasses = gerar_repasses_cocorretagem(
                comissoes, dados.get("carta"), dados.get("comissao_percentual"))
        if dados.get("comissao_parcelada") == "1":
            for k in _COMISSAO_FLAT_CONSORCIO:
                dados[k] = ""
        else:
            comissoes, repasses, erros_com, erros_rep = [], [], [], []
            for k in _COMISSAO_REL_CONSORCIO:
                dados[k] = ""
        erros = (validar_consorcio(dados) + erros_pv + erros_com + erros_rep + erros_bol)
        if erros:
            for e in erros:
                flash(e, "erro")
            return render_template(
                "consorcios_form.html", ativo="consorcios_lista",
                consorcio=_consorcio_para_form({**dados, "id": consorcio_id},
                                               parcela_valores=parcela_valores, comissoes=comissoes,
                                               repasses=repasses, boletos=boletos),
                voltar=voltar, **_dados_form_consorcio())
        if consorcio_id:
            repo.atualizar_consorcio(consorcio_id, dados, parcela_valores, comissoes, repasses, boletos)
            flash("Consórcio atualizado.", "ok")
        else:
            consorcio_id = repo.criar_consorcio(dados, parcela_valores, comissoes, repasses, boletos)
            flash("Consórcio cadastrado.", "ok")
        if request.form.get("permanecer") == "1":
            return redirect(url_for("consorcio_form", consorcio_id=consorcio_id, voltar=voltar))
        return redirect(voltar or url_for("consorcios_lista"))

    dados = _consorcio_para_form(consorcio)
    if consorcio is None:
        cli = request.args.get("cliente", type=int)
        if cli and repo.obter_cliente(cli):
            dados["cliente_id"] = cli
    return render_template("consorcios_form.html", ativo="consorcios_lista",
                           consorcio=dados, voltar=voltar, **_dados_form_consorcio())


@app.route("/consorcios/<int:consorcio_id>/excluir", methods=["POST"])
def consorcio_excluir(consorcio_id):
    repo.excluir_consorcio(consorcio_id)
    flash("Consórcio excluído.", "ok")
    return redirect(url_for("consorcios_lista"))


def _voltar_seguro(campo="voltar"):
    destino = request.form.get(campo)
    if destino and destino.startswith("/") and not destino.startswith("//"):
        return redirect(destino)
    return redirect(url_for("dashboard"))


def _origem_parcela():
    o = request.form.get("origem")
    return o if o in ("endosso", "consorcio") else "apolice"


@app.route("/parcelas/<int:parcela_id>/pagamento", methods=["POST"])
def parcela_pagamento(parcela_id):
    repo.marcar_parcela_paga(parcela_id, request.form.get("paga") == "1", _origem_parcela())
    flash("Parcela atualizada.", "ok")
    return _voltar_seguro()


@app.route("/parcelas/<int:parcela_id>/aviso-cliente", methods=["POST"])
def parcela_aviso(parcela_id):
    repo.marcar_aviso_parcela(parcela_id, request.form.get("aviso") == "1", _origem_parcela())
    flash("Aviso do boleto atualizado.", "ok")
    return _voltar_seguro()


@app.route("/parcelas/<int:parcela_id>/enviado", methods=["POST"])
def parcela_enviado(parcela_id):
    repo.marcar_parcela_enviada(parcela_id, request.form.get("enviado") == "1", _origem_parcela())
    flash("Status de envio do boleto atualizado.", "ok")
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


# ---------- Cotação ----------

# tipos de campo da cotação: (valor guardado, rótulo exibido).
# Cada tipo define como o campo é preenchido quando alguém GERA a cotação:
#   texto -> texto livre | valor -> R$ | numerico -> número | data -> data | percentual -> %
#   sim_nao -> escolha Sim/Não | selecao -> escolha numa lista de opções cadastrada no campo
_TIPOS_CAMPO_COTACAO = [
    ("texto", "Texto"),
    ("valor", "Valor (R$)"),
    ("numerico", "Numérico"),
    ("data", "Data"),
    ("percentual", "Percentual (%)"),
    ("sim_nao", "Sim ou Não"),
    ("selecao", "Seleção (lista de opções)"),
]
_TIPOS_CAMPO_COTACAO_LABEL = dict(_TIPOS_CAMPO_COTACAO)
app.jinja_env.globals["TIPO_CAMPO_COTACAO_LABEL"] = _TIPOS_CAMPO_COTACAO_LABEL

# tipos que viram <select> no formulário "Gerar cotação" (as opções vêm de `campo_cot_opcoes`)
_TIPOS_CAMPO_COTACAO_SELECT = ("sim_nao", "selecao")
app.jinja_env.globals["TIPOS_CAMPO_COTACAO_SELECT"] = _TIPOS_CAMPO_COTACAO_SELECT


def campo_cotacao_opcoes(campo):
    """Opções do <select> desse campo em 'Gerar cotação'."""
    if (campo or {}).get("tipo") == "sim_nao":
        return ["Sim", "Não"]
    return [l.strip() for l in ((campo or {}).get("opcoes") or "").splitlines() if l.strip()]


app.jinja_env.globals["campo_cot_opcoes"] = campo_cotacao_opcoes

# sufixo entre parênteses no fim do nome do campo -> unidade do valor.
# ex.: "Carro Reserva (dias)" -> rótulo "Carro Reserva", unidade "dias".
_RE_CAMPO_UNIDADE = re.compile(r"\s*\(([^()]+)\)\s*$")


def campo_cotacao_rotulo(nome):
    return _RE_CAMPO_UNIDADE.sub("", (nome or "").strip())


def campo_cotacao_unidade(nome):
    m = _RE_CAMPO_UNIDADE.search(nome or "")
    return m.group(1).strip() if m else ""


app.jinja_env.globals["campo_cot_rotulo"] = campo_cotacao_rotulo
app.jinja_env.globals["campo_cot_unidade"] = campo_cotacao_unidade

# papel do campo no cálculo do PDF de cotação (só um dono por papel).
#   base_parcelamento -> valor que é dividido    | num_parcelas -> em quantas vezes
_PAPEIS_CAMPO_COTACAO = [
    ("", "— nenhum —"),
    ("base_parcelamento", "Base do parcelamento (valor a dividir)"),
    ("num_parcelas", "Nº de parcelas"),
]
_PAPEIS_CAMPO_COTACAO_VALIDOS = {v for v, _ in _PAPEIS_CAMPO_COTACAO}
app.jinja_env.globals["PAPEL_CAMPO_COTACAO_LABEL"] = dict(_PAPEIS_CAMPO_COTACAO)


@app.route("/cotacao/campos")
def cotacao_campos():
    busca = request.args.get("busca", "").strip()
    return render_template("cotacao_campos_lista.html", ativo="cotacao_campos",
                           campos=repo.listar_campos_cotacao(busca or None), busca=busca)


@app.route("/cotacao/campos/novo", methods=["GET", "POST"])
@app.route("/cotacao/campos/<int:campo_id>", methods=["GET", "POST"])
def cotacao_campo_form(campo_id=None):
    campo = repo.obter_campo_cotacao(campo_id) if campo_id else None
    if campo_id and not campo:
        flash("Campo não encontrado.", "erro")
        return redirect(url_for("cotacao_campos"))

    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        tipo = request.form.get("tipo", "").strip()
        ordem_txt = request.form.get("ordem_form", "").strip()
        papel = request.form.get("papel", "").strip()
        if papel not in _PAPEIS_CAMPO_COTACAO_VALIDOS:
            papel = ""
        opcoes_lista = [o.strip() for o in request.form.getlist("opcao") if o.strip()]
        opcoes = "\n".join(opcoes_lista) if tipo == "selecao" else ""
        erros = []
        if not nome:
            erros.append("Informe o nome do campo.")
        if tipo not in _TIPOS_CAMPO_COTACAO_LABEL:
            erros.append("Escolha o tipo do campo.")
        if tipo == "selecao" and not opcoes_lista:
            erros.append("Cadastre ao menos uma opção para o tipo Seleção.")
        ordem = None
        if ordem_txt:
            try:
                ordem = int(ordem_txt)
            except ValueError:
                erros.append("A ordem no formulário deve ser um número inteiro.")
        if ordem is not None and repo.campo_cotacao_ordem_existe(ordem, ignorar_id=campo_id):
            erros.append(f"A ordem {ordem} já está em uso por outro campo — cada campo precisa de uma ordem única.")
        if not erros and repo.campo_cotacao_nome_existe(nome, ignorar_id=campo_id):
            erros.append("Já existe um campo de cotação com esse nome.")
        if erros:
            for e in erros:
                flash(e, "erro")
            return render_template("cotacao_campo_form.html", ativo="cotacao_campos",
                                   campo={"id": campo_id, "nome": nome, "tipo": tipo,
                                          "ordem": ordem if ordem is not None else ordem_txt,
                                          "papel": papel, "opcoes": "\n".join(opcoes_lista)},
                                   tipos=_TIPOS_CAMPO_COTACAO, papeis=_PAPEIS_CAMPO_COTACAO)
        if campo_id:
            repo.atualizar_campo_cotacao(campo_id, nome, tipo, ordem, papel, opcoes)
            flash("Campo atualizado.", "ok")
        else:
            repo.criar_campo_cotacao(nome, tipo, ordem, papel, opcoes)
            flash("Campo cadastrado.", "ok")
        return redirect(url_for("cotacao_campos"))

    return render_template("cotacao_campo_form.html", ativo="cotacao_campos",
                           campo=campo, tipos=_TIPOS_CAMPO_COTACAO, papeis=_PAPEIS_CAMPO_COTACAO)


@app.route("/cotacao/campos/<int:campo_id>/excluir", methods=["POST"])
def cotacao_campo_excluir(campo_id):
    repo.excluir_campo_cotacao(campo_id)
    flash("Campo excluído.", "ok")
    return redirect(url_for("cotacao_campos"))


@app.route("/cotacao/campos/reordenar", methods=["POST"])
def cotacao_campos_reordenar():
    """Arrastar-e-soltar na lista: recebe a nova sequência inteira de ids e
    renumera a `ordem` de 1 em diante nessa ordem."""
    dados = request.get_json(silent=True) or {}
    try:
        ids = [int(i) for i in (dados.get("ids") or [])]
    except (TypeError, ValueError):
        return jsonify(ok=False, erro="ids inválidos"), 400
    if not ids:
        return jsonify(ok=False, erro="lista vazia"), 400
    repo.reordenar_campos_cotacao(ids)
    return jsonify(ok=True)


@app.route("/cotacao/gerar", methods=["GET", "POST"])
def cotacao_gerar():
    campos = repo.listar_campos_cotacao()
    seguradoras = repo.listar_simples("seguradora")

    if request.method == "POST":
        cliente = request.form.get("cliente", "").strip()
        segs = request.form.getlist("cot_seguradora")
        # listas paralelas: campo_<id>[i] = valor da i-ésima cotação
        vals_por_campo = {c["id"]: request.form.getlist(f"campo_{c['id']}") for c in campos}

        cotacoes = []
        for i, seg in enumerate(segs):
            valores = {cid: (lst[i].strip() if i < len(lst) else "")
                       for cid, lst in vals_por_campo.items()}
            if not seg.strip() and not any(valores.values()):
                continue  # cotação totalmente vazia — ignora
            cotacoes.append({"seguradora": seg.strip(), "valores": valores})

        if not cotacoes:
            flash("Adicione ao menos uma seguradora com valores.", "erro")
            return render_template("cotacao_gerar.html", ativo="cotacao_gerar",
                                   campos=campos, seguradoras=seguradoras, cliente=cliente)

        import cotacao_pdf
        pdf = cotacao_pdf.gerar(cliente, cotacoes, campos)
        base = _sem_acento_para_arquivo(cliente) or "cotacao"
        nome = f"cotacao-{base}-{date.today().isoformat()}.pdf"
        return Response(pdf, mimetype="application/pdf",
                        headers={"Content-Disposition": f'attachment; filename="{nome}"'})

    return render_template("cotacao_gerar.html", ativo="cotacao_gerar",
                           campos=campos, seguradoras=seguradoras, cliente="")


# chave canônica (ver cotacao_leitura_pdf.CHAVES) -> trechos do NOME do campo cadastrado
# (sem acento/minúsculo, já sem o sufixo de unidade) que identificam esse campo.
# "valor_seguro" e "num_parcelas" preferem casar pelo `papel` (mais confiável, não muda
# se a usuária renomear o campo) e só caem aqui se nenhum campo tiver esse papel.
_CAMPO_COTACAO_PDF_NOME = {
    "danos_materiais": ("danos materiais",),
    "danos_corporais": ("danos corporais",),
    "app_morte": ("app morte",),
    "danos_morais": ("danos morais",),
    "assistencia": ("assist",),
    "vidros": ("vidros",),
    "carro_reserva": ("carro reserva",),
    "pequenos_reparos": ("pequenos reparos",),
    "protecao_roda": ("protecao roda", "protecao de roda", "protecao rodas"),
    "tipo_oficina": ("tipo de oficina", "oficina"),
    "valor_franquia": ("franquia",),
    "valor_seguro": ("valor do seguro",),
}


def _mapear_campos_cotacao_pdf(campos_cadastrados):
    """Pra cada chave canônica que a leitura de PDF pode devolver, acha o id do campo
    cadastrado correspondente. Devolve {chave: campo_id}."""
    mapa = {}
    for c in campos_cadastrados:
        if c["papel"] == "base_parcelamento":
            mapa.setdefault("valor_seguro", c["id"])
        elif c["papel"] == "num_parcelas":
            mapa.setdefault("num_parcelas", c["id"])
    for chave, substrs in _CAMPO_COTACAO_PDF_NOME.items():
        if chave in mapa:
            continue
        for c in campos_cadastrados:
            nome_norm = repo._sem_acento_minusculo(campo_cotacao_rotulo(c["nome"]))
            if any(s in nome_norm for s in substrs):
                mapa[chave] = c["id"]
                break
    return mapa


def _valor_pdf_para_campo(campo, valor_bruto):
    """Converte o texto extraído do PDF pro formato que o input desse campo espera.
    Em tipos de lista (sim/não, seleção), só aceita se casar com uma opção cadastrada —
    na dúvida, None (o usuário preenche)."""
    if campo["tipo"] not in ("sim_nao", "selecao"):
        return valor_bruto
    alvo = repo._sem_acento_minusculo(valor_bruto)
    for opc in campo_cotacao_opcoes(campo):
        o = repo._sem_acento_minusculo(opc)
        if o == alvo or o in alvo or alvo in o:
            return opc
    return None


@app.route("/cotacao/ler-pdf", methods=["POST"])
def cotacao_ler_pdf():
    arquivo = request.files.get("arquivo")
    if not arquivo or not arquivo.filename:
        return jsonify(ok=False, cliente=None, cotacoes=[], aviso="Nenhum arquivo enviado."), 400
    if not arquivo.filename.lower().endswith(".pdf"):
        return jsonify(ok=False, cliente=None, cotacoes=[], aviso="Envie um arquivo PDF."), 400
    dados = arquivo.read()
    if not dados:
        return jsonify(ok=False, cliente=None, cotacoes=[], aviso="Arquivo vazio."), 400

    try:
        lido = cotacao_leitura_pdf.ler_pdf_cotacao(dados)
    except Exception as e:  # noqa: BLE001 - devolve o erro pro front em vez de 500 seco
        app.logger.exception("falha ao ler PDF de cotação")
        return jsonify(ok=False, cliente=None, cotacoes=[], aviso=f"Erro ao ler o PDF: {e}"), 500

    campos_cadastrados = repo.listar_campos_cotacao()
    mapa = _mapear_campos_cotacao_pdf(campos_cadastrados)
    por_id = {c["id"]: c for c in campos_cadastrados}
    ids_sim_nao = [c["id"] for c in campos_cadastrados if c["tipo"] == "sim_nao"]

    cotacoes = []
    for oferta in lido.get("ofertas", []):
        valores = {}
        for chave, bruto in oferta.get("campos", {}).items():
            campo_id = mapa.get(chave)
            if not campo_id or not bruto:
                continue
            valor = _valor_pdf_para_campo(por_id[campo_id], bruto)
            if valor:
                valores[str(campo_id)] = valor
        # sim/não sem menção no PDF -> assume "Não" (não achamos evidência de que foi contratado)
        for cid in ids_sim_nao:
            valores.setdefault(str(cid), "Não")
        cotacoes.append({"seguradora": oferta.get("seguradora") or "", "valores": valores})

    return jsonify(ok=lido["ok"], origem=lido["origem"], cliente=lido.get("cliente"),
                   cotacoes=cotacoes, aviso=lido.get("aviso"), texto=lido.get("texto", ""))


def _sem_acento_para_arquivo(txt):
    import unicodedata
    t = unicodedata.normalize("NFKD", txt or "")
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    return "".join(ch if ch.isalnum() else "-" for ch in t).strip("-").lower()[:40]


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


def _cards_a_receber():
    """(a_receber_mes, a_receber_total) — repasse Plenus ainda NÃO recebido
    (`apolice_repasse.valor_recebido` vazio → soma `valor_previsto`). "mês" =
    parcela com data no mês corrente; "total" = qualquer data. Globais (não
    seguem os filtros da tela), como os cards fixos de Saídas."""
    mes_iso = date.today().strftime("%Y-%m")
    mes = total = 0.0
    for l in repo.listar_entradas_repasse():
        if l.get("valor_recebido") is not None:
            continue
        v = l.get("valor_previsto") or 0
        total += v
        if (l.get("data") or "")[:7] == mes_iso:
            mes += v
    return mes, total


@app.route("/financeiro/entradas")
def entradas_lista():
    # tela no estilo Saídas: 3 cards + barra curta (Buscar / período / Situação);
    # o corpo é SEMPRE a grade editável das comissões por apólice (o relatório
    # agrupado read-only + PDF ficam no menu "Relatório de entradas").
    busca = request.args.get("busca", "").strip()
    data_ini = request.args.get("data_ini", "").strip()
    data_fim = request.args.get("data_fim", "").strip()
    situacao = request.args.get("situacao", "")
    if situacao not in ("paga", "nao_paga"):
        situacao = ""
    tipo_id = request.args.get("tipo_id", type=int)

    apolices = repo.comissoes_repasses_por_apolice(data_ini or None, data_fim or None)
    if tipo_id:
        apolices = [a for a in apolices if a.get("tipo_seguro_id") == tipo_id]
    if busca:
        alvo = repo._sem_acento_minusculo(busca)
        apolices = [a for a in apolices
                    if alvo in repo._sem_acento_minusculo(a.get("cliente_nome") or "")
                    or alvo in repo._sem_acento_minusculo(a.get("numero_apolice") or "")]
    arvore_blocos, qtd_apolices = _blocos_entrada(apolices, [], situacao)
    a_receber_mes, a_receber_total = _cards_a_receber()

    return render_template(
        "entradas_lista.html", ativo="entradas_lista",
        arvore_blocos=arvore_blocos, qtd_apolices=qtd_apolices,
        a_receber_mes=a_receber_mes, a_receber_total=a_receber_total,
        busca=busca, data_ini=data_ini, data_fim=data_fim, situacao=situacao,
        tipo_id=tipo_id, tipos=repo.listar_simples("tipo_seguro"),
        tem_filtro=bool(busca or data_ini or data_fim or situacao or tipo_id),
        mes_atual=date.today().month, MESES=_MESES, presets=_presets_periodo())


# ---- panorama de comissões: uma linha por apólice, esperado x recebido ----
# Regra do negócio: comissão cheia C = prêmio líquido × %. A Plenus sempre fica
# com 75% de C. Sem cocorretagem a SEGURALTA recebe C (e repassa 75% à Plenus);
# com cocorretagem a SEGURALTA recebe só 25% de C e a Plenus recebe os 75% direto.
_PANORAMA_TOL = 0.01


def _calc_panorama(r):
    premio = r.get("premio_liquido") or 0
    pct = r.get("comissao_percentual") or 0
    coco = bool(r.get("cocorretagem"))
    cheia = round(premio * pct / 100, 2)
    r["comissao_cheia"] = cheia
    if r.get("is_endosso") or r.get("is_consorcio"):
        # endosso / consórcio: usa os valores "a receber" lançados; se vazios, cai no prêmio×%
        seg = r.get("end_com_seg")
        r["com_seguralta"] = seg if seg is not None else (round(cheia * 0.25, 2) if coco else cheia)
        ple = r.get("end_com_ple")
        r["com_plenus"] = ple if ple is not None else round(cheia * 0.75, 2)
    else:
        r["com_seguralta"] = round(cheia * 0.25, 2) if coco else cheia
        r["com_plenus"] = round(cheia * 0.75, 2)
    r["receb_seguralta"] = r.get("receb_seguralta") or 0
    r["receb_plenus"] = r.get("receb_plenus") or 0
    r["seguralta_a_receber"] = round(r["com_seguralta"] - r["receb_seguralta"], 2)
    r["plenus_a_receber"] = round(r["com_plenus"] - r["receb_plenus"], 2)
    # Conferência: quanto ainda "falta" para bater.
    #  - seguro de VIDA: comissão é mensal; confere se o recebido fecha um número
    #    inteiro de meses (Σ recebido ≈ n × valor mensal). O "a receber" dos meses
    #    futuros NÃO é falta.
    #  - demais (e endossos): falta = repasse ainda pendente (ple_a_receber).
    eh_vida = (not r.get("is_endosso") and not r.get("is_consorcio")
               and "vida" in (r.get("tipo_seguro_nome") or "").lower())
    if eh_vida and r["com_plenus"]:
        n_meses = round(r["receb_plenus"] / r["com_plenus"])
        r["conf_delta"] = round(n_meses * r["com_plenus"] - r["receb_plenus"], 2)
    else:
        r["conf_delta"] = r.get("ple_a_receber") or 0
    # divergência: recebido no sistema x recebido "no relatório da corretora"
    div = []
    rs, rp = r.get("rel_receb_seguralta"), r.get("rel_receb_plenus")
    if rs is not None and abs(rs - r["receb_seguralta"]) >= _PANORAMA_TOL:
        div.append("Seguralta recebido: sistema %s · corretora %s"
                   % (formatar_moeda(r["receb_seguralta"]), formatar_moeda(rs)))
    if rp is not None and abs(rp - r["receb_plenus"]) >= _PANORAMA_TOL:
        div.append("Plenus recebido: sistema %s · corretora %s"
                   % (formatar_moeda(r["receb_plenus"]), formatar_moeda(rp)))
    r["divergencia"] = div


_PANORAMA_SOMA = ("premio_liquido", "com_seguralta", "receb_seguralta",
                  "com_plenus", "receb_plenus", "ple_a_receber", "conf_delta")

_PANORAMA_GRUPOS = [("seguradora", "Seguradora"), ("mes", "Mês da vigência"),
                    ("cliente", "Cliente")]
_PANORAMA_GRUPOS_VALIDOS = {k for k, _ in _PANORAMA_GRUPOS}


def _somar_panorama(linhas):
    return {k: round(sum(r.get(k) or 0 for r in linhas), 2) for k in _PANORAMA_SOMA}


def _chave_grupo_panorama(r, g):
    """(chave_ordenação, rótulo) do grupo da linha, conforme g."""
    if g == "mes":
        return _rotulo_mes_iso(r.get("vigencia_inicio"))
    if g == "cliente":
        nome = r.get("cliente_nome") or "(sem cliente)"
    else:
        nome = r.get("seguradora_nome") or "(sem seguradora)"
    return (repo._sem_acento_minusculo(nome), nome)


def _presets_periodo():
    """Atalhos De/Até (mês, mês passado, ano) — mesmo padrão do relatório de fluxo de caixa."""
    hoje = date.today()
    prox_mes_1 = (date(hoje.year + 1, 1, 1) if hoje.month == 12
                  else date(hoje.year, hoje.month + 1, 1))
    fim_mes = (prox_mes_1 - timedelta(days=1)).isoformat()
    fim_mes_passado = hoje.replace(day=1) - timedelta(days=1)
    return {
        "mes": (hoje.replace(day=1).isoformat(), fim_mes),
        "mes_passado": (fim_mes_passado.replace(day=1).isoformat(), fim_mes_passado.isoformat()),
        "ano": (hoje.replace(month=1, day=1).isoformat(), hoje.replace(month=12, day=31).isoformat()),
    }


@app.route("/financeiro/entradas/panorama")
def entradas_panorama():
    busca = request.args.get("busca", "").strip()
    data_ini = request.args.get("data_ini", "").strip()
    data_fim = request.args.get("data_fim", "").strip()
    g = request.args.get("g", "seguradora")
    if g not in _PANORAMA_GRUPOS_VALIDOS:
        g = "seguradora"
    linhas = repo.panorama_comissoes(busca or None, data_ini or None, data_fim or None)
    for r in linhas:
        _calc_panorama(r)
    linhas.sort(key=lambda r: (_chave_grupo_panorama(r, g)[0],
                               repo._sem_acento_minusculo(r.get("cliente_nome") or ""),
                               str(r.get("apolice_id") or r.get("consorcio_id") or "")))
    grupos = []
    for r in linhas:
        chave, rotulo = _chave_grupo_panorama(r, g)
        if not grupos or grupos[-1]["chave"] != chave:
            grupos.append({"chave": chave, "rotulo": rotulo, "linhas": []})
        grupos[-1]["linhas"].append(r)
    for gr in grupos:
        gr["subtotal"] = _somar_panorama(gr["linhas"])
        gr["qtd"] = len(gr["linhas"])
    return render_template("panorama_comissoes.html", ativo="entradas_panorama",
                           grupos=grupos, tot=_somar_panorama(linhas), qtd=len(linhas),
                           busca=busca, data_ini=data_ini, data_fim=data_fim,
                           grupo=g, grupo_opcoes=_PANORAMA_GRUPOS,
                           grupo_label=dict(_PANORAMA_GRUPOS)[g],
                           presets=_presets_periodo())


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


# ---- entradas: parcela "paga" = tem valor recebido preenchido (mesma regra da
#      grade de Entradas, _merge_linhas_bloco); pagamento adiantado também conta.
#      paga → vale o recebido; não paga → vale o previsto ----

def _preparar_entradas(linhas):
    for l in linhas:
        receb = l.get("valor_recebido")
        l["paga"] = receb is not None
        l["valor"] = (receb or 0) if l["paga"] else (l.get("valor_previsto") or 0)
        l["status"] = "recebido" if l["paga"] else "a_receber"
        l["mes_key"], l["mes_rotulo"] = _rotulo_mes_iso(l.get("data"))
    return linhas


def _totais_entrada(itens):
    # soma REAL da coluna Pago Plenus: só o que de fato entrou (parcela sem
    # "recebido" não conta). "a receber" = o previsto das que ainda não entraram.
    recebido = sum(x.get("valor_recebido") or 0 for x in itens)
    a_receber = sum(x.get("valor_previsto") or 0
                    for x in itens if x.get("valor_recebido") is None)
    return {"qtd": len(itens), "soma": recebido,
            "soma_paga": recebido, "soma_aberto": a_receber}


# agrupamento do relatório de entradas: 0..2 níveis à escolha; cada função
# devolve (chave_de_ordenação, rótulo_exibido). A apólice é SEMPRE o nível-folha.
_GRUPOS_ENTRADA = {
    "tipo": ("Tipo de seguro", lambda l: (
        repo._sem_acento_minusculo(l.get("tipo_seguro_nome") or "") or "zzz",
        l.get("tipo_seguro_nome") or "Sem tipo de seguro")),
    "seguradora": ("Seguradora", lambda l: (
        repo._sem_acento_minusculo(l.get("seguradora_nome") or "") or "zzz",
        l.get("seguradora_nome") or "Sem seguradora")),
    "mes": ("Mês da parcela", lambda l: (l["mes_key"], l["mes_rotulo"])),
}
_GRUPO_OPCOES_ENTRADA = [("", "—"), ("tipo", "Tipo de seguro"),
                         ("seguradora", "Seguradora"), ("mes", "Mês da parcela")]


def _divergencia_repasse(apolice_id, divs):
    """Compara a soma do repasse no sistema com o total "no relatório da corretora"
    (`divs` = repo.repasse_vs_relatorio_plenus()). Devolve lista de
    {campo, sistema, relatorio} para os que diferem >= 0,01, ou None."""
    d = (divs or {}).get(apolice_id)
    if not d:
        return None
    itens = []
    pares = (("Previsto", d.get("prev_relatorio"), d.get("prev_sistema") or 0),
             ("Recebido", d.get("receb_relatorio"), d.get("receb_sistema") or 0))
    for campo, rel, sis in pares:
        if rel is not None and abs(rel - sis) >= 0.01:
            itens.append({"campo": campo, "sistema": sis, "relatorio": rel})
    return itens or None


def _apolices_entrada(linhas, divs=None):
    """Nível-folha: uma entrada por apólice, com suas parcelas e subtotais."""
    baldes = {}
    for l in linhas:
        baldes.setdefault(l["apolice_id"], []).append(l)
    apolices = []
    for parc in baldes.values():
        cab = parc[0]
        prem, pct = cab.get("premio_liquido"), cab.get("comissao_percentual")
        cheia = round(prem * pct / 100, 2) if prem is not None and pct is not None else None
        # entrada da Plenus calculada pelo sistema = 75% da comissão cheia (ver _calc_panorama)
        comissao_plenus = round(cheia * 0.75, 2) if cheia is not None else None
        apolices.append({
            "apolice_id": cab.get("apolice_id"),
            "cliente_nome": cab.get("cliente_nome") or "Sem cliente",
            "numero_apolice": cab.get("numero_apolice"),
            "is_endosso": bool(cab.get("is_endosso")),
            "is_consorcio": bool(cab.get("is_consorcio")),
            "premio_liquido": cab.get("premio_liquido"),
            "comissao_percentual": cab.get("comissao_percentual"),
            "comissao_plenus": comissao_plenus,
            "cocorretagem": bool(cab.get("comissao_cocorretagem")),
            "divergencia": _divergencia_repasse(cab.get("apolice_id"), divs),
            "parcelas": parc, **_totais_entrada(parc),
        })
    apolices.sort(key=lambda a: repo._sem_acento_minusculo(a["cliente_nome"]))
    return apolices


def _agrupar_entradas(linhas, chaves, divs=None):
    """`chaves` = lista de 0..2 nomes de `_GRUPOS_ENTRADA`. Árvore:
    {campo, chave, grupos:[{rotulo, ...totais, sub}]}  →  no fim, {campo: None,
    apolices:[...], ...totais}. A apólice é sempre a folha."""
    if not chaves:
        return {"campo": None, "apolices": _apolices_entrada(linhas, divs),
                **_totais_entrada(linhas)}
    campo_rotulo, fn = _GRUPOS_ENTRADA[chaves[0]]
    baldes = {}
    for l in linhas:
        baldes.setdefault(fn(l), []).append(l)
    grupos = []
    for chave in sorted(baldes):
        itens = baldes[chave]
        grupos.append({"rotulo": chave[1], **_totais_entrada(itens),
                       "sub": _agrupar_entradas(itens, chaves[1:], divs)})
    return {"campo": campo_rotulo, "chave": chaves[0], "grupos": grupos,
            **_totais_entrada(linhas)}


# ---- grade EDITÁVEL do menu Entradas: um bloco por apólice, casando as duas
#      tabelas de comissão (lado Seguralta × lado Plenus) linha a linha ----

def _merge_linhas_bloco(com, rep):
    """Casa `apolice_comissao[i]` com `apolice_repasse[i]` POR POSIÇÃO. Faltando
    um dos lados → campos vazios. Devolve as linhas de exibição do bloco."""
    n = max(len(com), len(rep)) or 1
    linhas = []
    for i in range(n):
        c = com[i] if i < len(com) else {}
        r = rep[i] if i < len(rep) else {}
        pg = r.get("valor_recebido")
        linhas.append({
            "seg_parcela": c.get("parcela"), "ple_parcela": r.get("parcela"),
            "parcela": c.get("parcela") or r.get("parcela") or "",
            "seg_previsto": c.get("valor_previsto"), "seg_recebido": c.get("valor_recebido"),
            "seg_data": c.get("data"),
            "ple_previsto": r.get("valor_previsto"), "ple_recebido": pg,
            "ple_data": r.get("data"), "conferido_banco": bool(r.get("conferido_banco")),
            "paga": pg is not None,
        })
    return linhas


def _agrupar_blocos(blocos, chaves):
    """Árvore de 0..2 níveis usando as chaves de `_GRUPOS_ENTRADA`; a folha traz
    `blocos` (apólices) já ordenados por cliente."""
    if not chaves:
        ordenados = sorted(blocos, key=lambda b: repo._sem_acento_minusculo(b["cliente_nome"]))
        return {"campo": None, "blocos": ordenados}
    campo_rotulo, fn = _GRUPOS_ENTRADA[chaves[0]]
    baldes = {}
    for b in blocos:
        baldes.setdefault(fn(b), []).append(b)
    grupos = [{"rotulo": chave[1], "sub": _agrupar_blocos(baldes[chave], chaves[1:])}
              for chave in sorted(baldes)]
    return {"campo": campo_rotulo, "grupos": grupos}


def _blocos_entrada(apolices, chaves, situacao):
    """`apolices` = repo.comissoes_repasses_por_apolice(...). Casa as duas
    tabelas, aplica o filtro de situação ('quais apólices aparecem') e agrupa.
    Devolve `(arvore, qtd_de_blocos)`."""
    blocos = []
    for ap in apolices:
        linhas = _merge_linhas_bloco(ap["comissoes"], ap["repasses"])
        if situacao == "paga" and not any(l["paga"] for l in linhas):
            continue
        if situacao == "nao_paga" and not any(not l["paga"] for l in linhas):
            continue
        primeira_data = next((l["seg_data"] or l["ple_data"] for l in linhas
                              if l["seg_data"] or l["ple_data"]), None)
        mes_key, mes_rotulo = _rotulo_mes_iso(primeira_data)
        # soma das colunas de entrada REAL do bloco (Seguralta = Recebido; Plenus = Pago).
        # O JS re-soma ao vivo.
        soma_seguralta = round(sum(l["seg_recebido"] or 0 for l in linhas), 2)
        soma_plenus = round(sum(l["ple_recebido"] or 0 for l in linhas), 2)
        prem, pct = ap.get("premio_liquido"), ap.get("comissao_percentual")
        comissao_valor = round(prem * pct / 100, 2) if prem is not None and pct is not None else None
        # Rateio calculado pelo sistema (mesma regra do Panorama, ver _calc_panorama):
        # Plenus fica sempre com 75% da comissão cheia; sem cocorretagem a Seguralta
        # recebe a comissão inteira, com cocorretagem recebe só 25%.
        if comissao_valor is None:
            comissao_seguralta = comissao_plenus = None
        else:
            comissao_plenus = round(comissao_valor * 0.75, 2)
            comissao_seguralta = (round(comissao_valor * 0.25, 2)
                                  if ap.get("comissao_cocorretagem") else comissao_valor)
        blocos.append({
            "apolice_id": ap["apolice_id"],
            "cliente_nome": ap.get("cliente_nome") or "Sem cliente",
            "numero_apolice": ap.get("numero_apolice"),
            "seguradora_nome": ap.get("seguradora_nome"),
            "tipo_seguro_nome": ap.get("tipo_seguro_nome"),
            "premio_liquido": prem,
            "comissao_percentual": pct,
            "comissao_valor": comissao_valor,
            "comissao_seguralta": comissao_seguralta,
            "comissao_plenus": comissao_plenus,
            "soma_seguralta": soma_seguralta,
            "soma_plenus": soma_plenus,
            "comissao_parcelada": bool(ap.get("comissao_parcelada")),
            "cocorretagem": bool(ap.get("comissao_cocorretagem")),
            "is_endosso": bool(ap.get("is_endosso")),
            "endosso_id": ap.get("endosso_id"),
            "endosso_numero": ap.get("endosso_numero"),
            "is_consorcio": bool(ap.get("is_consorcio")),
            "consorcio_id": ap.get("consorcio_id"),
            "consorcio_grupo": ap.get("consorcio_grupo") or ap.get("numero_grupo"),
            "linhas": linhas, "mes_key": mes_key, "mes_rotulo": mes_rotulo,
        })
    return _agrupar_blocos(blocos, chaves), len(blocos)


@app.route("/financeiro/entradas/<int:apolice_id>/comissoes", methods=["POST"])
def entradas_salvar_apolice(apolice_id):
    """Salva SÓ a comissão de uma apólice, a partir do bloco editável de Entradas."""
    if request.form.get("comissao_parcelada") == "1":
        comissoes, erros_c = preparar_comissoes(
            request.form.getlist("comissao_parcela"),
            request.form.getlist("comissao_previsto"),
            request.form.getlist("comissao_recebido"),
            request.form.getlist("comissao_data"))
        repasses, erros_r = preparar_repasses(
            request.form.getlist("repasse_parcela"),
            request.form.getlist("repasse_previsto"),
            request.form.getlist("repasse_recebido"),
            request.form.getlist("repasse_data"),
            request.form.getlist("repasse_conferido"))
        erros = erros_c + erros_r
        if erros:
            for e in erros:
                flash(e, "erro")
        else:
            repo.salvar_comissoes_repasses(apolice_id, comissoes, repasses)
            flash("Comissão da apólice atualizada.", "ok")
    else:
        valores = {
            "comissao_valor_seguralta_receber":
                para_decimal(request.form.get("comissao_valor_seguralta_receber")),
            "comissao_valor_seguralta_recebido":
                para_decimal(request.form.get("comissao_valor_seguralta_recebido")),
            "comissao_valor_plenus_receber":
                para_decimal(request.form.get("comissao_valor_plenus_receber")),
            "comissao_valor_plenus_recebido":
                para_decimal(request.form.get("comissao_valor_plenus_recebido")),
            "data_seguralta_recebido": (request.form.get("data_seguralta_recebido") or "").strip(),
            "data_plenus_recebido": (request.form.get("data_plenus_recebido") or "").strip(),
            "plenus_conferido_banco": request.form.get("plenus_conferido_banco"),
        }
        repo.salvar_comissao_unica(apolice_id, valores)
        flash("Comissão da apólice atualizada.", "ok")
    return _voltar_seguro()


@app.route("/financeiro/entradas/endosso/<int:endosso_id>/comissoes", methods=["POST"])
def entradas_salvar_endosso(endosso_id):
    """Salva a comissão de um endosso, a partir do bloco editável de Entradas."""
    if request.form.get("comissao_parcelada") == "1":
        comissoes, erros_c = preparar_comissoes(
            request.form.getlist("comissao_parcela"),
            request.form.getlist("comissao_previsto"),
            request.form.getlist("comissao_recebido"),
            request.form.getlist("comissao_data"))
        repasses, erros_r = preparar_repasses(
            request.form.getlist("repasse_parcela"),
            request.form.getlist("repasse_previsto"),
            request.form.getlist("repasse_recebido"),
            request.form.getlist("repasse_data"),
            request.form.getlist("repasse_conferido"))
        erros = erros_c + erros_r
        if erros:
            for e in erros:
                flash(e, "erro")
        else:
            repo.salvar_comissoes_repasses_endosso(endosso_id, comissoes, repasses)
            flash("Comissão do endosso atualizada.", "ok")
        return _voltar_seguro()
    valores = {
        "comissao_valor_seguralta_receber":
            para_decimal(request.form.get("comissao_valor_seguralta_receber")),
        "comissao_valor_seguralta_recebido":
            para_decimal(request.form.get("comissao_valor_seguralta_recebido")),
        "comissao_valor_plenus_receber":
            para_decimal(request.form.get("comissao_valor_plenus_receber")),
        "comissao_valor_plenus_recebido":
            para_decimal(request.form.get("comissao_valor_plenus_recebido")),
        "data_seguralta_recebido": (request.form.get("data_seguralta_recebido") or "").strip(),
        "data_plenus_recebido": (request.form.get("data_plenus_recebido") or "").strip(),
        "plenus_conferido_banco": request.form.get("plenus_conferido_banco"),
    }
    repo.salvar_comissao_endosso(endosso_id, valores)
    flash("Comissão do endosso atualizada.", "ok")
    return _voltar_seguro()


@app.route("/financeiro/entradas/consorcio/<int:consorcio_id>/comissoes", methods=["POST"])
def entradas_salvar_consorcio(consorcio_id):
    """Salva a comissão de um consórcio, a partir do bloco editável de Entradas."""
    if request.form.get("comissao_parcelada") == "1":
        comissoes, erros_c = preparar_comissoes(
            request.form.getlist("comissao_parcela"),
            request.form.getlist("comissao_previsto"),
            request.form.getlist("comissao_recebido"),
            request.form.getlist("comissao_data"))
        repasses, erros_r = preparar_repasses(
            request.form.getlist("repasse_parcela"),
            request.form.getlist("repasse_previsto"),
            request.form.getlist("repasse_recebido"),
            request.form.getlist("repasse_data"),
            request.form.getlist("repasse_conferido"))
        erros = erros_c + erros_r
        if erros:
            for e in erros:
                flash(e, "erro")
        else:
            repo.salvar_comissoes_repasses_consorcio(consorcio_id, comissoes, repasses)
            flash("Comissão do consórcio atualizada.", "ok")
        return _voltar_seguro()
    valores = {
        "comissao_valor_seguralta_receber":
            para_decimal(request.form.get("comissao_valor_seguralta_receber")),
        "comissao_valor_seguralta_recebido":
            para_decimal(request.form.get("comissao_valor_seguralta_recebido")),
        "comissao_valor_plenus_receber":
            para_decimal(request.form.get("comissao_valor_plenus_receber")),
        "comissao_valor_plenus_recebido":
            para_decimal(request.form.get("comissao_valor_plenus_recebido")),
        "data_seguralta_recebido": (request.form.get("data_seguralta_recebido") or "").strip(),
        "data_plenus_recebido": (request.form.get("data_plenus_recebido") or "").strip(),
        "plenus_conferido_banco": request.form.get("plenus_conferido_banco"),
    }
    repo.salvar_comissao_consorcio(consorcio_id, valores)
    flash("Comissão do consórcio atualizada.", "ok")
    return _voltar_seguro()


@app.route("/financeiro/relatorios")
def fluxo_relatorios_raiz():
    return redirect(url_for("fluxo_relatorios", slug="saidas"))


def _relatorio_contexto(slug, limpar_url=None):
    """Lê a querystring, aplica filtros/agrupamento e devolve TODO o contexto do
    relatório (usado pela tela HTML e pelo PDF). `None` se o slug for inválido.
    `limpar_url`: destino do botão "Limpar" (permite a mesma tela sob outra rota)."""
    tipo = slug if slug in ("saidas", "entradas") else None
    if tipo is None:
        return None

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
    modo = request.args.get("modo", "completo")
    if modo not in ("completo", "resumo", "grupos"):  # "grupos" só vale p/ entradas
        modo = "completo"
    situacao = request.args.get("situacao", "")   # entradas: "" | "paga" | "nao_paga"
    if situacao not in ("paga", "nao_paga"):
        situacao = ""

    linhas, arvore, resumo = [], None, None
    if tipo == "entradas":
        # agrupamento próprio (tipo de seguro / seguradora / mês); sem agrupar por padrão
        validos_e = set(_GRUPOS_ENTRADA)
        g1 = request.args.get("g1", "")
        g1 = g1 if g1 in validos_e else ""
        g2 = request.args.get("g2", "")
        g2 = g2 if (g2 in validos_e and g2 != g1) else ""
        linhas = repo.listar_entradas_repasse(data_ini=data_ini or None,
                                              data_fim=data_fim or None)
        _preparar_entradas(linhas)
        if situacao == "paga":
            linhas = [l for l in linhas if l["paga"]]
        elif situacao == "nao_paga":
            linhas = [l for l in linhas if not l["paga"]]
        linhas.sort(key=lambda l: (l.get("data") or "9999-99-99",
                                   repo._sem_acento_minusculo(l.get("cliente_nome") or "")))
        divs = repo.repasse_vs_relatorio_plenus()
        arvore = _agrupar_entradas(linhas, [c for c in (g1, g2) if c], divs)
        ids_apol = {l["apolice_id"] for l in linhas}
        tot = _totais_entrada(linhas)
        resumo = {
            **tot, "qtd_apolices": len(ids_apol),
            "qtd_paga": sum(1 for l in linhas if l["paga"]),
            "qtd_aberto": sum(1 for l in linhas if not l["paga"]),
            "qtd_diverg": sum(1 for a in ids_apol if _divergencia_repasse(a, divs)),
        }
    elif tipo == "saidas":
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

    if tipo == "entradas":
        tem_filtro = bool(data_ini or data_fim or situacao or g1 or g2
                          or modo in ("resumo", "grupos"))
    else:
        tem_filtro = bool(status or categoria_id or forma_id or fixo or busca
                          or data_ini or data_fim or g1 or base_data)
    titulo = "Fluxo de caixa — Relatório de " + ("saídas" if tipo == "saidas" else "entradas")
    cat_nome = next((c["nome"] for c in repo.categorias_saida() if c["id"] == categoria_id), None)
    forma_nome = next((f["nome"] for f in repo.listar_simples("forma_pagamento")
                       if f["id"] == forma_id), None)
    agora = datetime.now()
    return dict(
        tipo=tipo, titulo=titulo,
        emissao_data=agora.strftime("%d/%m/%Y"), emissao_hora=agora.strftime("%H:%M"),
        data_ini=data_ini, data_fim=data_fim, base_data=base_data, status=status,
        categoria_id=categoria_id, forma_id=forma_id, fixo=fixo, busca=busca,
        categoria_nome=cat_nome, forma_nome=forma_nome,
        g1=g1, g2=g2, ordem=ordem, ordem_dir=ordem_dir, modo=modo, tem_filtro=tem_filtro,
        situacao=situacao, grupo_opcoes_entrada=_GRUPO_OPCOES_ENTRADA,
        limpar_url=limpar_url or url_for("fluxo_relatorios", slug=tipo),
        linhas=linhas, arvore=arvore, resumo=resumo, presets=presets)


@app.route("/financeiro/relatorios/<slug>")
def fluxo_relatorios(slug):
    # a escolha saídas × entradas vem do MENU (URL), não mais de um filtro na tela
    ctx = _relatorio_contexto(slug)
    if ctx is None:
        return redirect(url_for("fluxo_relatorios", slug="saidas"))
    return render_template(
        "relatorios.html", ativo="fluxo_relatorios", **ctx,
        categorias=repo.categorias_saida(), formas=repo.listar_simples("forma_pagamento"),
        descricoes=repo.descricoes_saida(), grupo_opcoes=_GRUPO_OPCOES,
        ordem_opcoes=_ORDEM_OPCOES, MESES=_MESES)


@app.route("/financeiro/relatorios/<slug>/pdf")
def fluxo_relatorios_pdf(slug):
    ctx = _relatorio_contexto(slug)
    if ctx is None:
        abort(404)
    import relatorio_pdf
    pdf = relatorio_pdf.gerar(ctx)
    nome = f"relatorio-{ctx['tipo']}-{date.today().isoformat()}.pdf"
    return Response(pdf, mimetype="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{nome}"'})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
