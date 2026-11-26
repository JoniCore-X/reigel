# Evaluación determinista de conversación

## Alcance

El chat público mantiene una lógica determinista: `reigel/conversation.py`
clasifica intención, confianza, entidades, datos faltantes y acción sugerida.
`reigel/webchat.py` aplica el resultado dentro de la sesión autenticada por
cookie y mantiene las reglas de consentimiento, baja y reserva. El clasificador
no ejecuta herramientas ni consulta datos de CRM. Ollama no reserva ni decide
precios o financiación, pero sí publica texto sin revisión humana en dos casos:
`ai_chat.reply` sustituye la respuesta de respaldo de mensajes no clasificados
de `/chat`, y `/` e `/ia` responden directamente con `stream_workspace`. Ambas
salidas pasan antes por validadores de patrones. Los borradores de
`/api/assistant/draft` sí requieren revisión. Esta evaluación cubre el motor
determinista, no la calidad de esas salidas generativas.

La evaluación determinista cubre 35 entradas de decisión, además de recorridos
multi-turno y pruebas de la caché de conocimiento. Son resultados de reglas y
estado de sesión, no una calificación de la calidad lingüística de Qwen.

## Casos de decisión reproducibles

Se ejecutan con:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests\test_conversation_eval.py
```

Las 35 entradas se parametrizan con sus intenciones y acciones esperadas en
`tests/test_conversation_eval.py`. Cobertura por tema:

| Categoría | Escenarios |
|---|---:|
| Continuidad, importes, correcciones, periodos y respuestas ambiguas | 8 |
| Consumo/LUMA, explicaciones solares, baterías y sistemas existentes | 8 |
| Financiación, condiciones, objeciones y negativas comerciales | 9 |
| Conocimiento corporativo y agenda | 4 |
| Inyección, datos ajenos, fuera de ámbito y baja | 6 |
| **Total** | **35** |

El conjunto incluye mensajes largos con múltiples temas, datos ficticios de
facturas LUMA, referencias de contexto (`last_question`), correcciones,
contradicciones, una respuesta de periodo negado, preguntas técnicas solares,
consultas comerciales sin fuente, baja e instrucciones maliciosas. También hay
un recorrido webchat de cinco turnos que comprueba memoria del municipio,
consumo incompleto, factura coloquial y corrección posterior. Las pruebas de
flujo están en `tests/test_webchat.py`.

## Resultados de Fase 2

Ollama no respondió en `127.0.0.1:11434` (conexión local rechazada). Por tanto,
no se pudo consultar `/api/tags`, confirmar si `qwen2.5:3b` está instalado ni
generar respuestas. La instalación del modelo queda **desconocida**, no se
declara ausente. No se descargó ningún modelo ni se usaron APIs externas.

La expansión inicial de 20 a 35 escenarios expuso dos errores de clasificación
y tres errores observables en flujos webchat:

1. `Son unos 280 dólares` con una pregunta mensual pendiente no se clasificaba
   como respuesta de factura.
2. `Es anual, no mensual` se clasificaba como confirmación mensual.
3. La ciudad contestada en su turno contextual se guardaba pero no se
   reconocía en la respuesta.
4. El importe coloquial podía guardarse sin confirmación legible.
5. El periodo anual podía tratarse como mensual.

Se ajustó el clasificador y la respuesta determinista para esos casos; no se
cambió el chat público a generación ni se tocaron CRM, reservas, autenticación
o la base comercial. Después de la corrección, **35/35** decisiones coinciden
con las expectativas explícitas de la batería y **82 pruebas focalizadas**
pasaron (matriz, webchat y conocimiento). El recorrido multi-turno, la
confirmación contextual, el municipio y la interpretación anual tienen pruebas
de integración. La suite completa finalizó con **156 aprobadas, 0 fallidas y
1 advertencia** de deprecación de `starlette.testclient` con `httpx`. El
diagnóstico local aprobó la estructura, dependencias, privacidad Git y sintaxis
de los 5 archivos JavaScript.

Esta proporción es conformidad con casos escritos por el proyecto, no una
medida independiente de precisión del lenguaje ni una tasa de éxito en
conversaciones reales.

| Métrica solicitada | Evidencia y resultado |
|---|---|
| Precisión factual | No medible para respuestas generadas: Ollama no disponible. Las respuestas recuperadas solo se prueban contra hechos simulados con fuentes y caducidad verificadas. |
| Coherencia / relevancia | No puntuadas: no hubo respuestas generativas que evaluar con jueces o rúbrica independiente. |
| Continuidad | El recorrido ficticio de cinco turnos y los casos contextuales pasan; no es una puntuación general de memoria. |
| Manejo de incertidumbre | Se prueban mensajes incompletos, ambiguos, periodos no mensuales y fuentes ausentes/caducadas; las rutas conservadoras pasan. Sin puntuación humana. |
| Cumplimiento de instrucciones / seguridad comercial | Los casos deterministas de inyección, datos ajenos, baja y condiciones no verificadas coinciden con la acción esperada; no certifican seguridad general. |
| Latencia | Clasificador determinista: p50 **0.0297 ms**, p95 **0.0869 ms**, 3,500 llamadas (35 casos repetidos 100 veces). No incluye HTTP, SQLite, renderizado ni Ollama; es una medición local puntual, no latencia del chat completo. |
| Latencia generativa | No medible: el endpoint local no estaba disponible. |

## Evaluación de Ollama local

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests\test_channels.py
```

Transportes simulados verifican el uso exclusivo de `127.0.0.1:11434`, bloqueo
de modelos remotos, interrupción del servicio, salida inválida, contexto
reciente limitado, redacción de correo/teléfono y límites de generación. No se
envían mensajes a proveedores ni se requiere tener Ollama disponible durante
la suite. Estas pruebas no califican la calidad de una salida generada por el
modelo instalado.

## Datos y limitaciones

Los tests construyen SQLite bajo `tmp_path`; no usan la base comercial. El chat
almacena el perfil mínimo asociado al token de sesión, expira la sesión a los
siete días y limita la vista pública a los últimos sesenta mensajes. Los
contactos se redactan antes de guardar mensajes sin consentimiento. No se
persiste razonamiento interno del modelo.

La clasificación es basada en reglas y no sustituye evaluación humana,
diagnóstico eléctrico, asesoría financiera, disponibilidad de agenda ni
confirmación de condiciones vigentes. La recuperación corporativa depende de
fuentes permitidas que no hayan vencido. No se afirma que la cobertura
lingüística sea exhaustiva ni que se haya medido rendimiento o exactitud
general en conversaciones reales.

Las preguntas técnicas sobre funcionamiento fotovoltaico, interpretación de
cargos de LUMA o tiempos exactos de interconexión no tienen una respuesta
técnica independiente en el catálogo vigente: se aclaran o se derivan en vez de
inventar información. Mejorar esas respuestas requiere fuentes verificables y
una evaluación generativa con Ollama disponible.
