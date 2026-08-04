import os
import json

from gemelo_perfil import construir_perfil_gemelo

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

        "tono": "Intelectual, relajado y curioso."
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

        "tono": "Maduro, honesto y relajado."
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

        "tono": "Personal, emocional y reflexivo."
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

        "tono": "Honesto, introspectivo y respetuoso."
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

        "tono": "Liviano, cotidiano y natural."
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

        "tono": "Motivador, reflexivo y maduro."
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

        "tono": "Emocional, abierto y sincero."
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

        "tono": "Relajado, emocional y espontáneo."
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

        "tono": "Reflexivo, relajado y cercano."
    }
]
# Los perfiles ya no se hardcodean acá: se construyen a partir de las respuestas
# reales del onboarding (usuarios/{uid}/gemelo_setup/data en Firestore) con
# gemelo_perfil.construir_perfil_gemelo(). Ver el bloque __main__ para un ejemplo
# con datos de muestra que respetan esa misma forma.

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
    """Combina los pesos personales de cada usuario (de qué tan importante le
    resultan la afinidad psicológica, la química conversacional y los valores
    compartidos — ver gemelo_perfil._construir_pesos_compatibilidad) en un
    único peso por pareja. Si un perfil no trae pesos propios (perfiles viejos,
    o construidos a mano) se usa el default 0.35/0.40/0.25 de siempre."""

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

def simular_cita(perfil1, perfil2, turnos=3, escenario=0):
    """escenario puede ser un índice de escenarios_db (los 9 fijos) o un dict
    {"titulo","contexto","tension","tono"} armado al vuelo para una simulación
    a pedido del usuario (ej: "simulá que discutimos por plata")."""

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

    prompt_1 = generar_prompt_gemelo(perfil1)
    prompt_2 = generar_prompt_gemelo(perfil2)

    ultimo_mensaje = """
    Hola, me llamó la atención este tema.
    ¿Vos qué pensás?
    """

    print(f"{nombre1}: {ultimo_mensaje}\n")

    historial_chat.append({

        "role": "user",
        "name": nombre1,
        "content": ultimo_mensaje
    })

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

                *historial_chat
            ]
        )

        msg_2 = response_2.choices[0].message.content

        print(f"{nombre2}: {msg_2}\n")

        historial_chat.append({

            "role": "assistant",
            "name": nombre2,
            "content": msg_2
        })

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

                *historial_chat
            ]
        )

        msg_1 = response_1.choices[0].message.content

        print(f"{nombre1}: {msg_1}\n")

        historial_chat.append({

            "role": "assistant",
            "name": nombre1,
            "content": msg_1
        })

    # =====================================================
    # ANALISIS FINAL
    # =====================================================

    analisis = analizar_conversacion(
        historial_chat
    )

    print("\n--- ANALISIS ---\n")

    print(json.dumps(
        analisis,
        indent=4,
        ensure_ascii=False
    ))

    # =====================================================
    # SCORE FINAL
    # =====================================================

    score = calcular_compatibilidad(
        perfil1,
        perfil2,
        analisis
    )

    print("\n--- COMPATIBILIDAD ---\n")

    print(json.dumps(
        score,
        indent=4,
        ensure_ascii=False
    ))

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
    return "_".join(sorted([str(uid1), str(uid2)]))


def registro_simulacion(uid1, perfil1, uid2, perfil2, escenario, historial_chat, analisis, score, umbral=0.75):
    import datetime

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


if __name__ == "__main__":
    # Ejemplos de respuestas "crudas" con la MISMA forma que guarda
    # gemelo-setup.html en usuarios/{uid}/gemelo_setup/data (parciales a
    # propósito: así se ve que construir_perfil_gemelo tolera datos incompletos).
    respuestas_ejemplo_1 = {
        "etapa1": {"nombre": "Rosa", "edad": "22", "ocupacion": "Estudiante de tecnología",
                    "convivo": "Solo/a", "gustaOcup": "Sí, mucho", "rutina": "Cambiante"},
        "etapa2": {"artista": "Bon Iver", "genero": ["Indie", "Jazz"], "serie": "The Bear",
                    "deporte": "No hago", "lugarIdeal": "Librería"},
        "etapa3": {"comoSoy": ["Reservado/a", "Sensible", "Observador/a"],
                    "genteNueva": "Observás primero", "decision": "La pienso un montón, analizo pros y contras",
                    "sentirFondo": "Siento todo bastante intenso, me atraviesa lo que me pasa",
                    "ansiedadSeg": "Me da ansiedad no saber qué va a pasar, seguridad la rutina."},
        "etapa4": {"coqueteo": "Me cuesta mucho demostrarlo", "pelea": "Intento hablarlo con calma para resolverlo",
                    "cuandoMolesta": "Necesito tiempo primero",
                    "necesitasVinc": "Que respeten mi independencia y tiempos"},
        "etapa5": {"veloc": "Ir despacio", "profConv": "Charlas profundas desde el inicio",
                    "flags": {"0": "green", "1": "red", "2": "green"}},
        "etapa6": {"psi1": "Aprendí a no perseguir a quien no me busca.",
                    "conexionPrimero": "Emocional", "atraeMas": "Sensible"},
        "etapa7": {},
        "gemelo_final": "Soy alguien tranquilo que se abre despacio pero a fondo."
    }
    respuestas_ejemplo_2 = {
        "etapa1": {"nombre": "Mateo", "edad": "23", "ocupacion": "Trabajo de oficina",
                    "convivo": "Con amigos/as", "gustaOcup": "Bastante", "rutina": "Intensa"},
        "etapa2": {"artista": "Bad Bunny", "genero": ["Reggaetón", "Pop"], "serie": "Friends",
                    "deporte": "Fútbol", "equipo": "River", "lugarIdeal": "Recital"},
        "etapa3": {"comoSoy": ["Sociable", "Divertido/a", "Espontáneo/a"],
                    "genteNueva": "Tomás iniciativa", "decision": "Actúo rápido y confío en mi intuición",
                    "sentirFondo": "Suelo mantener cierta distancia emocional"},
        "etapa4": {"coqueteo": "Directo/a, lo dejo claro", "pelea": "Digo lo que pienso aunque genere discusión",
                    "cuandoMolesta": "Lo hablo enseguida",
                    "necesitasVinc": "Disponibilidad real cuando la necesito"},
        "etapa5": {"veloc": "Ir rápido", "profConv": "Conversaciones livianas primero",
                    "flags": {"0": "green", "1": "green", "2": "red"}},
        "etapa6": {"psi1": "Aprendí que hay que decir las cosas antes de que se acumulen.",
                    "conexionPrimero": "Física", "atraeMas": "Gracioso/a"},
        "etapa7": {},
        "gemelo_final": "Soy directo, sociable, y si algo me gusta lo digo enseguida."
    }

    perfil_1 = construir_perfil_gemelo(respuestas_ejemplo_1)
    perfil_2 = construir_perfil_gemelo(respuestas_ejemplo_2)

    print("--- PERFIL 1 (normalizado) ---")
    print(json.dumps(perfil_1, indent=2, ensure_ascii=False))
    print("\n--- PERFIL 2 (normalizado) ---")
    print(json.dumps(perfil_2, indent=2, ensure_ascii=False))

    # Esta parte no necesita OpenAI: es pura comparación de rasgos numéricos.
    print("\n--- COMPATIBILIDAD (sin simulación de charla) ---")
    print(json.dumps({
        "score_psicologico": round(compatibilidad_psicologica(perfil_1, perfil_2), 2),
        "score_valores": round(compatibilidad_valores(perfil_1, perfil_2), 2),
        "pesos_de_pareja": {k: round(v, 2) for k, v in pesos_compatibilidad_pareja(perfil_1, perfil_2).items()},
    }, indent=2, ensure_ascii=False))

    if os.getenv("OPENAI_API_KEY"):
        print("\n--- SIMULACIÓN COMPLETA (con OpenAI), se guarda al terminar ---")
        registro = simular_y_registrar("uid_rosa_demo", perfil_1, "uid_mateo_demo", perfil_2, turnos=2, umbral=0.75)
        print(f"\nGuardado en: simulaciones_guardadas/")
        print(f"¿Superó el umbral de 0.75? {registro['supera_umbral']}")
    else:
        print("\n(Sin OPENAI_API_KEY en el entorno: se salteó la simulación de charla real.)")