"""Verifica apólices perto do fim da vigência e dispara aviso no WhatsApp.

Feito pra rodar 1x por dia pela Tarefa Agendada do Windows:

    "C:\\Users\\renat\\PycharmProjects\\plenus_seguralta\\venv\\Scripts\\python.exe" ^
        "C:\\Users\\renat\\PycharmProjects\\plenus_seguralta\\verificar_vencimentos.py"

Para cada apólice com vigência a vencer, dispara UMA vez por marco (10, 5 e 1 dia por
padrão — configurável em plenus_config.json). O que já foi enviado fica em
notificacao_vencimento, então rodar de novo no mesmo dia não repete.

Flags:
    --forcar     ignora o registro de já-enviado (reenvia)
    --seco       não envia nada, só mostra o que faria
"""

import sys

import db
import repo
from validacao import dias_ate_data
from notificacoes import carregar_config, enviar_whatsapp, montar_texto_vencimento


def main(argv):
    forcar = "--forcar" in argv
    seco = "--seco" in argv

    db.inicializar_db()
    cfg = carregar_config()
    marcos = sorted({int(m) for m in cfg.get("marcos_dias", [10, 5, 1])})  # do mais urgente ao menos
    wa = cfg.get("whatsapp", {})
    destino = wa.get("destino", "")
    provedor = wa.get("provedor", "simulado")

    print(f"Provedor: {provedor} | destino: {destino or '(não configurado)'} | marcos: {marcos}")
    if not destino:
        print("!! Sem 'whatsapp.destino' no plenus_config.json — nada será enviado.")
        if not seco:
            return 1

    enviados = pulados = 0
    for ap in repo.listar_apolices():
        fim = ap.get("vigencia_fim")
        d = dias_ate_data(fim)
        if d is None or d < 0:
            continue
        # o marco relevante é o menor cujo limite ainda cobre os dias restantes
        marco = next((m for m in marcos if d <= m), None)
        if marco is None:
            continue
        if not forcar and repo.notificacao_ja_enviada(ap["id"], marco, fim):
            pulados += 1
            continue

        rotulo = f"apólice {ap.get('numero_apolice') or ap['id']} (faltam {d}d, marco {marco})"
        if seco:
            print(f"  [SECO] enviaria -> {destino}: {rotulo}")
            enviados += 1
            continue
        ok, detalhe = enviar_whatsapp(destino, montar_texto_vencimento(ap, d), cfg)
        repo.registrar_notificacao(ap["id"], marco, fim, provedor, destino,
                                   ("OK: " if ok else "ERRO: ") + detalhe)
        print(f"  {'OK  ' if ok else 'ERRO'} {rotulo} -> {detalhe}")
        enviados += 1

    print(f"Concluído: {enviados} enviado(s), {pulados} já enviado(s) antes.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
