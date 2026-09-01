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
| `notificacoes.py`, `agenda.py`, `verificar_vencimentos.py` | avisos de vencimento (e-mail + Google Agenda) |
| `templates/` | páginas (`base.html` = layout + menu + ícones) |
| `static/` | `css/app.css`, `js/app.js` (máscaras, validação, UF↔Cidade), `dados/municipios.json` |

## Avisos de vencimento (e-mail + Google Agenda)

- **No sistema**: na lista de apólices e no Painel, o que está a ≤ 20 dias do fim da
  vigência (ou vencido) fica em vermelho; o Painel também tem o card "Boletos a vencer".
- **E-mail** (`verificar_vencimentos.py`, 1x/dia): manda e-mail quando faltam **10/5/1 dia**
  para o fim da vigência e **10/1 dia** para uma parcela de boleto (marcos configuráveis).
  Cada marco dispara uma vez só.
- **Google Agenda**: cria um evento na data do vencimento (apólice e parcela de boleto),
  com lembretes automáticos; some quando a apólice vence/é apagada ou o boleto é pago.
- Parcela marcada como **paga** sai da lista de boletos e para de gerar aviso.
- Config: copie `plenus_config.exemplo.json` → `plenus_config.json` (fora do git) e
  preencha os blocos `email` e `google_agenda` (`"ativo": true`). Detalhes no `DEPLOY.md`.
  Enquanto ambos forem `false`, só grava em `notificacoes.log`.
- Agendamento: **Tarefa Agendada do Windows** ("Plenus - vencimentos", 08:00) já
  registrada localmente; no VPS é um cron (ver `DEPLOY.md`).

Teste sem enviar: `venv\Scripts\python.exe verificar_vencimentos.py --seco`

## Feito

- Cadastro de **Clientes** (dados pessoais, endereço, contato)
- Cadastro de **Tipos de Seguro** e **Formas de Pagamento** (só nome; FK em tabelas futuras)
- Cadastro de **Apólices**: cliente + tipo de seguro (FK), número, vigência, prêmio líquido,
  forma de pagamento (FK), comissão (% e valor, com botão de cálculo), lançado no Quiver,
  link do OneDrive, e **parcelas** (identificação/data/valor) com linhas dinâmicas e um
  gerador (qtd × valor total × 1ª data → parcelas mensais)
