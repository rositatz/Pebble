#Se conecta a Firestore y lee la colección usuarios.

#Filtra parejas por ubicación, rango de edad y preferencias básicas.

#Revisa qué parejas no han sido evaluadas antes y crea los registros en parejas_evaluacion en estado PENDIENTE.
import os
import json
import random
import re

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

# El mapeo atraeMas/persEngancha -> objetivo numérico de personalidad vive
# en gemelo_perfil.MAPA_PREFERENCIAS_PERSONALIDAD (se arma junto con el
# resto del perfil, no acá).
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
        model="gpt-5.6-terra",
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
        (directo/a, cariñoso/a, reservado/a, etc.). Incluí SIEMPRE una
        frase puntual sobre emojis: si en los mensajes usa emojis de
        verdad, decí cuáles (los que se repitan) y con qué frecuencia
        (mucho, de vez en cuando, muy poco) -- si NO usa ninguno en los
        mensajes, decilo explícitamente ('no usa emojis'). Nunca falta
        esta frase, ni inventes emojis que no aparezcan en el texto real.",
      "intereses_nuevos": ["intereses o gustos que se notan en los
        mensajes y que NO están ya en esta lista: {', '.join(intereses_actuales) or 'ninguno'}
        -- lista vacía si no hay ninguno claro, nunca inventes"]
    }}

    Mensajes:
    {texto_mensajes}
    """

    response = client().chat.completions.create(
        model="gpt-5.6-terra",
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


def extraer_correcciones_gemelo(mensajes_a_gemelo):
    """Analiza mensajes que la persona le escribió a SU PROPIO gemelo (chat
    personal, gemelo.html -- NUNCA charlas con matches) y detecta
    instrucciones EXPLÍCITAS que le dio sobre cómo comportarse o hablar (ej:
    "dejá de decir posta", "no me llames Rosita, decime Rosi", "hablame más
    corto"). Sin esto, una corrección solo vivía en el historial de ESA
    conversación puntual (los últimos mensajes que se mandan en cada llamada,
    ver chatear_con_gemelo) -- se perdía apenas se salía de esa ventana, o al
    volver otro día, y el gemelo repetía justo lo que se le había pedido que
    dejara de hacer, sin que fuera realmente un problema de "no aprender"
    sino de no tener dónde guardar la corrección de forma durable. Nunca
    inventa una corrección que no esté dicha tal cual."""

    if not mensajes_a_gemelo:
        return []

    texto_mensajes = "\n".join(f"- {m}" for m in mensajes_a_gemelo)

    prompt = f"""
    Estos son mensajes reales que una persona le escribió a su propio
    asistente de IA (su "gemelo digital") dentro de una app de citas.

    Buscá ÚNICAMENTE instrucciones EXPLÍCITAS que la persona le dio al
    gemelo sobre cómo comportarse, hablar o dirigirse a ella (ej: "dejá de
    decir X", "no me llames así", "hablame más corto", "no seas tan
    formal"). NO cuentan quejas generales, preguntas, ni comentarios sobre
    otras personas -- solo pedidos directos dirigidos AL GEMELO sobre su
    propio comportamiento.

    Devolvé únicamente JSON válido:
    {{
      "correcciones": ["lista de instrucciones tal cual se pueden aplicar,
        en imperativo corto (ej: 'no decir posta', 'llamarla Rosi, no
        Rosita') -- lista vacía si no hay ninguna, nunca inventes"]
    }}

    Mensajes:
    {texto_mensajes}
    """

    response = client().chat.completions.create(
        model="gpt-5.6-terra",
        messages=[
            {
                "role": "system",
                "content": "Detectás instrucciones explícitas que alguien le dio a su asistente de IA. Nunca inventás una que no esté dicha tal cual."
            },
            {"role": "user", "content": prompt}
        ],
        response_format={"type": "json_object"}
    )

    resultado = json.loads(response.choices[0].message.content)
    return [str(c).strip() for c in (resultado.get("correcciones") or []) if str(c).strip()]


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
    conjunto de géneros con los que estaría dispuesta a matchear -- o None
    si no hay ninguna restricción real (acepta cualquier género).

    Antes "sin restricción" se representaba con una lista fija (TODOS =
    Hombre/Mujer/No binario/Otro) que se usaba después como un simple "está
    en la lista sí o no". Esa lista se quedaba corta apenas alguien elegía
    una opción real del onboarding que no estuviera en ella -- "Prefiero no
    decir" es una opción real de la pregunta de género (no solo de
    orientación) y nunca estuvo en esa lista, así que cualquiera que la
    eligiera quedaba excluido de TODOS los matches posibles, aunque la
    orientación de la otra persona no impusiera ninguna restricción real.
    Un "Otro" con texto libre tenía el mismo problema. Usar None como
    sentinel de "sin restricción" (en vez de una lista finita que hay que
    mantener sincronizada con cada opción nueva del onboarding) hace que
    esto no se pueda repetir con la próxima opción que se agregue."""

    SIN_RESTRICCION = None

    o = (orientacion or "").strip().casefold()
    g = (genero or "").strip()

    if o == "heterosexual":
        if g == "Hombre":
            return {"Mujer"}
        if g == "Mujer":
            return {"Hombre"}
        return SIN_RESTRICCION
    if o in ("gay / lesbiana", "gay/lesbiana", "gay", "lesbiana"):
        if g in _GENEROS_CONOCIDOS:
            return {g}
        return SIN_RESTRICCION
    # bisexual, pansexual, asexual, "prefiero no decir", "otro", vacío, o
    # cualquier valor no reconocido: no filtramos por género.
    return SIN_RESTRICCION


def compatible_por_genero(perfil1, perfil2):
    """True si, según género + orientación de cada uno, ninguno de los dos
    quedaría excluido como candidato del otro. Si a alguno le falta el
    género propio no se puede chequear esa mitad -- se deja pasar (no
    excluir por datos faltantes) en vez de bloquear el par entero."""

    g1 = (perfil1.get("genero") or "").strip()
    g2 = (perfil2.get("genero") or "").strip()

    acepta1 = _generos_aceptados(g1, perfil1.get("orientacion"))
    acepta2 = _generos_aceptados(g2, perfil2.get("orientacion"))

    ok_1_acepta_2 = acepta1 is None or (not g2) or (g2 in acepta1)
    ok_2_acepta_1 = acepta2 is None or (not g1) or (g1 in acepta2)

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

        # Excepción confirmada por la investigación (Investigacion de
        # pareja.pdf): la complementariedad ("los opuestos se atraen") en
        # general tiene poco respaldo, PERO introvertido/a + extrovertido/a
        # fue el único caso con efecto positivo real en parejas casadas --
        # por eso acá la diferencia pesa la mitad en vez de penalizar igual
        # que el resto de los rasgos.
        if atributo == "introversion":
            compatibilidad = 1 - diferencia * 0.5
        else:
            compatibilidad = 1 - diferencia

        score += compatibilidad

    return score / len(atributos)


def compatibilidad_intereses(perfil1, perfil2):
    """Similitud de Jaccard (intersección / unión, sin importar mayúsculas)
    entre los intereses de cada uno. Usa intereses_onboarding si está (con
    perfiles viejos que no lo tengan, cae a "intereses"). A diferencia de
    personalidad/valores (que siguen viniendo SOLO del onboarding, nunca de
    un chat, para que no se puedan "inflar"), acá se decidió a propósito
    que sí valga un interés nuevo mencionado en un chat real con el propio
    gemelo o elegido a mano en perfil.html -- ver main.generar_gemelo_ahora,
    que mantiene intereses_onboarding e intereses sincronizados a la misma
    lista combinada (onboarding actual + lo acumulado aparte)."""

    i1 = {str(i).strip().casefold() for i in (perfil1.get("intereses_onboarding") or perfil1.get("intereses") or [])}
    i2 = {str(i).strip().casefold() for i in (perfil2.get("intereses_onboarding") or perfil2.get("intereses") or [])}

    if not i1 or not i2:
        return 0.5

    union = i1 | i2
    return len(i1 & i2) / len(union) if union else 0.5


# Escala ordinal para comparar preferencia de medio de comunicación
# (prefCom) -- 0 a 4, de más escrito/asincrónico a más presencial. Da
# crédito parcial a preferencias cercanas (llamada vs. videollamada) en vez
# de todo-o-nada.
_ESCALA_COMUNICACION = {
    "Mensajes de texto": 0,
    "Audios": 1,
    "Llamadas": 2,
    "Videollamadas": 3,
    "Verse en persona": 4,
}


def compatibilidad_comunicacion(perfil1, perfil2):
    """Similitud en cómo prefieren comunicarse (prefCom, etapa4 del
    onboarding) -- la investigación ubica las "habilidades sociales/estilo
    de comunicación" como el tercer tipo de similitud más preferido en
    pareja, después de valores e intereses."""

    c1 = _ESCALA_COMUNICACION.get((perfil1.get("prefCom") or "").strip())
    c2 = _ESCALA_COMUNICACION.get((perfil2.get("prefCom") or "").strip())
    if c1 is None or c2 is None:
        return 0.5

    return 1 - abs(c1 - c2) / 4


# Escalas ordinales propias por pregunta -- politicaImportancia tiene 3
# opciones, religionImportancia tiene 4, así que no comparten una sola
# escala.
_ESCALA_POLITICA_IMPORTANCIA = {"Muy importante": 2, "Algo importante": 1, "No me importa": 0}
_ESCALA_RELIGION_IMPORTANCIA = {"Muy importante": 3, "Algo importante": 2, "Poco importante": 1, "Nada importante": 0}


def _similitud_ordinal(v1, v2, escala):
    n1 = escala.get((v1 or "").strip())
    n2 = escala.get((v2 or "").strip())
    if n1 is None or n2 is None:
        return None
    maximo = max(escala.values()) or 1
    return 1 - abs(n1 - n2) / maximo


# Margen en cm dentro del cual dos alturas se consideran "misma altura" --
# nadie mide justo lo mismo, así que un par de cm de diferencia no debería
# arruinar la compatibilidad física.
_MARGEN_ALTURA_CM = 3


def _pref_categoria_satisfecha(preferencia, propio_del_otro):
    """True/False si la autodescripción del candidato (propio_del_otro)
    coincide con lo que el evaluador dijo que le atrae (preferencia) --
    None si falta algún dato o si la preferencia es de las que significan
    "no tengo preferencia" (ahí no hay nada que evaluar ni penalizar).

    colorPelo/estiloPelo pasaron a ser multi-select (podés marcar "castaño"
    Y "rubio" pero no "pelirrojo"), así que `preferencia` puede llegar como
    lista en vez de un string suelto -- se normaliza a lista siempre acá
    para no repetir el chequeo en cada llamador."""
    opciones = preferencia if isinstance(preferencia, list) else [preferencia] if preferencia else []
    opciones = [str(o).strip().casefold() for o in opciones if o]
    if not opciones or any(o in ("me da igual", "indiferente") for o in opciones):
        return None
    if not propio_del_otro:
        return None
    return 1.0 if str(propio_del_otro).strip().casefold() in opciones else 0.0


def _altura_satisfecha(preferencia, altura_propia_evaluador, altura_candidato, margen=_MARGEN_ALTURA_CM):
    """La preferencia de altura es relativa ("más bajo/a que yo"), así que
    hace falta la altura propia del evaluador para poder compararla contra
    la del candidato -- no alcanza con un solo dato como en las otras
    dimensiones físicas. Cerca del límite (dentro del margen) da crédito
    parcial en vez de todo o nada."""
    if not preferencia or preferencia == "Indiferente":
        return None
    if altura_propia_evaluador is None or altura_candidato is None:
        return None

    diferencia = altura_candidato - altura_propia_evaluador

    if preferencia == "Más bajos/as que yo":
        if diferencia <= -margen:
            return 1.0
        if diferencia >= margen:
            return 0.0
        return 0.5
    if preferencia == "Más altos/as":
        if diferencia >= margen:
            return 1.0
        if diferencia <= -margen:
            return 0.0
        return 0.5
    if preferencia == "Misma altura":
        return 1.0 if abs(diferencia) <= margen else max(0.0, 1 - (abs(diferencia) - margen) / 10)
    return None


def _satisfaccion_fisica_direccion(evaluador, candidato):
    """Cuánto satisface el físico real de "candidato" las preferencias que
    declaró "evaluador" -- promedio de las dimensiones donde hay preferencia
    Y autodescripción del otro para compararla. None si no hay ninguna
    dimensión evaluable en esta dirección."""
    prefs = evaluador.get("preferencias_pareja") or {}
    fisico_candidato = candidato.get("fisico_propio") or {}
    fisico_evaluador = evaluador.get("fisico_propio") or {}

    scores = []
    for campo in ("colorPelo", "estiloPelo", "contextura"):
        s = _pref_categoria_satisfecha(prefs.get(campo), fisico_candidato.get(campo))
        if s is not None:
            scores.append(s)

    s_altura = _altura_satisfecha(
        prefs.get("alturaAtrae"),
        fisico_evaluador.get("altura_cm"),
        fisico_candidato.get("altura_cm"),
    )
    if s_altura is not None:
        scores.append(s_altura)

    return sum(scores) / len(scores) if scores else None


def compatibilidad_fisica(perfil1, perfil2):
    """A diferencia de los demás ejes (similitud entre los dos), este mide
    SATISFACCIÓN de preferencia: ¿el físico que cada uno dice que le atrae
    (preferencias_pareja: colorPelo/estiloPelo/alturaAtrae/contextura)
    coincide con la autodescripción real del otro (fisico_propio)? Antes
    esas preferencias se guardaban pero no tenían con qué compararse -- el
    onboarding no preguntaba el físico propio de nadie. Se promedian las dos
    direcciones (qué tanto A satisface a B, y B a A). Sin preferencias
    declaradas o sin autodescripción de ningún lado, 0.5 neutro, igual que
    el resto de los ejes con datos faltantes -- nunca excluye por falta de
    datos."""

    s1 = _satisfaccion_fisica_direccion(perfil1, perfil2)
    s2 = _satisfaccion_fisica_direccion(perfil2, perfil1)

    if s1 is None and s2 is None:
        return 0.5
    if s1 is None:
        return s2
    if s2 is None:
        return s1
    return (s1 + s2) / 2


def compatibilidad_creencias(perfil1, perfil2):
    """Similitud en cuánto les importa la política y la religión
    (politicaImportancia/religionImportancia, guardados en perfil.creencias)
    -- el estudio de parejas reales encontró correlación MODERADA (no
    fuerte) en actitudes políticas/religiosas, por eso este eje pesa menos
    que valores/intereses/comunicacion en PESOS_DEFAULT. Falta el dato de
    alguna de las dos preguntas en algún lado -> esa preguntá no promedia,
    no bloquea el eje entero."""

    c1 = perfil1.get("creencias") or {}
    c2 = perfil2.get("creencias") or {}

    scores = []
    sp = _similitud_ordinal(c1.get("politicaImportancia"), c2.get("politicaImportancia"), _ESCALA_POLITICA_IMPORTANCIA)
    if sp is not None:
        scores.append(sp)
    sr = _similitud_ordinal(c1.get("religionImportancia"), c2.get("religionImportancia"), _ESCALA_RELIGION_IMPORTANCIA)
    if sr is not None:
        scores.append(sr)

    return sum(scores) / len(scores) if scores else 0.5

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

def _fit_psicologico_direccion(preferidor, candidato):
    objetivo = preferidor.get("preferencias_pareja_personalidad") or {}
    real = candidato.get("personalidad") or {}
    rasgos = set(objetivo) & set(real)
    if not rasgos:
        return 0.5
    return sum(1 - abs(objetivo[r] - real[r]) for r in rasgos) / len(rasgos)


def compatibilidad_preferencias_unidireccional(preferidor, candidato, analisis=None):
    """Qué tan bien encaja candidato con lo que preferidor busca, pesado con
    los pesos PROPIOS de preferidor (pesos_compatibilidad) -- llamar esto en
    las dos direcciones puede dar números distintos aunque el eje sea el
    mismo, porque lo que cambia es cuánto le importa ese eje a cada uno.

    fisico/psicologico comparan preferencia declarada vs. candidato real;
    valores/intereses/creencias/comunicacion son similitud (no hay
    "objetivo" declarado para esos ejes); conversacional necesita el
    análisis de una charla real -- sin `analisis` (fase de precálculo,
    antes de simular nada), neutro. Sin pesos propios, PESOS_DEFAULT."""

    from gemelo_perfil import PESOS_DEFAULT

    pesos_com = preferidor.get("pesos_compatibilidad") or PESOS_DEFAULT

    s_fisico = _satisfaccion_fisica_direccion(preferidor, candidato)

    ejes = {
        "fisico": 0.5 if s_fisico is None else s_fisico,
        "psicologico": _fit_psicologico_direccion(preferidor, candidato),
        "valores": compatibilidad_valores(preferidor, candidato),
        "intereses": compatibilidad_intereses(preferidor, candidato),
        "creencias": compatibilidad_creencias(preferidor, candidato),
        "comunicacion": compatibilidad_comunicacion(preferidor, candidato),
        "conversacional": compatibilidad_conversacional(analisis) if analisis is not None else 0.5,
    }
    pesos = {eje: pesos_com.get(eje, PESOS_DEFAULT[eje]) for eje in ejes}

    return sum(ejes[e] * pesos[e] for e in ejes) / sum(pesos.values())

def calcular_compatibilidad(perfil1, perfil2, analisis=None):

    # --------------------------------
    # 1. SIMILITUD PURA
    # --------------------------------

    score_psicologico = compatibilidad_psicologica(perfil1, perfil2)
    score_valores = compatibilidad_valores(perfil1, perfil2)
    score_intereses = compatibilidad_intereses(perfil1, perfil2)
    score_creencias = compatibilidad_creencias(perfil1, perfil2)
    score_comunicacion = compatibilidad_comunicacion(perfil1, perfil2)

    pesos_s = {
        "psicologico": 0.16,
        "valores": 0.35,
        "intereses": 0.09,
        "creencias": 0.25,
        "comunicacion": 0.15
    }

    S = (
        score_psicologico * pesos_s["psicologico"] +
        score_valores * pesos_s["valores"] +
        score_intereses * pesos_s["intereses"] +
        score_creencias * pesos_s["creencias"] +
        score_comunicacion * pesos_s["comunicacion"]
    )

    # --------------------------------
    # 2. PREFERENCIA A → B
    # Usa pesos de A
    # --------------------------------

    pref_a_b = compatibilidad_preferencias_unidireccional(
        perfil1,
        perfil2,
        analisis
    )

    # --------------------------------
    # 3. PREFERENCIA B → A
    # Usa pesos de B
    # --------------------------------

    pref_b_a = compatibilidad_preferencias_unidireccional(
        perfil2,
        perfil1,
        analisis
    )

    # --------------------------------
    # 4. INTERACCIÓN
    # --------------------------------

    if analisis is not None:
        score_conversacional = compatibilidad_conversacional(analisis)
    else:
        score_conversacional = None

    # --------------------------------
    # 5. SCORE FINAL
    # --------------------------------

    if score_conversacional is not None:

        # Ejemplo
        alpha = 0.20
        beta = 0.35
        gamma = 0.35
        delta = 0.10


        total = (
            alpha * S +
            beta * pref_a_b +
            gamma * pref_b_a +
            delta * score_conversacional
        )

    else:

        alpha = 0.30
        beta = 0.35
        gamma = 0.35

        total = (
            alpha * S +
            beta * pref_a_b +
            gamma * pref_b_a
        )

    # Desglose por eje -- antes solo se devolvía S (el promedio ya
    # combinado), así que no había forma de mostrarle al usuario POR QUÉ
    # es compatible con alguien (ej: "compatibilidad de valores: 80%" en
    # vez de un solo número mezclado). matches.html lo usa para las barras
    # de "Razones de compatibilidad".
    desglose = {
        "psicologico": score_psicologico,
        "valores": score_valores,
        "intereses": score_intereses,
        "creencias": score_creencias,
        "comunicacion": score_comunicacion,
    }

    return total, S, pref_a_b, pref_b_a, score_conversacional, desglose


# Frase por rasgo describiendo la DIFERENCIA cuando uno lo tiene alto y el
# otro bajo -- (nombre1_tiene_alto, nombre2_tiene_alto), armadas para
# describir a la otra persona en tercera persona ("tiene alta tolerancia al
# conflicto, vos baja"). Mismos 9 rasgos que ya usa _directiva en simulador.
_DIFERENCIA_RASGO = {
    # Las tres de abajo (introversion/apertura_mental/sensibilidad_emocional)
    # antes decían "es bastante más/menos QUE VOS frente a ideas nuevas" --
    # le faltaba el adjetivo del rasgo, quedaba una frase incompleta ("menos
    # ¿qué?"). Ahora {alto} modifica un adjetivo real (abierto-a/sensible),
    # no queda pegado directo a "que vos". "introversion" en particular
    # describe el rasgo CRUDO (introvertido/a), no "sociable" -- {alto} ya
    # viene calculado sobre el valor de introversión, así que frasearlo
    # como "más/menos sociable" invertía el sentido (más introvertido/a =
    # MENOS sociable, no más).
    "introversion": "es bastante {alto} introvertido/a que vos",
    "empatia": "le da bastante más/menos peso que a vos a cómo se siente el otro emocionalmente",
    "sarcasmo": "tiene un sentido del humor bastante distinto al tuyo (mucho más o mucho menos sarcástico/a)",
    "apertura_mental": "es bastante {alto} abierto/a a ideas o planes nuevos que vos",
    "ambicion": "le importa bastante {alto} que a vos crecer/lograr cosas a nivel profesional",
    "sensibilidad_emocional": "es bastante {alto} sensible que vos a nivel emocional -- le afectan {alto} las cosas del día a día",
    "necesidad_afecto": "necesita bastante {alto} validación/cercanía afectiva que vos",
    "independencia": "valora bastante {alto} su independencia que vos",
    "tolerancia_conflicto": "tolera bastante {alto} el conflicto/discutir que vos",
}


# Frase por eje de VALORES describiendo la diferencia -- familia/aventura/
# estabilidad viven en perfil.valores, no en perfil.personalidad. "ambicion"
# vive en los dos (gemelo_perfil.construir_perfil_gemelo copia el valor a
# personalidad para que _directiva pueda usarlo en el prompt) así que NO se
# repite acá para no duplicar la misma frase de fricción dos veces.
_DIFERENCIA_VALOR = {
    "familia": "le da bastante {alto} peso a formar/priorizar una familia que vos",
    "aventura": "es bastante {alto} de tirarse a planes nuevos o arriesgados que vos",
    "estabilidad": "necesita bastante {alto} estabilidad y rutina en su vida que vos",
}


def _resolver_genero(texto, genero):
    """Mismo mecanismo que resolverGenero() en gemelo-setup.html (JS), pero
    del lado del servidor -- las plantillas de _DIFERENCIA_RASGO/_DIFERENCIA_
    VALOR usan la forma "palabra/a" (introvertido/a, abierto/a) porque no se
    sabe de antemano el género de quién describen. Sin esto, la frase le
    quedaba literal "es bastante más abierto/a" a cualquiera, sin importar
    que su perfil ya tuviera declarado "Mujer"/"Hombre"/etc."""
    if not texto:
        return texto
    femenino = genero == "Mujer"

    def _reemplazar(m):
        base = m.group(1)
        if not femenino:
            return base
        return base[:-1] + "a" if base.endswith("o") else base + "a"

    texto = re.sub(r"(\w+)/a\b", _reemplazar, texto, flags=re.UNICODE)
    texto = re.sub(r"\bEl/la\b", "La" if femenino else "El", texto)
    texto = re.sub(r"\bel/la\b", "la" if femenino else "el", texto)
    return texto


def _diferencias_personalidad(perfil1, perfil2, nombre2, umbral_diferencia=0.3, top_n=2, minimo=0):
    """Desde la perspectiva de perfil1: en qué rasgos reales diverge más de
    perfil2 (personalidad Y valores juntos, ordenado por magnitud real de la
    diferencia, no por eje), para dar puntos de fricción CONCRETOS en vez de
    una instrucción abstracta de "no estén siempre de acuerdo". Sin esto,
    una pareja que difiere sobre todo en VALORES (familia/aventura/
    estabilidad, el eje que más pesa en la similitud pura -- ver pesos_s en
    calcular_compatibilidad) pero tiene personalidades parecidas terminaba
    sin ningún punto de fricción concreto, aunque su compatibilidad total
    fuera media/baja por esa diferencia de valores. Devuelve una lista de
    frases listas para mostrar, ya en tercera persona (sobre nombre2) --
    vacía si no hay diferencias grandes o faltan datos.

    "minimo" garantiza un piso de frases aunque no lleguen al umbral -- para
    mostrar en matches.html hacen falta al menos 3 puntos de análisis, pero
    con umbral_diferencia=0.3 un par muy parecido en casi todo podía dejar
    solo 1. Si no alcanza el umbral, se completa con las siguientes
    diferencias más grandes disponibles (nunca con diferencias
    insignificantes -- ver el descarte de <= 0.02 abajo, donde la frase
    "más/menos" ya no describiría nada real)."""
    p1, p2 = perfil1.get("personalidad") or {}, perfil2.get("personalidad") or {}
    val1, val2 = perfil1.get("valores") or {}, perfil2.get("valores") or {}

    todas = []
    for campo1, campo2, plantillas in ((p1, p2, _DIFERENCIA_RASGO), (val1, val2, _DIFERENCIA_VALOR)):
        for rasgo, plantilla in plantillas.items():
            v1, v2 = campo1.get(rasgo), campo2.get(rasgo)
            if v1 is None or v2 is None:
                continue
            diferencia = abs(v1 - v2)
            if diferencia <= 0.02:
                continue
            alto = "más" if v2 > v1 else "menos"
            texto = _resolver_genero(plantilla.format(alto=alto), perfil2.get("genero", ""))
            todas.append((diferencia, f"{nombre2} {texto}."))

    todas.sort(key=lambda x: -x[0])
    n = max(top_n, minimo)

    resultado = [texto for mag, texto in todas if mag >= umbral_diferencia][:n]
    if minimo and len(resultado) < minimo:
        ya = set(resultado)
        for _, texto in todas:
            if len(resultado) >= minimo:
                break
            if texto not in ya:
                resultado.append(texto)
                ya.add(texto)
    return resultado


# Temas CONCRETOS que se pueden pedir sin inventar nada, porque están
# anclados a preguntas reales del onboarding (ver gemelo_perfil.py) -- cada
# uno solo se agrega si al menos uno de los dos perfiles tiene el dato real
# que lo respalda. Reemplaza dejar que el modelo elija sus propios "temas
# profundos": antes a veces eran genéricos o directamente no tenían dato
# real detrás, así que terminaba rellenando con algo inventado.
def _temas_obligatorios(perfil1, perfil2, nombre1=None, nombre2=None, top_n=3):
    """Arma una lista de temas que la charla tiene que tocar sí o sí, en
    orden de prioridad, filtrando solo los que tienen datos reales de
    onboarding para al menos uno de los dos perfiles."""
    disponibles = []

    if perfil1.get("conflictos") or perfil2.get("conflictos"):
        disponibles.append(
            "Un desacuerdo o conflicto REAL entre ustedes dos -- NO es una "
            "charla sobre cómo manejan los conflictos en general ni sobre "
            "su forma de ser, es un choque que pasa AHORA, en esta misma "
            "charla. Usen las diferencias reales de personalidad/valores de "
            "más arriba (si hay) como motivo concreto para el desacuerdo. "
            "MUY IMPORTANTE: cada uno reacciona SEGÚN SU PROPIO estilo real "
            "de manejar el conflicto (ver 'CÓMO MANEJA LOS CONFLICTOS' en su "
            "propio perfil) -- eso NO es opcional ni una opción más entre "
            "varias, es LA que corresponde usar. Si tus datos dicen que "
            "necesitás distancia o te cuesta abrirte, tu reacción real acá "
            "es pedir espacio, cerrarte o cortar la charla un rato -- NUNCA "
            "confrontar directo, marcar todo punto por punto, ni ponerte "
            "frío/a de golpe, aunque eso sea más dramático o 'interesante' "
            "narrativamente. Si tus datos dicen que confrontás directo, "
            "ahí sí corresponde decir las cosas de frente. No mezcles: la "
            "persona que dijo que le cuesta mostrar cómo se siente y busca "
            "distancia primero JAMÁS reacciona con un choque frontal solo "
            "porque es lo que arma un conflicto más rápido. Lo que importa "
            "es que se vea CÓMO LO ENFRENTAN Y LO RESUELVEN (o si no lo "
            "resuelven) siendo fieles a cómo son de verdad, no una versión "
            "genérica de 'alguien peleando'."
        )

    if perfil1.get("plan_futuro") or perfil2.get("plan_futuro") or perfil1.get("valores") or perfil2.get("valores"):
        disponibles.append(
            "Cómo se imaginan a futuro (usen '¿Cómo se imagina en 5 años?' "
            "de cada perfil si está -- instalarse y estar estable, formar "
            "familia, enfocarse en la carrera, seguir explorando, viajar "
            "sin planes fijos) y ambición profesional / estabilidad vs. "
            "aventura en general (VALORES PERSONALES de cada perfil) -- "
            "esto dice mucho de si encajan a largo plazo, no lo traten "
            "como un dato de relleno."
        )

    hijos1 = perfil1.get("postura_hijos", "")
    hijos2 = perfil2.get("postura_hijos", "")
    if hijos1 or hijos2:
        disponibles.append(
            "Si quieren tener hijos o no, y qué tan importante es la "
            "familia a futuro -- usen la postura real de '¿Quiere tener "
            "hijos?' de cada perfil (arriba, en VALORES PERSONALES), nunca "
            "inventen una postura que no esté ahí."
        )

    cre1, cre2 = perfil1.get("creencias") or {}, perfil2.get("creencias") or {}
    valores_creencias = list(cre1.values()) + list(cre2.values())
    _MUY_IMPORTANTE = {"Muy importante"}
    if any(v in _MUY_IMPORTANTE for v in valores_creencias):
        disponibles.append(
            "Qué tan importante es para cada uno la política y/o la "
            "religión en su vida diaria (usen la POSTURA FRENTE A POLÍTICA "
            "Y RELIGIÓN real de cada perfil, nunca inventen una ideología "
            "puntual) -- a al menos uno de los dos le importa bastante, así "
            "que este tema amerita profundizar de verdad si sale."
        )
    elif any(v and v not in ("No me importa", "Nada importante") for v in valores_creencias):
        disponibles.append(
            "Política y/o religión les puede importar ALGO, pero no mucho "
            "a ninguno de los dos -- si sale el tema, tóquenlo rápido y de "
            "pasada (una frase, un comentario) y sigan a otra cosa "
            "enseguida. No lo conviertan en un tema central ni se queden "
            "dando vueltas ahí -- eso no sería realista para alguien a "
            "quien esto no le importa tanto."
        )

    if perfil1.get("prioridad_compatibilidad") or perfil2.get("prioridad_compatibilidad"):
        disponibles.append(
            "Qué es lo que más necesitan/valoran en una conexión con "
            "alguien (ya está declarado en cada perfil, en orden de "
            "prioridad)."
        )

    resultado = disponibles[:top_n]

    # Los intereses van SIEMPRE aparte, sin competir por los top_n lugares
    # de arriba -- no es un tema "profundo" a agregar a la lista de a uno,
    # es un piso mínimo de charla casual que tiene que estar sí o sí, pero
    # sin ir tan en detalle (a diferencia de los temas de arriba, que sí
    # ameritan profundizar).
    # Se sortean 1-2 intereses REALES de cada uno para esta charla puntual
    # -- antes se le dejaba al modelo elegir qué interés mencionar, y
    # sistemáticamente convergía en los mismos de siempre (fútbol, día de
    # descanso, música, series) sin importar qué tuviera cada perfil
    # realmente cargado. Sorteando server-side, cada simulación toca algo
    # distinto de verdad, no lo que el modelo "prefiere" mencionar.
    intereses1 = perfil1.get("intereses") or []
    intereses2 = perfil2.get("intereses") or []
    elegidos1 = random.sample(intereses1, min(2, len(intereses1)))
    elegidos2 = random.sample(intereses2, min(2, len(intereses2)))
    if elegidos1 or elegidos2:
        partes_intereses = []
        if elegidos1:
            partes_intereses.append(f"de {nombre1 or 'uno/a'}: {', '.join(elegidos1)}")
        if elegidos2:
            partes_intereses.append(f"de {nombre2 or 'el/la otro/a'}: {', '.join(elegidos2)}")
        resultado.append(
            "De sus intereses reales, para ESTA charla puntual les toca la "
            "posibilidad de mencionar (si sale con naturalidad, sin forzarlo "
            "ni anunciarlo) -- " + "; ".join(partes_intereses) + ". Elegidos al "
            "azar para esta charla en particular -- en otra charla tocarían "
            "otros. Alcanza con mencionarlos de pasada, sin ir muy en "
            "profundidad en ninguno -- esto es un piso mínimo de charla "
            "casual, no el eje central. No se queden solo en series/música "
            "por costumbre si estos intereses sorteados son otra cosa."
        )

    return resultado


def instruccion_nivel_compatibilidad(perfil1, perfil2, umbral, nombre1=None, nombre2=None):
    """Texto para inyectar en el prompt de generar_prompt_gemelo/
    contexto_escenario -- sin esto, una charla podía fluir perfecta entre
    dos perfiles que en los datos reales (onboarding) comparten poco,
    porque nada le decía al modelo que calibrara la facilidad de la
    charla contra la compatibilidad real. No se le pasa el % exacto (para
    que no lo actúe/mencione literal) -- solo un nivel cualitativo, que
    sirve de guía de qué tan fácil o difícil tiene que sentirse fluir.
    Usa compatibilidad SOLO de onboarding (analisis=None) -- la charla en
    cuestión todavía no pasó, no se puede analizar a sí misma."""
    promedio_previo, _, _, _, _, _ = calcular_compatibilidad(perfil1, perfil2)

    # 4 escalones, no 3 -- antes "MEDIA" era un solo balde entre el umbral y
    # 0.70, así que un 53% y un 68% recibían EXACTAMENTE la misma exigencia
    # de fricción, aunque haya casi 15 puntos de diferencia real entre
    # ellos. El nivel de conflicto tiene que escalar junto con el score, no
    # ser binario (hay conflicto / no hay conflicto).
    punto_medio = (umbral + 0.70) / 2
    if promedio_previo >= 0.70:
        nivel = "ALTA -- comparten bastante de verdad en valores, forma de ser y de comunicarse"
    elif promedio_previo >= punto_medio:
        nivel = "MEDIA-ALTA -- comparten bastante, pero no todo -- hay alguna diferencia real de fondo"
    elif promedio_previo >= umbral:
        nivel = "MEDIA-BAJA -- comparten algunas cosas pero también hay diferencias reales de peso"
    else:
        nivel = "BAJA -- en los datos reales de los dos hay bastante poco en común"

    # Puntos de fricción CONCRETOS (no solo "no estén siempre de acuerdo"
    # en abstracto) -- en la práctica, la instrucción cualitativa sola no
    # alcanzaba para evitar que dos perfiles con 53% de compatibilidad
    # terminaran reflejándose el uno al otro como calcados. Con diferencias
    # de personalidad puntuales y nombradas, el modelo tiene algo real y
    # específico para chocar, no solo la orden genérica de "generar
    # fricción" (mucho más fácil de ignorar).
    friccion_txt = ""
    if promedio_previo < 0.70 and nombre1 and nombre2:
        diffs_1_ve_2 = _diferencias_personalidad(perfil1, perfil2, nombre2)
        diffs_2_ve_1 = _diferencias_personalidad(perfil2, perfil1, nombre1)
        if diffs_1_ve_2 or diffs_2_ve_1:
            puntos = "\n    ".join(f"- {d}" for d in (diffs_1_ve_2 + diffs_2_ve_1))
            friccion_txt = f"""
    DIFERENCIAS REALES DE PERSONALIDAD ENTRE USTEDES DOS (usalas como
    semillas de fricción real -- si sale un tema donde esto aplica, que SE
    NOTE la diferencia en cómo reaccionan, no la disimulen ni la
    suavicen):
    {puntos}
    Por ejemplo: si uno tolera mal el conflicto y el otro no, uno se va a
    sentir incómodo/a con algo que el otro dice con total naturalidad. Si
    uno necesita mucha más cercanía afectiva, puede sentir que el otro es
    frío/a. USEN esto quien corresponda -- no lo ignoren para llevarse
    bien porque sí."""

    temas = _temas_obligatorios(perfil1, perfil2, nombre1=nombre1, nombre2=nombre2, top_n=4)
    temas_txt = ""
    if temas:
        puntos_temas = "\n    ".join(f"- {t}" for t in temas)
        temas_txt = f"""
    TEMAS QUE ESTA CHARLA TIENE QUE TOCAR SÍ O SÍ (sacados directo de datos
    reales del onboarding de los dos -- no los reemplacen por otros
    inventados, y no hace falta anunciarlos, que salgan con naturalidad en
    algún punto de la charla):
    {puntos_temas}"""

    # La intensidad de la fricción exigida escala junto con el nivel --
    # antes MEDIA-ALTA (ej: 68%) y MEDIA-BAJA (ej: 53%) recibían la MISMA
    # exigencia ("al menos una pelea/desacuerdo notorio"), así que subir de
    # 53% a 60% no cambiaba en nada qué tan fuerte tenía que ser el choque.
    if nivel.startswith("ALTA"):
        intensidad_txt = ""
    elif nivel.startswith("MEDIA-ALTA"):
        intensidad_txt = """
    Como la compatibilidad es MEDIA-ALTA, la fricción tiene que ser LEVE --
    nada de pelea seria ni de ponerse frío/a de golpe, eso EXAGERARÍA la
    incompatibilidad real. Alcanza con un roce chico: una diferencia de
    opinión puntual que no escala, un comentario que incomoda un toque,
    un "che, no sé si estoy de acuerdo con eso" sin más drama, o un
    silencio corto antes de seguir. EXIGENCIA CONCRETA: al menos UN roce
    así tiene que pasar, pero manteniéndose liviano -- no lo conviertan en
    el eje de la charla."""
    elif nivel.startswith("MEDIA-BAJA"):
        intensidad_txt = """
    Como la compatibilidad es MEDIA-BAJA, la fricción tiene que notarse de
    verdad, más que un roce chico -- un desacuerdo real donde uno dice
    derecho que no está de acuerdo, algo parecido a una discusión corta,
    o un ambiente notoriamente más incómodo/con menos onda en algún tramo
    de la charla. No hace falta que sea una pelea grande, pero sí algo
    más que un comentario suelto. EXIGENCIA CONCRETA: al menos UNA de
    estas formas tiene que pasar de manera clara, no sutil."""
    else:
        intensidad_txt = """
    Como la compatibilidad es BAJA, la fricción tiene que ser fuerte y
    real: un desacuerdo serio, algo parecido a una pelea de verdad, o muy
    poca confianza para abrirse (respuestas cortas/evasivas en temas
    personales) combinado con un ambiente incómodo sostenido, no solo un
    momento puntual. EXIGENCIA CONCRETA, no opcional: en algún punto de
    esta charla tiene que pasar al menos UNA de estas formas de manera
    clara y notoria."""

    return f"""
    COMPATIBILIDAD REAL ENTRE USTEDES DOS (según sus datos reales de
    fondo, no esta charla puntual): {nivel}. Esto NO es algo que tengan
    que mencionar ni actuar de forma literal -- es una guía para qué tan
    fácil o difícil tiene que fluir la charla. NUNCA repitan o parafraseen
    lo que acaba de decir el otro como si fuera lo mismo que ustedes
    piensan/sienten/hacen -- eso es el error más grave posible acá,
    literalmente actuar como si fueran la misma persona cuando NO comparten
    tanto en los datos reales.
    {"" if nivel.startswith("ALTA") else '''
    OJO: compatibilidad no-ALTA no significa una charla más corta ni con
    menos temas -- la charla dura lo mismo y toca la misma cantidad de
    temas que cualquier otra. La diferencia se nota en CÓMO SE SIENTEN esos
    temas y en la intensidad de la fricción (ver abajo), nunca en cuántos
    hay ni cuánto dura la charla. Lo que NO sirve para mostrar esto: cortar
    la charla antes, evitar cambiar de tema, o simplemente hablar menos en
    general -- eso no se lee como incompatibilidad, se lee como una charla
    mal actuada.'''}
    {intensidad_txt}
    {friccion_txt}
    {temas_txt}
    """
