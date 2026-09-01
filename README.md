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

## Estrutura

| Arquivo | Papel |
|---|---|
| `app.py` | rotas Flask |
| `db.py` | conexão, esquema, migração, backup |
| `repo.py` | consultas por entidade |
| `validacao.py` | CPF / CEP / e-mail / telefone (validação do servidor) |
| `templates/` | páginas (`base.html` = layout + menu + ícones) |
| `static/` | `css/app.css`, `js/app.js` (máscaras, validação, UF↔Cidade), `dados/municipios.json` |

## Feito

- Cadastro de **Clientes** (dados pessoais, endereço, contato)
- Cadastro de **Tipos de Seguro** e **Formas de Pagamento** (só nome; FK em tabelas futuras)
- Cadastro de **Apólices**: cliente + tipo de seguro (FK), número, vigência, prêmio líquido,
  forma de pagamento (FK), comissão (% e valor, com botão de cálculo), lançado no Quiver,
  link do OneDrive, e **parcelas** (identificação/data/valor) com linhas dinâmicas e um
  gerador (qtd × valor total × 1ª data → parcelas mensais)
