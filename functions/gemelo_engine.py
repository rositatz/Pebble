import os
import json
import datetime

# El cliente de OpenAI se crea recién al usarlo (ver client()), no al importar
# el módulo -- en Cloud Functions la key llega como secreto en la variable de
# entorno OPENAI_API_KEY (ver secrets=["OPENAI_API_KEY"] en main.py).
_client = None


def client():
    global _client
    if _client is None:
        from openai import OpenAI
        _client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    return _client


# Cada escenario tiene "tipos_relacion": para qué opciones del campo "busco"
# (perfil.html: Algo serio / Algo casual / Nuevas amistades / Sin definir) es
# relevante correrlo. Ver escenarios_para_tipo() más abajo, que filtra por esto.
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
        "tipos_relacion": ["Algo serio", "Algo casual", "Nuevas amistades"]
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
        "tipos_relacion": ["Algo serio", "Nuevas amistades"]
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
        "tipos_relacion": ["Algo serio", "Algo casual", "Nuevas amistades"]
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
        "tipos_relacion": ["Algo serio", "Algo casual", "Nuevas amistades"]
    },

    {
        "titulo": "Planes de finde y salidas",

        "contexto": """
        La conversación gira en torno a qué hacen un sábado a la noche,
        salidas espontáneas, previas, recitales o planes de último momento.
        Es una charla liviana, sin hablar de futuro ni de compromiso.
        """,

        "objetivo": [
            "Evaluar compatibilidad de planes y ritmo social",
            "Medir espontaneidad",
            "Detectar química inmediata",
            "Evaluar sentido del humor"
        ],

        "tension": """
        Pueden chocar los ritmos: alguien más de planificar
        contra alguien más de improvisar sobre la marcha.
        """,

        "tono": "Divertido, liviano y espontáneo.",
        "tipos_relacion": ["Algo casual"]
    },

    {
        "titulo": "Códigos de humor y coqueteo",

        "contexto": """
        Ambos empiezan a tirar chistes y ver si hay buena onda y química.
        La charla se mueve con soltura entre bromas, indirectas
        y algo de coqueteo, sin ninguna presión de que "vaya a algún lado".
        """,

        "objetivo": [
            "Medir compatibilidad de humor",
            "Evaluar química y coqueteo",
            "Detectar soltura conversacional",
            "Medir capacidad de seguir el juego sin incomodarse"
        ],

        "tension": """
        El humor de uno puede no aterrizar en el otro,
        o el nivel de coqueteo puede no estar parejo.
        """,

        "tono": "Juguetón, picante y relajado.",
        "tipos_relacion": ["Algo casual"]
    },

    {
        "titulo": "Hobbies y planes para compartir",

        "contexto": """
        Hablan de hobbies, deportes, juegos o series que les gustan,
        pensando en cosas que podrían hacer juntos como amigos.
        No hay ninguna carga romántica en la charla.
        """,

        "objetivo": [
            "Detectar intereses en común",
            "Evaluar compatibilidad de planes de amistad",
            "Medir iniciativa social",
            "Analizar afinidad de sentido del humor"
        ],

        "tension": """
        Pueden no compartir casi ningún hobby,
        o tener ritmos de vida social muy distintos.
        """,

        "tono": "Natural, cómodo y sin presión.",
        "tipos_relacion": ["Nuevas amistades"]
    },

    {
        "titulo": "Buena onda en grupo",

        "contexto": """
        Charlan sobre cómo son en una juntada con amigos, si son de sumar
        gente nueva al grupo o prefieren círculos chicos, y qué tipo de
        energía aportan cuando están con otras personas.
        """,

        "objetivo": [
            "Evaluar compatibilidad social",
            "Medir apertura a integrarse a nuevos grupos",
            "Detectar estilo de vínculo entre amigos",
            "Analizar empatía grupal"
        ],

        "tension": """
        Uno puede ser mucho más sociable/expansivo que el otro,
        o tener expectativas distintas de qué tan seguido verse.
        """,

        "tono": "Cálido, sociable y genuino.",
        "tipos_relacion": ["Nuevas amistades"]
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


def generar_prompt_gemelo(perfil, memoria=None):

    # =====================================================
    # PERFIL PSICOLOGICO
    # =====================================================

    personalidad = perfil.get("personalidad", {})

    personalidad_txt = f"""
    PERFIL PSICOLÓGICO:

    - Introversión: {personalidad.get('introversion', 0.5)}
    - Empatía: {personalidad.get('empatia', 0.5)}
    - Sarcasmo: {personalidad.get('sarcasmo', 0.5)}
    - Apertura mental: {personalidad.get('apertura_mental', 0.5)}
    - Ambición: {personalidad.get('ambicion', 0.5)}
    - Sensibilidad emocional: {personalidad.get('sensibilidad_emocional', 0.5)}
    - Necesidad afectiva: {personalidad.get('necesidad_afecto', 0.5)}
    - Independencia: {personalidad.get('independencia', 0.5)}
    - Tolerancia al conflicto: {personalidad.get('tolerancia_conflicto', 0.5)}
    """

    # =====================================================
    # ESTILO CONVERSACIONAL
    # =====================================================

    estilo_chat = perfil.get("estilo_chat", {})

    estilo = f"""
    ESTILO CONVERSACIONAL:

    - Mensajes cortos: {estilo_chat.get('mensajes_cortos', False)}
    - Usa humor: {estilo_chat.get('usa_humor', False)}
    - Nivel de coqueteo: {estilo_chat.get('coqueto', False)}
    - Estilo analítico: {estilo_chat.get('analitico', False)}
    """

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
    """

    return prompt


def analizar_conversacion(historial_chat):

    prompt_analisis = f"""
    Analiza la siguiente conversación entre dos usuarios.

    Devuelve únicamente JSON válido.

    Evalúa:

    - quimica
    - interes_mutuo
    - comodidad
    - tension
    - empatia
    - humor
    - coqueteo
    - compatibilidad_emocional
    - compatibilidad_intelectual
    - red_flags
    - resumen_interaccion

    Escala:
    0.0 a 1.0

    Conversación:
    {historial_chat}
    """

    response = client().chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": (
                    "Eres un analista de comportamiento social "
                    "y compatibilidad romántica."
                )
            },
            {
                "role": "user",
                "content": prompt_analisis
            }
        ],
        response_format={"type": "json_object"}
    )

    analisis = json.loads(
        response.choices[0].message.content
    )

    return analisis


def actualizar_memoria(memoria, analisis):
    """Si es la primera interacción entre este par de gemelos, memoria
    todavía no existe (None) -- se crea acá. Si ya existía, se le hace append
    del resumen de esta nueva interacción arriba de las anteriores."""

    if memoria is None:
        memoria = {"interacciones": []}

    memoria.setdefault("interacciones", []).append({

        "quimica": analisis.get("quimica", 0.5),

        "interes_mutuo": analisis.get("interes_mutuo", 0.5),

        "comodidad": analisis.get("comodidad", 0.5),

        "tension": analisis.get("tension", 0.5),

        "resumen": analisis.get("resumen_interaccion", "")
    })

    return memoria


def compatibilidad_psicologica(perfil1, perfil2):

    p1 = perfil1.get("personalidad", {})
    p2 = perfil2.get("personalidad", {})

    atributos = set(p1) & set(p2)
    if not atributos:
        return 0.5

    score = 0

    for atributo in atributos:

        diferencia = abs(
            p1[atributo] - p2[atributo]
        )

        compatibilidad = 1 - diferencia

        score += compatibilidad

    return score / len(atributos)


def compatibilidad_valores(perfil1, perfil2):

    v1 = perfil1.get("valores", {})
    v2 = perfil2.get("valores", {})

    atributos = set(v1) & set(v2)
    if not atributos:
        return 0.5

    score = 0

    for valor in atributos:

        diferencia = abs(
            v1[valor] - v2[valor]
        )

        compatibilidad = 1 - diferencia

        score += compatibilidad

    return score / len(atributos)


def compatibilidad_conversacional(analisis):

    pesos = {

        "quimica": 0.25,
        "interes_mutuo": 0.20,
        "comodidad": 0.15,
        "empatia": 0.15,
        "humor": 0.10,
        "coqueteo": 0.10,
        "tension": -0.15
    }

    score = 0

    for k, peso in pesos.items():

        valor = analisis.get(k, 0.5)

        score += valor * peso

    return max(0, min(score, 1))


def pesos_compatibilidad_pareja(perfil1, perfil2):
    """Combina los pesos personales de cada usuario (ver
    gemelo_perfil._construir_pesos_compatibilidad) en un único peso por
    pareja. Si un perfil no trae pesos propios se usa el default 0.35/0.40/0.25."""

    from gemelo_perfil import PESOS_DEFAULT

    p1 = perfil1.get("pesos_compatibilidad") or PESOS_DEFAULT
    p2 = perfil2.get("pesos_compatibilidad") or PESOS_DEFAULT

    combinados = {
        eje: (p1.get(eje, PESOS_DEFAULT[eje]) + p2.get(eje, PESOS_DEFAULT[eje])) / 2
        for eje in PESOS_DEFAULT
    }
    total = sum(combinados.values()) or 1.0
    return {eje: v / total for eje, v in combinados.items()}


def calcular_compatibilidad(perfil1, perfil2, analisis):

    score_psicologico = compatibilidad_psicologica(
        perfil1,
        perfil2
    )

    score_valores = compatibilidad_valores(
        perfil1,
        perfil2
    )

    score_conversacional = compatibilidad_conversacional(
        analisis
    )

    pesos = pesos_compatibilidad_pareja(perfil1, perfil2)

    compatibilidad_total = (

        score_psicologico * pesos["psicologico"] +

        score_conversacional * pesos["conversacional"] +

        score_valores * pesos["valores"]
    )

    return {

        "compatibilidad_total": round(
            compatibilidad_total,
            2
        ),

        "score_psicologico": round(
            score_psicologico,
            2
        ),

        "score_conversacional": round(
            score_conversacional,
            2
        ),

        "score_valores": round(
            score_valores,
            2
        ),

        "pesos_usados": {
            eje: round(v, 2) for eje, v in pesos.items()
        }
    }


def simular_cita(perfil1, perfil2, turnos=2, escenario=0, memoria1=None, memoria2=None):
    """escenario puede ser un índice de escenarios_db o un dict
    {"titulo","contexto","tono"} armado con armar_escenario_personalizado()
    para una simulación a pedido del usuario.

    memoria1/memoria2 son lo que cada gemelo recuerda de interacciones previas
    con el otro (ver actualizar_memoria) -- se usan en simular_relacion_completa
    para que, al correr varios escenarios seguidos, la charla se sienta
    continuada en vez de arrancar de cero cada vez."""

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

    ultimo_mensaje = "Hola, me llamó la atención este tema. ¿Vos qué pensás?"

    historial_chat.append({
        "role": "user",
        "name": nombre1,
        "content": ultimo_mensaje
    })

    for _ in range(turnos):

        response_2 = client().chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": contexto_escenario + prompt_2},
                *historial_chat
            ]
        )
        msg_2 = response_2.choices[0].message.content
        historial_chat.append({"role": "assistant", "name": nombre2, "content": msg_2})

        response_1 = client().chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": contexto_escenario + prompt_1},
                *historial_chat
            ]
        )
        msg_1 = response_1.choices[0].message.content
        historial_chat.append({"role": "assistant", "name": nombre1, "content": msg_1})

    analisis = analizar_conversacion(historial_chat)
    score = calcular_compatibilidad(perfil1, perfil2, analisis)

    return historial_chat, analisis, score


def _par_id(uid1, uid2):
    return "_".join(sorted([str(uid1), str(uid2)]))


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


def simular_y_registrar(uid1, perfil1, uid2, perfil2, turnos=2, escenario=0, umbral=0.75):
    """Corre la simulación y devuelve (registro_listo_para_guardar). Quien
    llama a esta función es el que decide dónde guardar registro (acá,
    main.py lo guarda en Firestore)."""

    historial_chat, analisis, score = simular_cita(perfil1, perfil2, turnos=turnos, escenario=escenario)

    return registro_simulacion(
        uid1, perfil1, uid2, perfil2, escenario, historial_chat, analisis, score, umbral
    )


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
