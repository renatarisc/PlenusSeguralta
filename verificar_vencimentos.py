"""Avisos de vencimento — por E-MAIL (diário) e Google Agenda (evento com lembretes).

Rodar 1x por dia (Tarefa Agendada do Windows / cron no VPS):

    venv\\Scripts\\python.exe verificar_vencimentos.py

O que faz:
- **E-mail**: manda um e-mail TODO DIA enquanto o vencimento estiver dentro da janela de
  antecedência (`max(marcos_dias)` p/ a vigência da apólice, `max(marcos_dias_boleto)` p/ a
  parcela de boleto) E o usuário ainda NÃO marcou no sistema que o cliente foi avisado
  (`aviso_vigencia_ok` na apólice / `aviso_ok` na parcela) E, no boleto, a parcela não
  está paga. Para de enviar `dias_max_aviso_apos_vencer` dias depois de vencer (padrão 45).
- **Google Agenda**: cria/atualiza UM evento por apólice (data = fim da vigência) e por
  parcela de boleto não paga (data = vencimento), com lembretes automáticos
  (`lembretes_dias`). Remove o evento quando a apólice vence/some ou o boleto é pago.

Enquanto `email.ativo` e `google_agenda.ativo` forem false, nada sai de verdade — só
grava em notificacoes.log.

Flags:  --forcar (envia de novo mesmo se já mandou hoje)   --seco (não faz nada, só mostra)
"""

import sys

import agenda
import db
import repo
from validacao import dias_ate_data
from notificacoes import (
    carregar_config, enviar_email, enviar_whatsapp, texto_vencimento, texto_boleto,
)


def _enviar_canais(cfg, assunto, corpo):
    """Manda pelo(s) canal(is) ativo(s). Devolve (ok, detalhe)."""
    ok, det = enviar_email(assunto, corpo, cfg)
    partes = [f"email={det}"]
    wa = cfg.get("whatsapp", {})
    if (wa.get("provedor") or "simulado") != "simulado" and wa.get("destino"):
        _, detw = enviar_whatsapp(wa["destino"], f"{assunto}\n\n{corpo}", cfg)
        partes.append(f"whatsapp={detw}")
    return ok, " | ".join(partes)


def _passo_email(cfg, forcar, seco):
    """E-mail DIÁRIO enquanto: dentro da janela de antecedência, o 'cliente avisado' não
    foi marcado no sistema, e (boleto) a parcela não está paga. Para de enviar `cap` dias
    depois de vencer, pra não spammar apólice velha nunca renovada."""
    janela_vig = max([int(m) for m in cfg.get("marcos_dias", [10, 5, 1])] or [10])
    janela_bol = max([int(m) for m in cfg.get("marcos_dias_boleto", [10, 1])] or [10])
    cap = int(cfg.get("dias_max_aviso_apos_vencer", 45))
    enviados = pulados = 0

    for ap in repo.listar_apolices():
        if ap.get("aviso_vigencia_ok"):
            continue
        d = dias_ate_data(ap.get("vigencia_fim"))
        if d is None or d > janela_vig or d < -cap:
            continue
        if not forcar and repo.email_vigencia_enviado_hoje(ap["id"]):
            pulados += 1
            continue
        assunto, corpo = texto_vencimento(ap, d)
        rot = f"e-mail vigência {ap.get('numero_apolice') or ap['id']} ({d}d)"
        if seco:
            print(f"  [SECO] {rot}"); enviados += 1; continue
        ok, det = _enviar_canais(cfg, assunto, corpo)
        repo.registrar_notificacao(ap["id"], 0, ap["vigencia_fim"], "email",
                                   "", ("OK: " if ok else "ERRO: ") + det)
        print(f"  {'OK  ' if ok else 'ERRO'} {rot} -> {det}"); enviados += 1

    for p in repo.parcelas_boleto_pendentes():
        if p.get("aviso_ok"):
            continue
        d = dias_ate_data(p.get("data"))
        if d is None or d > janela_bol or d < -cap:
            continue
        if not forcar and repo.email_boleto_enviado_hoje(p["parcela_id"]):
            pulados += 1
            continue
        assunto, corpo = texto_boleto(p, d)
        rot = f"e-mail boleto {p.get('numero_apolice')} parc {p.get('identificacao')} ({d}d)"
        if seco:
            print(f"  [SECO] {rot}"); enviados += 1; continue
        ok, det = _enviar_canais(cfg, assunto, corpo)
        repo.registrar_notificacao_parcela(p["parcela_id"], 0, p["data"], "email",
                                           "", ("OK: " if ok else "ERRO: ") + det)
        print(f"  {'OK  ' if ok else 'ERRO'} {rot} -> {det}"); enviados += 1

    return enviados, pulados


def _passo_agenda(cfg, seco):
    lembretes = cfg.get("google_agenda", {}).get("lembretes_dias", [10, 1])
    ativos = set()

    for ap in repo.listar_apolices():
        d = dias_ate_data(ap.get("vigencia_fim"))
        if d is None or d < 0:
            continue
        chave = f"vigencia:{ap['id']}"
        ativos.add(chave)
        titulo = f"Renovar apólice {ap.get('numero_apolice') or ap['id']}"
        if ap.get("cliente_nome"):
            titulo += f" — {ap['cliente_nome']}"
        _, corpo = texto_vencimento(ap, d)
        _, det = agenda.sincronizar_evento(cfg, chave, titulo, corpo,
                                           ap["vigencia_fim"][:10], lembretes, seco)
        print(f"  agenda {chave} -> {det}")

    for p in repo.parcelas_boleto_pendentes():
        d = dias_ate_data(p.get("data"))
        if d is None or d < 0:
            continue
        chave = f"boleto:{p['parcela_id']}"
        ativos.add(chave)
        titulo = f"Boleto {p.get('identificacao') or ''} apólice {p.get('numero_apolice') or ''}".strip()
        if p.get("cliente_nome"):
            titulo += f" — {p['cliente_nome']}"
        _, corpo = texto_boleto(p, d)
        _, det = agenda.sincronizar_evento(cfg, chave, titulo, corpo,
                                           p["data"][:10], lembretes, seco)
        print(f"  agenda {chave} -> {det}")

    for reg in repo.eventos_agenda_todos():
        if reg["chave"] not in ativos:
            _, det = agenda.remover_evento(cfg, reg["chave"], seco)
            print(f"  agenda {reg['chave']} (obsoleto) -> {det}")


def main(argv):
    forcar = "--forcar" in argv
    seco = "--seco" in argv
    db.inicializar_db()
    cfg = carregar_config()

    email_ativo = cfg.get("email", {}).get("ativo")
    agenda_ativo = agenda.agenda_ativa(cfg)
    print(f"E-mail: {'ativo' if email_ativo else 'simulado'} | "
          f"Google Agenda: {'ativo' if agenda_ativo else 'simulado'}")

    enviados, pulados = _passo_email(cfg, forcar, seco)
    _passo_agenda(cfg, seco)

    print(f"Concluído: {enviados} e-mail(s) enviado(s), {pulados} já enviado(s) antes.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
