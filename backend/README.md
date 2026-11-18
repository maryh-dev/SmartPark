# SmartPark

Aplicação Flask com Firebase Admin/Firestore. O frontend está em `public/` e é servido pelo
mesmo domínio da API, mantendo o login por sessão na mesma origem.

## Executar localmente

1. Use Python 3.10 ou superior.
2. Crie um ambiente virtual e instale as dependências:

   ```powershell
   py -m venv backend\venv
   .\backend\venv\Scripts\Activate.ps1
   python -m pip install -r backend\requirements.txt
   ```

3. Copie `backend\.env.example` para `backend\.env` e configure:
   - `GOOGLE_APPLICATION_CREDENTIALS` com o caminho local da conta de serviço;
   - `FLASK_SECRET_KEY` com um valor aleatório;
   - `FLASK_ENV=development` e `SESSION_COOKIE_SECURE=false` para a execução local.
4. O arquivo da conta de serviço e `backend\.env` nunca devem ser enviados ao Git.
5. Inicie o servidor na raiz do projeto:

   ```powershell
   python backend\app.py
   ```

   Abra `http://127.0.0.1:5000`. Não abra `index.html` diretamente como arquivo.

6. Cadastre o primeiro administrador em um terminal local:

   ```powershell
   python backend\app.py create-admin
   ```

   A senha é solicitada sem aparecer no terminal. O endpoint público de cadastro cria somente
   clientes; ele nunca aceita um papel administrativo.

7. Para carregar os documentos fictícios do roteiro, rode `python backend\seed_firestore.py`
   apenas quando estiver pronto para inserir/atualizar os IDs fixos de demonstração no Firestore.
   O script reutiliza IDs fixos e atualiza esses documentos ao rodar novamente.

## Publicar a aplicação completa no Vercel

O projeto está configurado para o runtime Python do Vercel: `pyproject.toml` aponta para
`backend.app:app`, `requirements.txt` inclui as dependências e `public/` contém os arquivos
estáticos do site. Configure a raiz do projeto como a raiz do repositório, sem definir
diretório de saída/build estático.

1. Envie o projeto para um repositório GitHub e importe esse repositório no Vercel.
2. Em **Project Settings → Environment Variables**, configure para Production (e Preview,
   se for usar):
   - `FIREBASE_SERVICE_ACCOUNT_JSON`: conteúdo JSON completo de uma conta de serviço com acesso
     somente ao projeto Firestore necessário. Não use nem envie `service-account.json`.
   - `FLASK_SECRET_KEY`: segredo aleatório longo, diferente das credenciais do Firebase.
   - `FLASK_ENV`: `production`.
   - `SESSION_COOKIE_SECURE`: `true`.
3. Faça um novo deploy e confira `https://seu-dominio/api/health`.
4. Abra a raiz do domínio Vercel para usar a aplicação. O Vercel fornece HTTPS, necessário para
   o cookie seguro de sessão.

O arquivo `.vercelignore` exclui ambiente virtual e credenciais locais do pacote de deploy.
As variáveis do Vercel não substituem regras de segurança do Firestore; conceda à conta de
serviço somente as permissões necessárias e nunca coloque esses segredos em `public/`.

### Regras do Firestore

O arquivo `firestore.rules` nega todas as leituras e gravações feitas diretamente por clientes.
Isso é intencional: o site acessa os dados exclusivamente pela API Flask, usando Firebase Admin
no servidor. As regras do Firestore não limitam o Admin SDK; proteja as credenciais do servidor
e mantenha-as fora do Git.

Para publicar as regras com o Firebase CLI, selecione o projeto correto antes e execute na raiz:

```powershell
firebase use SEU_PROJECT_ID
firebase deploy --only firestore:rules
```

Não altere a regra para liberar leitura/escrita pública. O cadastro, login e demais operações
devem passar pela API, que verifica a sessão e as permissões.

### GitHub Pages

É possível publicar `public/` no GitHub Pages como prévia estática. Pages não executa Flask nem
conecta diretamente ao Firestore; portanto, cadastro, login, reservas e chamadas da API não
funcionarão nessa prévia. Para a aplicação completa com a arquitetura atual, use o domínio
Vercel para frontend e backend no mesmo domínio. Publicar somente o frontend no Pages apontando
para o Vercel exigiria configurar autenticação entre domínios e CORS.

### Compatibilidade da conta administrativa

Este login procura `users/{sha256_do_email_normalizado}` no Firestore, com `password_hash`,
`active` e `role`. Uma conta que exista apenas no Firebase Authentication não será reconhecida
automaticamente. Para o administrador entrar, crie o documento no formato esperado usando
`python backend\app.py create-admin`, ou implemente uma migração explícita para Firebase Auth.

## API, pagamento e pendências

Veja `docs/FIRESTORE.md` (coleções, política de tarifa e rotas), `docs/PASSO_A_PASSO.md`
(Mercado Pago, Telegram, Wokwi, túnel e entrega) e `docs/HARDWARE.md` (pinagem e 5 V).

Fluxo: `POST /api/reservations` (PENDING_PAYMENT, 15 min) → `POST .../checkout` (Checkout Pro) →
webhook `POST /webhooks/mercadopago` (assinatura + consulta à API) → `CONFIRMED`.
Somente `CONFIRMED` dentro da janela de tolerância libera a cancela.

Limitações conhecidas: a entrada usa a reserva confirmada mais antiga do estacionamento (o firmware
não envia código de reserva); o servidor de desenvolvimento Flask não deve ser exposto na Internet
sem túnel restrito; reembolsos são manuais.
