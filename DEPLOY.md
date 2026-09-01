# Deploy do Plenus numa VPS (Ubuntu) com HTTPS e backup

Passo a passo para hospedar o sistema sempre no ar, com login, HTTPS e backup para fora
da máquina. Feito para **Ubuntu 22.04 / 24.04**. Comandos como `root` só no início; depois
tudo com o usuário `plenus`.

Ao final: `https://SEU-DOMINIO` pede o primeiro usuário (administrador); o resto se cadastra
pelo menu **Usuários**. As 2 pessoas usam ao mesmo tempo, tudo liberado.

---

## 1. Contratar a VPS

Qualquer provedor serve (Hetzner, DigitalOcean, Contabo, Hostinger, etc.). O menor plano
já basta: **1 vCPU, 1–2 GB de RAM, 20 GB de disco**. Peça **Ubuntu 24.04**.

Anote o **IP** da máquina. Tenha um **domínio** (ou subdomínio) apontando um registro **A**
para esse IP — o HTTPS automático precisa disso. Ex.: `plenus.suacorretora.com.br → IP`.

## 2. Primeiro acesso e usuário do sistema

```bash
ssh root@SEU_IP

# atualiza tudo
apt update && apt -y upgrade

# usuário sem privilégio para rodar o app
adduser --disabled-password --gecos "" plenus
usermod -aG sudo plenus

# sua chave SSH para o novo usuário (cole a MESMA chave pública que você usa)
mkdir -p /home/plenus/.ssh
cp ~/.ssh/authorized_keys /home/plenus/.ssh/
chown -R plenus:plenus /home/plenus/.ssh
chmod 700 /home/plenus/.ssh && chmod 600 /home/plenus/.ssh/authorized_keys
```

### Endurecer o SSH

```bash
nano /etc/ssh/sshd_config
```
Garanta estas linhas (descomente/edite):
```
PermitRootLogin no
PasswordAuthentication no
```
```bash
systemctl restart ssh
```
Feche esta sessão e reentre como `plenus`: `ssh plenus@SEU_IP`

### Firewall + atualizações automáticas

```bash
sudo apt -y install ufw unattended-upgrades fail2ban
sudo ufw allow OpenSSH
sudo ufw allow 80,443/tcp
sudo ufw --force enable
sudo dpkg-reconfigure -plow unattended-upgrades   # responда "Yes"
```
O `fail2ban` já vem com proteção de SSH ativa por padrão.

## 3. Instalar o sistema

```bash
sudo apt -y install python3-venv python3-pip git tesseract-ocr tesseract-ocr-por

# código
sudo mkdir -p /opt/plenus && sudo chown plenus:plenus /opt/plenus
git clone https://github.com/renatarisc/PlenusSeguralta.git /opt/plenus
cd /opt/plenus

python3 -m venv venv
./venv/bin/pip install --upgrade pip
./venv/bin/pip install -r requirements.txt
```

> No Linux o Tesseract fica no PATH; o `leitura_pdf.py` acha sozinho. (O caminho
> `C:\Program Files\...` no código é só o fallback do Windows e é ignorado aqui.)

### Config do WhatsApp (aviso de vencimento)

```bash
cp plenus_config.exemplo.json plenus_config.json
nano plenus_config.json      # preencha whatsapp.destino; deixe "provedor": "simulado" por enquanto
chmod 600 plenus_config.json
```

## 4. Rodar como serviço (systemd)

```bash
sudo nano /etc/systemd/system/plenus.service
```
```ini
[Unit]
Description=Plenus SEGURALTA
After=network.target

[Service]
User=plenus
WorkingDirectory=/opt/plenus
Environment=PLENUS_HTTPS=1
Environment=PLENUS_ATRAS_DE_PROXY=1
Environment=PLENUS_BIND=127.0.0.1
ExecStart=/opt/plenus/venv/bin/python servir.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now plenus
sudo systemctl status plenus          # deve estar "active (running)"
```
O app agora escuta só em `127.0.0.1:5000` — ninguém acessa direto, só pelo proxy.
O arquivo `plenus_secret.key` é criado automático na 1ª execução (não commitar, não apagar).

## 5. HTTPS com Caddy (certificado automático)

```bash
sudo apt -y install debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update && sudo apt -y install caddy

sudo nano /etc/caddy/Caddyfile
```
```
plenus.suacorretora.com.br {
    encode gzip
    reverse_proxy 127.0.0.1:5000
}
```
```bash
sudo systemctl reload caddy
```
Em segundos o Caddy pega o certificado Let's Encrypt. Abra `https://plenus.suacorretora.com.br`
— vai aparecer a tela **"Primeiro acesso"**. Crie o administrador e pronto.

## 6. Backup para fora da VPS (essencial)

O `backups/` fica no disco da VPS. Precisa de uma cópia em outro lugar.

**Opção simples — snapshot do provedor:** ligue "backups automáticos" no painel da VPS
(geralmente ~20% do valor do plano). Já resolve.

**Opção controlada — `restic` para um bucket/pasta remota:**
```bash
sudo apt -y install restic
# exemplo com um destino S3/Backblaze/rclone já configurado em ~/.config/rclone/rclone.conf
restic -r rclone:remoto:plenus-backup init      # uma vez

sudo nano /opt/plenus/backup.sh
```
```bash
#!/bin/bash
set -e
cd /opt/plenus
./venv/bin/python backup_db.py /tmp/plenus_snapshot.db
export RESTIC_PASSWORD='UMA-SENHA-FORTE-DE-BACKUP'
restic -r rclone:remoto:plenus-backup backup /tmp/plenus_snapshot.db plenus_config.json
restic -r rclone:remoto:plenus-backup forget --keep-daily 14 --keep-weekly 8 --prune
rm -f /tmp/plenus_snapshot.db
```
```bash
chmod +x /opt/plenus/backup.sh
sudo crontab -u plenus -e
```
```
30 2 * * *  /opt/plenus/backup.sh >> /opt/plenus/backup.log 2>&1
```
(`backup_db.py` usa a API de backup do SQLite — a cópia é consistente mesmo com o sistema
em uso.)

## 7. Aviso de vencimento (cron, em vez da Tarefa Agendada do Windows)

```bash
sudo crontab -u plenus -e
```
```
0 8 * * *  cd /opt/plenus && ./venv/bin/python verificar_vencimentos.py >> /opt/plenus/vencimentos.log 2>&1
```
Enquanto `whatsapp.provedor` for `"simulado"`, ele só escreve em `notificacoes.log`.

## 8. Atualizar o sistema depois

```bash
cd /opt/plenus
git pull
./venv/bin/pip install -r requirements.txt
sudo systemctl restart plenus
```
O banco migra sozinho ao subir (só acrescenta colunas, nunca apaga dado). Um backup é
gravado antes de cada migração.

---

## Resumo de segurança já embutido no código

- Login obrigatório em todas as telas; senha com hash; trava de 5 tentativas / 5 min.
- Cookie de sessão `HttpOnly` + `SameSite=Lax`; vira `Secure` com `PLENUS_HTTPS=1`.
- **CSRF** em todos os formulários (Flask-WTF) e no upload do "Ler apólice".
- Cabeçalhos: `Content-Security-Policy`, `X-Frame-Options: DENY`, `X-Content-Type-Options`,
  `Referrer-Policy`, e `HSTS` quando em HTTPS.
- `ProxyFix` (com `PLENUS_ATRAS_DE_PROXY=1`) para o IP real do cliente chegar na trava de login.
- App escuta só em `127.0.0.1` — exposição só via Caddy/HTTPS.
- Queries parametrizadas (sem SQL injection); limite de 20 MB por upload.

O que depende do servidor (este guia cobre): HTTPS, firewall, SSH sem senha, updates
automáticos, `fail2ban`, backup para fora da máquina.
