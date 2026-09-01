"""Avisos de vencimento — por E-MAIL e Google Agenda (e ainda WhatsApp, se configurado).

Config em `plenus_config.json` (fora do git; modelo em plenus_config.exemplo.json):
- `email`:  {ativo, smtp_host, smtp_port, usuario, senha, de, para:[...]}  → e-mail nos marcos
- `google_agenda`: {ativo, calendar_id, conta_servico_json, lembretes_dias:[...]}  → cria
  um evento na data do vencimento e o Google lembra sozinho (ver agenda.py)
- `whatsapp`: mantido, opcional

Cada função de envio devolve (ok: bool, detalhe: str) e nunca levanta exceção.
"""

import json
import os
from datetime import datetime

_RAIZ = os.path.dirname(os.path.abspath(__file__))
_CONFIG_PATH = os.path.join(_RAIZ, "plenus_config.json")
_LOG_PATH = os.path.join(_RAIZ, "notificacoes.log")

_PADRAO = {
    "marcos_dias": [10, 5, 1],          # e-mail antes do fim da vigência
    "marcos_dias_boleto": [10, 1],      # e-mail antes do vencimento da parcela de boleto
    "email": {"ativo": False, "smtp_host": "smtp.gmail.com", "smtp_port": 587,
              "usuario": "", "senha": "", "de": "", "para": []},
    "google_agenda": {"ativo": False, "calendar_id": "", "conta_servico_json": "",
                      "lembretes_dias": [10, 1]},
    "whatsapp": {"provedor": "simulado", "destino": "", "zapi": {}, "cloud": {}, "twilio": {}},
}


def carregar_config():
    cfg = json.loads(json.dumps(_PADRAO))  # cópia profunda
    if os.path.exists(_CONFIG_PATH):
        try:
            with open(_CONFIG_PATH, encoding="utf-8") as f:
                usuario = json.load(f)
            for k, v in usuario.items():
                if k.startswith("_"):
                    continue
                if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                    cfg[k] = {**cfg[k], **v}
                else:
                    cfg[k] = v
        except (json.JSONDecodeError, OSError) as e:
            _log(f"AVISO: não consegui ler plenus_config.json ({e}); usando padrões")
    return cfg


def canais_ativos(cfg):
    canais = []
    if cfg.get("email", {}).get("ativo"):
        canais.append("email")
    if (cfg.get("whatsapp", {}).get("provedor") or "simulado") != "simulado" \
            and cfg.get("whatsapp", {}).get("destino"):
        canais.append("whatsapp")
    if not canais:
        canais.append("email")  # cai no modo simulado de e-mail (só loga)
    return canais


def _log(msg):
    linha = f"{datetime.now():%Y-%m-%d %H:%M:%S}  {msg}"
    try:
        with open(_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(linha + "\n")
    except OSError:
        pass
    print(linha)


# ---------------------------------------------------------------- E-MAIL

def enviar_email(assunto, corpo, cfg=None):
    cfg = cfg or carregar_config()
    e = cfg.get("email", {})
    if not e.get("ativo"):
        _log(f"[EMAIL SIMULADO] {assunto}\n{corpo}\n{'-' * 40}")
        return True, "simulado (email.ativo = false)"

    host = e.get("smtp_host")
    porta = int(e.get("smtp_port") or 587)
    usuario = e.get("usuario")
    senha = e.get("senha")
    de = e.get("de") or usuario
    para = e.get("para") or []
    if isinstance(para, str):
        para = [para]
    if not (host and usuario and senha and para):
        return False, "email: smtp_host/usuario/senha/para não configurados"

    try:
        import smtplib
        from email.message import EmailMessage

        msg = EmailMessage()
        msg["Subject"] = assunto
        msg["From"] = de
        msg["To"] = ", ".join(para)
        msg.set_content(corpo)

        if porta == 465:
            with smtplib.SMTP_SSL(host, porta, timeout=30) as s:
                s.login(usuario, senha)
                s.send_message(msg)
        else:
            with smtplib.SMTP(host, porta, timeout=30) as s:
                s.starttls()
                s.login(usuario, senha)
                s.send_message(msg)
        return True, f"e-mail enviado para {', '.join(para)}"
    except Exception as ex:  # noqa: BLE001
        return False, f"falha no e-mail: {ex}"


# ---------------------------------------------------------------- WhatsApp (opcional)

def _so_digitos(s):
    return "".join(c for c in str(s or "") if c.isdigit())


def enviar_whatsapp(numero, texto, cfg=None):
    cfg = cfg or carregar_config()
    wa = cfg.get("whatsapp", {})
    provedor = (wa.get("provedor") or "simulado").lower()
    numero = _so_digitos(numero)
    if not numero:
        return False, "sem número de destino"
    try:
        if provedor == "simulado":
            _log(f"[WHATSAPP SIMULADO] -> {numero}\n{texto}\n{'-' * 40}")
            return True, "simulado"
        if provedor == "zapi":
            return _enviar_zapi(numero, texto, wa.get("zapi", {}))
        if provedor == "cloud":
            return _enviar_cloud(numero, texto, wa.get("cloud", {}))
        if provedor == "twilio":
            return _enviar_twilio(numero, texto, wa.get("twilio", {}))
        return False, f"provedor desconhecido: {provedor}"
    except Exception as e:  # noqa: BLE001
        return False, f"falha no envio ({provedor}): {e}"


def _enviar_zapi(numero, texto, c):
    import requests
    base = (c.get("base_url") or "").rstrip("/")
    if not base:
        return False, "zapi.base_url não configurado"
    headers = {"Content-Type": "application/json"}
    if c.get("client_token"):
        headers["Client-Token"] = c["client_token"]
    r = requests.post(f"{base}/send-text", json={"phone": numero, "message": texto},
                      headers=headers, timeout=30)
    return (r.ok, f"HTTP {r.status_code} {r.text[:200]}")


def _enviar_cloud(numero, texto, c):
    import requests
    pnid, token = c.get("phone_number_id"), c.get("token")
    if not (pnid and token):
        return False, "cloud.phone_number_id/token não configurados"
    if c.get("template"):
        payload = {"messaging_product": "whatsapp", "to": numero, "type": "template",
                   "template": {"name": c["template"], "language": {"code": c.get("idioma", "pt_BR")}}}
    else:
        payload = {"messaging_product": "whatsapp", "to": numero, "type": "text", "text": {"body": texto}}
    r = requests.post(f"https://graph.facebook.com/v20.0/{pnid}/messages", json=payload,
                      headers={"Authorization": f"Bearer {token}"}, timeout=30)
    return (r.ok, f"HTTP {r.status_code} {r.text[:200]}")


def _enviar_twilio(numero, texto, c):
    import requests
    sid, token, de = c.get("account_sid"), c.get("auth_token"), c.get("from")
    if not (sid and token and de):
        return False, "twilio.account_sid/auth_token/from não configurados"
    r = requests.post(
        f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
        data={"From": de, "To": f"whatsapp:+{numero}", "Body": texto},
        auth=(sid, token), timeout=30)
    return (r.ok, f"HTTP {r.status_code} {r.text[:200]}")


# ---------------------------------------------------------------- textos

def _data_br(iso):
    s = (iso or "")[:10]
    return f"{s[8:10]}/{s[5:7]}/{s[0:4]}" if len(s) == 10 else (s or "?")


def _moeda(v):
    if v is None:
        return "—"
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _quando(dias):
    if dias == 0:
        return "vence HOJE"
    return f"vence em {dias} dia" + ("s" if dias != 1 else "")


_RODAPE_DIARIO = ("\n\nEste aviso se repete todos os dias até você abrir a apólice no Plenus "
                  "e marcar \"cliente avisado\".")


def texto_vencimento(ap, dias):
    """Devolve (assunto, corpo) do aviso de fim de vigência."""
    num = ap.get("numero_apolice") or "(sem número)"
    assunto = f"[Plenus] Apólice {num} {_quando(dias)} — avisar o cliente"
    corpo = "\n".join([
        f"A apólice {num} {_quando(dias)} ({_data_br(ap.get('vigencia_fim'))}).",
        "",
        f"Cliente: {ap.get('cliente_nome') or '—'}",
        f"Seguradora: {ap.get('seguradora_nome') or '—'}",
        f"Tipo de seguro: {ap.get('tipo_seguro_nome') or '—'}",
        f"Vigência: {_data_br(ap.get('vigencia_inicio'))} a {_data_br(ap.get('vigencia_fim'))}",
    ]) + _RODAPE_DIARIO
    return assunto, corpo


def texto_boleto(p, dias):
    """Devolve (assunto, corpo) do aviso de parcela de boleto."""
    num = p.get("numero_apolice") or "(sem número)"
    ident = p.get("identificacao") or "?"
    assunto = f"[Plenus] Boleto {ident} da apólice {num} {_quando(dias)} — avisar o cliente"
    corpo = "\n".join([
        f"Parcela {ident} da apólice {num} {_quando(dias)} ({_data_br(p.get('data'))}).",
        f"Valor: {_moeda(p.get('valor'))}",
        "",
        f"Cliente: {p.get('cliente_nome') or '—'}",
        f"Seguradora: {p.get('seguradora_nome') or '—'}",
    ]) + _RODAPE_DIARIO
    return assunto, corpo


# compatibilidade com chamadas antigas (WhatsApp usa só o corpo)
def montar_texto_vencimento(ap, dias):
    return texto_vencimento(ap, dias)[1]


def montar_texto_boleto(p, dias):
    return texto_boleto(p, dias)[1]
