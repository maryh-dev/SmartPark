# Hardware simulado (Wokwi) — pinagem e nível lógico de 5 V

| Componente | Pino | GPIO ESP32 |
|---|---|---|
| HC-SR04 entrada | TRIG / ECHO | 5 / 34 (via divisor) |
| HC-SR04 saída | TRIG / ECHO | 17 / 35 (via divisor) |
| Servo (cancela) | PWM | 13 |
| LED verde / vermelho / amarelo (220 Ω) | — | 25 / 26 / 27 |
| Botão teste de entrada / manutenção | — | 32 / 33 (INPUT_PULLUP) |
| LCD 16x2 I2C (0x27) | SDA / SCL | 21 / 22 |

## Consideração de engenharia: Echo do HC-SR04 é 5 V
O HC-SR04 é alimentado com 5 V (VIN) e seu pino **ECHO responde em 5 V**, enquanto os GPIOs do ESP32 toleram **no máximo 3,3 V**. Ligar o ECHO direto pode danificar o ESP32 em hardware real.
Solução adotada no diagrama: **divisor resistivo** 1 kΩ (em série) + 2 kΩ (para GND): `Vout = 5 V × 2k / (1k + 2k) ≈ 3,33 V`. Usamos GPIO 34 e 35 (somente entrada) para o ECHO. Alternativas: level shifter bidirecional ou sensor de 3,3 V (HC-SR04P). O Wokwi não danifica o chip, mas o projeto documenta e implementa a proteção como seria em montagem real.
Obs.: o servo também é alimentado por VIN (5 V); em hardware real use fonte separada com GND comum.

## Segurança do ESP32
O ESP32 **não** guarda token do Mercado Pago, do Telegram nem credenciais do Firebase: só o `DEVICE_SECRET` de teste. Sem resposta válida do backend a cancela permanece fechada (`FALHA_REDE`/`ACESSO_NEGADO`). Este protótipo **não** deve controlar uma cancela real sem projeto de segurança.
