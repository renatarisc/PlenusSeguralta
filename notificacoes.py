"""Envio de aviso de vencimento de apólice por WhatsApp.

Ponto único de integração: `enviar_whatsapp(numero, texto)`. O provedor real ainda não foi
escolhido, então o padrão é "simulado" (só grava em notificacoes.log e no banco). Quando
decidir, preencha `plenus_config.json` (veja plenus_config.exemplo.json) com provedor
"zapi" / "cloud" / "twilio" e as credenciais.
"""

import json
import os
from datetime import datetime

_RAIZ = os.path.dirname(os.path.abspath(__file__))
_CONFIG_PATH = os.path.join(_RAIZ, "plenus_config.json")
_LOG_PATH = os.path.join(_RAIZ, "notificacoes.log")

_PADRAO = {
    "marcos_dias": [10, 5, 1],
    "whatsapp": {"provedor": "simulado", "destino": "", "zapi": {}, "cloud": {}, "twilio": {}},
}


def carregar_config():
    cfg = json.loads(json.dumps(_PADRAO))  # cópia
    if os.path.exists(_CONFIG_PATH):
        try:
            with open(_CONFIG_PATH, encoding="utf-8") as f:
                usuario = json.load(f)
            cfg.update({k: v for k, v in usuario.items() if not k.startswith("_")})
            cfg["whatsapp"] = {**_PADRAO["whatsapp"], **usuario.get("whatsapp", {})}
        except (json.JSONDecodeError, OSError) as e:
            _log(f"AVISO: não consegui ler plenus_config.json ({e}); usando padrão simulado")
    return cfg


def _log(msg):
    linha = f"{datetime.now():%Y-%m-%d %H:%M:%S}  {msg}"
    try:
        with open(_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(linha + "\n")
    except OSError:
        pass
    print(linha)


def _so_digitos(s):
    return "".join(c for c in str(s or "") if c.isdigit())


def enviar_whatsapp(numero, texto, cfg=None):
    """Devolve (ok: bool, detalhe: str). Nunca levanta exceção — erro vira (False, motivo)."""
    cfg = cfg or carregar_config()
    wa = cfg.get("whatsapp", {})
    provedor = (wa.get("provedor") or "simulado").lower()
    numero = _so_digitos(numero)
    if not numero:
        return False, "sem número de destino"

    try:
        if provedor == "simulado":
            _log(f"[SIMULADO] -> {numero}\n{texto}\n{'-' * 40}")
            return True, "simulado (nada enviado de verdade)"
        if provedor == "zapi":
            return _enviar_zapi(numero, texto, wa.get("zapi", {}))
        if provedor == "cloud":
            return _enviar_cloud(numero, texto, wa.get("cloud", {}))
        if provedor == "twilio":
            return _enviar_twilio(numero, texto, wa.get("twilio", {}))
        return False, f"provedor desconhecido: {provedor}"
    except Exception as e:  # noqa: BLE001
        return False, f"falha no envio ({provedor}): {e}"


# ---- provedores (preenchidos quando houver credenciais) ----

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
    # mensagem iniciada pela empresa exige TEMPLATE aprovado
    if c.get("template"):
        payload = {
            "messaging_product": "whatsapp", "to": numero, "type": "template",
            "template": {"name": c["template"], "language": {"code": c.get("idioma", "pt_BR")}},
        }
    else:
        payload = {"messaging_product": "whatsapp", "to": numero, "type": "text",
                   "text": {"body": texto}}
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


# ---- montagem da mensagem ----

def montar_texto_vencimento(ap, dias):
    quando = "vence HOJE" if dias == 0 else f"vence em {dias} dia" + ("s" if dias != 1 else "")
    linhas = [
        "*Plenus — aviso de vencimento de apólice*",
        "",
        f"Apólice: {ap.get('numero_apolice') or '(sem número)'} {quando}.",
        f"Cliente: {ap.get('cliente_nome') or '—'}",
        f"Seguradora: {ap.get('seguradora_nome') or '—'}",
        f"Tipo: {ap.get('tipo_seguro_nome') or '—'}",
        f"Vigência: {ap.get('vigencia_inicio') or '?'} a {ap.get('vigencia_fim') or '?'}",
    ]
    return "\n".join(linhas)
