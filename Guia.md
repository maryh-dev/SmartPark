# SmartPark IoT

Sistema de estacionamento inteligente com frontend estático, API Flask, Firebase
Firestore, pagamentos via Mercado Pago e integração com dispositivos ESP32.

## Pré-requisitos

- Python 3.10 ou superior
- Um projeto Firebase com o Firestore habilitado
- Uma conta de serviço do Firebase salva fora do repositório
- [Firebase CLI](https://firebase.google.com/docs/cli) (somente para publicar as regras)
- Opcional: ngrok ou cloudflared para testar webhooks e o Wokwi

## Executar localmente

Os comandos abaixo devem ser executados na raiz do repositório.

1. Crie e ative o ambiente virtual:

   ```powershell
   py -m venv backend\venv
   .\backend\venv\Scripts\Activate.ps1
   ```

2. Instale as dependências:

   ```powershell
   python -m pip install -r backend\requirements.txt
   ```

3. Crie `backend\.env` a partir de `backend\.env.example` e configure, no mínimo:

   ```dotenv
   GOOGLE_APPLICATION_CREDENTIALS=C:\caminho\seguro\service-account.json
   FLASK_SECRET_KEY=um-segredo-aleatorio-longo
   FLASK_ENV=development
   SESSION_COOKIE_SECURE=false
   ```

   Gere um segredo com:

   ```powershell
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```

   Para pagamentos, Telegram e Wokwi, preencha também as variáveis correspondentes
   descritas no arquivo `.env.example`.

4. Inicie a aplicação:

   ```powershell
   python backend\app.py
   ```

5. Acesse <http://127.0.0.1:5000>. Não abra `public\index.html` diretamente, pois o
   frontend precisa da API Flask e da sessão no mesmo domínio.

## Preparar o Firestore

Com as credenciais configuradas:

```powershell
python backend\seed_firestore.py
python backend\app.py create-admin
```

O primeiro comando cria dados fictícios para demonstração e pode ser executado novamente
sem duplicar os documentos de teste. O segundo cadastra o primeiro administrador e solicita
a senha sem exibi-la no terminal.

Para publicar as regras do Firestore:

```powershell
firebase use SEU_PROJECT_ID
firebase deploy --only firestore:rules
```

As regras bloqueiam o acesso direto do navegador; as operações passam pela API usando o
Firebase Admin SDK.

## Testar Mercado Pago, Telegram e Wokwi

Essas integrações precisam de uma URL HTTPS pública. Inicie o servidor local e execute:

```powershell
ngrok http 5000
```

Coloque a URL HTTPS gerada em `APP_BASE_URL`, reinicie o Flask e use essa URL para abrir
o sistema. Configure também as credenciais de teste do Mercado Pago e o token do Telegram
em `backend\.env`. Para o Wokwi, use os arquivos de `wokwi\` e configure a URL do túnel
e o mesmo `DEVICE_SHARED_SECRET` no sketch.

Consulte [docs/PASSO_A_PASSO.md](docs/PASSO_A_PASSO.md) para o roteiro completo, testes
de pagamento e operação do Wokwi.

## Publicar no Vercel

1. Importe o repositório no Vercel usando a raiz do projeto como diretório.
2. Configure as variáveis de ambiente:
   - `FIREBASE_SERVICE_ACCOUNT_JSON`: JSON completo da conta de serviço;
   - `FLASK_SECRET_KEY`: segredo aleatório longo;
   - `FLASK_ENV=production`;
   - `SESSION_COOKIE_SECURE=true`;
   - demais variáveis necessárias para Mercado Pago, Telegram e cron.
3. Faça o deploy e teste `https://seu-dominio/api/health`.

Em produção, não envie `backend\.env`, chaves JSON ou tokens para o Git. O arquivo
`pyproject.toml` já aponta o Vercel para `backend.app:app`, e `public\` contém o frontend.

## Documentação adicional

- [backend/README.md](backend/README.md): execução local, Vercel e limitações conhecidas.
- [docs/FIRESTORE.md](docs/FIRESTORE.md): coleções, regras e rotas da API.
- [docs/HARDWARE.md](docs/HARDWARE.md): pinagem e requisitos elétricos.
- [docs/TESTES.md](docs/TESTES.md): roteiro de testes.
