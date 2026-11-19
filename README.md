# SmartPark — Sistema Inteligente de Estacionamento

Sistema de gerenciamento inteligente de estacionamentos desenvolvido como projeto acadêmico, integrando Internet das Coisas (IoT), aplicação web, banco de dados em nuvem e processamento de pagamentos em ambiente de testes.

O SmartPark tem como objetivo facilitar o gerenciamento de vagas, reservas e acessos, oferecendo uma solução que conecta dispositivos físicos simulados a uma aplicação centralizada.

## Sobre o projeto

O SmartPark propõe automatizar processos de um estacionamento por meio da comunicação entre sensores, microcontrolador e backend.

A solução permite organizar informações sobre estacionamentos e vagas, realizar consultas e reservas, acompanhar solicitações de acesso e integrar pagamentos por meio do Mercado Pago.

## Funcionalidades

- Cadastro e consulta de estacionamentos e vagas.
- Gerenciamento de reservas.
- Integração com o Mercado Pago Checkout Pro em ambiente de testes.
- Comunicação entre ESP32 e backend por meio de requisições HTTP.
- Monitoramento de sensores de distância.
- Simulação de controle de entrada e saída.
- Controle de cancela por servo motor.
- Indicação visual de estados por LEDs e display LCD.
- Registro de eventos e informações no Firebase/Firestore.
- Estrutura de notificações e registro de ocorrências.

## Tecnologias utilizadas

| Tecnologia | Aplicação |
|---|---|
| Python | Desenvolvimento do backend |
| Flask | Criação das rotas e API |
| Firebase / Firestore | Armazenamento de dados |
| ESP32 | Controle do dispositivo IoT |
| Arduino / C++ | Programação do microcontrolador |
| Wokwi | Simulação do circuito eletrônico |
| HTML, CSS e JavaScript | Interface web |
| Mercado Pago | Integração de pagamentos |
| ngrok | Exposição temporária do servidor local para testes |

## Arquitetura do sistema

O projeto é dividido em três partes principais:

**1. Interface web**

Responsável pela interação com o usuário, consulta de informações e gerenciamento das funcionalidades disponibilizadas pelo sistema.

**2. Backend**

Desenvolvido em Python com Flask, recebe requisições da interface e do dispositivo IoT, processa as operações e realiza a comunicação com o banco de dados e serviços externos.

**3. Dispositivo IoT**

Representado por um ESP32 simulado no Wokwi, conectado a sensores, LEDs, botões, display LCD e servo motor.

A comunicação entre o dispositivo e o backend ocorre por meio de requisições HTTP autenticadas.

## Banco de dados

O projeto utiliza Firebase Firestore para armazenamento das informações.

A estrutura de dados contempla as seguintes coleções:

- `parking_lots`: informações dos estacionamentos.
- `spaces`: informações das vagas.
- `reservations`: registros de reservas.
- `payments`: informações relacionadas aos pagamentos.
- `access_events`: eventos de entrada e saída.
- `tickets`: registros de ocorrências.
- `devices`: identificação dos dispositivos IoT.
- `notifications`: registros de notificações.

## Integração com pagamentos

O SmartPark utiliza o Mercado Pago Checkout Pro para simular o processo de pagamento de reservas.

A integração foi testada utilizando contas de teste do Mercado Pago.

O backend também possui uma rota de webhook destinada ao recebimento de notificações sobre eventos de pagamento.

**Observação sobre os testes:** o recebimento de uma requisição de webhook foi verificado, mas a validação da assinatura retornou HTTP 401 — `Assinatura inválida`. Portanto, a validação completa do webhook e a confirmação automática do pagamento por esse mecanismo permanecem pendentes de ajuste.

## Dispositivo IoT

A simulação utiliza um ESP32 DevKit V1 conectado aos seguintes componentes:

- 2 sensores ultrassônicos HC-SR04.
- 1 servo motor para simulação da cancela.
- 1 display LCD 1602 com comunicação I2C.
- 3 LEDs indicadores.
- 2 botões de controle.

O dispositivo possui rotinas para leitura dos sensores, controle da cancela, indicação de estados e comunicação com o backend.

A simulação foi desenvolvida no Wokwi.

## Executando o projeto

### Pré-requisitos

- Python instalado.
- Git.
- Conta e projeto configurados no Firebase.
- Credenciais de teste do Mercado Pago, caso queira executar a integração de pagamentos.
- Conta no Wokwi para visualizar a simulação IoT.

### 1. Clonar o repositório

```bash
git clone URL_DO_REPOSITORIO
cd SmartPark
```

Substitua `URL_DO_REPOSITORIO` pelo endereço real do repositório.

### 2. Configurar o backend

Entre na pasta do backend:

```bash
cd backend
```

Crie um ambiente virtual:

```bash
python -m venv venv
```

Ative o ambiente virtual no Windows:

```powershell
.\venv\Scripts\Activate.ps1
```

Instale as dependências:

```bash
pip install -r requirements.txt
```

### 3. Configurar as variáveis de ambiente

Crie um arquivo `.env` na pasta do backend, seguindo as variáveis exigidas pelo código.

Exemplo de configuração:

```env
DEVICE_SHARED_SECRET=SEU_SEGREDO_DO_DISPOSITIVO
MERCADOPAGO_ACCESS_TOKEN=SEU_TOKEN_DE_TESTE
MERCADOPAGO_WEBHOOK_SECRET=SEU_SEGREDO_DO_WEBHOOK
```

Configure também as credenciais do Firebase conforme a implementação do projeto.

**Importante:** os valores acima são exemplos. Utilize suas próprias credenciais e nunca publique tokens, chaves privadas ou arquivos de conta de serviço no GitHub.

### 4. Executar o servidor

Com o ambiente virtual ativado:

```bash
python app.py
```

O backend poderá ser acessado localmente em:

```text
http://127.0.0.1:5000
```

### 5. Executar a simulação IoT

Abra o projeto do ESP32 no Wokwi, carregue o código e execute a simulação.

Para a comunicação com o backend local, configure o endereço da API e as credenciais do dispositivo de acordo com o ambiente de teste utilizado.

## Testes realizados

Durante o desenvolvimento, foram realizados testes envolvendo:

- Inicialização do backend Flask.
- Verificação de resposta HTTP do servidor.
- Comunicação entre o ambiente de simulação e o backend.
- Exposição do servidor local por meio do ngrok.
- Integração com o Mercado Pago Checkout Pro em ambiente de testes.
- Verificação do estado de pagamento.
- Envio de requisição ao endpoint de webhook.
- Verificação de autenticação do dispositivo IoT.
- Simulação dos componentes eletrônicos no Wokwi.

### Limitações identificadas

- A validação da assinatura do webhook do Mercado Pago retornou HTTP 401, sendo necessário ajustar a autenticação para concluir o fluxo automático.
- O funcionamento dos botões de entrada e manutenção no Wokwi necessita de validação adicional.
- A execução das integrações depende das credenciais e configurações de cada ambiente.

## Segurança

O projeto utiliza autenticação para a comunicação entre o dispositivo IoT e o backend.

As credenciais devem ser armazenadas em variáveis de ambiente ou arquivos locais não versionados.

Não devem ser publicados no repositório:

- Tokens de acesso.
- Segredos de autenticação.
- Chaves privadas do Firebase.
- Arquivos `.env`.
- Dados pessoais ou informações sensíveis de usuários.

## Estrutura do projeto

```text
SmartPark/
│
├── backend/
│   ├── app.py
│   ├── requirements.txt
│   └── ...
│
├── public/
│   ├── index.html
│   ├── css/
│   ├── js/
│   └── ...
│
├── docs/
│   ├── relatorio-tecnico.pdf
│   ├── arquitetura.png
│   └── testes/
│
├── wokwi/
│   ├── diagram.json
│   └── sketch.ino
│
├── .gitignore
└── README.md
```

*A estrutura acima é uma organização sugerida. Ajuste os nomes e caminhos de acordo com os arquivos existentes no repositório.*

## Documentação

O relatório técnico do projeto reúne informações complementares sobre desenvolvimento, arquitetura, testes, resultados e limitações identificadas.

Consulte a pasta `docs/` para acessar a documentação e os registros de testes disponibilizados.

## Autoria

Projeto acadêmico desenvolvido como proposta de aplicação de conceitos de desenvolvimento de sistemas, Internet das Coisas, integração de APIs e banco de dados.

**SmartPark — Tecnologia e conectividade para estacionamentos inteligentes.**