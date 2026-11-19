'#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <ESP32Servo.h>
#include <Wire.h>
#include <LiquidCrystal_I2C.h>

// ==========================================
// 1. CONFIGURACOES
// ==========================================

// WiFi do simulador Wokwi
const char* WIFI_SSID = "Wokwi-GUEST";
const char* WIFI_PASSWORD = "";

// Endereco HTTPS do backend Flask.
// Substitua pelo endereco do tunel HTTPS.
const char* API_BASE = "https://SEU-TUNEL-HTTPS";

// Credencial de dispositivo para ambiente de teste.
// Nunca utilize uma credencial real no repositorio.
const char* DEVICE_SECRET = "SUA_CHAVE_DE_TESTE";

const char* DEVICE_ID = "esp32_pelourinho_01";  // igual ao ID cadastrado em devices (seed_firestore.py)

// ==========================================
// 2. PINOS
// ==========================================

// Sensor de entrada
#define TRIG_ENTRADA 5
#define ECHO_ENTRADA 34

// Sensor de saida
#define TRIG_SAIDA 17
#define ECHO_SAIDA 35

// Servo
#define PIN_SERVO 13

// LEDs
#define LED_VERDE 25
#define LED_VERMELHO 26
#define LED_AMARELO 27

// Botoes
#define BTN_ENTRADA 32
#define BTN_MANUTENCAO 33

// ==========================================
// 3. OBJETOS
// ==========================================

Servo cancela;

LiquidCrystal_I2C lcd(0x27, 16, 2);

// ==========================================
// 4. MAQUINA DE ESTADOS
// ==========================================

enum Estado {
  INICIALIZANDO,
  PRONTO,
  VALIDANDO,
  ACESSO_LIBERADO,
  ACESSO_NEGADO,
  FALHA_REDE,
  MANUTENCAO
};

Estado estadoAtual = INICIALIZANDO;

// ==========================================
// 5. VARIAVEIS
// ==========================================

const int DISTANCIA_DETECCAO = 15;

bool modoManutencao = false;
bool cancelaAberta = false;

unsigned long tempoAbertura = 0;
unsigned long tempoEstado = 0;
unsigned long ultimoEventoEntrada = 0;
unsigned long ultimoEventoSaida = 0;

const unsigned long TEMPO_CANCELA = 4000;
const unsigned long INTERVALO_DETECCAO = 3000;

// ==========================================
// 6. IDENTIFICADOR UNICO
// ==========================================

String gerarEventId() {
  uint32_t aleatorio = esp_random();

  char identificador[32];

  snprintf(
    identificador,
    sizeof(identificador),
    "%08lX-%08lX",
    (unsigned long)aleatorio,
    (unsigned long)millis()
  );

  return String(identificador);
}

// ==========================================
// 7. CONTROLE DO LCD
// ==========================================

void mostrarLCD(String linha1, String linha2) {

  lcd.clear();

  lcd.setCursor(0, 0);
  lcd.print(linha1.substring(0, 16));

  lcd.setCursor(0, 1);
  lcd.print(linha2.substring(0, 16));
}

// ==========================================
// 8. CONTROLE DOS LEDS
// ==========================================

void desligarLEDs() {

  digitalWrite(LED_VERDE, LOW);
  digitalWrite(LED_VERMELHO, LOW);
  digitalWrite(LED_AMARELO, LOW);
}

void atualizarLEDs() {

  desligarLEDs();

  switch (estadoAtual) {

    case PRONTO:
      break;

    case VALIDANDO:
    case FALHA_REDE:
      digitalWrite(LED_AMARELO, HIGH);
      break;

    case ACESSO_LIBERADO:
      digitalWrite(LED_VERDE, HIGH);
      break;

    case ACESSO_NEGADO:
    case MANUTENCAO:
      digitalWrite(LED_VERMELHO, HIGH);
      break;

    default:
      digitalWrite(LED_AMARELO, HIGH);
      break;
  }
}

// ==========================================
// 9. ALTERACAO DE ESTADO
// ==========================================

void mudarEstado(Estado novoEstado) {

  estadoAtual = novoEstado;
  tempoEstado = millis();

  atualizarLEDs();

  switch (estadoAtual) {

    case INICIALIZANDO:
      mostrarLCD("SmartPark IoT", "Inicializando...");
      break;

    case PRONTO:
      mostrarLCD("SmartPark IoT", "Aguardando...");
      break;

    case VALIDANDO:
      mostrarLCD("Validando...", "Aguarde...");
      break;

    case ACESSO_LIBERADO:
      mostrarLCD("Acesso liberado", "Boa viagem!");
      break;

    case ACESSO_NEGADO:
      mostrarLCD("Acesso negado", "Cancela fechada");
      break;

    case FALHA_REDE:
      mostrarLCD("Falha de rede", "Acesso bloqueado");
      break;

    case MANUTENCAO:
      mostrarLCD("MANUTENCAO", "Sistema bloqueado");
      break;
  }
}

// ==========================================
// 10. SENSORES ULTRASSONICOS
// ==========================================

float medirDistancia(int trig, int echo) {

  digitalWrite(trig, LOW);
  delayMicroseconds(2);

  digitalWrite(trig, HIGH);
  delayMicroseconds(10);

  digitalWrite(trig, LOW);

  unsigned long duracao = pulseIn(echo, HIGH, 30000);

  if (duracao == 0) {
    return -1;
  }

  return duracao * 0.0343 / 2;
}

bool veiculoNaEntrada() {

  float distancia = medirDistancia(
    TRIG_ENTRADA,
    ECHO_ENTRADA
  );

  return distancia > 0 &&
         distancia < DISTANCIA_DETECCAO;
}

bool veiculoNaSaida() {

  float distancia = medirDistancia(
    TRIG_SAIDA,
    ECHO_SAIDA
  );

  return distancia > 0 &&
         distancia < DISTANCIA_DETECCAO;
}

// ==========================================
// 11. CONTROLE DA CANCELA
// ==========================================

void abrirCancela() {

  cancela.write(90);

  cancelaAberta = true;
  tempoAbertura = millis();
}

void fecharCancela() {

  cancela.write(0);

  cancelaAberta = false;
}

void controlarTempoCancela() {

  if (
    cancelaAberta &&
    millis() - tempoAbertura >= TEMPO_CANCELA
  ) {

    fecharCancela();

    if (!modoManutencao) {
      mudarEstado(PRONTO);
    }
  }
}

// ==========================================
// 12. CONEXAO WIFI
// ==========================================

void conectarWiFi() {

  WiFi.mode(WIFI_STA);

  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  Serial.print("Conectando ao WiFi");

  unsigned long inicio = millis();

  while (
    WiFi.status() != WL_CONNECTED &&
    millis() - inicio < 15000
  ) {

    delay(500);
    Serial.print(".");
  }

  Serial.println();

  if (WiFi.status() == WL_CONNECTED) {

    Serial.println("WiFi conectado!");
    Serial.println(WiFi.localIP());

  } else {

    Serial.println("Falha na conexao WiFi");
  }
}

// ==========================================
// 13. COMUNICACAO COM BACKEND
// ==========================================

bool enviarRequisicao(
  String rota,
  String tipoEvento,
  float distancia,
  bool* autorizado = nullptr,
  const char* campo = "allowed"
) {

  if (WiFi.status() != WL_CONNECTED) {

    Serial.println("Sem conexao WiFi");

    return false;
  }

  HTTPClient http;

  String url = String(API_BASE) + rota;

  http.setConnectTimeout(5000);
  http.setTimeout(5000);

  // Wokwi: sem validar certificado (apenas simulação). Em hardware real, fixe a CA do servidor.
  WiFiClientSecure clienteSeguro;
  clienteSeguro.setInsecure();
  bool iniciou = url.startsWith("https") ? http.begin(clienteSeguro, url) : http.begin(url);

  if (!iniciou) {

    Serial.println("Falha ao iniciar HTTP");

    return false;
  }

  http.addHeader("Content-Type", "application/json");
  http.addHeader("ngrok-skip-browser-warning", "1");  // evita a página de aviso do ngrok

  http.addHeader(
    "X-Device-Secret",
    DEVICE_SECRET
  );

  StaticJsonDocument<256> documento;

  documento["device_id"] = DEVICE_ID;
  documento["event_id"] = gerarEventId();
  documento["event_type"] = tipoEvento;
  documento["distance_cm"] = distancia;

  String corpo;

  serializeJson(documento, corpo);

  Serial.println("Enviando requisicao:");
  Serial.println(url);
  Serial.println(corpo);

  int codigoHTTP = http.POST(corpo);

  bool sucesso = false;

  if (codigoHTTP > 0) {

    String resposta = http.getString();

    Serial.print("HTTP: ");
    Serial.println(codigoHTTP);

    Serial.println(resposta);

    if (codigoHTTP >= 200 && codigoHTTP < 300) {

      sucesso = true;

      if (autorizado != nullptr) {

        StaticJsonDocument<512> respostaJSON;

        DeserializationError erro =
          deserializeJson(respostaJSON, resposta);

        if (!erro) {

          *autorizado =
            respostaJSON[campo] | false;

        } else {

          sucesso = false;
        }
      }
    }

  } else {

    Serial.print("Erro HTTP: ");
    Serial.println(http.errorToString(codigoHTTP));
  }

  http.end();

  return sucesso;
}

// ==========================================
// 14. VALIDACAO DE ENTRADA
// ==========================================

void validarEntrada() {

  if (modoManutencao) {
    return;
  }

  mudarEstado(VALIDANDO);

  Serial.println("Solicitando autorizacao...");

  float distancia = medirDistancia(
    TRIG_ENTRADA,
    ECHO_ENTRADA
  );

  bool autorizado = false;

  bool comunicacaoOK = enviarRequisicao(
    "/api/iot/access-request",
    "ENTRY",
    distancia,
    &autorizado
  );

  if (!comunicacaoOK) {

    fecharCancela();

    mudarEstado(FALHA_REDE);

    return;
  }

  if (autorizado) {

    Serial.println("Acesso autorizado!");

    mudarEstado(ACESSO_LIBERADO);

    abrirCancela();

  } else {

    Serial.println("Acesso negado!");

    fecharCancela();

    mudarEstado(ACESSO_NEGADO);
  }
}

// ==========================================
// 15. REGISTRO DE SAIDA
// ==========================================

void registrarSaida() {

  if (modoManutencao) {
    return;
  }

  Serial.println("Veiculo detectado na saida");

  float distancia = medirDistancia(
    TRIG_SAIDA,
    ECHO_SAIDA
  );

  bool registrado = false;

  bool sucesso = enviarRequisicao(
    "/api/iot/telemetry",
    "EXIT",
    distancia,
    &registrado,
    "registered"
  );

  if (sucesso && !registrado) {

    mostrarLCD("Saida nao", "registrada");

    Serial.println("Backend nao registrou a saida");

  } else if (sucesso) {

    mostrarLCD("Saida registrada", "Ate logo!");

    Serial.println("Evento de saida enviado!");

  } else {

    Serial.println("Falha ao registrar saida");

    mudarEstado(FALHA_REDE);

    fecharCancela();
  }
}

// ==========================================
// 16. BOTAO DE MANUTENCAO
// ==========================================

void controlarManutencao() {

  static bool estadoAnterior = HIGH;

  bool leitura = digitalRead(BTN_MANUTENCAO);

  if (
    leitura == LOW &&
    estadoAnterior == HIGH
  ) {

    delay(40);

    if (digitalRead(BTN_MANUTENCAO) == LOW) {

      modoManutencao = !modoManutencao;

      if (modoManutencao) {

        fecharCancela();

        mudarEstado(MANUTENCAO);

        Serial.println("Manutencao ativada");

      } else {

        mudarEstado(PRONTO);

        Serial.println("Manutencao desativada");
      }
    }
  }

  estadoAnterior = leitura;
}

// ==========================================
// 17. BOTAO DE TESTE
// ==========================================

void controlarBotaoEntrada() {

  static bool estadoAnterior = HIGH;

  bool leitura = digitalRead(BTN_ENTRADA);

  if (
    leitura == LOW &&
    estadoAnterior == HIGH
  ) {

    delay(40);

    if (digitalRead(BTN_ENTRADA) == LOW) {

      if (!modoManutencao) {
        validarEntrada();
      }
    }
  }

  estadoAnterior = leitura;
}

// ==========================================
// 18. SETUP
// ==========================================

void setup() {

  Serial.begin(115200);

  Wire.begin(21, 22);

  lcd.init();
  lcd.backlight();

  pinMode(TRIG_ENTRADA, OUTPUT);
  pinMode(ECHO_ENTRADA, INPUT);

  pinMode(TRIG_SAIDA, OUTPUT);
  pinMode(ECHO_SAIDA, INPUT);

  pinMode(LED_VERDE, OUTPUT);
  pinMode(LED_VERMELHO, OUTPUT);
  pinMode(LED_AMARELO, OUTPUT);

  pinMode(BTN_ENTRADA, INPUT_PULLUP);
  pinMode(BTN_MANUTENCAO, INPUT_PULLUP);

  cancela.attach(PIN_SERVO);

  fecharCancela();

  mudarEstado(INICIALIZANDO);

  conectarWiFi();

  if (WiFi.status() == WL_CONNECTED) {

    mudarEstado(PRONTO);

  } else {

    mudarEstado(FALHA_REDE);
  }

  Serial.println("SmartPark IoT iniciado!");
}

// ==========================================
// 19. LOOP PRINCIPAL
// ==========================================

void loop() {

  controlarManutencao();

  controlarTempoCancela();

  if (modoManutencao) {
    return;
  }

  if (estadoAtual != PRONTO) {

    if (
      estadoAtual == ACESSO_NEGADO &&
      millis() - tempoEstado > 2500
    ) {
      mudarEstado(PRONTO);
    }

    if (
      estadoAtual == FALHA_REDE &&
      millis() - tempoEstado > 5000
    ) {

      if (WiFi.status() != WL_CONNECTED) {
        WiFi.reconnect();
      }

      mudarEstado(
        WiFi.status() == WL_CONNECTED
          ? PRONTO
          : FALHA_REDE
      );
    }

    return;
  }

  controlarBotaoEntrada();

  if (estadoAtual != PRONTO) {
    return;
  }

  // Detecta veiculo na entrada
  if (
    millis() - ultimoEventoEntrada >
    INTERVALO_DETECCAO
  ) {

    if (veiculoNaEntrada()) {

      ultimoEventoEntrada = millis();

      validarEntrada();

      return;
    }
  }

  // Detecta veiculo na saida
  if (
    millis() - ultimoEventoSaida >
    INTERVALO_DETECCAO
  ) {

    if (veiculoNaSaida()) {

      ultimoEventoSaida = millis();

      registrarSaida();

      if (estadoAtual != PRONTO) {
        return;
      }
    }
  }

  delay(100);
}