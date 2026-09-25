"""Regras puras (sem banco): rateio da comissão, preparo de parcelas, validações."""

import unittest

import tests  # noqa: F401
from validacao import (FATOR_PLENUS, PCT_PLENUS, PCT_SEGURALTA_COCO, gerar_repasses_cocorretagem,
                       preparar_boletos, preparar_parcelas, rateio_comissao, validar_servico)


class TestRateio(unittest.TestCase):
    def test_constantes(self):
        self.assertEqual((PCT_PLENUS, PCT_SEGURALTA_COCO), (75, 25))
        self.assertEqual(FATOR_PLENUS, 0.75)

    def test_sem_cocorretagem_seguralta_recebe_a_comissao_inteira(self):
        self.assertEqual(rateio_comissao(100.0, False), (100.0, 75.0))

    def test_com_cocorretagem_25_e_75(self):
        self.assertEqual(rateio_comissao(758.53, True), (189.63, 568.9))

    def test_repasses_cocorretagem_somam_75_por_cento(self):
        comissoes = [{"parcela": "1", "valor_previsto": 50.0, "data": "2026-01-10"},
                     {"parcela": "2", "valor_previsto": 50.0, "data": "2026-02-10"}]
        rep = gerar_repasses_cocorretagem(comissoes, "1.000,00", "10")
        self.assertEqual(len(rep), 2)
        self.assertAlmostEqual(sum(r["valor_previsto"] for r in rep), 75.0, places=2)
        self.assertTrue(all(r.get("valor_recebido") is None for r in rep))


class TestPreparo(unittest.TestCase):
    def test_parcelas_levam_o_id_da_linha(self):
        ps, erros = preparar_parcelas(["1/2", "2/2"], ["2026-01-01", ""], ["10,00", "20,00"],
                                      ["1", "0"], ["0", "0"], ["0", "0"], ["55", ""])
        self.assertFalse(erros)
        self.assertEqual([p["id"] for p in ps], ["55", None])
        self.assertEqual(ps[0]["paga"], 1)

    def test_linha_vazia_e_ignorada_sem_desalinhar_ids(self):
        ps, _ = preparar_parcelas(["", "2/2"], ["", "2026-01-01"], ["", "5,00"],
                                  ["0", "0"], ["0", "0"], ["0", "0"], ["", "77"])
        self.assertEqual(len(ps), 1)
        self.assertEqual(ps[0]["id"], "77")

    def test_boletos_levam_o_id(self):
        bs, _ = preparar_boletos(["1"], ["10,00"], [""], ["2026-01-01"], [""], ["a_enviar"], ["0"], ["9"])
        self.assertEqual(bs[0]["id"], "9")

    def test_valor_invalido_gera_erro(self):
        _, erros = preparar_parcelas(["1"], [""], ["abc"])
        self.assertTrue(erros)


class TestValidacaoServico(unittest.TestCase):
    def test_obrigatorios(self):
        erros = " ".join(validar_servico({}))
        for trecho in ("cliente", "tipo de serviço", "apólice", "seguradora"):
            self.assertIn(trecho, erros)

    def test_vigencia_invertida(self):
        erros = validar_servico({"cliente_id": "1", "tipo_servico_id": "1", "apolice_id": "1",
                                 "seguradora_id": "1", "vigencia_inicio": "2026-05-01",
                                 "vigencia_fim": "2026-01-01"})
        self.assertIn("O fim da vigência é anterior ao início.", erros)


if __name__ == "__main__":
    unittest.main()
