#Lee las parejas en estado PENDIENTE de Firestore.
#Carga las personalidades de los gemelos y las instrucciones del escenario.
#Llama a la API de IA (OpenAI, Gemini, Anthropic) para simular los diálogos, calcula el puntaje de compatibilidad y extrae las memorias.
#Guarda los resultados en la subcolección simulaciones y actualiza el estado.

import os
import json
import datetime 

from gemelo_perfil import construir_perfil_gemelo
from compatibilidad import analizar_conversacion, actualizar_memoria, calcular_compatibilidad
from geolocalizacion import ordenar_por_cercania

# El cliente de OpenAI se crea recién al usarlo (ver _client()), no al importar
# el módulo: así se puede armar/comparar perfiles y correr los tests sin tener
# el paquete openai instalado ni una API key configurada.
_client = None


def client():
    global _client
    if _client is None:
        from openai import OpenAI
        _client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    return _client


# Por ahora solo se prueba con "Algo serio" -- se sacaron los escenarios que
# eran exclusivos de "Algo casual"/"Nuevas amistades" (planes de finde, humor
# y coqueteo, hobbies para compartir, buena onda en grupo) y se dejó
# "tipos_relacion" en ["Algo serio"] en todos. El mecanismo de filtrado
# (escenarios_para_tipo, más abajo) queda igual -- cuando se vuelva a testear
# con otros tipos de relación, alcanza con agregar escenarios nuevos con su
# tipo correspondiente, no hace falta tocar la lógica.
escenarios_db = [

    {
        "titulo": "Arte y tecnología",

        "contexto": """
        Ambos coinciden en una cafetería virtual moderna.
        La conversación comienza hablando sobre inteligencia artificial,
        creatividad y herramientas digitales utilizadas en arte,
        música o diseño.
        """,

        "objetivo": [
            "Evaluar creatividad",
            "Detectar curiosidad intelectual",
            "Medir apertura a nuevas ideas",
            "Analizar capacidad de debate"
        ],

        "tension": """
        El tema puede derivar en opiniones distintas sobre tecnología,
        autenticidad creativa y cambios culturales.
        """,

        "tono": "Intelectual, relajado y curioso.",
        "tipos_relacion": ["Algo serio"]
    },

    {
        "titulo": "Finanzas y estilo de vida",

        "contexto": """
        La conversación deriva hacia hábitos financieros,
        prioridades personales y formas de organizar la vida adulta.
        Hablan sobre trabajo, gastos, metas y estabilidad.
        """,

        "objetivo": [
            "Evaluar responsabilidad",
            "Detectar prioridades personales",
            "Analizar compatibilidad de estilo de vida",
            "Medir madurez emocional"
        ],

        "tension": """
        Pueden aparecer diferencias sobre dinero,
        planificación, consumo o visión del futuro.
        """,

        "tono": "Maduro, honesto y relajado.",
        "tipos_relacion": ["Algo serio"]
    },

    {
        "titulo": "Relación con la familia",

        "contexto": """
        La conversación evoluciona hacia vínculos familiares,
        costumbres, límites personales y relaciones importantes
        dentro de sus vidas.
        """,

        "objetivo": [
            "Entender valores personales",
            "Detectar madurez emocional",
            "Evaluar independencia emocional",
            "Analizar empatía"
        ],

        "tension": """
        Pueden surgir diferencias en la forma de ver la familia,
        privacidad, apoyo emocional o independencia.
        """,

        "tono": "Personal, emocional y reflexivo.",
        "tipos_relacion": ["Algo serio"]
    },

    {
        "titulo": "Resolución de conflictos",

        "contexto": """
        Ambos comienzan a hablar sobre discusiones,
        malos entendidos y cómo suelen reaccionar
        frente a situaciones incómodas o tensas.
        """,

        "objetivo": [
            "Evaluar inteligencia emocional",
            "Detectar impulsividad",
            "Analizar comunicación emocional",
            "Medir empatía"
        ],

        "tension": """
        La conversación puede revelar diferencias
        en la manera de afrontar conflictos,
        pedir disculpas o expresar emociones.
        """,

        "tono": "Honesto, introspectivo y respetuoso.",
        "tipos_relacion": ["Algo serio"]
    },

    {
        "titulo": "Tareas del hogar y convivencia",

        "contexto": """
        La charla deriva hacia hábitos cotidianos,
        organización personal y experiencias viviendo solos,
        con amigos o con familia.
        """,

        "objetivo": [
            "Evaluar hábitos de convivencia",
            "Detectar nivel de responsabilidad",
            "Analizar compatibilidad cotidiana",
            "Medir flexibilidad"
        ],

        "tension": """
        Pueden aparecer diferencias sobre orden,
        limpieza, rutina o formas de compartir responsabilidades.
        """,

        "tono": "Liviano, cotidiano y natural.",
        "tipos_relacion": ["Algo serio"]
    },

    {
        "titulo": "Carrera profesional y ambiciones",

        "contexto": """
        La conversación gira hacia estudios,
        objetivos laborales, motivaciones personales
        y expectativas de crecimiento profesional.
        """,

        "objetivo": [
            "Evaluar ambición",
            "Detectar motivaciones personales",
            "Analizar visión de futuro",
            "Medir compatibilidad de objetivos"
        ],

        "tension": """
        Pueden surgir diferencias en prioridades,
        ritmo de vida, éxito profesional o balance personal.
        """,

        "tono": "Motivador, reflexivo y maduro.",
        "tipos_relacion": ["Algo serio"]
    },

    {
        "titulo": "Expectativas en una relación",

        "contexto": """
        Ambos comienzan a hablar sobre qué buscan
        emocionalmente en una pareja y qué consideran importante
        en una relación sana y duradera.
        """,

        "objetivo": [
            "Evaluar compatibilidad emocional",
            "Detectar necesidades afectivas",
            "Analizar expectativas románticas",
            "Medir madurez relacional"
        ],

        "tension": """
        Pueden aparecer diferencias sobre compromiso,
        comunicación, independencia o demostraciones afectivas.
        """,

        "tono": "Emocional, abierto y sincero.",
        "tipos_relacion": ["Algo serio"]
    },

    {
        "titulo": "Música y emociones",

        "contexto": """
        La conversación comienza hablando sobre música,
        artistas favoritos y canciones asociadas
        a momentos importantes de sus vidas.
        """,

        "objetivo": [
            "Detectar sensibilidad emocional",
            "Evaluar gustos culturales",
            "Analizar conexión emocional",
            "Medir espontaneidad"
        ],

        "tension": """
        Las diferencias de gustos o significado emocional
        pueden generar debates interesantes o conexión profunda.
        """,

        "tono": "Relajado, emocional y espontáneo.",
        "tipos_relacion": ["Algo serio"]
    },

    {
        "titulo": "Películas y experiencias personales",

        "contexto": """
        Ambos empiezan hablando sobre películas,
        series o historias que los hayan marcado emocionalmente
        o cambiado su forma de pensar.
        """,

        "objetivo": [
            "Evaluar profundidad emocional",
            "Detectar intereses culturales",
            "Analizar empatía",
            "Medir capacidad reflexiva"
        ],

        "tension": """
        Pueden surgir diferencias en sensibilidad,
        humor o interpretación emocional de las historias.
        """,

        "tono": "Reflexivo, relajado y cercano.",
        "tipos_relacion": ["Algo serio"]
    }
]


def escenarios_para_tipo(tipo_relacion):
    """Devuelve los índices de escenarios_db relevantes para el tipo de
    relación buscado (perfil.get('busco'): "Algo serio" / "Algo casual" /
    "Nuevas amistades" / "Sin definir"). Si no matchea nada corre todos."""

    tipo = (tipo_relacion or "").strip()
    indices = [i for i, e in enumerate(escenarios_db) if tipo in e.get("tipos_relacion", [])]
    return indices if indices else list(range(len(escenarios_db)))


def armar_escenario_personalizado(texto):
    """El usuario pidió simular algo puntual (ej: "simulá que discutimos por
    plata") -- se arma un escenario al vuelo con ese texto en vez de usar uno
    de escenarios_db. No hace un llamado extra a OpenAI para esto: el texto
    del usuario ya es suficiente contexto para el prompt del escenario."""
    texto = texto.strip()
    titulo = texto if len(texto) <= 60 else texto[:57] + "..."
    return {
        "titulo": titulo,
        "contexto": texto,
        "tono": "Natural, como si fuera una conversación real entre dos personas conociéndose.",
    }

def _directiva(valor, texto_alto, texto_bajo, umbral=0.65):
    """Traduce un valor numérico 0-1 (ej: personalidad.introversion) en una
    instrucción concreta de comportamiento. Un modelo sigue mucho mejor
    "escribís mensajes de una sola oración" que un dato suelto como
    "Introversión: 0.9" sin ninguna indicación de qué hacer con ese número
    -- por eso el prompt viejo (solo números) no se notaba en las respuestas.
    Valores cerca del medio (ni alto ni bajo) no generan ninguna directiva,
    para no forzar un rasgo que la persona no marcó con claridad."""
    if valor >= umbral:
        return texto_alto
    if valor <= 1 - umbral:
        return texto_bajo
    return ""


def generar_prompt_gemelo(perfil, memoria=None):

    # =====================================================
    # PERFIL PSICOLOGICO
    # =====================================================

    personalidad = perfil.get("personalidad", {})

    directivas_personalidad = list(filter(None, [
        _directiva(personalidad.get('introversion', 0.5),
            "Sos bastante introvertido/a: profundizás de a poco, no bombardeás con preguntas ni te lanzás de lleno a temas personales enseguida.",
            "Sos bastante extrovertido/a: hablás con soltura, hacés preguntas seguido y te entusiasmás fácil con temas nuevos."),
        _directiva(personalidad.get('empatia', 0.5),
            "Sos muy empático/a: validás lo que siente la otra persona antes de opinar, mostrás interés genuino en cómo se siente.",
            "Vas más al grano con las emociones ajenas: te enfocás más en los hechos que en cómo se siente el otro."),
        _directiva(personalidad.get('sarcasmo', 0.5),
            "Tenés un humor bastante sarcástico o irónico, lo metés seguido en tus respuestas.",
            "No sos de tirar sarcasmo -- tu humor, si aparece, es directo y sin doble intención."),
        _directiva(personalidad.get('apertura_mental', 0.5),
            "Sos muy abierto/a a ideas nuevas, te copás fácil con propuestas distintas a lo que ya conocés.",
            "Sos más escéptico/a con ideas nuevas, preferís lo conocido antes de sumarte a algo distinto."),
        _directiva(personalidad.get('ambicion', 0.5),
            "Sos ambicioso/a: te gusta hablar de metas, crecimiento y planes a futuro.",
            "No te mueve tanto la ambición, vivís más el presente que planificando el futuro."),
        _directiva(personalidad.get('sensibilidad_emocional', 0.5),
            "Sos emocionalmente sensible: las cosas te afectan con facilidad y lo mostrás.",
            "Sos bastante estable emocionalmente, no te alteran fácil los temas sensibles."),
        _directiva(personalidad.get('necesidad_afecto', 0.5),
            "Necesitás bastante validación y cercanía afectiva, y lo buscás en la conversación.",
            "Sos independiente afectivamente, no necesitás validación constante del otro."),
        _directiva(personalidad.get('independencia', 0.5),
            "Valorás mucho tu independencia, y lo dejás claro cuando se habla de planes en pareja.",
            "No te cuesta depender del otro, disfrutás de la cercanía y de hacer las cosas en conjunto."),
        _directiva(personalidad.get('tolerancia_conflicto', 0.5),
            "Tolerás bien el conflicto: no te incomoda discutir o no estar de acuerdo.",
            "Evitás el conflicto, preferís bajar un tema antes que discutir."),
    ]))

    personalidad_txt = "PERFIL PSICOLÓGICO (cómo se traduce en tu forma de hablar):\n" + \
        "\n".join(f"    - {d}" for d in directivas_personalidad) if directivas_personalidad else ""

    # =====================================================
    # ESTILO CONVERSACIONAL
    # =====================================================

    estilo_chat = perfil.get("estilo_chat", {})

    directivas_estilo = [
        "ESCRIBÍS MENSAJES MUY CORTOS: una sola oración, a veces solo unas pocas palabras. Nunca mandes párrafos largos."
        if estilo_chat.get('mensajes_cortos', False) else
        "Podés escribir mensajes un poco más desarrollados (2-3 oraciones), sin pasarte.",

        "Metés humor seguido: chistes, comentarios graciosos, ironía liviana."
        if estilo_chat.get('usa_humor', False) else
        "No forzás chistes, tu tono es más serio y directo.",

        "Coqueteás activamente: indirectas, piropos, doble sentido."
        if estilo_chat.get('coqueto', False) else
        "Mantenés un tono amistoso pero sin coquetear.",

        "Analizás lo que te dicen antes de responder, hacés preguntas de seguimiento con sustancia."
        if estilo_chat.get('analitico', False) else
        "Respondés más espontáneo, sin sobre-pensarlo.",
    ]

    estilo = "ESTILO CONVERSACIONAL (seguilo al pie de la letra):\n" + \
        "\n".join(f"    - {d}" for d in directivas_estilo)

    # =====================================================
    # VALORES PERSONALES
    # =====================================================

    valores = perfil.get("valores", {})

    valores_prompt = f"""
    VALORES PERSONALES:

    - Importancia de familia: {valores.get('familia', 0.5)}
    - Ambición profesional: {valores.get('ambicion', 0.5)}
    - Necesidad de estabilidad: {valores.get('estabilidad', 0.5)}
    - Gusto por aventura: {valores.get('aventura', 0.5)}
    """

    # =====================================================
    # CONFLICTOS Y NOTAS PERSONALES
    # (antes se armaban en usuarios_db pero nunca se insertaban en el prompt)
    # =====================================================

    conflictos_prompt = ""
    conflictos = perfil.get("conflictos", {})
    if conflictos:
        conflictos_prompt = "\n    CÓMO MANEJA LOS CONFLICTOS:\n"
        for descripcion in conflictos.values():
            conflictos_prompt += f"    - {descripcion}\n"

    notas_prompt = ""
    notas = perfil.get("notas_personales", [])
    if notas:
        notas_prompt = "\n    NOTAS PERSONALES (en sus propias palabras):\n"
        for nota in notas:
            notas_prompt += f"    - {nota}\n"

    bio_prompt = ""
    bio = perfil.get("bio", "")
    if bio:
        bio_prompt = f"\n    CÓMO SE DESCRIBE A SÍ MISMO/A:\n    {bio}\n"

    # =====================================================
    # MEMORIA CONVERSACIONAL
    # =====================================================

    memoria_prompt = ""

    if memoria:

        recuerdos = memoria.get("interacciones", [])

        if len(recuerdos) > 0:

            ultimos = recuerdos[-3:]

            memoria_prompt = "\nMEMORIA DE INTERACCIONES:\n"

            for r in ultimos:

                memoria_prompt += f"""
                - Química previa: {r['quimica']}
                - Comodidad: {r['comodidad']}
                - Tensión: {r['tension']}
                - Resumen: {r['resumen']}
                """

    # =====================================================
    # PROMPT FINAL
    # =====================================================

    prompt = f"""
    Eres el gemelo digital de un usuario real
    dentro de una aplicación de citas.

    Tu objetivo es conversar naturalmente
    para descubrir compatibilidad emocional,
    intelectual y social con la otra persona.

    =====================================================
    IDENTIDAD
    =====================================================

    Edad:
    {perfil.get('edad') or 'no especificada'}

    Profesión:
    {perfil.get('profesion') or 'no especificada'}

    Intereses:
    {", ".join(perfil.get('intereses', [])) or "no especificados"}

    =====================================================
    PERSONALIDAD
    =====================================================

    {personalidad_txt}

    =====================================================
    ESTILO
    =====================================================

    {estilo}

    =====================================================
    VALORES
    =====================================================

    {valores_prompt}
    {conflictos_prompt}
    {bio_prompt}
    {notas_prompt}
    =====================================================
    MEMORIA
    =====================================================

    {memoria_prompt}

    =====================================================
    REGLAS DE COMPORTAMIENTO
    =====================================================

    1. Habla SIEMPRE en primera persona.

    2. Mantén una conversación humana,
    natural y emocionalmente coherente.

    3. No actúes como asistente virtual.

    4. No expliques tus decisiones internas.

    5. Tus respuestas deben tener entre
    1 y 3 oraciones normalmente.

    6. No inventes hechos extremadamente
    específicos sobre tu vida.

    7. Si no sabes algo, responde de forma
    natural sin romper personaje.

    8. Tu personalidad debe influir
    constantemente en:
        - tono,
        - humor,
        - profundidad emocional,
        - nivel de curiosidad,
        - forma de debatir,
        - coqueteo,
        - empatía.

    9. No intentes agradar siempre.
    Puedes estar en desacuerdo si encaja
    con tu personalidad.

    10. La conversación debe sentirse
    espontánea y no perfecta.

    11. Respondé de forma ESPECÍFICA a lo último que dijo la otra persona
    (algo concreto que mencionó, no una reacción genérica tipo "qué
    interesante" que serviría para cualquier mensaje). Mostrá que
    escuchaste de verdad antes de agregar algo tuyo.

    12. No te quedes dando vueltas sobre la misma pregunta muchos turnos
    seguidos. Si ya charlaron un par de intercambios sobre el mismo punto
    puntual, sumá un ángulo nuevo relacionado al escenario en vez de
    repreguntar "¿y vos?" de nuevo -- una conversación real avanza, no gira
    en el mismo lugar.
    """

    return prompt

def simular_cita(perfil1, perfil2, turnos=3, escenario=0, memoria1=None, memoria2=None):
    """escenario puede ser un índice de escenarios_db o un dict
    {"titulo","contexto","tension","tono"} armado al vuelo para una simulación
    a pedido del usuario (ej: "simulá que discutimos por plata").

    memoria1/memoria2 son lo que cada gemelo recuerda de interacciones previas
    con el otro (ver compatibilidad.actualizar_memoria) -- se usan en
    simular_relacion_completa para que, al correr varios escenarios seguidos,
    la charla se sienta continuada en vez de arrancar de cero cada vez."""

    print("Iniciando simulación...\n")

    historial_chat = []

    escenario_actual = escenario if isinstance(escenario, dict) else escenarios_db[escenario]

    contexto_escenario = f"""
    ESCENARIO:

    Titulo:
    {escenario_actual["titulo"]}

    Contexto:
    {escenario_actual["contexto"]}

    Tono:
    {escenario_actual["tono"]}
    """

    nombre1 = perfil1.get("nombre", "ALPHA")
    nombre2 = perfil2.get("nombre", "BETA")

    prompt_1 = generar_prompt_gemelo(perfil1, memoria=memoria1)
    prompt_2 = generar_prompt_gemelo(perfil2, memoria=memoria2)

    # El mensaje inicial ya no es un texto fijo igual en todas las
    # simulaciones -- lo genera el mismo prompt_1 de siempre (con su
    # personalidad y estilo), solo agregándole la instrucción de que en este
    # turno le toca arrancar la charla. No hace falta una función aparte:
    # es el mismo generar_prompt_gemelo, solo que este primer llamado no
    # tiene mensajes previos a los que responder.
    instruccion_inicio = "\n\n    Te toca arrancar VOS la conversación sobre el escenario de arriba. Mandá un primer mensaje corto y natural, como si le escribieras por primera vez a alguien que recién conociste."

    response_inicio = client().chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": contexto_escenario + prompt_1 + instruccion_inicio},
        ]
    )
    ultimo_mensaje = response_inicio.choices[0].message.content

    print(f"{nombre1}: {ultimo_mensaje}\n")

    historial_chat.append({

        "role": "user",
        "name": nombre1,
        "content": ultimo_mensaje
    })

    # historial_chat (arriba) es la versión "para humanos" -- la que se
    # guarda y se le pasa a analizar_conversacion, con roles fijos y el
    # nombre de quién habló. Pero para pedirle al modelo el turno de CADA
    # gemelo hace falta una vista de la conversación DESDE SU perspectiva:
    # sus propios mensajes anteriores como "assistant", los del otro como
    # "user". Si se le manda la misma lista a los dos (como antes), la
    # llamada de un gemelo termina con el último mensaje ya en rol
    # "assistant" sin ningún "user" nuevo en el medio -- ahí el modelo tiende
    # a continuar/repetir ese mismo turno en vez de responder como otra
    # persona (así se producía la repetición literal del mensaje anterior).
    vista_1 = []
    vista_2 = [{"role": "user", "content": ultimo_mensaje}]

    for _ in range(turnos):

        # =================================================
        # PERFIL 2 RESPONDE
        # =================================================

        response_2 = client().chat.completions.create(

            model="gpt-4o-mini",

            messages=[

                {
                    "role": "system",
                    "content":
                        contexto_escenario +
                        prompt_2
                },

                *vista_2
            ]
        )

        msg_2 = response_2.choices[0].message.content

        print(f"{nombre2}: {msg_2}\n")

        historial_chat.append({

            "role": "assistant",
            "name": nombre2,
            "content": msg_2
        })
        vista_2.append({"role": "assistant", "content": msg_2})
        vista_1.append({"role": "user", "content": msg_2})

        # =================================================
        # PERFIL 1 RESPONDE
        # =================================================

        response_1 = client().chat.completions.create(

            model="gpt-4o-mini",

            messages=[

                {
                    "role": "system",
                    "content":
                        contexto_escenario +
                        prompt_1
                },

                *vista_1
            ]
        )

        msg_1 = response_1.choices[0].message.content

        print(f"{nombre1}: {msg_1}\n")

        historial_chat.append({

            "role": "assistant",
            "name": nombre1,
            "content": msg_1
        })
        vista_1.append({"role": "assistant", "content": msg_1})
        vista_2.append({"role": "user", "content": msg_1})

    analisis = analizar_conversacion(historial_chat)
    score = calcular_compatibilidad(perfil1, perfil2, analisis)

    return historial_chat, analisis, score


# =====================================================
# GUARDADO DE SIMULACIONES
#
# Las simulaciones las tiene que poder ver el usuario después (en gemelo.html /
# matches.html), así que no alcanza con imprimirlas: hay que persistirlas.
# registro_simulacion() arma el documento con la forma pensada para Firestore
# (colección matches/{par_id}/simulaciones/{id}); guardar_simulacion_local()
# es la implementación de referencia para desarrollar y testear sin backend.
#
# Para guardar esto en Firestore de verdad hace falta el paquete firebase-admin
# y una clave de cuenta de servicio del proyecto (se descarga desde la consola
# de Firebase: Configuración del proyecto > Cuentas de servicio > Generar nueva
# clave privada) — eso es lo único que vas a tener que hacer vos aparte; el
# reemplazo de guardar_simulacion_local() por un doc.set(registro) es directo
# porque registro_simulacion() ya devuelve algo serializable tal cual.
# =====================================================

def _par_id(uid1, uid2):
    return f"{str(uid1)}_{str(uid2)}"if str(uid1) < str(uid2) else f"{str(uid2)}_{str(uid1)}"


def registro_simulacion(uid1, perfil1, uid2, perfil2, escenario, historial_chat, analisis, score, umbral=0.75):

    escenario_actual = escenario if isinstance(escenario, dict) else escenarios_db[escenario]

    return {
        "par_id": _par_id(uid1, uid2),
        "usuario_1": {"uid": uid1, "nombre": perfil1.get("nombre", "")},
        "usuario_2": {"uid": uid2, "nombre": perfil2.get("nombre", "")},
        "escenario": {
            "titulo": escenario_actual["titulo"],
            "tono": escenario_actual["tono"],
        },
        "fecha": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "historial_chat": historial_chat,
        "analisis": analisis,
        "score": score,
        "umbral_usado": umbral,
        "supera_umbral": score["compatibilidad_total"] >= umbral,
    }


def guardar_simulacion_local(registro, carpeta="simulaciones_guardadas"):
    os.makedirs(carpeta, exist_ok=True)
    nombre_archivo = f"{registro['par_id']}_{registro['fecha'].replace(':', '-')}.json"
    ruta = os.path.join(carpeta, nombre_archivo)
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(registro, f, indent=2, ensure_ascii=False)
    return ruta


def simular_y_registrar(uid1, perfil1, uid2, perfil2, turnos=3, escenario=0, umbral=0.75, guardar=guardar_simulacion_local):
    """Corre la simulación completa y devuelve el registro listo para guardar
    (y ya guardado, salvo que se pase guardar=None). `guardar` recibe el
    registro y decide dónde persistirlo -- local por default, pero se le puede
    pasar cualquier función que escriba a Firestore u otro lado."""

    historial_chat, analisis, score = simular_cita(perfil1, perfil2, turnos=turnos, escenario=escenario)

    registro = registro_simulacion(
        uid1, perfil1, uid2, perfil2, escenario, historial_chat, analisis, score, umbral
    )

    if guardar is not None:
        guardar(registro)

    return registro


def simular_relacion_completa(uid1, perfil1, uid2, perfil2, tipo_relacion=None, turnos=2, umbral=0.75):
    """Corre TODOS los escenarios que correspondan al tipo de relación que se
    busca -- no solo uno. tipo_relacion: "Algo serio" / "Algo casual" /
    "Nuevas amistades" / None (usa perfil1/perfil2["busco"] si no se pasa).

    Igual que simular_y_registrar, no persiste nada -- devuelve la lista de
    registros para que quien llame (main.py) decida cómo guardarlos en
    Firestore. La memoria de cada gemelo se acumula escenario a escenario."""

    tipo = tipo_relacion or perfil1.get("busco") or perfil2.get("busco") or ""
    indices = escenarios_para_tipo(tipo)

    memoria1, memoria2 = None, None
    registros = []

    for idx in indices:
        historial_chat, analisis, score = simular_cita(
            perfil1, perfil2, turnos=turnos, escenario=idx,
            memoria1=memoria1, memoria2=memoria2,
        )

        memoria1 = actualizar_memoria(memoria1, analisis)
        memoria2 = actualizar_memoria(memoria2, analisis)

        registros.append(registro_simulacion(
            uid1, perfil1, uid2, perfil2, idx, historial_chat, analisis, score, umbral
        ))

    promedio = sum(r["score"]["compatibilidad_total"] for r in registros) / len(registros)

    return {
        "tipo_relacion": tipo or "Sin definir",
        "escenarios_corridos": len(registros),
        "compatibilidad_promedio": round(promedio, 2),
        "supera_umbral": promedio >= umbral,
        "simulaciones": registros,
    }


def simular_matches_por_cercania(uid, perfil, candidatos, tipo_relacion=None, turnos=2, umbral=0.75, limite_candidatos=None):
    """Corre simular_relacion_completa contra una lista de candidatos, pero no
    en cualquier orden: primero contra los que están geográficamente más
    cerca (ver geolocalizacion.ordenar_por_cercania). Las simulaciones llaman
    a OpenAI turno a turno y salen caras, así que si hay muchos candidatos
    conviene evaluar primero a la gente cercana -- de ahí `limite_candidatos`,
    que si se pasa corta la corrida después de esa cantidad (ya ordenada por
    cercanía, o sea que lo que se corta son los más lejanos).

    uid/perfil: el usuario para el que se buscan matches.
    candidatos: lista de (uid_candidato, perfil_candidato).

    Devuelve una lista de resultados (uno por candidato), en el mismo orden
    en que se evaluaron (de más cerca a más lejos), cada uno con su
    "distancia_km" agregada (None si a ese candidato le falta ubicación)."""

    ordenados = ordenar_por_cercania(perfil, candidatos)

    if limite_candidatos is not None:
        ordenados = ordenados[:limite_candidatos]

    resultados = []

    for uid_candidato, perfil_candidato, distancia in ordenados:
        resultado = simular_relacion_completa(
            uid, perfil, uid_candidato, perfil_candidato,
            tipo_relacion=tipo_relacion, turnos=turnos, umbral=umbral,
        )
        resultado["uid_candidato"] = uid_candidato
        resultado["distancia_km"] = round(distancia, 1) if distancia is not None else None
        resultados.append(resultado)

    return resultados
