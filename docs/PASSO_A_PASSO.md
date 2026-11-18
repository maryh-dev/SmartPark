# SmartPark IoT — passo a passo para concluir o projeto

Ordem recomendada. Itens marcados com 🔒 são segurança e vêm antes de qualquer commit.

## 0. 🔒 Segurança (faça agora)
1. **Firebase:** Console → Configurações do projeto → Contas de serviço → gerar **nova** chave; depois apague a antiga (a chave que estava no zip deve ser considerada vazada). Salve a nova fora do Git.
2. **Telegram:** o token que aparece no PDF "Divisão de Tarefas" deve ser revogado: BotFather → `/revoke` → escolha o bot → use o novo token.
3. Rode `git init` na raiz (o `.gitignore` já está pronto) e confira antes do primeiro commit:
   ```
   git add -A && git ls-files | findstr /i "env service-account venv"
   ```
   O resultado deve mostrar só `.env.example`. Nunca envie `backend/venv`.

## 1. Firebase / Firestore
1. Console Firebase → criar projeto → **Firestore Database** (modo produção).
2. `backend/.env`: copie `.env.example` e preencha `GOOGLE_APPLICATION_CREDENTIALS` (caminho da NOVA chave), `FLASK_SECRET_KEY` e `DEVICE_SHARED_SECRET`
   (`python -c "import secrets;print(secrets.token_urlsafe(32))"`).
3. `pip install -r backend/requirements.txt`
4. `python backend/seed_firestore.py` (2 estacionamentos, 10 vagas, 2 dispositivos **ONLINE**, 1 reserva de teste dentro da janela de entrada).
5. `python backend/app.py create-admin` (cria o administrador).
6. `firebase deploy --only firestore:rules` (regras negam todo acesso direto do cliente).

## 2. Túnel HTTPS (necessário para Mercado Pago e Wokwi)
1. Instale o ngrok (ou `cloudflared`) e rode: `ngrok http 5000`.
2. Copie a URL `https://xxxx.ngrok-free.app` para `APP_BASE_URL` no `.env` e **reinicie o Flask**.
3. Abra o sistema **sempre pela URL do túnel** (o cookie de sessão é por domínio; se abrir por `127.0.0.1`, o retorno do pagamento cairá sem login).
4. Só as rotas `/api/iot/*` e `/webhooks/mercadopago` precisam ser públicas; as rotas admin exigem login de administrador.

## 3. Mercado Pago (Checkout Pro) — passo a passo
O código já está pronto em `backend/payments.py`. Falta configurar a conta:

1. **Aplicação:** mercadopago.com.br/developers → *Suas integrações* → **Criar aplicação** → produto **Checkout Pro**.
2. **Credenciais de teste:** na aplicação, *Credenciais de teste* → copie o **Access Token** (começa com `TEST-`) para `MERCADOPAGO_ACCESS_TOKEN`.
3. **Contas de teste:** *Contas de teste* → crie um usuário **Comprador** (e use o vendedor de teste da própria aplicação). Pague **sempre logado como comprador de teste**; não é possível pagar com a mesma conta da aplicação.
4. **Webhook:** na aplicação → *Webhooks* → *Configurar notificações*:
   - modo **Teste**; URL: `https://SEU-TUNEL/webhooks/mercadopago`; evento: **Pagamentos**;
   - copie a **Assinatura secreta** para `MERCADOPAGO_WEBHOOK_SECRET` e reinicie o Flask;
   - o botão *Simular notificação* deve retornar **200** (o backend responde 200 mesmo quando o pagamento simulado não existe).
5. **Fluxo completo:** cliente cria reserva → **Pagar com Mercado Pago** → Checkout → página de retorno. A reserva vira `CONFIRMED` quando o backend consulta o pagamento (via webhook ou via `sync-payment` da página de retorno). Confira `payments` no Firestore.
6. **Cartões de teste** (confirme os números atuais em *Credenciais de teste → Cartões de teste* na documentação do MP): Mastercard `5031 4332 1540 6351`, CVV `123`, validade `11/30`. O nome do titular define o resultado: `APRO` aprovado, `OTHE` recusado, `CONT` pendente. CPF de teste: `12345678909`.
7. **Como cobrir os testes:**
   - **T04** pague com titular `OTHE` → reserva continua `PENDING_PAYMENT`; a entrada é negada.
   - **T05** titular `APRO` → `CONFIRMED` uma vez; mensagem no Telegram.
   - **T06** reenvie o mesmo evento pelo painel de webhooks → nada muda (confira que só há 1 mensagem e 1 doc em `payments`).
   - **Pagamento após expiração:** crie a reserva, espere 15 min e pague → `payments` fica com `refund_needed: true`, a reserva **não** confirma.
8. **Produção:** só depois de testes e revisão (taxas, estorno, termos). Troque o token e o segredo do webhook e use outra URL.

## 4. Telegram
1. BotFather → `/newbot` → guarde o token em `TELEGRAM_BOT_TOKEN`.
2. No Telegram abra o bot e envie `/start`.
3. Descubra o chat_id: acesse `https://api.telegram.org/bot<TOKEN>/getUpdates` no **seu** navegador (não cole o token em prints) e leia `message.chat.id` → `TELEGRAM_DEFAULT_CHAT_ID`.
4. `python backend/telegram_service.py` → deve chegar a mensagem de teste (403 = faltou `/start`; 400 = chat_id errado; 401 = token errado).
5. Coberto no código: confirmação (webhook), ticket (saída), alerta (`send_operational_alert`), retentativas e `PENDING_RETRY`. Para reenviar pendências: botão/rota `POST /api/admin/notifications/retry`.
6. **T12:** apague o token no `.env` temporariamente, faça uma saída → ticket fica salvo com `telegram_status: PENDING_RETRY`; restaure o token e chame a rota de retry.
7. *(Opcional, nota maior)* vínculo seguro do chat_id por usuário: gere um código único por conta, o usuário envia `/start CODIGO` ao bot e o backend (webhook do bot ou `getUpdates`) grava o `chat_id` no usuário. Nunca aceite chat_id vindo do navegador.

## 5. Wokwi
1. wokwi.com → novo projeto **ESP32** → substitua `sketch.ino` e `diagram.json` pelos arquivos de `wokwi/`; em *Library Manager* adicione as de `wokwi/libraries.txt`.
2. No sketch: `API_BASE` = URL do túnel; `DEVICE_SECRET` = mesmo valor de `DEVICE_SHARED_SECRET`. (Não salve o segredo real em projeto público: use um valor só de teste.)
3. O `DEVICE_ID` já é `esp32_pelourinho_01`, igual ao seed.
4. Rode e teste: botão "TESTE ENTRADA" com a reserva do seed → LED verde + servo 90°. Sem reserva → LED vermelho. Túnel desligado → `FALHA_REDE` (T09).
5. Para os sensores, clique no HC-SR04 e arraste a distância (< 15 cm detecta veículo).
6. *Share* → copie o **link do projeto** para a entrega.

## 6. Pendências de código que ficaram de fora (e como fazer)
- **Código da reserva no ESP32:** hoje a entrada é associada à reserva confirmada mais antiga do local. Melhoria: adicionar um teclado/serial para digitar o código (`SP-xxxxxx`), enviar `reservation_code` e filtrar por ele no `iot_access_request`.
- **Telemetria/heartbeat:** `/api/iot/telemetry` só aceita `EXIT`. Para alertas de "dispositivo sem comunicação", faça o ESP32 enviar um `HEARTBEAT` a cada 60 s e chame `send_operational_alert` quando `last_seen` passar de 5 min (o painel admin já mostra esse alerta).
- **Limite de frequência** nas rotas IoT: adicione `flask-limiter` (ex.: 30/min por device).
- **Expiração agendada:** chame `POST /api/admin/expire-pending` com o cabeçalho `X-Cron-Secret` (valor de `CRON_SECRET`) a cada 5 min (Vercel Cron ou GitHub Actions).
- **Reembolso:** pagamentos com `refund_needed` aparecem nos alertas do admin; o estorno é manual no painel do Mercado Pago (documente a regra).

## 7. Entrega final
- [ ] Link do Wokwi + diagrama identificado (`wokwi/diagram.json`, nota dos 5 V em `docs/HARDWARE.md`)
- [ ] Relatório de testes `docs/TESTES.md` preenchido com prints/logs **sem segredos**
- [ ] Estrutura do Firestore: `docs/FIRESTORE.md`
- [ ] T15: `git log -p | findstr /i "token secret private_key"` sem resultados reais
- [ ] Limpar dados de teste do Firestore
- [ ] Apresentação de 5–10 min e reflexão individual
