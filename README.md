# Plenus · SEGURALTA

Sistema web da SEGURALTA (seguros, consórcios, saúde): cadastros, controle financeiro e
relatórios. Construído aos poucos — o banco evolui por migração aditiva e **nunca apaga dado já
inserido**.

## Rodar

```bash
venv\Scripts\python.exe app.py
```

- No PC: <http://localhost:5000>
- No celular (mesma rede Wi-Fi): `http://IP-DO-PC:5000`

## Stack

- **Flask** + templates Jinja2, HTML/CSS/JS puro (responsivo — menu lateral colapsável no celular)
- **SQLite** (`plenus.db`) com migração em `db.py` (`CREATE TABLE IF NOT EXISTS` + `ALTER TABLE`);
  snapshot de backup em `backups/` antes de toda gravação
- UF × Cidade: dataset do IBGE embutido em `static/dados/municipios.json`
- CEP: validação + autofill via ViaCEP; CPF: validação mód. 11
- **Ler apólice**: `leitura_pdf.py` extrai campos de um PDF (PyMuPDF; cai para OCR com
  Tesseract em PDF digitalizado). Precisa do Tesseract instalado
  (`C:\Program Files\Tesseract-OCR\`) para o caminho OCR.

## Estrutura

| Arquivo | Papel |
|---|---|
| `app.py` | rotas Flask |
| `db.py` | conexão, esquema, migração, backup |
| `repo.py` | consultas por entidade |
| `validacao.py` | CPF / CEP / e-mail / telefone (validação do servidor) |
| `templates/` | páginas (`base.html` = layout + menu + ícones) |
| `static/` | `css/app.css`, `js/app.js` (máscaras, validação, UF↔Cidade), `dados/municipios.json` |

## Aviso de vencimento de apólice

- Na lista de apólices, quando faltam **≤ 20 dias** para o fim da vigência (ou já venceu),
  a linha fica destacada em vermelho com uma tarja "vence em Nd".
- `verificar_vencimentos.py` manda um WhatsApp para um número fixo da corretora quando
  faltam **10, 5 e 1 dia** (marcos configuráveis). Cada marco dispara uma vez só
  (registrado em `notificacao_vencimento`).
- Configuração: copie `plenus_config.exemplo.json` para `plenus_config.json` (fora do git)
  e preencha `whatsapp.destino` e o provedor. Enquanto `provedor` for `"simulado"`, nada
  é enviado de verdade — só grava em `notificacoes.log`.
- Rodar 1x/dia pela **Tarefa Agendada do Windows**:

```bat
schtasks /create /tn "Plenus - vencimentos" /sc daily /st 08:00 /tr "\"C:\Users\renat\PycharmProjects\plenus_seguralta\venv\Scripts\python.exe\" \"C:\Users\renat\PycharmProjects\plenus_seguralta\verificar_vencimentos.py\""
```

Teste sem enviar: `venv\Scripts\python.exe verificar_vencimentos.py --seco`

## Feito

- Cadastro de **Clientes** (dados pessoais, endereço, contato)
- Cadastro de **Tipos de Seguro** e **Formas de Pagamento** (só nome; FK em tabelas futuras)
- Cadastro de **Apólices**: cliente + tipo de seguro (FK), número, vigência, prêmio líquido,
  forma de pagamento (FK), comissão (% e valor, com botão de cálculo), lançado no Quiver,
  link do OneDrive, e **parcelas** (identificação/data/valor) com linhas dinâmicas e um
  gerador (qtd × valor total × 1ª data → parcelas mensais)
