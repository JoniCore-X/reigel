# Batería de evaluación de R.E.I.G.E.L.

`casos_ia.json` es el conjunto de casos con los que se mide la IA. Cada caso lleva
expectativas **comprobables**, no juicios de valor: qué intención debe detectar el
motor, qué objeción debe extraer, qué tema técnico debe recuperar, y qué debe o no
debe aparecer en la respuesta del modelo.

## Dos particiones, y no se mezclan

- **`optimizacion`** — con estos se afina. Se pueden mirar las respuestas, cambiar el
  prompt y volver a correr tantas veces como haga falta.
- **`final`** — reservados. Se corren **al final**, una vez, para saber si lo que se
  afinó sirve de verdad o solo se ajustó a los casos que se estaban mirando.

Afinar contra los casos finales los invalida: dejan de medir y pasan a ser parte del
entrenamiento. Si hay que usarlos, se escriben casos finales nuevos.

## Qué mide cada grupo

| Grupo | Qué comprueba | Necesita el modelo |
| --- | --- | --- |
| `precision_tecnica` | Que el recuperador devuelva el tema y el estado correctos | No |
| `deteccion_objeciones` | Que el extractor saque la objeción que es | No |
| `seguridad` | Que el motor clasifique bien inyecciones, bajas y privacidad | No |
| `seguimiento_instrucciones` | Que la respuesta cierre preguntando, sea breve y pase los validadores | Sí |
| `coherencia` | Que esté en español, sin marcadores del prompt y sin contradecirse | Sí |
| `capacidad_comercial` | Que no prometa y que lleve hacia la evaluación | Sí |
| `ambiguo` | Que el motor admita que no sabe y el mensaje llegue al modelo | Mixto |

Lo que no necesita el modelo corre en la suite normal (`tests/test_eval_battery.py`),
rápido y en cada cambio. Lo que sí lo necesita corre con `scripts/evaluar_ia.py`, que
pide Ollama encendido.

## Cómo correrla

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_eval_battery.py -q
.\.venv\Scripts\python.exe scripts\evaluar_ia.py
.\.venv\Scripts\python.exe scripts\evaluar_ia.py --particion final --json resultado.json
```

## Cómo añadir casos

Un caso sin expectativa comprobable no sirve: se vuelve una opinión. Campos:

- `id` — único y estable; no se renumera al insertar.
- `grupo` — uno de la tabla de arriba.
- `particion` — `optimizacion` o `final`.
- `mensaje` — lo que escribe la persona, tal cual.
- `perfil` — opcional, lo que el chat ya sabía de ella.
- `espera` — las comprobaciones. Todas opcionales, pero al menos una:
  - `intencion` — la que debe devolver `conversation.classify_message`.
  - `tema_tecnico` y `estado_tecnico` — lo que debe devolver `knowledge.answer_technical`.
  - `objecion` — la afirmación exacta que debe extraer `agent.extract`.
  - `creencia` — otro asunto que la extracción debe reconocer, como `{"decisor": "..."}`.
  - `respuesta_valida` — si la respuesta del modelo debe pasar `validate_reply`.
  - `cierra_preguntando` — si debe terminar con una pregunta.
  - `no_debe_contener` — lista de expresiones regulares que no pueden aparecer.
  - `maximo_palabras` — tope de extensión.
