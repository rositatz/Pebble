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
def extraer_aprendizaje_chats(mensajes, intereses_actuales=None):
    """Analiza mensajes REALES que la persona escribió (chat con su propio
    gemelo + chats con matches, solo mensajes propios) y devuelve señales
    para que el gemelo hable/se relacione más parecido a como esa persona
    escribe de verdad. A propósito NO devuelve ni toca personalidad/valores
    numéricos -- esos siguen viniendo solo del onboarding (ver
    main.actualizar_aprendizaje_gemelo), así que esto es puramente
    descriptivo: estilo de escritura + intereses nuevos que se mencionaron
    de verdad, nunca inventados."""

    intereses_actuales = intereses_actuales or []
    texto_mensajes = "\n".join(f"- {m}" for m in mensajes)

    prompt = f"""
    Estos son mensajes reales que una persona escribió en distintas
    conversaciones (con su propio asistente de IA y con otras personas en
    una app de citas). Analizá SOLO su forma de escribir y de relacionarse
    -- no evalúes ni juzgues el contenido.

    Devolvé únicamente JSON válido con esta forma:
    {{
      "estilo": "2-3 oraciones describiendo cómo escribe (largo de
        mensajes, tono, humor, formalidad, muletillas) y cómo se relaciona
        (directo/a, cariñoso/a, reservado/a, etc.)",
      "intereses_nuevos": ["intereses o gustos que se notan en los
        mensajes y que NO están ya en esta lista: {', '.join(intereses_actuales) or 'ninguno'}
        -- lista vacía si no hay ninguno claro, nunca inventes"]
    }}

    Mensajes:
    {texto_mensajes}
    """

    response = client().chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": "Analizás estilo de escritura a partir de mensajes reales. Nunca inventás datos que no estén en el texto."
            },
            {"role": "user", "content": prompt}
        ],
        response_format={"type": "json_object"}
    )

    resultado = json.loads(response.choices[0].message.content)
    return {
        "estilo": (resultado.get("estilo") or "").strip(),
        "intereses_nuevos": [str(i).strip() for i in (resultado.get("intereses_nuevos") or []) if str(i).strip()],
    }


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


# Años de margen sobre el rango de edad que cada uno pidió -- "busco 25-30"
# no descarta a alguien de 32. Nunca baja el piso legal (ver EDAD_MINIMA en
# _edad_en_rango): con busco 18-25, el margen no hace que alguien de 16
# pueda entrar.
TOLERANCIA_EDAD = 3

EDAD_MINIMA = 18


def _edad_en_rango(edad_candidato, rango_busco, tolerancia):
    """True si edad_candidato entra en rango_busco (+-tolerancia años). Sin
    la edad del candidato o sin preferencia de rango puesta, no se puede
    evaluar esa mitad -- se deja pasar en vez de bloquear el par entero."""

    if edad_candidato is None or not rango_busco:
        return True

    minimo = rango_busco.get("min")
    maximo = rango_busco.get("max")

    piso = max(EDAD_MINIMA, minimo - tolerancia) if minimo is not None else EDAD_MINIMA
    techo = maximo + tolerancia if maximo is not None else 999

    return piso <= edad_candidato <= techo


def compatible_por_edad(perfil1, perfil2, tolerancia=TOLERANCIA_EDAD):
    """True si la edad de cada uno entra en el rango que busca el otro (con
    `tolerancia` años de margen para cada lado). Sea cual sea la preferencia
    de cualquiera de los dos, alguien menor de 18 nunca es candidato de
    nadie -- ese piso es absoluto y la tolerancia nunca lo cruza."""

    edad1 = perfil1.get("edad")
    edad2 = perfil2.get("edad")

    if edad1 is not None and edad1 < EDAD_MINIMA:
        return False
    if edad2 is not None and edad2 < EDAD_MINIMA:
        return False

    ok_1_acepta_2 = _edad_en_rango(edad2, perfil1.get("rango_edad_busco"), tolerancia)
    ok_2_acepta_1 = _edad_en_rango(edad1, perfil2.get("rango_edad_busco"), tolerancia)

    return ok_1_acepta_2 and ok_2_acepta_1


def compatible_por_hijos(perfil1, perfil2):
    """Si alguien dijo que le incomodaría salir con alguien que ya tiene
    hijos ("¿Te incomodaría salir con alguien que ya tiene hijos?" ==
    "Sí, prefiero que no"), no se lo considera candidato de alguien que sí
    tiene hijos -- y viceversa. "Un poco" no excluye, es una molestia leve
    declarada, no un rechazo. Sin el dato de alguno de los dos lados, no se
    puede evaluar esa mitad -- se deja pasar en vez de excluir."""

    rechaza1 = perfil1.get("tolerancia_hijos") == "Sí, prefiero que no"
    rechaza2 = perfil2.get("tolerancia_hijos") == "Sí, prefiero que no"

    ok_1_acepta_2 = not (rechaza1 and perfil2.get("tiene_hijos"))
    ok_2_acepta_1 = not (rechaza2 and perfil1.get("tiene_hijos"))

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

