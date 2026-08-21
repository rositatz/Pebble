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

PESOS_DEFAULT = {
    "conversacional": 0.26,
    "valores": 0.20,
    "intereses": 0.14,
    "fisico": 0.12,
    "psicologico": 0.12,
    "comunicacion": 0.09,
    "creencias": 0.07,
}

# Qué tan importante es cada eje de compatibilidad para ESTE usuario, según lo
# que dijo que más necesita en un vínculo (necesitasVinc), qué es lo que más
# le atrae / qué tipo de conexión busca primero en otra persona (conexionPrimero,
# atraeMas), y qué tan importante le resultan la política/religión
# (politicaImportancia/religionImportancia -- si le importan mucho a ESTA
# persona, el eje "creencias" pesa más específicamente para ella). Esto
# reemplaza el peso fijo por uno propio de cada persona; calcular_compatibilidad()
# combina el de los dos usuarios de la pareja.
REGLAS_PESOS = [
    ("etapa4", "necesitasVinc", "Poder hablar de lo que me pasa sin filtro", {"psicologico": 0.05}),
    ("etapa4", "necesitasVinc", "Disponibilidad real cuando la necesito", {"conversacional": 0.05, "comunicacion": 0.05}),
    ("etapa4", "necesitasVinc", "Estabilidad y tranquilidad en el vínculo", {"valores": 0.08}),
    ("etapa4", "necesitasVinc", "Que respeten mi independencia y tiempos", {"psicologico": 0.05}),
    ("etapa4", "necesitasVinc", "Poder resolver conflictos hablando, sin dramas", {"psicologico": 0.05, "comunicacion": 0.05}),
    ("etapa6", "conexionPrimero", "Emocional", {"psicologico": 0.08}),
    ("etapa6", "conexionPrimero", "Mental", {"psicologico": 0.05, "intereses": 0.05}),
    ("etapa6", "conexionPrimero", "Física", {"conversacional": 0.08}),
    ("etapa6", "conexionPrimero", "Divertida", {"conversacional": 0.08}),
    ("etapa6", "conexionPrimero", "Tranquila", {"valores": 0.08}),
    ("etapa6", "atraeMas", "Seguro/a", {"psicologico": 0.04}),
    ("etapa6", "atraeMas", "Sensible", {"psicologico": 0.04}),
    ("etapa6", "atraeMas", "Gracioso/a", {"conversacional": 0.06}),
    ("etapa6", "atraeMas", "Inteligente", {"psicologico": 0.04}),
    ("etapa6", "atraeMas", "Creativo/a", {"conversacional": 0.04}),
    ("etapa6", "atraeMas", "Ambicioso/a", {"valores": 0.06}),
    ("etapa6", "politicaImportancia", "Muy importante", {"creencias": 0.10}),
    ("etapa6", "religionImportancia", "Muy importante", {"creencias": 0.10}),

    # "¿Qué es lo que más te importa para conectar de verdad con alguien?"
    # (etapa6, prioridadCompatibilidad) -- a diferencia de todas las reglas
    # de arriba (que INFIEREN el peso de otra respuesta), esta pregunta lo
    # dice directamente, así que el empujón es más grande (0.10, el mismo
    # que politica/religionImportancia, el máximo que se usa en esta tabla)
    # y no se reparte entre varios ejes como conexionPrimero/atraeMas.
    ("etapa6", "prioridadCompatibilidad", "Los valores que compartimos", {"valores": 0.10}),
    ("etapa6", "prioridadCompatibilidad", "Los intereses y gustos en común", {"intereses": 0.10}),
    ("etapa6", "prioridadCompatibilidad", "La química cuando charlamos", {"conversacional": 0.10}),
    ("etapa6", "prioridadCompatibilidad", "Nuestras personalidades", {"psicologico": 0.10}),
    ("etapa6", "prioridadCompatibilidad", "Cómo nos comunicamos", {"comunicacion": 0.10}),
    ("etapa6", "prioridadCompatibilidad", "Compartir creencias (política o religión)", {"creencias": 0.10}),
    ("etapa6", "prioridadCompatibilidad", "La atracción física", {"fisico": 0.10}),
]

# (etapa, campo, respuesta_exacta, {"grupo.rasgo": delta})
REGLAS_NUMERICAS = [
    # ── Etapa 1: identidad y rutina ──
    ("etapa1", "convivo", "Solo/a", {"personalidad.independencia": 0.10, "personalidad.introversion": 0.05}),
    ("etapa1", "convivo", "Con mi familia", {"valores.familia": 0.10}),
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
    ("etapa2", "planIdeal", "Pasar el día al aire libre, en la playa, parque o naturaleza.", {"valores.aventura": 0.10}),
    ("etapa2", "planIdeal", "Quedarme en casa y disfrutar de un plan tranquilo.", {"valores.estabilidad": 0.05, "personalidad.introversion": 0.05}),
    ("etapa2", "planIdeal", "Ir a un recital, bar o evento.", {"valores.aventura": 0.05}),
    ("etapa2", "planIdeal", "Improvisar y salir a descubrir la ciudad.", {"valores.aventura": 0.10, "personalidad.apertura_mental": 0.05}),
    ("etapa2", "planIdeal", "Recorrer una librería, museo o lugar cultural.", {"personalidad.apertura_mental": 0.05}),
    ("etapa2", "planIdeal", "Ir a una cafetería y charlar durante horas.", {"personalidad.introversion": -0.05, "personalidad.necesidad_afecto": 0.05}),
    ("etapa2", "planIdeal", "Hacer algo creativo: cocinar, pintar, sacar fotos, etc.", {"personalidad.apertura_mental": 0.05}),

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

    # ── Preguntas que antes no tocaban nada (ni personalidad ni compatibilidad) ──
    # Se les asigna acá el rasgo que más describen, mismo criterio que el
    # resto del archivo -- deltas chicos porque son señales secundarias, no
    # las preguntas centrales de personalidad.
    ("etapa1", "productiv", "De noche", {"valores.aventura": 0.05, "personalidad.apertura_mental": 0.05}),
    ("etapa1", "productiv", "De mañana", {"valores.estabilidad": 0.05}),
    ("etapa2", "arreglo", "Me arreglo bastante", {"personalidad.apertura_mental": 0.05}),
    ("etapa2", "arreglo", "Cómodo/a siempre", {"personalidad.independencia": 0.05}),
    ("etapa2", "prefComida", "Cocinar", {"valores.estabilidad": 0.05}),
    ("etapa2", "prefComida", "Ir a un restaurante", {"valores.aventura": 0.03}),
    ("etapa2", "prefComida", "Pedir delivery", {"personalidad.independencia": 0.03}),
    ("etapa3", "causaAnsiedad", "No saber qué va a pasar", {"personalidad.sensibilidad_emocional": 0.08, "valores.estabilidad": 0.05}),
    ("etapa3", "causaAnsiedad", "No poder cambiar la situación", {"personalidad.tolerancia_conflicto": -0.05}),
    ("etapa3", "causaAnsiedad", "Presión por expectativas", {"valores.ambicion": 0.05, "personalidad.sensibilidad_emocional": 0.05}),
    ("etapa3", "causaAnsiedad", "Lo que alguien piensa de mí", {"personalidad.necesidad_afecto": 0.08}),
    ("etapa4", "prefCom", "Verse en persona", {"personalidad.introversion": -0.05}),
    ("etapa4", "prefCom", "Mensajes de texto", {"personalidad.introversion": 0.03}),
    ("etapa4", "inaceptable", "Que me grite o se vuelva agresivo/a", {"personalidad.tolerancia_conflicto": 0.05}),
    ("etapa4", "inaceptable", "Que minimice lo que siento", {"personalidad.sensibilidad_emocional": 0.08, "personalidad.empatia": 0.05}),
    ("etapa4", "inaceptable", "Que no escuche mi punto de vista", {"personalidad.empatia": 0.05}),
    ("etapa4", "inaceptable", "Que me mienta o me oculte cosas", {"valores.estabilidad": 0.05}),
    ("etapa4", "inaceptable", "Que me falte el respeto", {"personalidad.tolerancia_conflicto": 0.05}),
    ("etapa4", "fiestaReac", "Me muestro natural y sigo la conversación", {"personalidad.introversion": -0.10}),
    ("etapa4", "fiestaReac", "Me pongo nervioso/a pero intento seguirle el ritmo", {"personalidad.sensibilidad_emocional": 0.05}),
    ("etapa4", "fiestaReac", "Espero señales antes de abrirme más", {"personalidad.introversion": 0.05}),
    ("etapa4", "fiestaReac", "Me quedo más reservado/a", {"personalidad.introversion": 0.15}),
    ("etapa4", "comportaInt", "Me pongo más atento/a y presente, lo demuestro bastante", {"personalidad.necesidad_afecto": 0.08}),
    ("etapa4", "comportaInt", "Me vuelvo un poco más tímido/a", {"personalidad.introversion": 0.10}),
    ("etapa4", "comportaInt", "Intento actuar normal aunque por dentro piense todo", {"personalidad.introversion": 0.05}),
    ("etapa4", "comportaInt", "Depende, puedo ser muy expresivo/a o muy frío/a", {"personalidad.sensibilidad_emocional": 0.05}),
    ("etapa5", "citaClima", "Lluvia y películas", {"personalidad.introversion": 0.05}),
    ("etapa5", "citaClima", "Playa y música", {"personalidad.introversion": -0.05, "valores.aventura": 0.03}),
    ("etapa5", "citaActividad", "Mirar estrellas", {"personalidad.sensibilidad_emocional": 0.05}),
    ("etapa5", "citaActividad", "Caminar sin rumbo", {"valores.aventura": 0.05}),
    ("etapa5", "carinoComm", "Audios", {"personalidad.necesidad_afecto": 0.05}),
    ("etapa5", "carinoComm", "Videollamadas", {"personalidad.necesidad_afecto": 0.08}),
    ("etapa5", "carinoResp", "Responder rápido", {"personalidad.necesidad_afecto": 0.08}),
    ("etapa5", "carinoResp", "Responder bien", {"personalidad.independencia": 0.05}),
    ("etapa5", "carinoCoqueteo", "Coqueteo directo", {"personalidad.introversion": -0.08}),
    ("etapa5", "carinoCoqueteo", "Coqueteo indirecto", {"personalidad.introversion": 0.05}),
    ("etapa5", "siGusta", "Le hablo más", {"personalidad.introversion": -0.05}),
    ("etapa5", "siGusta", "Le hablo menos (me pongo raro/a)", {"personalidad.sensibilidad_emocional": 0.08}),
    ("etapa5", "siGusta", "Stalkeo todas sus redes", {"personalidad.necesidad_afecto": 0.08}),
    ("etapa5", "siGusta", "Sobrepiensa cada mensaje", {"personalidad.sensibilidad_emocional": 0.08}),
    ("etapa5", "siGusta", "Espero señales", {"personalidad.introversion": 0.05}),
    ("etapa5", "siGusta", "Soy directo/a, lo dejo claro", {"personalidad.introversion": -0.08}),
    ("etapa5", "siGusta", "Lo muestro con indirectas", {"personalidad.introversion": 0.03}),
    ("etapa5", "siGusta", "Observo si hay reciprocidad", {"personalidad.tolerancia_conflicto": 0.03}),
    ("etapa5", "siGusta", "Me cuesta mucho demostrarlo", {"personalidad.introversion": 0.10}),
]

# Campos que describen preferencias sobre LA OTRA PERSONA, no rasgos propios.
# No se usan hoy en calcular_compatibilidad; quedan disponibles para un futuro
# prefiltro de matching.
CAMPOS_PREFERENCIA_PAREJA = [
    ("etapa3", "persEngancha"),
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
    ("etapa3", "ansiedadSeg", "Qué me da ansiedad y qué me da seguridad sobre el futuro"),
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


def _construir_edad_int(valor):
    valor = str(valor or "").strip()
    return int(valor) if valor.isdigit() else None


def _construir_rango_edad_busco(e1):
    """Rango de edad que la persona busca en un match -- lo usa
    compatibilidad.compatible_por_edad() para filtrar candidatos (con un
    margen de tolerancia y un piso de 18 años que nunca se cruza). Si no
    puso min y/o max, esa punta queda en None -- compatible_por_edad() lo
    trata como "sin preferencia" en esa punta, no como "rechaza todo"."""
    minimo = _construir_edad_int(e1.get("edadMinBusco"))
    maximo = _construir_edad_int(e1.get("edadMaxBusco"))
    if minimo is None and maximo is None:
        return None
    return {"min": minimo, "max": maximo}


def _con_otro(e1, campo, campo_otro):
    """Igual que el manejo de "Otro" en orientación/género: si eligió
    "Otro" en un pill, usa lo que escribió a mano en vez del string "Otro"
    literal -- si no lo completó, se queda en "Otro"."""
    valor = e1.get(campo, "")
    if valor == "Otro":
        return (e1.get(campo_otro) or "").strip() or "Otro"
    return valor


def _construir_situacion(e1):
    """Arma un texto natural para el prompt (perfil.profesion) a partir de
    "¿cuál es tu situación actual?" + las preguntas condicionales que
    dispara (nivel de estudio si estudia, área si trabaja) + el proyecto
    adicional -- antes esto era un solo campo de texto libre (ocupacion),
    ahora son varias preguntas de opciones (ver gemelo-setup.html)."""

    situacion = e1.get("situacion", "")
    nivel = _con_otro(e1, "nivelEstudio", "nivelEstudioOtro")
    area = _con_otro(e1, "areaTrabajo", "areaTrabajoOtro")
    proyecto = _con_otro(e1, "proyectoAdicional", "proyectoAdicionalOtro")

    partes = []
    if situacion and situacion != "Prefiero no decirlo":
        partes.append(situacion)
    if nivel:
        partes.append(f"nivel: {nivel}")
    if area:
        partes.append(f"área: {area}")
    if proyecto and proyecto != "Ninguno":
        partes.append(f"además: {proyecto}")

    return " · ".join(partes)


def _construir_identidad(e1):
    # Si eligió "Otro" en orientación o género, usamos lo que escribió a mano
    # como el valor real en vez de guardar el string "Otro" literal -- si no
    # lo completó, se queda en "Otro".
    orientacion = e1.get("orientacion", "")
    if orientacion == "Otro":
        orientacion = (e1.get("orientacionOtro") or "").strip() or "Otro"

    genero = e1.get("generoIdentidad", "")
    if genero == "Otro":
        genero = (e1.get("generoIdentidadOtro") or "").strip() or "Otro"

    return {
        "nombre": e1.get("nombre") or e1.get("apodo") or "Usuario",
        "apodo": e1.get("apodo", ""),
        "edad": _construir_edad_int(e1.get("edad")),
        "rango_edad_busco": _construir_rango_edad_busco(e1),
        "ciudad": e1.get("ciudad", ""),
        "ubicacion": _construir_ubicacion(e1),
        "profesion": _construir_situacion(e1),
        "convivencia": e1.get("convivo", ""),
        "signo": e1.get("signo", ""),
        "genero": genero,
        "orientacion": orientacion,
        # Ya no se pregunta en el onboarding (la app es solo para "Algo
        # serio") -- queda por perfiles viejos/editados a mano en perfil.html.
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


def _construir_hijos(e3):
    """De etapa3: si ya tiene hijos (hijosFuturo == "Ya tengo") y qué tan
    dispuesta está a salir con alguien que ya los tiene (hijosAjenos) --
    antes esto solo alimentaba el valor numérico "familia", ahora también
    queda como dato crudo para que compatibilidad.compatible_por_hijos()
    pueda usarlo como filtro real: si alguien dijo que le incomodaría salir
    con alguien que ya tiene hijos, no se lo empareja con alguien que sí
    tiene, y viceversa."""
    return {
        "tiene_hijos": e3.get("hijosFuturo") == "Ya tengo",
        "tolerancia_hijos": e3.get("hijosAjenos", ""),
    }


def _construir_fisico_propio(e6):
    """Autodescripción física real (etapa6, sección "Sobre tu físico") --
    distinto de preferencias_pareja (qué tipo físico ATRAE), esto es sobre
    uno/a mismo/a. compatibilidad.compatibilidad_fisica lo usa para chequear
    si el físico real de cada uno coincide con lo que el otro dijo que le
    atrae -- antes esas preferencias no tenían con qué compararse."""
    return {
        "colorPelo": e6.get("colorPeloPropio", ""),
        "estiloPelo": e6.get("estiloPeloPropio", ""),
        "altura_cm": _construir_edad_int(e6.get("alturaPropia")),
        "contextura": e6.get("contexturaPropia", ""),
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


# Traduce atraeMas/persEngancha a un objetivo NUMÉRICO por rasgo (misma
# escala 0.0-1.0 y misma clave que BASE_PERSONALIDAD), para poder comparar
# contra la personalidad real del candidato en compatibilidad_preferencias_
# unidireccional. Son valores objetivo, no deltas -- si dos reglas tocan el
# mismo rasgo, gana la última que matchee.
MAPA_PREFERENCIAS_PERSONALIDAD = [
    ("etapa6", "atraeMas", "Seguro/a", {"independencia": 0.75, "tolerancia_conflicto": 0.75}),
    ("etapa6", "atraeMas", "Sensible", {"sensibilidad_emocional": 0.8, "empatia": 0.8}),
    ("etapa6", "atraeMas", "Inteligente", {"apertura_mental": 0.85}),
    ("etapa6", "atraeMas", "Creativo/a", {"apertura_mental": 0.85}),
    ("etapa3", "persEngancha", "Súper expresiva, habladora y con mucha onda", {"introversion": 0.15}),
    ("etapa3", "persEngancha", "Tranquila, que sabe escuchar y transmite paz", {"introversion": 0.55, "empatia": 0.75}),
    ("etapa3", "persEngancha", "Intensa o hiperactiva", {"introversion": 0.15, "sensibilidad_emocional": 0.7}),
    ("etapa3", "persEngancha", "Muy cerrada, de las que cuesta remarles la conversación", {"introversion": 0.85}),
]


def _construir_preferencias_pareja_personalidad(respuestas_raw):
    objetivo = {}
    for etapa, campo, respuesta_esperada, rasgos in MAPA_PREFERENCIAS_PERSONALIDAD:
        datos_etapa = respuestas_raw.get(etapa) or {}
        seleccionadas = {str(v).strip().casefold() for v in _seleccion(datos_etapa, campo)}
        if respuesta_esperada.strip().casefold() in seleccionadas:
            objetivo.update(rasgos)
    return objetivo


def _construir_creencias(respuestas_raw):
    creencias = {}
    for etapa, campo in CAMPOS_CREENCIAS:
        valor = (respuestas_raw.get(etapa) or {}).get(campo)
        if valor:
            creencias[campo] = valor
    return creencias


# Mismo orden y mismo texto que la constante FLAGS de gemelo-setup.html --
# el juego solo guarda {índice: "green"|"red"} en Firestore, así que hace
# falta esta copia acá para poder traducir cada índice de vuelta a qué
# comportamiento representa. Si se edita una de las dos hay que editar la
# otra.
FLAGS_JUEGO = [
    "Te escribe primero todos los días",
    "Te dice «Te extraño» a la semana de conocerse",
    "Te cuenta toda su vida en la primera cita",
    "Te manda 5 audios seguidos",
    "Te presenta a sus amigos después de dos citas",
    "Te pone un apodo cariñoso al toque",
    "Tarda en responder",
    "No postea nada de la relación",
    "Tiene opiniones fuertes en todo",
    "Te deja ganar siempre",
    "Es espontáneo/a",
    "Vive el presente, no planea nada",
    "Es adicto/a al trabajo o estudio",
    "Llora en las películas",
    "Sale de fiesta todos los fines de semana",
    "No usa mucho el teléfono",
]


def _resumir_flags(e5):
    """Además del conteo (para mostrar "marcaste X green flags"), guarda el
    TEXTO de cada comportamiento marcado green/red -- antes solo se
    contaba, así que el gemelo nunca podía saber CUÁLES eran esos green/red
    flags, solo cuántos había de cada uno. Ver generar_prompt_gemelo
    (simulador.py), que ahora sí usa green_textos/red_textos."""
    flags = e5.get("flags")
    if not isinstance(flags, dict) or not flags:
        return {"green": 0, "red": 0, "total": 0, "green_textos": [], "red_textos": []}

    def _textos(votos_filtrados):
        textos = []
        for indice in votos_filtrados:
            try:
                textos.append(FLAGS_JUEGO[int(indice)])
            except (ValueError, IndexError, TypeError):
                continue
        return textos

    indices_verdes = [i for i, v in flags.items() if v == "green"]
    indices_rojos = [i for i, v in flags.items() if v == "red"]

    return {
        "green": len(indices_verdes),
        "red": len(indices_rojos),
        "total": len(flags),
        "green_textos": _textos(indices_verdes),
        "red_textos": _textos(indices_rojos),
    }


def construir_perfil_gemelo(respuestas_raw):
    """Toma el doc completo de usuarios/{uid}/gemelo_setup/data (etapa1..etapa7,
    gemelo_final, completed) y devuelve el perfil normalizado para prueba.py."""
    e1 = respuestas_raw.get("etapa1") or {}
    e2 = respuestas_raw.get("etapa2") or {}
    e3 = respuestas_raw.get("etapa3") or {}
    e4 = respuestas_raw.get("etapa4") or {}
    e5 = respuestas_raw.get("etapa5") or {}
    e6 = respuestas_raw.get("etapa6") or {}
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

    intereses = _construir_intereses(e1, e2)

    perfil = {
        **_construir_identidad(e1),
        **_construir_hijos(e3),
        # "intereses" es el que se sigue mostrando/usando en los prompts y
        # que actualizar_aprendizaje_gemelo (main.py) puede seguir sumando
        # con el tiempo a partir de chats reales (con consentimiento).
        # "intereses_onboarding" es una copia CONGELADA del mismo valor
        # inicial, tomada en el momento de generar el perfil -- es la que
        # usa compatibilidad.compatibilidad_intereses() para el % de
        # compatibilidad real, justamente para que nadie pueda "inflar" sus
        # intereses charlando con su propio gemelo y matchear más fácil.
        "intereses": intereses,
        "intereses_onboarding": intereses,
        "personalidad": personalidad,
        "estilo_chat": _construir_estilo_chat(e3, e4),
        "valores": valores,
        "conflictos": _construir_conflictos(e4),
        "notas_personales": _construir_notas(respuestas_raw),
        "preferencias_pareja": _construir_preferencias_pareja(respuestas_raw),
        "preferencias_pareja_personalidad": _construir_preferencias_pareja_personalidad(respuestas_raw),
        "fisico_propio": _construir_fisico_propio(e6),
        "creencias": _construir_creencias(respuestas_raw),
        # Preferencia de medio de comunicación ("Mensajes de texto"/"Audios"/
        # "Llamadas"/"Videollamadas"/"Verse en persona") -- además de nutrir
        # personalidad.introversion vía REGLAS_NUMERICAS, es el dato crudo
        # que lee compatibilidad.compatibilidad_comunicacion() directamente.
        "prefCom": e4.get("prefCom", ""),
        # Orden de prioridad tal cual lo eligió la persona (etapa6,
        # "¿qué es lo que más te importa...?") -- ya alimenta los pesos de
        # compatibilidad (_construir_pesos_compatibilidad, arriba); se
        # guarda también tal cual para que generar_prompt_gemelo
        # (simulador.py) pueda usarlo en las simulaciones de escenarios.
        "prioridad_compatibilidad": _seleccion(e6, "prioridadCompatibilidad"),
        "pesos_compatibilidad": _construir_pesos_compatibilidad(respuestas_raw),
        "flags_resumen": _resumir_flags(e5),
        "bio": (respuestas_raw.get("gemelo_final") or e7.get("gedit") or "").strip(),
    }
    return perfil
