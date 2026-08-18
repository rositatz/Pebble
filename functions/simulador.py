#Lee las parejas en estado PENDIENTE de Firestore.
#Carga las personalidades de los gemelos y las instrucciones del escenario.
#Llama a la API de IA (OpenAI, Gemini, Anthropic) para simular los diálogos, calcula el puntaje de compatibilidad y extrae las memorias.
#Guarda los resultados en la subcolección simulaciones y actualiza el estado.

import os
import json
import datetime 

from gemelo_perfil import construir_perfil_gemelo
from compatibilidad import analizar_conversacion, actualizar_memoria, calcular_compatibilidad

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


# Sin decirle explícitamente el género a la IA, por defecto escribe en
# neutro/ambiguo -- "el/la que se enamora", "enamorado/a", con barras -- que
# no es como habla una persona real. Con género conocido se le pide
# terminantemente que escriba en ese género en vez de usar barras; "No
# binario"/"Género fluido"/"Prefiero no decir"/"Otro"/vacío se dejan en
# neutro a propósito (no hay una forma gramatical única "correcta" para
# imponer ahí).
_GENERO_INSTRUCCION = {
    "Mujer": "Género: femenino -- escribí siempre en femenino (ej: \"segura\", \"la que se enamora rápido\"), nunca uses barras como \"o/a\" ni \"el/la\".",
    "Hombre": "Género: masculino -- escribí siempre en masculino (ej: \"seguro\", \"el que se enamora rápido\"), nunca uses barras como \"o/a\" ni \"el/la\".",
}


def _instruccion_genero(perfil):
    return _GENERO_INSTRUCCION.get((perfil.get("genero") or "").strip(), "")


_DIAS_ES = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
_MESES_ES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]


def _ahora_argentina_txt():
    """El modelo no tiene reloj propio -- sin decirle la hora real, adivina
    (mal) si le preguntan qué hora es o si algo está abierto ahora. Argentina
    usa UTC-3 todo el año, sin horario de verano, así que alcanza con un
    offset fijo -- no hace falta la base de datos de husos horarios
    (zoneinfo/tzdata), que no siempre está disponible en el runtime de
    Cloud Functions."""
    ahora = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=-3)))
    dia = _DIAS_ES[ahora.weekday()]
    mes = _MESES_ES[ahora.month - 1]
    return f"{dia} {ahora.day} de {mes} de {ahora.year}, {ahora.strftime('%H:%M')} (hora Argentina)"


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

    # Igual que en generar_prompt_gemelo_personal: estilo_aprendido viene de
    # mensajes reales (con consentimiento) y solo afecta CÓMO habla acá, no
    # los números de personalidad/valores de arriba -- esos siguen siendo
    # los del onboarding, que es lo que se compara matemáticamente con el
    # perfil de la otra persona en compatibilidad.calcular_compatibilidad.
    estilo_aprendido_prompt = ""
    estilo_aprendido = perfil.get("estilo_aprendido", "")
    if estilo_aprendido:
        estilo_aprendido_prompt = f"\n    CÓMO ESCRIBE/SE RELACIONA EN LA PRÁCTICA (aprendido de chats reales):\n    {estilo_aprendido}\n"

    # Autodescripción física real (etapa6, "Sobre tu físico") -- para que el
    # gemelo pueda responder con naturalidad si en la charla sale el tema,
    # en vez de no saber nada de su propio aspecto.
    fisico_prompt = ""
    fisico = perfil.get("fisico_propio") or {}
    fisico_partes = [v for v in (fisico.get("colorPelo"), fisico.get("estiloPelo"), fisico.get("contextura")) if v]
    if fisico.get("altura_cm"):
        fisico_partes.append(f"{fisico['altura_cm']}cm")
    if fisico_partes:
        fisico_prompt = f"\n    CÓMO ES FÍSICAMENTE (por si sale el tema en la charla):\n    {', '.join(fisico_partes)}\n"

    # Orden de prioridad que la persona eligió a propósito ("¿qué es lo que
    # más te importa para conectar de verdad con alguien?", etapa6) -- a
    # diferencia de los rasgos de personalidad/valores (que describen CÓMO
    # es), esto describe QUÉ le importa más buscar en la cita, así que
    # influye en qué temas profundiza durante la simulación, no solo en el
    # cálculo de compatibilidad (ver compatibilidad.calcular_compatibilidad).
    prioridad_prompt = ""
    prioridad = perfil.get("prioridad_compatibilidad") or []
    if prioridad:
        prioridad_prompt = (
            "\n    LO QUE MÁS TE IMPORTA EN ESTA CITA (en orden, lo primero es lo más importante -- "
            "priorizá naturalmente estos temas en la charla, sin anunciarlo):\n"
            + "\n".join(f"    {i+1}. {p}" for i, p in enumerate(prioridad))
            + "\n"
        )

    # Resultado del mini-juego de green/red flags (etapa5) -- antes se
    # guardaba pero no se usaba en ningún lado, ni siquiera para mostrar de
    # qué se trataba (solo un conteo). Ahora el gemelo sabe CUÁLES
    # comportamientos considera green/red flag, así puede evitar los que le
    # generan rechazo y acercarse a los que valora durante la simulación.
    flags_prompt = ""
    flags_resumen = perfil.get("flags_resumen") or {}
    green_flags = flags_resumen.get("green_textos") or []
    red_flags = flags_resumen.get("red_textos") or []
    if green_flags or red_flags:
        flags_prompt = "\n    QUÉ CONSIDERÁS GREEN FLAG Y RED FLAG EN UNA RELACIÓN:\n"
        if green_flags:
            flags_prompt += "    - Te gusta / lo ves bien: " + ", ".join(green_flags) + "\n"
        if red_flags:
            flags_prompt += "    - No te gusta / te genera dudas: " + ", ".join(red_flags) + "\n"

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
    {fisico_prompt}
    {_instruccion_genero(perfil)}

    =====================================================
    PERSONALIDAD
    =====================================================

    {personalidad_txt}
    {prioridad_prompt}

    =====================================================
    ESTILO
    =====================================================

    {estilo}
    {estilo_aprendido_prompt}
    =====================================================
    VALORES
    =====================================================

    {valores_prompt}
    {conflictos_prompt}
    {flags_prompt}
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


def generar_prompt_gemelo_personal(perfil, matches_resumen=None, total_simulaciones=0, mejor_score_sin_match=0):
    """Prompt para el chat DIRECTO entre el usuario y su propio gemelo
    (gemelo.html) -- a diferencia de generar_prompt_gemelo (que arma un
    gemelo simulando una cita con el gemelo de OTRA persona), acá el gemelo
    le habla al propio usuario, en segunda persona, como su reflejo de
    confianza dentro de la app. Reusa la misma traducción de personalidad a
    directivas de comportamiento (_directiva) para que el tono sea
    consistente con el que se ve en las simulaciones.

    total_simulaciones/mejor_score_sin_match: igual que el cartel "Tu gemelo
    está activo" de home.html -- cuentan TODAS las conexiones (match o no),
    no solo matches_resumen (que son solo las que superaron el umbral). Sin
    esto, si preguntaban "con quién corriste simulaciones" el gemelo decía
    que no había corrido ninguna aunque sí hubiera corrido, solo que ninguna
    llegó al 75% necesario para hacer match."""

    personalidad = perfil.get("personalidad", {})

    directivas_personalidad = list(filter(None, [
        _directiva(personalidad.get('introversion', 0.5),
            "Sos bastante introvertido/a: no te desvivís por llenar el silencio ni sos efusivo/a de entrada.",
            "Sos bastante extrovertido/a: hablás con soltura y entusiasmo."),
        _directiva(personalidad.get('empatia', 0.5),
            "Sos muy empático/a: antes de opinar, validás lo que siente la persona que te escribe.",
            "Vas más al grano: te enfocás en resolver, no tanto en cómo se siente el otro."),
        _directiva(personalidad.get('sarcasmo', 0.5),
            "Tenés un humor bastante sarcástico o irónico, lo metés seguido.",
            "No sos de tirar sarcasmo -- tu humor, si aparece, es directo."),
        _directiva(personalidad.get('apertura_mental', 0.5),
            "Sos abierto/a a ideas nuevas y a que te contradigan.",
            "Sos más escéptico/a, preferís lo probado antes que lo nuevo."),
        _directiva(personalidad.get('ambicion', 0.5),
            "Sos ambicioso/a: te gusta hablar en términos de metas y progreso.",
            "No te mueve tanto la ambición, vivís más el presente."),
        _directiva(personalidad.get('sensibilidad_emocional', 0.5),
            "Sos emocionalmente sensible: las cosas te afectan y lo mostrás.",
            "Sos bastante estable emocionalmente, no te alteran fácil los temas sensibles."),
        _directiva(personalidad.get('necesidad_afecto', 0.5),
            "Buscás cercanía afectiva en cómo te comunicás.",
            "Sos independiente afectivamente, no necesitás validar todo el tiempo."),
        _directiva(personalidad.get('independencia', 0.5),
            "Valorás mucho la independencia, y se nota en los consejos que das.",
            "No te cuesta la cercanía ni depender del otro."),
        _directiva(personalidad.get('tolerancia_conflicto', 0.5),
            "Tolerás bien el conflicto: no evitás decir algo incómodo si hace falta.",
            "Evitás el conflicto, suavizás lo que decís."),
    ]))

    personalidad_txt = "\n".join(f"    - {d}" for d in directivas_personalidad)

    nombre = perfil.get("nombre") or "tu usuario"

    # Antes este prompt solo tenía la personalidad -- no sabía nada de la
    # situación real de la persona (estudia/trabaja/en qué), sus intereses
    # ni su bio, así que no podía dar consejos que tuvieran en cuenta eso.
    identidad_txt = "\n    SOBRE VOS (la persona a la que representás):\n"
    if perfil.get("edad"):
        identidad_txt += f"    - Edad: {perfil['edad']}\n"
    if perfil.get("profesion"):
        identidad_txt += f"    - Situación actual: {perfil['profesion']}\n"
    if perfil.get("intereses"):
        identidad_txt += f"    - Intereses: {', '.join(perfil['intereses'])}\n"
    if perfil.get("bio"):
        identidad_txt += f"    - Cómo se describe: {perfil['bio']}\n"
    # estilo_aprendido lo arma actualizar_aprendizaje_gemelo (main.py) a partir
    # de mensajes reales que la persona escribió (chat con su propio gemelo +
    # chats con matches, solo si dio consentimiento) -- a diferencia de
    # personalidad/valores (que son fijos desde el onboarding para que nadie
    # pueda "inflarlos" chateando y matchear más fácil), esto es pura forma de
    # hablar, así que sí se deja actualizar con el tiempo.
    if perfil.get("estilo_aprendido"):
        identidad_txt += f"    - Cómo escribe/se relaciona en la práctica: {perfil['estilo_aprendido']}\n"
    if _instruccion_genero(perfil):
        identidad_txt += f"    - {_instruccion_genero(perfil)}\n"

    sin_match = max(0, total_simulaciones - len(matches_resumen))
    sin_match_txt = "1 simulación" if sin_match == 1 else f"{sin_match} simulaciones"
    total_txt = "1 simulación" if total_simulaciones == 1 else f"{total_simulaciones} simulaciones"

    if matches_resumen:
        matches_txt = "\n    SUS MATCHES ACTUALES (para dar consejos concretos si te preguntan por alguno):\n"
        for m in matches_resumen:
            matches_txt += f"    - {m['nombre']}: {m['score']}% de afinidad\n"
        if sin_match:
            matches_txt += (
                f"    Además corriste {sin_match_txt} con otras personas que no llegaron al 75% "
                f"necesario para hacer match -- no digas nombres de esas, solo la cantidad si preguntan.\n"
            )
    elif total_simulaciones:
        matches_txt = (
            f"\n    Todavía no tiene matches, pero SÍ corriste {total_txt} con otras personas -- "
            f"ninguna llegó al 75% necesario para hacer match todavía (la mejor dio "
            f"{mejor_score_sin_match}%). Si te pregunta por esto, contestale con estos números "
            f"reales -- NO digas que no corriste ninguna simulación, y no inventes nombres (no los tenés).\n"
        )
    else:
        matches_txt = "\n    Todavía no corriste ninguna simulación con nadie -- si te pregunta por eso, decíselo tal cual, no inventes nombres.\n"

    prompt = f"""
    Sos el gemelo digital de {nombre} dentro de la app de citas Pebble.

    IMPORTANTE: acá NO estás simulando una cita ni hablando con el gemelo de
    otra persona. Le estás hablando DIRECTAMENTE a {nombre}, tu propio
    usuario -- sos su reflejo de IA, hecho de su propia personalidad, y tu
    trabajo es darle charla, consejos y compañía sobre su vida en la app
    (sus matches, cómo hablarles, cómo le está yendo).

    AHORA MISMO ES: {_ahora_argentina_txt()}.

    PERSONALIDAD (tiene que notarse en cómo hablás):
    {personalidad_txt}
    {identidad_txt}
    {matches_txt}

    REGLAS:
    1. Hablále a {nombre} en segunda persona, como alguien que lo/la conoce
       mejor que nadie -- nunca en primera persona como si fueras la persona
       en una cita.
    2. Si te pregunta por un match específico, usá SOLO los datos reales de
       arriba (nombre y % de afinidad) -- si no tenés más info que esa, decilo,
       no inventes detalles sobre esa persona.
    3. Sé breve: entre 1 y 4 oraciones, salvo que te pidan algo más largo.
    4. No actúes como asistente genérico ("¿en qué puedo ayudarte?") -- tenés
       personalidad propia, mostrala.
    5. Usá los datos de "SOBRE VOS" cuando sea relevante (ej: si te pregunta
       algo sobre su día a día, su carrera o sus intereses) -- son datos
       reales, no los ignores ni inventes otros en su lugar.
    6. Si no sabés algo, decilo con naturalidad en vez de inventar.
    7. Si te pregunta la hora, el día, o algo que dependa de eso (ej: si algo
       está abierto ahora), usá el dato de "AHORA MISMO ES" de arriba -- es
       la hora real, no la adivines ni la inventes.
    """

    return prompt


def generar_resumen_gemelo(perfil):
    """Arma el párrafo de presentación del gemelo (lo que se ve/edita en la
    última etapa del onboarding, gemelo-setup.html) con IA.

    A propósito NO le pasa a la IA una lista de frases de personalidad ya
    traducidas (como hacen generar_prompt_gemelo/generar_prompt_gemelo_personal
    con _directiva) -- acá se le dan los NÚMEROS crudos de personalidad y
    valores para que tenga que analizarlos de verdad (¿hay una tensión entre
    cómo se describe y sus rasgos? ¿qué combinación de datos es la más
    distintiva de esta persona en particular?), en vez de simplemente elegir
    qué oraciones pre-armadas mencionar. Es la diferencia entre un resumen
    que "copia y pega" respuestas con el mismo esquema para todos, y uno que
    realmente varía en estructura y enfoque según la persona."""

    personalidad = perfil.get("personalidad", {})
    valores = perfil.get("valores", {})

    nombre = perfil.get("nombre") or "esta persona"
    partes_datos = []
    if perfil.get("edad"):
        partes_datos.append(f"Edad: {perfil['edad']}")
    if perfil.get("profesion"):
        partes_datos.append(f"Situación actual: {perfil['profesion']}")
    if perfil.get("ciudad"):
        partes_datos.append(f"Ciudad: {perfil['ciudad']}")
    if perfil.get("intereses"):
        partes_datos.append(f"Intereses: {', '.join(perfil['intereses'])}")
    if perfil.get("busco"):
        partes_datos.append(f"Busca: {perfil['busco']}")
    if personalidad:
        partes_datos.append(
            "Rasgos de personalidad (escala 0.0 a 1.0, 0.5 es neutro): "
            + ", ".join(f"{k} {v}" for k, v in personalidad.items())
        )
    if valores:
        partes_datos.append(
            "Valores personales (escala 0.0 a 1.0, 0.5 es neutro): "
            + ", ".join(f"{k} {v}" for k, v in valores.items())
        )
    conflictos = perfil.get("conflictos") or {}
    if conflictos:
        partes_datos.append("Cómo maneja los conflictos: " + "; ".join(conflictos.values()))
    if perfil.get("notas_personales"):
        partes_datos.append("En sus propias palabras:\n" + "\n".join(f"- {n}" for n in perfil["notas_personales"]))
    creencias = perfil.get("creencias") or {}
    if creencias:
        partes_datos.append("Postura frente a política/religión: " + "; ".join(f"{k}: {v}" for k, v in creencias.items()))
    fisico = perfil.get("fisico_propio") or {}
    fisico_partes = [v for v in (fisico.get("colorPelo"), fisico.get("estiloPelo"), fisico.get("contextura")) if v]
    if fisico.get("altura_cm"):
        fisico_partes.append(f"{fisico['altura_cm']}cm")
    if fisico_partes:
        partes_datos.append("Físico: " + ", ".join(fisico_partes))
    prioridad = perfil.get("prioridad_compatibilidad") or []
    if prioridad:
        partes_datos.append("Lo que más le importa en una conexión, en orden: " + " > ".join(prioridad))
    flags_resumen = perfil.get("flags_resumen") or {}
    if flags_resumen.get("green_textos") or flags_resumen.get("red_textos"):
        partes_datos.append(
            "Green flags que valora: " + ", ".join(flags_resumen.get("green_textos") or ["ninguno marcado"])
            + " | Red flags que le preocupan: " + ", ".join(flags_resumen.get("red_textos") or ["ninguno marcado"])
        )
    if _instruccion_genero(perfil):
        partes_datos.append(_instruccion_genero(perfil))

    datos_txt = "\n".join(partes_datos) if partes_datos else "No hay datos suficientes todavía."

    prompt = f"""
    Sos un psicólogo que conoce muy bien a esta persona y va a escribir su
    presentación para una app de citas, en primera persona, como si fuera
    ella misma escribiéndola. Tenés MUCHOS datos reales sobre ella (más
    abajo) -- usalos todos, no te quedes solo con edad/trabajo/intereses.

    Antes de escribir, analizá los datos de verdad y encontrá AL MENOS DOS
    de estas cosas (no una sola):
    - Una tensión real entre cómo se describe en sus propias palabras y lo
      que muestran sus rasgos numéricos (ej: dice ser independiente pero sus
      números muestran mucha necesidad de cercanía; es ambicioso/a pero
      valora mucho la estabilidad; parece extrovertido/a pero le cuesta el
      conflicto).
    - Qué combinación de prioridades, green/red flags, físico, creencias y
      personalidad es la más distintiva o menos obvia de ESTA persona en
      particular -- no la mencione todas por separado, conectalas entre sí.
    - Qué es lo que probablemente busca de verdad en una relación, leyendo
      entre líneas de lo que priorizó y de sus notas personales, no solo
      repitiendo lo que puso.
    Un resumen que solo reordena las respuestas con otras palabras NO
    cumple con esto -- tiene que sonar a que alguien que la conoce bien
    de verdad se dio cuenta de algo, no a una lista prolija.

    NO uses siempre el mismo orden ni la misma estructura (edad, trabajo,
    intereses, personalidad, cierre) -- cada persona arranca por lo que más
    la define a ELLA, no por una plantilla fija. No empieces siempre con
    "Soy [nombre]" ni con la edad o el trabajo si no es lo más relevante de
    esta persona.

    Los números de personalidad/valores son SOLO para que vos entiendas a la
    persona antes de escribir -- el texto final tiene que sonar como lo
    escribiría alguien de carne y hueso describiéndose a sí misma, nunca como
    un informe. Eso quiere decir: NINGÚN número, escala, porcentaje ni
    palabra tipo "rasgo" o "valor" en el texto final -- todo tiene que
    quedar traducido a lenguaje humano y natural (ej: no "introversión 0.8",
    sino algo como "necesito mis tiempos a solas para recargar pilas").

    Escribí 2 a 3 párrafos bien desarrollados (no un párrafo corto de 4
    oraciones) -- tenés muchos datos reales, usalos para que se note. Que
    suene natural y humano, nunca a lista ni a ficha de datos.

    DATOS REALES DE LA PERSONA (para tu análisis interno -- no los repitas
    tal cual en el texto final, son para que entiendas a la persona, no
    para citarlos uno por uno; no inventes datos que no estén acá):
    {datos_txt}

    Devolvé SOLO el texto final, sin comillas, sin encabezados, sin
    explicaciones tuyas.
    """

    response = client().chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=1.0,
    )
    return response.choices[0].message.content.strip()


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


