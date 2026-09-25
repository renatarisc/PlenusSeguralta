"""Salvar apólice/endosso/serviço/consórcio atualiza parcelas e boletos NO LUGAR:
preserva ids, datas de pago/aviso/envio e o histórico de avisos."""

from datetime import date, timedelta

import db
import repo
from tests.base import TesteBase

ANTIGA = "2026-01-15"
HOJE = date.today().isoformat()
D10 = (date.today() + timedelta(days=10)).isoformat()


class TestParcelasApolice(TesteBase):
    def setUp(self):
        super().setUp()
        self.cid = self.novo_cliente()
        self.base = {"cliente_id": self.cid, "seguradora_id": self.id_simples("seguradora"),
                     "numero_apolice": "AP-PARC", "forma_pagamento_id": self.id_simples("forma_pagamento", "boleto")}
        self.cli.post("/apolices/nova", data={**self.base, **self.form_parcelas([
            (None, "1/3", HOJE, "100,00", "1", "1", "1"),
            (None, "2/3", D10, "100,00", "0", "0", "0"),
            (None, "3/3", D10, "100,00", "0", "0", "0")])})
        self.aid = self.sql("SELECT id FROM apolice WHERE cliente_id=%s", (self.cid,))[0]["id"]
        self.ps = self.parcelas()
        with db.conexao() as con:
            con.execute("UPDATE apolice_parcela SET pago_em=%s, aviso_ok_em=%s, enviado_em=%s WHERE id=%s",
                        (ANTIGA, ANTIGA, ANTIGA, self.ps[0]["id"]))
        repo.registrar_notificacao_parcela(self.ps[1]["id"], 0, D10, "email", "", "OK: teste")

    def parcelas(self):
        return self.sql("SELECT * FROM apolice_parcela WHERE apolice_id=%s ORDER BY id", (self.aid,))

    def editar(self, linhas, **extra):
        return self.cli.post(f"/apolices/{self.aid}", data={**self.base, **extra, **self.form_parcelas(linhas)})

    def test_editar_preserva_ids_datas_e_historico(self):
        p0, p1, p2 = self.ps
        r = self.editar([(p0["id"], "1/3", HOJE, "150,00", "1", "1", "1"),
                         (p1["id"], "2/3", D10, "100,00", "0", "0", "0"),
                         (None, "nova", D10, "50,00", "0", "0", "0")])
        self.assertEqual(r.status_code, 302)
        novas = {p["id"]: p for p in self.parcelas()}
        self.assertIn(p0["id"], novas)
        self.assertIn(p1["id"], novas)
        self.assertNotIn(p2["id"], novas, "linha removida na tela deve ser apagada")
        self.assertEqual(len(novas), 3)
        self.assertEqual(novas[p0["id"]]["valor"], 150)
        for campo in ("pago_em", "aviso_ok_em", "enviado_em"):
            self.assertEqual(novas[p0["id"]][campo], ANTIGA)
        n = self.sql("SELECT COUNT(*) n FROM notificacao_parcela WHERE parcela_id=%s", (p1["id"],))[0]["n"]
        self.assertEqual(n, 1)
        self.assertTrue(repo.email_boleto_enviado_hoje(p1["id"]))

    def test_desmarcar_pago_limpa_so_pago_em(self):
        p0 = self.ps[0]
        self.editar([(p0["id"], "1/3", HOJE, "100,00", "0", "1", "1")])
        p = self.parcelas()[0]
        self.assertEqual((p["paga"], p["pago_em"], p["aviso_ok_em"]), (0, None, ANTIGA))

    def test_id_de_outra_apolice_vira_linha_nova(self):
        outra = self.nova_apolice(self.cid, "AP-OUTRA", parcelas=[{"identificacao": "1/1", "data": HOJE, "valor": 9.0}])
        alheia = self.sql("SELECT * FROM apolice_parcela WHERE apolice_id=%s", (outra,))[0]
        self.editar([(alheia["id"], "x", HOJE, "1,00", "0", "0", "0")])
        self.assertEqual(self.sql("SELECT * FROM apolice_parcela WHERE id=%s", (alheia["id"],))[0], alheia)

    def test_erro_de_validacao_mantem_id_escondido(self):
        p0 = self.ps[0]
        r = self.editar([(p0["id"], "1/3", HOJE, "100,00", "1", "1", "1")], numero_apolice="")
        self.assertIn(f'name="parcela_id" value="{p0["id"]}"', r.get_data(as_text=True))


class TestParcelasOutros(TesteBase):
    def test_endosso(self):
        cid = self.novo_cliente()
        aid = self.nova_apolice(cid, "AP-END")
        base = {"apolice_id": aid, "numero": "E1", "vigencia_inicio": HOJE, "vigencia_fim": D10,
                "situacao": "onus", "valor": "80,00", "forma_pagamento_id": self.id_simples("forma_pagamento", "boleto")}
        self.cli.post("/endossos/novo", data={**base, **self.form_parcelas([
            (None, "1/2", HOJE, "40,00", "1", "0", "0"), (None, "2/2", D10, "40,00", "0", "0", "0")])})
        eid = self.sql("SELECT id FROM apolice_endosso WHERE apolice_id=%s", (aid,))[0]["id"]
        pe = self.sql("SELECT * FROM apolice_endosso_parcela WHERE endosso_id=%s ORDER BY id", (eid,))
        with db.conexao() as con:
            con.execute("UPDATE apolice_endosso_parcela SET pago_em=%s WHERE id=%s", (ANTIGA, pe[0]["id"]))
        self.cli.post(f"/endossos/{eid}", data={**base, **self.form_parcelas([
            (pe[0]["id"], "1/2", HOJE, "40,00", "1", "0", "0"), (pe[1]["id"], "2/2", D10, "45,00", "0", "0", "0")])})
        pe2 = self.sql("SELECT * FROM apolice_endosso_parcela WHERE endosso_id=%s ORDER BY id", (eid,))
        self.assertEqual([p["id"] for p in pe2], [p["id"] for p in pe])
        self.assertEqual((pe2[0]["pago_em"], pe2[1]["valor"]), (ANTIGA, 45))

    def test_consorcio_boletos(self):
        cid = self.novo_cliente()
        base = {"cliente_id": cid, "seguradora_id": self.id_simples("seguradora"),
                "tipo_consorcio_id": self.id_simples("tipo_consorcio"), "numero_grupo": "G1",
                "numero_cota": "1", "situacao": "ativo", "carta": "1000,00"}

        def fb(linhas):
            return {"boleto_id": [str(l[0] or "") for l in linhas],
                    "boleto_identificacao": [l[1] for l in linhas], "boleto_valor": [l[2] for l in linhas],
                    "boleto_emissao": [HOJE] * len(linhas), "boleto_vencimento": [D10] * len(linhas),
                    "boleto_pagamento": [""] * len(linhas), "boleto_status": [l[3] for l in linhas],
                    "boleto_aviso": [l[4] for l in linhas]}
        r = self.cli.post("/consorcios/novo", data={**base, **fb([(None, "1", "100,00", "a_enviar", "1"),
                                                                (None, "2", "100,00", "a_enviar", "0")])})
        self.assertEqual(r.status_code, 302)
        coid = self.sql("SELECT id FROM consorcio WHERE cliente_id=%s", (cid,))[0]["id"]
        bs = self.sql("SELECT * FROM consorcio_boleto WHERE consorcio_id=%s ORDER BY id", (coid,))
        with db.conexao() as con:
            con.execute("UPDATE consorcio_boleto SET aviso_ok_em=%s WHERE id=%s", (ANTIGA, bs[0]["id"]))
        repo.registrar_notificacao_parcela(bs[0]["id"], 0, D10, "email", "", "OK", "consorcio")
        self.cli.post(f"/consorcios/{coid}", data={**base, **fb([(bs[0]["id"], "1", "110,00", "enviado", "1"),
                                                                (bs[1]["id"], "2", "100,00", "a_enviar", "0")])})
        bs2 = self.sql("SELECT * FROM consorcio_boleto WHERE consorcio_id=%s ORDER BY id", (coid,))
        self.assertEqual([b["id"] for b in bs2], [b["id"] for b in bs])
        self.assertEqual((bs2[0]["aviso_ok_em"], bs2[0]["valor"], bs2[0]["status"]), (ANTIGA, 110, "enviado"))
        n = self.sql("SELECT COUNT(*) n FROM notificacao_consorcio_boleto WHERE parcela_id=%s", (bs[0]["id"],))[0]["n"]
        self.assertEqual(n, 1)
