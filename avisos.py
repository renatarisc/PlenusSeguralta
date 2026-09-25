"""Regras de aviso: o que aparece no painel, no contador do menu, em destaque nas listas
e no e-mail diário.

Cada tipo tem uma data base (escolhida numa lista fechada, por tipo), começa a avisar em
data_base + dias_inicio (negativo = antes) e continua até o item ser resolvido (o que
resolve é fixo por tipo) ou, se configurado, até data_base + dias_parar_apos.
As regras ficam na tabela `regra_aviso` e são editadas em Configurações › Avisos.
"""

import repo
from validacao import dias_ate_data


def _consorcio_nao_enviados():
    itens = repo.boletos_consorcio_nao_enviados()
    for b in itens:
        b["origem"] = "consorcio"
        b["parcela_id"] = b["boleto_id"]
        b["data"] = b.get("data_vencimento")
    return itens


# campos: campo_base -> (rótulo no select, forma "de + artigo" usada nas frases)
# chaves: campo_base -> chave no dict do item, quando o nome difere
# vencimento: chave usada p/ `dias_restantes` (o "vence em Nd" das telas)
TIPOS = {
    "vigencia": {
        "email": True,
        "titulo": "Vigência da apólice",
        "campos": {"vigencia_fim": ("Fim da vigência", "do fim da vigência"),
                   "vigencia_inicio": ("Início da vigência", "do início da vigência")},
        "resolvido": "você marcar “cliente avisado” na apólice",
        "tambem": "o número vermelho ao lado de “Apólices” no menu (só este aviso tem contador) "
                  "e a linha vermelha com “vence em” na lista de apólices.",
        "fonte": repo.listar_apolices,
        "pendente": lambda a: not a.get("aviso_vigencia_ok"),
        "vencimento": "vigencia_fim",
    },
    "boleto_vencer": {
        "email": True,
        "titulo": "Boletos de clientes a vencer",
        "campos": {"data_vencimento": ("Vencimento da parcela", "do vencimento da parcela")},
        "chaves": {"data_vencimento": "data"},
        "resolvido": "você marcar “cliente avisado” ou a parcela como paga",
        "fonte": repo.parcelas_boleto_pendentes,
        "pendente": lambda p: not p.get("aviso_ok"),
        "vencimento": "data",
    },
    "boleto_enviar_consorcio": {
        "email": True,
        "titulo": "Boletos a enviar — consórcio",
        "campos": {"data_emissao": ("Emissão do boleto", "da emissão do boleto"),
                   "data_vencimento": ("Vencimento do boleto", "do vencimento do boleto")},
        "resolvido": "você marcar o boleto como enviado",
        "fonte": _consorcio_nao_enviados,
        "pendente": lambda b: True,
        "vencimento": "data_vencimento",
    },
    "boleto_enviar_apolice": {
        "email": True,
        "titulo": "Boletos a enviar — apólice, endosso e serviço",
        "campos": {"data_vencimento": ("Vencimento da parcela", "do vencimento da parcela")},
        "chaves": {"data_vencimento": "data"},
        "resolvido": "você marcar a parcela como enviada",
        "fonte": lambda: [p for p in repo.parcelas_boleto_pendentes()
                          if p.get("origem") != "consorcio"],
        "pendente": lambda p: not p.get("enviado"),
        "vencimento": "data",
    },
    "conta_pagar": {
        "email": False,
        "titulo": "Contas a pagar",
        "campos": {"data_vencimento": ("Vencimento", "do vencimento")},
        "resolvido": "a saída ser marcada como paga",
        "tambem": "a etiqueta “vence em” na lista de saídas.",
        "fonte": lambda: repo.listar_saidas(status=None),
        "pendente": lambda s: s.get("status") != "pago",
        "vencimento": "data_vencimento",
    },
}


def _data_base(tipo, regra, item):
    campo = regra["campo_base"]
    return item.get(TIPOS[tipo].get("chaves", {}).get(campo, campo))


def na_janela(tipo, regra, item):
    """Só a janela de datas (não olha se já foi resolvido) — destaque de linhas nas listas."""
    if not regra or not regra.get("ativo"):
        return False
    d = dias_ate_data(_data_base(tipo, regra, item))
    if d is None:
        return bool(regra.get("avisar_sem_data"))
    if d > -regra["dias_inicio"]:
        return False
    parar = regra.get("dias_parar_apos")
    return parar is None or d >= -parar


def itens(tipo, regras=None):
    """Itens pendentes dentro da janela, da data base mais antiga pra mais nova."""
    regras = repo.regras_aviso() if regras is None else regras
    regra = regras.get(tipo)
    if not regra or not regra.get("ativo"):
        return []
    t = TIPOS[tipo]
    saida = []
    for it in t["fonte"]():
        if t["pendente"](it) and na_janela(tipo, regra, it):
            it["dias_restantes"] = dias_ate_data(it.get(t["vencimento"]))
            saida.append(it)
    saida.sort(key=lambda it: (_data_base(tipo, regra, it) or "9999")[:10])
    return saida


def contar_vigencia(regras):
    """Contador do menu (roda em toda página): consulta leve, mesma regra do painel."""
    regra = regras.get("vigencia")
    if not regra or not regra.get("ativo"):
        return 0
    pendente = TIPOS["vigencia"]["pendente"]
    return sum(1 for a in repo.apolices_datas_vigencia()
               if pendente(a) and na_janela("vigencia", regra, a))


def destinatarios_email(cfg):
    """Quem recebe o e-mail diário: a lista salva na tela Avisos; se nunca foi salva, a do
    plenus_config.json (`email.para`)."""
    salvos = repo.destinatarios_email()
    if salvos is not None:
        return salvos
    para = cfg.get("email", {}).get("para") or []
    return [para] if isinstance(para, str) else list(para)


def _dias(n):
    return f"{n} dia" + ("s" if n != 1 else "")


def descricao(tipo, regra):
    """Frase p/ as telas, ex.: 'Avisa a partir de 10 dias antes do fim da vigência, até ...'."""
    if not regra or not regra.get("ativo"):
        return "Aviso desativado em Configurações › Avisos."
    t = TIPOS[tipo]
    de = t["campos"].get(regra["campo_base"], ("", regra["campo_base"]))[1]
    n = regra["dias_inicio"]
    if n < 0:
        ini = f"a partir de {_dias(-n)} antes {de}"
    elif n > 0:
        ini = f"a partir de {_dias(n)} depois {de}"
    else:
        ini = f"a partir do dia {de}"
    fim = f"até {t['resolvido']}"
    parar = regra.get("dias_parar_apos")
    if parar is not None:
        fim += f" (no máximo até {_dias(parar)} depois {de})"
    return f"Avisa {ini}, {fim}."
