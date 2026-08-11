# Convierte las respuestas crudas del onboarding (gemelo-setup.html, guardadas en
# Firestore bajo usuarios/{uid}/gemelo_setup/data) en el perfil normalizado que
# consume el motor de gemelos de prueba.py.
#
# Reglas cerradas (pills/radios/binarias) -> rasgos numéricos 0.0-1.0, por señales
# acumulativas sobre una base neutra de 0.5. Preguntas de texto libre -> notas
# narrativas (se citan tal cual en el prompt, no se intenta convertirlas a número).
# Preguntas sobre "qué te atrae de otra persona" -> preferencias_pareja, separado
# de los rasgos propios (no se usan en calcular_compatibilidad todavía).

BASE_PERSONALIDAD = (
    "introversion", "empatia", "sarcasmo", "apertura_mental",
    "sensibilidad_emocional", "necesidad_afecto", "independencia", "tolerancia_conflicto",
)
BASE_VALORES = ("familia", "ambicion", "aventura", "estabilidad")

# Pesos por default para combinar los 3 ejes de calcular_compatibilidad
# (deben coincidir con los que usaba prueba.py originalmente, así el
# comportamiento no cambia para quien no respondió estas preguntas).
PESOS_DEFAULT = {"psicologico": 0.35, "conversacional": 0.40, "valores": 0.25}

# Qué tan importante es cada eje de compatibilidad para ESTE usuario, según lo
# que dijo que más necesita en un vínculo (necesitasVinc) y qué es lo que más
# le atrae / qué tipo de conexión busca primero en otra persona (conexionPrimero,
# atraeMas). Esto reemplaza el peso fijo 0.35/0.40/0.25 por uno propio de cada
# persona; calcular_compatibilidad() combina el de los dos usuarios de la pareja.
REGLAS_PESOS = [
    ("etapa4", "necesitasVinc", "Poder hablar de lo que me pasa sin filtro", {"psicologico": 0.05}),
    ("etapa4", "necesitasVinc", "Disponibilidad real cuando la necesito", {"conversacional": 0.05}),
    ("etapa4", "necesitasVinc", "Estabilidad y tranquilidad en el vínculo", {"valores": 0.08}),
    ("etapa4", "necesitasVinc", "Que respeten mi independencia y tiempos", {"psicologico": 0.05}),
    ("etapa4", "necesitasVinc", "Poder resolver conflictos hablando, sin dramas", {"psicologico": 0.05}),
    ("etapa6", "conexionPrimero", "Emocional", {"psicologico": 0.08}),
    ("etapa6", "conexionPrimero", "Mental", {"psicologico": 0.05}),
    ("etapa6", "conexionPrimero", "Física", {"conversacional": 0.08}),
    ("etapa6", "conexionPrimero", "Divertida", {"conversacional": 0.08}),
    ("etapa6", "conexionPrimero", "Tranquila", {"valores": 0.08}),
    ("etapa6", "atraeMas", "Seguro/a", {"psicologico": 0.04}),
    ("etapa6", "atraeMas", "Sensible", {"psicologico": 0.04}),
    ("etapa6", "atraeMas", "Gracioso/a", {"conversacional": 0.06}),
    ("etapa6", "atraeMas", "Inteligente", {"psicologico": 0.04}),
    ("etapa6", "atraeMas", "Creativo/a", {"conversacional": 0.04}),
    ("etapa6", "atraeMas", "Ambicioso/a", {"valores": 0.06}),
]

# (etapa, campo, respuesta_exacta, {"grupo.rasgo": delta})
REGLAS_NUMERICAS = [
    # ── Etapa 1: identidad y rutina ──
    ("etapa1", "convivo", "Solo/a", {"personalidad.independencia": 0.10, "personalidad.introversion": 0.05}),
    ("etapa1", "convivo", "Con mi familia", {"valores.familia": 0.10}),
    ("etapa1", "convivo", "Con pareja", {"valores.estabilidad": 0.05}),
    ("etapa1", "gustaOcup", "Sí, mucho", {"valores.ambicion": 0.15}),
    ("etapa1", "gustaOcup", "Bastante", {"valores.ambicion": 0.08}),
    ("etapa1", "gustaOcup", "No realmente", {"valores.ambicion": -0.10}),
    ("etapa1", "rutina", "Tranquila", {"valores.estabilidad": 0.10, "personalidad.apertura_mental": -0.05}),
    ("etapa1", "rutina", "Intensa", {"valores.ambicion": 0.10}),
    ("etapa1", "rutina", "Cambiante", {"valores.aventura": 0.10, "personalidad.apertura_mental": 0.10}),
    ("etapa1", "rutina", "Caótica", {"valores.aventura": 0.10, "personalidad.apertura_mental": 0.10, "valores.estabilidad": -0.10}),
    ("etapa1", "rutina", "Repetitiva", {"valores.estabilidad": 0.10, "personalidad.apertura_mental": -0.10}),

    # ── Etapa 2: estilo, redes ──
    ("etapa2", "estetica", "Alternativa", {"personalidad.apertura_mental": 0.05}),
    ("etapa2", "estetica", "Artística", {"personalidad.apertura_mental": 0.05}),
    ("etapa2", "sobreLikes", "Sí, bastante", {"personalidad.sensibilidad_emocional": 0.10, "personalidad.necesidad_afecto": 0.05}),
    ("etapa2", "sobreLikes", "Para nada", {"personalidad.sensibilidad_emocional": -0.05}),
    ("etapa2", "stalkear", "Obvio que sí", {"personalidad.necesidad_afecto": 0.10}),
    ("etapa2", "stalkear", "No, no me interesa", {"personalidad.necesidad_afecto": -0.05, "personalidad.independencia": 0.05}),
    ("etapa2", "lugarIdeal", "Ruta / viaje", {"valores.aventura": 0.10}),
    ("etapa2", "lugarIdeal", "En casa", {"valores.estabilidad": 0.05, "personalidad.introversion": 0.05}),
    ("etapa2", "lugarIdeal", "Recital", {"valores.aventura": 0.05}),

    # ── Etapa 3: personalidad y mundo interior ──
    ("etapa3", "comoSoy", "Tranquilo/a", {"personalidad.introversion": 0.05, "valores.estabilidad": 0.05}),
    ("etapa3", "comoSoy", "Divertido/a", {"personalidad.sarcasmo": 0.05}),
    ("etapa3", "comoSoy", "Intenso/a", {"personalidad.sensibilidad_emocional": 0.10}),
    ("etapa3", "comoSoy", "Reservado/a", {"personalidad.introversion": 0.15, "personalidad.sarcasmo": -0.05}),
    ("etapa3", "comoSoy", "Sociable", {"personalidad.introversion": -0.15}),
    ("etapa3", "comoSoy", "Creativo/a", {"personalidad.apertura_mental": 0.10}),
    ("etapa3", "comoSoy", "Sensible", {"personalidad.empatia": 0.10, "personalidad.sensibilidad_emocional": 0.15}),
    ("etapa3", "comoSoy", "Impulsivo/a", {"personalidad.tolerancia_conflicto": -0.05, "valores.aventura": 0.05}),
    ("etapa3", "comoSoy", "Observador/a", {"personalidad.introversion": 0.05}),
    ("etapa3", "comoSoy", "Espontáneo/a", {"valores.aventura": 0.10, "personalidad.apertura_mental": 0.05}),
    ("etapa3", "genteNueva", "Tomás iniciativa", {"personalidad.introversion": -0.15}),
    ("etapa3", "genteNueva", "Esperás que se acerquen", {"personalidad.introversion": 0.15}),
    ("etapa3", "genteNueva", "Observás primero", {"personalidad.introversion": 0.08}),
    ("etapa3", "findeDesc", "Quedarme solo/a en casa para descansar", {"personalidad.introversion": 0.15}),
    ("etapa3", "findeDesc", "Salir a tomar algo con gente para distraerme", {"personalidad.introversion": -0.15}),
    ("etapa3", "diasSolo", "Re bien, disfruto mis momentos a solas", {"personalidad.introversion": 0.15, "personalidad.independencia": 0.10}),
    ("etapa3", "diasSolo", "Un poco encerrado/a, me dan ganas de ver gente", {"personalidad.introversion": -0.10}),
    ("etapa3", "viajePlan", "Prefiero planificar y tener todo organizado", {"valores.estabilidad": 0.10, "valores.aventura": -0.05}),
    ("etapa3", "viajePlan", "Prefiero fluir y decidir en el momento", {"valores.aventura": 0.15}),
    ("etapa3", "decision", "Actúo rápido y confío en mi intuición", {"valores.aventura": 0.05}),
    ("etapa3", "cambioPlanes", "Me adapto fácil, incluso me puede gustar lo inesperado", {"personalidad.apertura_mental": 0.15, "valores.estabilidad": -0.05}),
    ("etapa3", "cambioPlanes", "Me cuesta, necesito tiempo para acomodarme", {"personalidad.apertura_mental": -0.15, "valores.estabilidad": 0.10}),
    ("etapa3", "sentirFondo", "Siento todo bastante intenso, me atraviesa lo que me pasa", {"personalidad.sensibilidad_emocional": 0.20}),
    ("etapa3", "sentirFondo", "Suelo mantener cierta distancia emocional", {"personalidad.sensibilidad_emocional": -0.20}),
    ("etapa3", "impactoEmoc", "Necesito hablarlo con alguien para ordenarme", {"personalidad.necesidad_afecto": 0.10, "personalidad.sensibilidad_emocional": 0.05}),
    ("etapa3", "impactoEmoc", "Lo proceso por mi cuenta y después veo si lo comparto", {"personalidad.independencia": 0.10}),
    ("etapa3", "impactoEmoc", "Lo escribo o busco entenderlo de alguna forma", {"personalidad.apertura_mental": 0.05}),
    ("etapa3", "impactoEmoc", "Intento distraerme y que se me pase", {"personalidad.sensibilidad_emocional": -0.10, "personalidad.tolerancia_conflicto": -0.05}),

    # ── Etapa 4: comunicación y vínculos ──
    ("etapa4", "velocResp", "Siempre rápido", {"personalidad.necesidad_afecto": 0.05}),
    ("etapa4", "velocResp", "Desaparezco seguido", {"personalidad.independencia": 0.10, "personalidad.necesidad_afecto": -0.10}),
    ("etapa4", "iniciarConv", "No, arranco yo siempre", {"personalidad.introversion": -0.10}),
    ("etapa4", "iniciarConv", "Sí, prefiero que me escriban", {"personalidad.introversion": 0.10}),
    ("etapa4", "respSecas", "Sí, mucho", {"personalidad.necesidad_afecto": 0.15, "personalidad.sensibilidad_emocional": 0.05}),
    ("etapa4", "respSecas", "No me importa", {"personalidad.necesidad_afecto": -0.10}),
    ("etapa4", "demostrar", "Contacto físico", {"personalidad.necesidad_afecto": 0.05}),
    ("etapa4", "intensoGusta", "Sí, bastante", {"personalidad.sensibilidad_emocional": 0.15, "personalidad.necesidad_afecto": 0.10}),
    ("etapa4", "intensoGusta", "No, soy bastante calmo/a", {"personalidad.sensibilidad_emocional": -0.10}),
    ("etapa4", "enamoraFacil", "Sí, me pasa seguido", {"personalidad.sensibilidad_emocional": 0.10, "personalidad.necesidad_afecto": 0.10}),
    ("etapa4", "enamoraFacil", "No, me cuesta mucho", {"personalidad.sensibilidad_emocional": -0.05, "personalidad.independencia": 0.05}),
    ("etapa4", "cuandoMolesta", "Lo hablo enseguida", {"personalidad.tolerancia_conflicto": 0.15}),
    ("etapa4", "cuandoMolesta", "Me alejo", {"personalidad.tolerancia_conflicto": -0.15}),
    ("etapa4", "cuandoMolesta", "Exploto después", {"personalidad.tolerancia_conflicto": -0.10, "personalidad.sensibilidad_emocional": 0.10}),
    ("etapa4", "cuandoMolesta", "Actúo como si nada", {"personalidad.tolerancia_conflicto": -0.10}),
    ("etapa4", "pedirAlgo", "Sí, suelo decir lo que necesito sin problema", {"personalidad.tolerancia_conflicto": 0.05}),
    ("etapa4", "pedirAlgo", "Me cuesta bastante pedir ayuda o expresar lo que necesito", {"personalidad.necesidad_afecto": 0.10, "personalidad.tolerancia_conflicto": -0.05}),
    ("etapa4", "pelea", "Digo lo que pienso aunque genere discusión", {"personalidad.tolerancia_conflicto": 0.15}),
    ("etapa4", "pelea", "Intento hablarlo con calma para resolverlo", {"personalidad.tolerancia_conflicto": 0.15, "personalidad.empatia": 0.10}),
    ("etapa4", "pelea", "Me guardo cosas para evitar conflictos", {"personalidad.tolerancia_conflicto": -0.15}),
    ("etapa4", "pelea", "Necesito tomar distancia antes de hablar", {"personalidad.tolerancia_conflicto": -0.05}),
    ("etapa4", "coqueteo", "Me cuesta mucho demostrarlo", {"personalidad.introversion": 0.05}),
    ("etapa4", "acompaniado", "Que me busquen sin que pida", {"personalidad.necesidad_afecto": 0.15}),
    ("etapa4", "acompaniado", "Que me escuchen y validen", {"personalidad.empatia": 0.05, "personalidad.necesidad_afecto": 0.10}),
    ("etapa4", "necesitasVinc", "Que respeten mi independencia y tiempos", {"personalidad.independencia": 0.15}),
    ("etapa4", "necesitasVinc", "Disponibilidad real cuando la necesito", {"personalidad.necesidad_afecto": 0.10}),
    ("etapa4", "necesitasVinc", "Estabilidad y tranquilidad en el vínculo", {"valores.estabilidad": 0.15}),
    ("etapa4", "necesitasVinc", "Poder resolver conflictos hablando, sin dramas", {"personalidad.tolerancia_conflicto": 0.10}),

    # ── Etapa 5: chin-chin (binarias propias, no las de "qué te atrae") ──
    ("etapa5", "veloc", "Ir despacio", {"valores.estabilidad": 0.05}),
    ("etapa5", "veloc", "Ir rápido", {"valores.aventura": 0.05}),
    ("etapa5", "profConv", "Charlas profundas desde el inicio", {"personalidad.apertura_mental": 0.10, "personalidad.sensibilidad_emocional": 0.05}),
    ("etapa5", "frecContact", "Hablar todo el día", {"personalidad.necesidad_afecto": 0.10}),
    ("etapa5", "frecContact", "Hablar más espaciado", {"personalidad.independencia": 0.10}),
    ("etapa5", "citaLugar", "Quedarse en casa", {"personalidad.introversion": 0.05}),
    ("etapa5", "citaLugar", "Salir de noche", {"personalidad.introversion": -0.05, "valores.aventura": 0.05}),
    ("etapa5", "citaJuntada", "Fiesta grande", {"personalidad.introversion": -0.05}),
    ("etapa5", "citaJuntada", "Juntada chica", {"personalidad.introversion": 0.05}),
    ("etapa5", "carinoPublic", "Cariño privado", {"personalidad.introversion": 0.05}),
    ("etapa5", "carinoPublic", "Demostrar públicamente", {"personalidad.introversion": -0.05}),
    ("etapa5", "enElAmor", "El/la que se enamora rápido", {"personalidad.sensibilidad_emocional": 0.10, "personalidad.necesidad_afecto": 0.10}),
    ("etapa5", "enElAmor", "El/la que tarda en abrirse", {"personalidad.introversion": 0.10, "personalidad.independencia": 0.05}),
    ("etapa5", "enElAmor", "El/la que da demasiado", {"personalidad.necesidad_afecto": 0.15, "personalidad.empatia": 0.10}),
    ("etapa5", "enElAmor", "El/la protector/a", {"personalidad.empatia": 0.10}),
    ("etapa5", "enElAmor", "El/la intenso/a", {"personalidad.sensibilidad_emocional": 0.15}),
    ("etapa5", "enRelacion", "Independiente", {"personalidad.independencia": 0.15}),
    ("etapa5", "enRelacion", "Celoso/a", {"personalidad.necesidad_afecto": 0.10, "personalidad.tolerancia_conflicto": -0.05}),
    ("etapa5", "enRelacion", "Protector/a", {"personalidad.empatia": 0.10}),
    ("etapa5", "enRelacion", "Sensible", {"personalidad.sensibilidad_emocional": 0.10}),
    ("etapa5", "dejResponder", "Te da igual", {"personalidad.necesidad_afecto": -0.10, "personalidad.independencia": 0.05}),
    ("etapa5", "dejResponder", "Sobrepensás", {"personalidad.sensibilidad_emocional": 0.10, "personalidad.necesidad_afecto": 0.10}),
    ("etapa5", "dejResponder", "Te alejás emocionalmente", {"personalidad.tolerancia_conflicto": -0.05}),

    # ── Etapa 6: psicología ──
    ("etapa6", "perdonar", "Perdonar a otros", {"personalidad.empatia": 0.05}),
    ("etapa6", "perdonar", "Perdonarme a mí", {"personalidad.sensibilidad_emocional": 0.05}),

    # ── Etapa 3: familia y futuro ──
    ("etapa3", "hijosFuturo", "Sí", {"valores.familia": 0.15}),
    ("etapa3", "hijosFuturo", "Ya tengo", {"valores.familia": 0.15}),
    ("etapa3", "hijosFuturo", "No", {"valores.familia": -0.15}),
    ("etapa3", "hijosAjenos", "No, para nada", {"valores.familia": 0.05}),
    ("etapa3", "hijosAjenos", "Sí, prefiero que no", {"valores.familia": -0.05}),
    ("etapa3", "relacionPadres", "Muy cercana", {"valores.familia": 0.15}),
    ("etapa3", "relacionPadres", "Buena pero con distancia", {"valores.familia": 0.05}),
    ("etapa3", "relacionPadres", "Complicada", {"valores.familia": -0.10, "personalidad.independencia": 0.05}),
    ("etapa3", "relacionPadres", "Prefiero no hablar de eso", {"personalidad.introversion": 0.05}),
    ("etapa3", "familiaEnPareja", "Muy presente", {"valores.familia": 0.15}),
    ("etapa3", "familiaEnPareja", "Presente pero con límites propios", {"personalidad.independencia": 0.05}),
    ("etapa3", "familiaEnPareja", "Prefiero mantenerla aparte", {"personalidad.independencia": 0.15, "valores.familia": -0.10}),
    ("etapa3", "futuro5anios", "Instalado/a y estable", {"valores.estabilidad": 0.15}),
    ("etapa3", "futuro5anios", "Todavía explorando opciones", {"personalidad.apertura_mental": 0.10, "valores.estabilidad": -0.05}),
    ("etapa3", "futuro5anios", "Formando una familia", {"valores.familia": 0.15, "valores.estabilidad": 0.05}),
    ("etapa3", "futuro5anios", "Enfocado/a en mi carrera", {"valores.ambicion": 0.15}),
    ("etapa3", "futuro5anios", "Viajando, sin planes fijos", {"valores.aventura": 0.15}),
    ("etapa3", "estabilidadEconomica", "Muy importante", {"valores.ambicion": 0.10, "valores.estabilidad": 0.10}),
    ("etapa3", "estabilidadEconomica", "No es prioridad ahora", {"valores.ambicion": -0.05, "valores.aventura": 0.05}),
]

# Campos que describen preferencias sobre LA OTRA PERSONA, no rasgos propios.
# No se usan hoy en calcular_compatibilidad; quedan disponibles para un futuro
# prefiltro de matching.
CAMPOS_PREFERENCIA_PAREJA = [
    ("etapa5", "similitud"), ("etapa5", "carinoIntens"),
    ("etapa6", "vibeAtrae"), ("etapa6", "conexionPrimero"), ("etapa6", "gustaMueven"),
    ("etapa6", "atraeMas"), ("etapa6", "colorPelo"), ("etapa6", "estiloPelo"),
    ("etapa6", "alturaAtrae"), ("etapa6", "contextura"), ("etapa6", "outfitCrush"),
]

# Política y religión: no hay una correlación defendible con ningún rasgo de
# BASE_PERSONALIDAD/BASE_VALORES, así que en vez de inventar una regla numérica
# se guardan tal cual -- listas para un futuro eje de compatibilidad por
# creencias en vez de forzarlas en el modelo psicológico actual.
CAMPOS_CREENCIAS = [
    ("etapa6", "politicaImportancia"), ("etapa6", "politicaHablar"),
    ("etapa6", "religionImportancia"), ("etapa6", "religionCompartir"),
]

# Preguntas de texto libre -> se citan tal cual en el prompt, con una etiqueta corta.
CAMPOS_NOTAS = [
    ("etapa1", "diaPerfecto", "Un día perfecto para mí"),
    ("etapa1", "siNoOcup", "Si no hiciera lo que hago, haría"),
    ("etapa2", "tardeLibre", "En una tarde libre, sin obligaciones"),
    ("etapa2", "desconectar", "Lo que me ayuda a desconectar"),
    ("etapa2", "probarNuevo", "Algo nuevo que probaría"),
    ("etapa3", "cuestaMostrar", "Lo que me cuesta mostrar"),
    ("etapa3", "malinterp", "Lo que la gente suele malinterpretar de mí"),
    ("etapa3", "ansiedadSeg", "Qué me da ansiedad y qué me da seguridad"),
    ("etapa6", "psi1", "Lo que aprendí de vínculos pasados"),
    ("etapa6", "psi3", "Cómo manejo soltar personas o idealizar relaciones"),
    ("etapa6", "psi4", "Patrones que se repiten en mi vida"),
    ("etapa6", "psi5", "Lo que más necesito escuchar y nunca me dijeron"),
]

_MAPA_PELEA = {
    "Digo lo que pienso aunque genere discusión": "prefiere confrontar directamente antes que evitar el tema",
    "Intento hablarlo con calma para resolverlo": "busca resolver hablando con calma, evita el griterío",
    "Me guardo cosas para evitar conflictos": "tiende a callarse para no generar conflicto",
    "Necesito tomar distancia antes de hablar": "necesita tiempo a solas antes de poder hablarlo",
}
_MAPA_MOLESTA = {
    "Lo hablo enseguida": "cuando algo le molesta lo dice en el momento",
    "Necesito tiempo primero": "necesita procesar antes de hablar de lo que le molesta",
    "Me alejo": "ante el malestar tiende a alejarse",
    "Exploto después": "acumula hasta que explota",
    "Actúo como si nada": "prefiere disimular que algo le molesta",
}


def _clip01(x):
    return max(0.0, min(1.0, x))


def _seleccion(datos_etapa, campo):
    valor = datos_etapa.get(campo)
    if not valor:
        return []
    return valor if isinstance(valor, list) else [valor]


def _aplicar_reglas(numerico, respuestas_raw, reglas):
    for etapa, campo, respuesta_esperada, cambios in reglas:
        datos_etapa = respuestas_raw.get(etapa) or {}
        seleccionadas = {str(v).strip().casefold() for v in _seleccion(datos_etapa, campo)}
        if respuesta_esperada.strip().casefold() not in seleccionadas:
            continue
        for ruta, delta in cambios.items():
            grupo, clave = ruta.split(".")
            numerico[grupo][clave] = numerico[grupo].get(clave, 0.5) + delta


def _construir_pesos_compatibilidad(respuestas_raw):
    pesos = dict(PESOS_DEFAULT)
    for etapa, campo, respuesta_esperada, cambios in REGLAS_PESOS:
        datos_etapa = respuestas_raw.get(etapa) or {}
        seleccionadas = {str(v).strip().casefold() for v in _seleccion(datos_etapa, campo)}
        if respuesta_esperada.strip().casefold() not in seleccionadas:
            continue
        for eje, delta in cambios.items():
            pesos[eje] += delta
    total = sum(pesos.values()) or 1.0
    return {eje: round(v / total, 3) for eje, v in pesos.items()}


def _construir_ubicacion(e1):
    """lat/lng vienen del botón "Usar mi ubicación" del onboarding (geolocalización
    del navegador) -- es opcional, así que si no están no se arma nada acá.
    Se usa para calcular distancia_km entre perfiles (ver
    geolocalizacion.distancia_entre_perfiles), que es lo que ordena la cola
    de parejas pendientes en main.buscar_parejas_pendientes."""
    try:
        lat = float(e1.get("lat"))
        lng = float(e1.get("lng"))
    except (TypeError, ValueError):
        return None
    return {"lat": lat, "lng": lng}


def _construir_identidad(e1):
    edad_raw = str(e1.get("edad", "")).strip()

    # Si eligió "Otro" en orientación, usamos lo que escribió a mano
    # (orientacionOtro) como el valor real en vez de guardar el string "Otro"
    # literal -- si no lo completó, se queda en "Otro".
    orientacion = e1.get("orientacion", "")
    if orientacion == "Otro":
        orientacion = (e1.get("orientacionOtro") or "").strip() or "Otro"

    return {
        "nombre": e1.get("nombre") or e1.get("apodo") or "Usuario",
        "apodo": e1.get("apodo", ""),
        "edad": int(edad_raw) if edad_raw.isdigit() else None,
        "ciudad": e1.get("ciudad", ""),
        "ubicacion": _construir_ubicacion(e1),
        "profesion": e1.get("ocupacion", ""),
        "convivencia": e1.get("convivo", ""),
        "signo": e1.get("signo", ""),
        "orientacion": orientacion,
        # Qué tipo de relación busca ("Algo serio"/"Algo casual"/"Nuevas
        # amistades"/"Sin definir") -- lo usa escenarios_para_tipo() para
        # decidir qué escenarios correr con simular_relacion_completa().
        "busco": e1.get("busco", ""),
    }


def _construir_intereses(e1, e2):
    intereses = []
    if e2.get("artista"):
        intereses.append(e2["artista"])
    intereses += _seleccion(e2, "genero")
    if e2.get("serie"):
        intereses.append(e2["serie"])
    deporte = (e2.get("deporte") or "").strip()
    if deporte and deporte.casefold() not in ("no hago", "no", "ninguno"):
        intereses.append(deporte)
    if e2.get("equipo"):
        intereses.append(e2["equipo"])
    if e2.get("lugarIdeal"):
        intereses.append(e2["lugarIdeal"])
    if e2.get("estetica"):
        intereses.append(e2["estetica"])

    vistos, limpio = set(), []
    for i in intereses:
        i = str(i).strip()
        if i and i.casefold() not in vistos:
            vistos.add(i.casefold())
            limpio.append(i)
    return limpio


def _construir_estilo_chat(e3, e4):
    # No hay pregunta directa sobre longitud de mensajes en el onboarding actual;
    # queda en False por default hasta que se agregue una pregunta específica.
    coqueteo = (e4.get("coqueteo") or "").strip()
    decision = (e3.get("decision") or "").strip()
    como_soy = _seleccion(e3, "comoSoy")
    return {
        "mensajes_cortos": False,
        "usa_humor": "Divertido/a" in como_soy or "Espontáneo/a" in como_soy,
        "coqueto": coqueteo in ("Directo/a, lo dejo claro", "Indirecto/a, por actitudes", "Primero espero señales"),
        "analitico": decision == "La pienso un montón, analizo pros y contras",
    }


def _construir_conflictos(e4):
    pelea = (e4.get("pelea") or "").strip()
    molesta = (e4.get("cuandoMolesta") or "").strip()
    conflictos = {}
    if pelea in _MAPA_PELEA:
        conflictos["peleas"] = _MAPA_PELEA[pelea]
    if molesta in _MAPA_MOLESTA:
        conflictos["cuando_le_molesta_algo"] = _MAPA_MOLESTA[molesta]
    return conflictos


def _construir_notas(respuestas_raw):
    notas = []
    for etapa, campo, etiqueta in CAMPOS_NOTAS:
        texto = ((respuestas_raw.get(etapa) or {}).get(campo) or "").strip()
        if texto:
            notas.append(f"{etiqueta}: {texto}")
    return notas


def _construir_preferencias_pareja(respuestas_raw):
    prefs = {}
    for etapa, campo in CAMPOS_PREFERENCIA_PAREJA:
        valor = (respuestas_raw.get(etapa) or {}).get(campo)
        if valor:
            prefs[campo] = valor
    return prefs


def _construir_creencias(respuestas_raw):
    creencias = {}
    for etapa, campo in CAMPOS_CREENCIAS:
        valor = (respuestas_raw.get(etapa) or {}).get(campo)
        if valor:
            creencias[campo] = valor
    return creencias


def _resumir_flags(e5):
    flags = e5.get("flags")
    if not isinstance(flags, dict) or not flags:
        return {"green": 0, "red": 0, "total": 0}
    votos = list(flags.values())
    verdes = sum(1 for v in votos if v == "green")
    return {"green": verdes, "red": len(votos) - verdes, "total": len(votos)}


def construir_perfil_gemelo(respuestas_raw):
    """Toma el doc completo de usuarios/{uid}/gemelo_setup/data (etapa1..etapa7,
    gemelo_final, completed) y devuelve el perfil normalizado para prueba.py."""
    e1 = respuestas_raw.get("etapa1") or {}
    e2 = respuestas_raw.get("etapa2") or {}
    e3 = respuestas_raw.get("etapa3") or {}
    e4 = respuestas_raw.get("etapa4") or {}
    e5 = respuestas_raw.get("etapa5") or {}
    e7 = respuestas_raw.get("etapa7") or {}

    personalidad = {k: 0.5 for k in BASE_PERSONALIDAD}
    valores = {k: 0.5 for k in BASE_VALORES}
    numerico = {"personalidad": personalidad, "valores": valores}

    _aplicar_reglas(numerico, respuestas_raw, REGLAS_NUMERICAS)

    for grupo in numerico.values():
        for clave in grupo:
            grupo[clave] = round(_clip01(grupo[clave]), 2)

    # La ambición aparece en dos secciones del prompt (rasgo de personalidad y
    # valor personal); es el mismo impulso visto desde dos ángulos, no se
    # recalcula dos veces para no generar contradicciones.
    personalidad["ambicion"] = valores["ambicion"]

    perfil = {
        **_construir_identidad(e1),
        "intereses": _construir_intereses(e1, e2),
        "personalidad": personalidad,
        "estilo_chat": _construir_estilo_chat(e3, e4),
        "valores": valores,
        "conflictos": _construir_conflictos(e4),
        "notas_personales": _construir_notas(respuestas_raw),
        "preferencias_pareja": _construir_preferencias_pareja(respuestas_raw),
        "creencias": _construir_creencias(respuestas_raw),
        "pesos_compatibilidad": _construir_pesos_compatibilidad(respuestas_raw),
        "flags_resumen": _resumir_flags(e5),
        "bio": (respuestas_raw.get("gemelo_final") or e7.get("gedit") or "").strip(),
    }
    return perfil
