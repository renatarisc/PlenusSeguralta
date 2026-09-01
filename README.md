# Plenus · SEGURALTA

Sistema web da SEGURALTA (seguros, consórcios, saúde): cadastros, controle financeiro e
relatórios. Construído aos poucos — o banco evolui por migração aditiva e **nunca apaga dado já
inserido**.

## Rodar

**Desenvolvimento** (uma pessoa, com auto-reload):

```bash
venv\Scripts\python.exe app.py
```

**Uso compartilhado / produção** (servidor waitress, sem debug):

```bash
venv\Scripts\python.exe servir.py
```

- No PC: <http://localhost:5000>
- Nas outras máquinas: `http://<IP-ou-nome-Tailscale>:5000`

No **primeiro acesso** o sistema pede para criar o usuário administrador. Depois, todo
mundo precisa de login (menu **Usuários** para cadastrar as demais pessoas). O segredo da
sessão fica em `plenus_secret.key` (fora do git — não apagar). Para servir por HTTPS,
suba com a variável `PLENUS_HTTPS=1` para o cookie de sessão virar `Secure`.

### Compartilhar entre 2 computadores com Tailscale

1. Instale o **Tailscale** (tailscale.com/download) nos 3 pontos: o PC que vai ser o
   servidor e as 2 máquinas das usuárias. Faça login com a **mesma conta** (ative 2FA nessa
   conta) — ou use "Share" para convidar a outra conta.
2. No PC servidor, deixe o Plenus rodando: `venv\Scripts\python.exe servir.py`
   (deixe essa janela aberta, ou registre como serviço/Tarefa Agendada no logon).
3. Descubra o nome/IP Tailscale do servidor: `tailscale ip -4` (ou o nome em
   `tailscale status`). Ex.: `100.x.y.z` ou `pc-servidor`.
4. Nas outras máquinas, abra no navegador `http://100.x.y.z:5000` (ou `http://pc-servidor:5000`
   se o MagicDNS estiver ligado). Pronto — as duas usam ao mesmo tempo, tudo liberado.
5. (Opcional, HTTPS) no servidor: `tailscale serve --bg 5000` → dá uma URL `https://…ts.net`.
   Nesse caso rode o Plenus com `set PLENUS_HTTPS=1 && venv\Scripts\python.exe servir.py`.

**Regra do SQLite:** só o PC servidor roda o app e é dono do `plenus.db`. As outras máquinas
**não** rodam o `servir.py` nem abrem o `.db` — só acessam pelo navegador.

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
| `servir.py` | servidor de produção (waitress) para uso compartilhado |
| `db.py` | conexão, esquema, migração, backup |
| `repo.py` | consultas por entidade |
| `validacao.py` | CPF / CEP / e-mail / telefone (validação do servidor) |
| `seguranca.py` | secret key, hash de senha, throttle de login |
| `leitura_pdf*.py` | "Ler apólice" (extração de PDF) |
| `notificacoes.py`, `verificar_vencimentos.py` | aviso de vencimento por WhatsApp |
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
