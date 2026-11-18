# Relatório de testes (T01–T15)

Preencha *Resultado observado*, *Evidência* (print/log **sem segredos**) e *Correção*.

| ID | Ação | Resultado esperado | Resultado observado | Evidência | Correção |
|---|---|---|---|---|---|
| T01 | Abrir dashboard | Mapa carrega; marcadores mostram dados do projeto |  |  |  |
| T02 | Datas inválidas (saída antes da chegada) | Backend rejeita com 400 |  |  |  |
| T03 | Duas pessoas reservam a mesma vaga/horário | No máximo uma reserva; a outra recebe 409 |  |  |  |
| T04 | Pagamento rejeitado (titular OTHE) | Reserva não confirma; entrada negada |  |  |  |
| T05 | Pagamento aprovado (titular APRO) com webhook válido | CONFIRMED uma única vez; mensagem no Telegram |  |  |  |
| T06 | Mesmo webhook duas vezes | Sem confirmação/mensagem duplicada |  |  |  |
| T07 | Entrada com reserva válida | Servo abre, LED verde, evento GRANTED |  |  |  |
| T08 | Entrada sem reserva paga | Cancela fechada, LED vermelho |  |  |  |
| T09 | Backend fora do ar | ESP32 em FALHA_REDE, sem liberar |  |  |  |
| T10 | Registrar saída | Horário real, duração e valor final salvos |  |  |  |
| T11 | Repetir evento de saída (mesmo event_id) | Sem novo ticket nem cobrança |  |  |  |
| T12 | Telegram indisponível | Ticket salvo; telegram_status = PENDING_RETRY |  |  |  |
| T13 | Alterar preço pelo navegador | Backend ignora; preço do Firestore |  |  |  |
| T14 | Consultar reserva de outro usuário | 404 sem revelar existência |  |  |  |
| T15 | Verificar repositório Git | Nenhum token/segredo versionado |  |  |  |
