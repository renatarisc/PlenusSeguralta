"""Avisos por WhatsApp: fim da vigência da apólice + parcelas de boleto a vencer.

Feito pra rodar 1x por dia (Tarefa Agendada do Windows / cron no VPS):

    venv\\Scripts\\python.exe verificar_vencimentos.py

- **Vigência**: para cada apólice com o fim da vigência chegando, dispara UMA vez por
  marco (padrão 10/5/1 dias — `marcos_dias` no plenus_config.json). Dedup em
  notificacao_vencimento.
- **Boleto**: se a forma de pagamento da apólice for "boleto", para cada parcela com data,
  dispara UMA vez por marco (padrão 10 e 1 dia — `marcos_dias_boleto`). Dedup em
  notificacao_parcela.

Rodar de novo no mesmo dia não repete.

Flags:
    --forcar     ignora o registro de já-enviado (reenvia)
    --seco       não envia nada, só mostra o que faria
"""

import sys

import db
import repo
from validacao import dias_ate_data
from notificacoes import (
    carregar_config, enviar_whatsapp, montar_texto_vencimento, montar_texto_boleto,
)


def _marco_relevante(dias, marcos):
    """O menor marco que ainda cobre os dias restantes (marcos em ordem crescente)."""
    return next((m for m in marcos if dias <= m), None)


def main(argv):
    forcar = "--forcar" in argv
    seco = "--seco" in argv

    db.inicializar_db()
    cfg = carregar_config()
    marcos_vig = sorted({int(m) for m in cfg.get("marcos_dias", [10, 5, 1])})
    marcos_bol = sorted({int(m) for m in cfg.get("marcos_dias_boleto", [10, 1])})
    wa = cfg.get("whatsapp", {})
    destino = wa.get("destino", "")
    provedor = wa.get("provedor", "simulado")

    print(f"Provedor: {provedor} | destino: {destino or '(não configurado)'}")
    print(f"Marcos vigência: {marcos_vig} | marcos boleto: {marcos_bol}")
    if not destino and not seco:
        print("!! Sem 'whatsapp.destino' no plenus_config.json — nada será enviado.")
        return 1

    enviados = pulados = 0

    # ---- 1) fim da vigência da apólice ----
    for ap in repo.listar_apolices():
        fim = ap.get("vigencia_fim")
        d = dias_ate_data(fim)
        if d is None or d < 0:
            continue
        marco = _marco_relevante(d, marcos_vig)
        if marco is None:
            continue
        if not forcar and repo.notificacao_ja_enviada(ap["id"], marco, fim):
            pulados += 1
            continue
        rotulo = f"vigência {ap.get('numero_apolice') or ap['id']} (faltam {d}d, marco {marco})"
        if seco:
            print(f"  [SECO] {rotulo}")
            enviados += 1
            continue
        ok, detalhe = enviar_whatsapp(destino, montar_texto_vencimento(ap, d), cfg)
        repo.registrar_notificacao(ap["id"], marco, fim, provedor, destino,
                                   ("OK: " if ok else "ERRO: ") + detalhe)
        print(f"  {'OK  ' if ok else 'ERRO'} {rotulo} -> {detalhe}")
        enviados += 1

    # ---- 2) parcelas de boleto a vencer ----
    for p in repo.parcelas_boleto_pendentes():
        venc = p.get("data")
        d = dias_ate_data(venc)
        if d is None or d < 0:
            continue
        marco = _marco_relevante(d, marcos_bol)
        if marco is None:
            continue
        if not forcar and repo.notificacao_parcela_ja_enviada(p["parcela_id"], marco, venc):
            pulados += 1
            continue
        rotulo = (f"boleto {p.get('numero_apolice') or p['apolice_id']} "
                  f"parc {p.get('identificacao') or '?'} (faltam {d}d, marco {marco})")
        if seco:
            print(f"  [SECO] {rotulo}")
            enviados += 1
            continue
        ok, detalhe = enviar_whatsapp(destino, montar_texto_boleto(p, d), cfg)
        repo.registrar_notificacao_parcela(p["parcela_id"], marco, venc, provedor, destino,
                                           ("OK: " if ok else "ERRO: ") + detalhe)
        print(f"  {'OK  ' if ok else 'ERRO'} {rotulo} -> {detalhe}")
        enviados += 1

    print(f"Concluído: {enviados} enviado(s), {pulados} já enviado(s) antes.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
