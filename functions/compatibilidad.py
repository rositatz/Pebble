#Se conecta a Firestore y lee la colección usuarios.

#Filtra parejas por ubicación, rango de edad y preferencias básicas.

#Revisa qué parejas no han sido evaluadas antes y crea los registros en parejas_evaluacion en estado PENDIENTE.
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


# Géneros posibles que puede tener una persona (perfil.get("genero")) --
# "Otro" con texto libre (ej: "Género fluido") también cae acá como
# candidato válido para quien busca "todos los géneros".
_GENEROS_CONOCIDOS = {"Hombre", "Mujer", "No binario"}


def _generos_aceptados(genero, orientacion):
    """A partir del género de una persona y su orientación sexual, arma el
    conjunto de géneros con los que estaría dispuesta a matchear.

    Con datos faltantes o ambiguos (orientación "Prefiero no decir"/"Otro",
    o una etiqueta pensada para binario -tipo "Heterosexual"- combinada con
    un género no binario/"Otro"/sin dato) se deja ABIERTO a todos los
    géneros en vez de excluir: con información incompleta preferimos
    mostrar de más que ocultar matches por error."""

    TODOS = {"Hombre", "Mujer", "No binario", "Otro"}

    o = (orientacion or "").strip().casefold()
    g = (genero or "").strip()

    if o == "heterosexual":
        if g == "Hombre":
            return {"Mujer"}
        if g == "Mujer":
            return {"Hombre"}
        return TODOS
    if o in ("gay / lesbiana", "gay/lesbiana", "gay", "lesbiana"):
        if g in _GENEROS_CONOCIDOS:
            return {g}
        return TODOS
    # bisexual, pansexual, asexual, "prefiero no decir", "otro", vacío, o
    # cualquier valor no reconocido: no filtramos por género.
    return TODOS


def compatible_por_genero(perfil1, perfil2):
    """True si, según género + orientación de cada uno, ninguno de los dos
    quedaría excluido como candidato del otro. Si a alguno le falta el
    género propio no se puede chequear esa mitad -- se deja pasar (no
    excluir por datos faltantes) en vez de bloquear el par entero."""

    g1 = (perfil1.get("genero") or "").strip()
    g2 = (perfil2.get("genero") or "").strip()

    acepta1 = _generos_aceptados(g1, perfil1.get("orientacion"))
    acepta2 = _generos_aceptados(g2, perfil2.get("orientacion"))

    ok_1_acepta_2 = (not g2) or (g2 in acepta1)
    ok_2_acepta_1 = (not g1) or (g1 in acepta2)

    return ok_1_acepta_2 and ok_2_acepta_1


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

