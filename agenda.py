"""Integração com o Google Agenda (Calendar) para os avisos de vencimento.

Em vez de mandar uma mensagem em cada marco, cria UM evento na data do vencimento e deixa
os lembretes automáticos do Google avisarem (ex.: 10 dias e 1 dia antes). Se a data mudar,
o evento é atualizado; se a apólice/parcela sair da situação de aviso (venceu, foi paga,
apólice apagada), o evento é removido.

Autenticação: **conta de serviço** do Google Cloud (arquivo JSON). Passos no DEPLOY.md.
As libs do Google são importadas só quando o Agenda está ativo.

`sincronizar_evento(cfg, chave, titulo, descricao, data_iso, lembretes_dias)` e
`remover_evento(cfg, chave)` — o `chave` é 'vigencia:<apolice_id>' ou 'boleto:<parcela_id>'.
O mapa chave -> event_id fica na tabela `evento_agenda`.
"""

import os

import repo
from notificacoes import _log

_RAIZ = os.path.dirname(os.path.abspath(__file__))
_ESCOPOS = ["https://www.googleapis.com/auth/calendar.events"]


def agenda_ativa(cfg):
    g = cfg.get("google_agenda", {})
    return bool(g.get("ativo") and g.get("calendar_id") and g.get("conta_servico_json"))


def _servico(cfg):
    g = cfg["google_agenda"]
    caminho = g["conta_servico_json"]
    if not os.path.isabs(caminho):
        caminho = os.path.join(_RAIZ, caminho)
    if not os.path.exists(caminho):
        raise FileNotFoundError(f"conta_servico_json não encontrado: {caminho}")
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    cred = service_account.Credentials.from_service_account_file(caminho, scopes=_ESCOPOS)
    return build("calendar", "v3", credentials=cred, cache_discovery=False)


def _corpo_evento(titulo, descricao, data_iso, lembretes_dias):
    return {
        "summary": titulo,
        "description": descricao,
        "start": {"date": data_iso},
        "end": {"date": data_iso},
        "reminders": {
            "useDefault": False,
            # o Google aceita no máx. 5 overrides por evento
            "overrides": [
                {"method": m, "minutes": int(d) * 24 * 60}
                for d in sorted({int(x) for x in (lembretes_dias or [10, 1])}, reverse=True)
                for m in ("popup", "email")
            ][:5],
        },
    }


def sincronizar_evento(cfg, chave, titulo, descricao, data_iso, lembretes_dias, seco=False):
    """Cria ou atualiza o evento. Devolve (ok, detalhe)."""
    if not agenda_ativa(cfg):
        _log(f"[AGENDA SIMULADO] {chave}: {titulo} em {data_iso}")
        return True, "simulado (google_agenda.ativo = false)"
    if seco:
        return True, f"[SECO] sincronizaria {chave} em {data_iso}"
    try:
        svc = _servico(cfg)
        cal = cfg["google_agenda"]["calendar_id"]
        corpo = _corpo_evento(titulo, descricao, data_iso, lembretes_dias)
        reg = repo.evento_agenda_obter(chave)
        if reg and reg.get("event_id"):
            svc.events().patch(calendarId=cal, eventId=reg["event_id"], body=corpo).execute()
            repo.evento_agenda_salvar(chave, reg["event_id"], data_iso, titulo)
            return True, f"evento atualizado ({data_iso})"
        ev = svc.events().insert(calendarId=cal, body=corpo).execute()
        repo.evento_agenda_salvar(chave, ev["id"], data_iso, titulo)
        return True, f"evento criado ({data_iso})"
    except Exception as e:  # noqa: BLE001
        return False, f"falha no Agenda: {e}"


def remover_evento(cfg, chave, seco=False):
    reg = repo.evento_agenda_obter(chave)
    if not reg:
        return True, "sem evento"
    if not agenda_ativa(cfg) or seco:
        return True, "simulado/seco"
    try:
        svc = _servico(cfg)
        cal = cfg["google_agenda"]["calendar_id"]
        try:
            svc.events().delete(calendarId=cal, eventId=reg["event_id"]).execute()
        except Exception:  # noqa: BLE001  (evento já pode não existir)
            pass
        repo.evento_agenda_remover(chave)
        return True, "evento removido"
    except Exception as e:  # noqa: BLE001
        return False, f"falha ao remover no Agenda: {e}"
