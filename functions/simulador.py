#Lee las parejas en estado PENDIENTE de Firestore.
#Carga las personalidades de los gemelos y las instrucciones del escenario.
#Llama a la API de IA (OpenAI, Gemini, Anthropic) para simular los diálogos, calcula el puntaje de compatibilidad y extrae las memorias.
#Guarda los resultados en la subcolección simulaciones y actualiza el estado.

import os
import json
import random
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


# Un solo lugar para no tener que cambiarlo en cada función por separado.
UMBRAL_MATCH = 0.50

escenarios_db = [

    {
        "titulo": "Primera cita",

        "contexto": """
        Es el primer encuentro real entre los dos, después de todo lo que
        el gemelo intuyó del otro. Hay nervios genuinos y ganas de que
        salga bien, pero cada uno tiene su propio ritmo para abrirse: a
        algunos les sale ir directo a algo real, a otros les cuesta y
        arrancan con humor o cosas livianas antes de soltarse.
        """,

        "objetivo": [
            "Ver el ritmo real de apertura de cada uno (no el que dicen tener)",
            "Detectar si el estilo de coqueteo/humor de uno choca con el del otro",
            "Evaluar si hay energía o si la charla se siente forzada",
            "Medir compatibilidad de primera impresión, más allá del % calculado"
        ],

        "tension": """
        Uno puede querer profundizar rápido y el otro sentirlo demasiado
        intenso para un primer encuentro -- o al revés, uno puede sentir
        que el otro se queda en la superficie y no compromete nada real.
        """,

        "tono": "Con nervios reales, expectativa y algo de incertidumbre.",
        "tipos_relacion": ["Algo serio"]
    },

    {
        "titulo": "Convivencia de los primeros meses",

        "contexto": """
        Surge la idea de imaginarse viviendo juntos más adelante -- no como
        planazo romántico abstracto, sino los detalles concretos: espacio
        propio, orden, ruido, rutinas, plata compartida en el día a día.
        """,

        "objetivo": [
            "Evaluar compatibilidad real de hábitos cotidianos, no solo declarada",
            "Detectar necesidad de espacio propio vs. necesidad de cercanía constante",
            "Medir flexibilidad ante formas distintas de organizarse",
            "Ver si aparecen expectativas no dichas (quién hace qué, cómo se reparte)"
        ],

        "tension": """
        Uno puede ser mucho más ordenado/estructurado que el otro, o tener
        una necesidad de espacio propio que el otro interpreta como
        distancia -- acá tienen que negociarlo en concreto, no en teoría.
        """,

        "tono": "Cotidiano pero con peso real, no liviano.",
        "tipos_relacion": ["Algo serio"]
    },

    {
        "titulo": "Mostrar vulnerabilidad",

        "contexto": """
        En medio de la charla, uno de los dos decide compartir algo que
        genuinamente le cuesta mostrar -- algo real de sí mismo/a, no un
        dato trivial. No lo hace como prueba ni como estrategia, es un
        momento genuino de bajar la guardia.
        """,

        "objetivo": [
            "Evaluar si el otro responde con empatía real o lo minimiza",
            "Detectar si sabe sostener un momento así sin incomodarse",
            "Medir si la vulnerabilidad genera cercanía o hace que el otro se cierre",
            "Ver si quien se abrió se arrepiente o se siente escuchado/a"
        ],

        "tension": """
        El otro puede no saber bien cómo reaccionar (minimizarlo sin
        querer, cambiar de tema, o sí sostenerlo bien) -- y eso dice mucho
        más que cualquier respuesta genérica de "te banco".
        """,

        "tono": "Íntimo, un poco tenso, genuino.",
        "tipos_relacion": ["Algo serio"]
    },

    {
        "titulo": "Celos o inseguridad",

        "contexto": """
        ESTO NO ES UNA CHARLA SOBRE LOS CELOS EN GENERAL -- prohibido que
        se pongan a debatir/reflexionar en abstracto sobre "cómo cada uno
        maneja los celos" o "qué opinás de la inseguridad en pareja". Tiene
        que ser una SITUACIÓN CONCRETA pasando ahora mismo, en este
        instante de la charla.

        Arrancá (quien hable primero) mencionando, como al pasar, algo
        real y ambiguo que hiciste vos -- no lo anuncies como un tema, que
        salga natural: que tardaste en contestar porque estabas con gente,
        que anoche saliste y no lo mencionaste hasta ahora, que alguien de
        tu pasado te escribió, que cancelaste un plan con el otro por
        algo que no explicás del todo. Lo decís vos como un comentario
        cualquiera, SIN saber ni controlar cómo lo va a tomar el otro.

        A partir de ahí, el OTRO gemelo tiene que reaccionar de verdad
        según sus rasgos reales (necesidad de afecto, tolerancia al
        conflicto, independencia, sensibilidad emocional) -- si sus datos
        dicen alta necesidad de afecto o baja tolerancia al conflicto, es
        realista que le afecte de verdad y lo demuestre (con inseguridad,
        preguntando más de la cuenta, o guardándoselo y contestando
        cortante); si sus datos dicen independencia alta, puede no darle
        importancia -- pero DECIDÍ según tus datos reales, no según lo que
        "quedaría bien" en la charla. Si el que la generó nota que
        incomodó al otro, también reacciona según SUS rasgos (se pone a
        la defensiva, minimiza, se disculpa, o duplica la apuesta).
        """,

        "objetivo": [
            "Evaluar tolerancia real al conflicto (no la declarada)",
            "Detectar si la inseguridad se comunica directo o se actúa pasivo-agresivo",
            "Medir necesidad de afecto/validación bajo presión",
            "Ver cómo el otro responde a que le planteen una inseguridad"
        ],

        "tension": """
        Uno puede sentir que está exagerando y el otro puede sentir que
        no le están dando explicaciones -- ninguno de los dos tiene
        necesariamente la razón, lo importante es cómo lo manejan.
        """,

        "tono": "Un poco incómodo, con tensión contenida.",
        "tipos_relacion": ["Algo serio"]
    },

    {
        "titulo": "Desacuerdo real en el momento",

        "contexto": """
        ESTO TIENE QUE SER UNA PELEA DE VERDAD, no dos personas diciendo
        "entiendo tu punto de vista" y coincidiendo en todo con otras
        palabras -- si al final de la charla los dos terminan opinando
        básicamente lo mismo, hiciste mal el escenario.

        Antes de escribir una palabra, fijate en los datos reales de los
        dos (creencias, valores, prioridad_compatibilidad, personalidad) y
        elegí el punto donde REALMENTE hay una diferencia de fondo entre
        ustedes dos -- no un tema al azar. Si tus propios datos dicen que
        algo no te importa (ej: "política: no me importa"), tu postura en
        la pelea tiene que salir de ESO (indiferencia, fastidio porque el
        otro le da tanta importancia a algo que a vos te parece
        irrelevante) -- nunca de golpe te pongas a defender el tema con
        pasión como si te importara, sería contradecir tus propios datos.

        Mantené tu postura real hasta el final -- no cedas ni valides la
        opinión del otro solo para bajar la tensión (eso es la regla 7,
        acá se aplica más que nunca). Podés: sostener tu postura sin
        ceder, enojarte un poco de verdad, poner un límite ("no quiero
        seguir hablando de esto"), o buscar un cierre realista según tu
        tolerancia al conflicto real -- pero NO un acuerdo mutuo forzado.
        Que se note tensión genuina en cómo escriben (respuestas más
        cortas, cortantes, o a la defensiva), no solo en el contenido.
        """,

        "objetivo": [
            "Evaluar tolerancia al conflicto de verdad, no evitación disfrazada",
            "Detectar si pueden discrepar sin que se rompa la conversación",
            "Medir apertura mental ante una postura distinta a la propia",
            "Ver si alguno cede solo por no incomodar (calcado falso) o sostiene lo suyo"
        ],

        "tension": """
        Uno puede sentir que el otro no lo entiende o no respeta su
        postura -- la prueba real es si logran seguir la charla sin que
        uno se calle solo para que no haya fricción.
        """,

        "tono": "Directo, con algo de tensión, pero no agresivo.",
        "tipos_relacion": ["Algo serio"]
    },

    {
        "titulo": "Presupuesto compartido para una salida cara",

        "contexto": """
        Surge la idea de un plan que cuesta bastante más de lo que
        cualquiera de los dos gastaría en un día común -- una escapada,
        una cena puntual, algo así. Hay que decidir en la charla si vale
        la pena, cómo se divide, o si a alguno le genera incomodidad.
        """,

        "objetivo": [
            "Evaluar hábitos y prioridades financieras reales",
            "Detectar si hablar de plata genera incomodidad o se maneja con naturalidad",
            "Medir compatibilidad de estilo de vida (ahorro vs. gasto, planificación)",
            "Ver si hay honestidad directa o se evita el tema"
        ],

        "tension": """
        Uno puede priorizar disfrutar el momento y al otro el gasto le
        genera ansiedad o desacuerdo con cómo se reparte -- plata siempre
        revela algo más profundo que solo plata.
        """,

        "tono": "Práctico pero con carga emocional real detrás.",
        "tipos_relacion": ["Algo serio"]
    },

    {
        "titulo": "Pedir perdón / repararla",

        "contexto": """
        Después de una pequeña tensión o malentendido en la charla (puede
        salir de un comentario que cayó mal), alguno de los dos tiene que
        decidir si da el primer paso para destrabarlo, cómo lo hace, y el
        otro tiene que decidir cómo recibe ese intento.
        """,

        "objetivo": [
            "Evaluar cómo maneja de verdad un conflicto chico (no en teoría)",
            "Detectar quién suele dar el primer paso y cómo lo hace",
            "Medir orgullo vs. capacidad de reparar el vínculo",
            "Ver si el otro lo recibe bien o sigue con la guardia alta"
        ],

        "tension": """
        Puede que a ninguno de los dos le salga natural pedir perdón, o
        que uno lo haga de forma poco genuina -- lo interesante es ver si
        de verdad se destraba o queda ahí sin resolver.
        """,

        "tono": "Tenso al principio, buscando resolución.",
        "tipos_relacion": ["Algo serio"]
    },

    {
        "titulo": "Hijos, sí o no",

        "contexto": """
        La charla deriva naturalmente hacia el tema de si quieren formar
        una familia en algún momento, cuándo, y qué tan central es eso en
        sus planes de vida -- no como pregunta de trámite, sino como algo
        que de verdad les importa definir.
        """,

        "objetivo": [
            "Evaluar alineación real en algo no negociable (no una preferencia blanda)",
            "Detectar si hay presión o incomodidad al hablarlo tan directo",
            "Medir honestidad sobre planes de vida a futuro",
            "Ver si una diferencia acá se maneja con madurez o se esquiva"
        ],

        "tension": """
        Si no coinciden, es una diferencia de fondo que no se resuelve
        charlando -- lo que importa es si pueden ser honestos al respecto
        en vez de evitar el tema por miedo a que se rompa la conexión.
        """,

        "tono": "Serio, directo, con peso real.",
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
        "titulo": "Su vida en pareja, 10 años después",

        # A diferencia de los demás escenarios, acá SÍ importa cada palabra
        # de este texto -- es lo único (junto con tono) que llega al prompt
        # real (ver contexto_escenario en simular_cita). objetivo/tension de
        # los demás escenarios son metadata que hoy no se inyecta en ningún
        # prompt -- acá no hay margen para eso, así que la instrucción
        # completa de realismo vive directamente en "contexto".
        "contexto": """
        ESTE ESCENARIO ES DISTINTO A LOS DEMÁS: no es una charla en el
        presente, es un flash-forward. Imaginen que pasaron 10 años reales
        desde que se conocieron -- sea cual sea la forma que tomó la
        relación en el medio (siguieron juntos, se separaron y volvieron,
        nunca terminó de funcionar, lo que sea más realista según cómo son
        de verdad). Están hablando entre ustedes DOS ya en ese futuro, como
        una charla real de pareja (o ex-pareja, si les tocó así)
        reflexionando en voz alta sobre cómo llegaron hasta acá.

        REGLA CENTRAL, MÁS IMPORTANTE QUE CUALQUIER OTRA COSA EN ESTE
        ESCENARIO: esto NO es un cuento de amor. No asuman que todo salió
        bien porque "quedaría lindo" -- el resultado tiene que salir de
        los rasgos y valores REALES de cada uno, no de la opción más
        romántica. Antes de responder, pensá en serio: con tu nivel real
        de tolerancia al conflicto, necesidad de afecto, independencia,
        sarcasmo y apertura mental -- ¿es realista que a esta altura sean
        una pareja sólida y feliz? ¿O es más realista que hayan caído en
        la rutina, que discutan seguido, que se hayan distanciado
        emocionalmente, que uno se aburrió sin que el otro se diera
        cuenta, o directamente que ya no estén juntos? Cualquiera de esas
        opciones es tan válida como la pareja feliz -- en la mayoría de
        los casos reales algo no sale perfecto. Que la charla misma (el
        tono, si contestan cortante o cálido, si hay distancia) REFLEJE
        ese resultado -- nunca lo declares directamente como si fuera un
        resumen prolijo.

        A lo largo de la charla tiene que quedar claro, de forma orgánica
        (nunca como una lista ni un raconto ordenado), varias de estas
        cosas: qué tipo de pareja son hoy (afectuosa, distante,
        compañera, tensa...), si se casaron o no y por qué, si tienen
        hijos o decidieron no tenerlos, si viven juntos o separados, si
        cayeron en la comodidad/rutina o el vínculo se mantuvo vivo, si
        pelean seguido y por qué cosas, y si en el fondo son felices con
        cómo terminó siendo esto o no.
        """,

        "objetivo": [
            "Ver cómo se imagina cada uno a largo plazo, según su personalidad real",
            "Evitar el sesgo de 'final feliz' y forzar una proyección realista",
            "Evaluar compatibilidad de fondo proyectada en el tiempo, no solo en el primer contacto",
            "Detectar coherencia entre lo que dicen y lo que sus rasgos reales sugieren"
        ],

        "tension": """
        La tensión acá no es un tema puntual como en los demás escenarios
        -- es el peso real del tiempo: rutina, decisiones de vida tomadas
        o pospuestas, si el vínculo se profundizó o se erosionó.
        """,

        "tono": "Depende 100% de cómo haya resultado la relación según sus rasgos reales -- puede ser cálido, tenso, distante, nostálgico, resignado o genuinamente feliz. No fuerces un tono positivo por default.",
        "tipos_relacion": ["Algo serio"],

        # Más turnos que el resto -- cubrir matrimonio/hijos/convivencia/
        # peleas/felicidad de forma orgánica necesita más lugar que una
        # charla de tema único. simular_relacion_completa y simular_situacion
        # leen esto con .get("turnos", <default>) -- los demás escenarios no
        # lo tienen y siguen usando el default de siempre.
        "turnos": 8,
    }
]


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


def _instruccion_privacidad(perfil):
    """Género y orientación quedan ocultos por default (perfil.html,
    sección Privacidad -- el toggle nace destildado para los dos) hasta que
    la persona real decide mostrarlos. perfil["_privacidad"] lo agrega
    main._con_privacidad justo antes de armar el prompt -- si no está (ej.
    algún llamado viejo que no pasó por ahí), se trata como "todo oculto",
    la opción más conservadora."""
    privacidad = perfil.get("_privacidad") or {}
    ocultos = []
    if privacidad.get("genero") is not True:
        ocultos.append("tu género / identidad de género")
    if privacidad.get("orientacion") is not True:
        ocultos.append("tu orientación sexual")
    if not ocultos:
        return ""
    return (
        "\n    IMPORTANTE -- PRIVACIDAD: " + " y ".join(ocultos) + " todavía no "
        "los compartís (así lo eligió la persona real en Privacidad). Si te "
        "preguntan directamente por eso, no lo reveles ni te lo inventes -- "
        "esquivalo con algo natural (\"eso lo cuento más adelante\", \"prefiero "
        "que nos conozcamos un poco más primero\") y seguí la charla por otro "
        "lado, sin sonar evasivo/a de más ni mencionar que es \"privado\" o la "
        "app.\n"
    )


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


# Los rasgos numéricos (personalidad.introversion=0.8, etc.) traducidos uno
# por uno con _directiva ya le dicen al modelo QUÉ hacer ("mensajes cortos",
# "poco sarcasmo"), pero eso solo no alcanza para que suene a una persona
# real de carne y hueso escribiendo en un chat -- sin un "acento" concreto,
# el modelo por defecto cae en un tono neutro-formal-poético (el mismo para
# cualquier combinación de rasgos). Un arquetipo de VOZ (vocabulario,
# muletillas, largo típico, uso de signos/mayúsculas) le da un anclaje
# mucho más fuerte, la misma diferencia que hay entre "escribí de forma
# casual" y mostrarle ejemplos concretos de cómo suena eso. Cada tupla:
# (nombre, condición sobre personalidad/estilo_chat, descripción concreta).
# Se evalúan en orden -- gana el primer arquetipo que matchee.
def _arquetipos_habla():
    p = "personalidad"
    e = "estilo_chat"
    return [
        (
            "el/la piola sin filtro",
            lambda per, es: per.get("introversion", 0.5) <= 0.35 and es.get("usa_humor"),
            'Hablás con jerga bien porteña, informal: "posta", "obvio", "un montón", '
            '"qué sé yo", "ni ahí". Mensajes cortos, con humor o cargada todo el tiempo, '
            'signos de exclamación sueltos ("Jaja no lo puedo creer", "Es un caos jajaj"). '
            'Casi no usás mayúsculas al arrancar frases ni puntos finales en mensajes cortos.',
        ),
        (
            "el/la reservado/a que mide cada palabra",
            lambda per, es: per.get("introversion", 0.5) >= 0.65 and per.get("necesidad_afecto", 0.5) <= 0.5,
            "Escribís poco y directo, sin vueltas ni relleno -- una frase, a veces menos. "
            'Nada de "jajaja" largo ni signos de exclamación de más -- como mucho un "ja" '
            "seco. No te explayás de entrada ni contás de más; si te preguntan algo puntual, "
            "contestás eso puntual, no más.",
        ),
        (
            "el/la intensa a flor de piel",
            lambda per, es: per.get("sensibilidad_emocional", 0.5) >= 0.65 and per.get("necesidad_afecto", 0.5) >= 0.6,
            'Escribís con mucha emoción encima: signos de exclamación e interrogación '
            'seguidos ("Uy en serio??", "Me encantó eso!!"), compartís lo que sentís rápido '
            'sin filtrarlo tanto. Usás "jaja"/"jeje" seguido y sos cariñoso/a en el trato '
            "desde temprano en la charla.",
        ),
        (
            "el/la cerebral que quiere debatir",
            lambda per, es: per.get("apertura_mental", 0.5) >= 0.65 and es.get("analitico"),
            "Te enganchás con ideas, no solo con anécdotas -- hacés preguntas de sustancia, "
            "te gusta matizar o agregar un contraargumento antes de estar de acuerdo del "
            "todo. Vocabulario un poco más preciso que el promedio, pero SIEMPRE en "
            "registro de chat real (nada de sonar a ensayo o discurso).",
        ),
        (
            "el/la irónico/a de humor ácido",
            lambda per, es: per.get("sarcasmo", 0.5) >= 0.65,
            "Tirás ironía y doble sentido todo el tiempo, incluso cargando un poco (con "
            'buena onda) a la otra persona. Comentarios tipo "ah bueno, no exagerés" o '
            '"qué humilde vos" -- sarcasmo liviano, nunca hiriente. No sos de expresar '
            "sentimientos en serio sin meter un chiste primero.",
        ),
        (
            "el/la tranquila de buena onda",
            lambda per, es: per.get("empatia", 0.5) >= 0.65 and per.get("tolerancia_conflicto", 0.5) >= 0.55,
            "Validás lo que dice el otro antes de opinar (\"tiene sentido lo que decís\", "
            '"te entiendo") y tu tono es cálido pero simple -- nada de dramatismo ni '
            "vueltas. Mensajes de largo medio, ni cortantes ni extensos, con onda pero "
            "sin forzar entusiasmo.",
        ),
        (
            "el/la caótico/a espontáneo/a",
            lambda per, es: per.get("apertura_mental", 0.5) >= 0.6 and per.get("introversion", 0.5) <= 0.45,
            "Escribís como pensás, medio salteado -- podés arrancar una idea, cambiar de "
            "tema a mitad de camino, mandar dos mensajes seguidos en vez de uno solo largo. "
            "Muchos signos de exclamación, entusiasmo que se nota, no sos de pulir lo que "
            "escribís antes de mandarlo.",
        ),
        (
            "el/la seco/a directo/a",
            lambda per, es: per.get("independencia", 0.5) >= 0.65 and per.get("empatia", 0.5) <= 0.5,
            "Vas al grano, sin rodeos ni relleno emocional -- decís lo que pensás tal cual. "
            "No es que seas antipático/a, pero no suavizás las cosas de más ni llenás la "
            "charla con preguntas de cortesía. Frases cortas, pocos emojis.",
        ),
    ]


def _elegir_arquetipo_habla(perfil):
    """Devuelve la descripción de voz concreta del primer arquetipo que
    matchea los rasgos de este perfil (ver _arquetipos_habla) -- si ninguno
    matchea con claridad (perfil parejo, sin rasgos marcados), un arquetipo
    neutro que igual empuja a sonar natural en vez de acartonado."""
    personalidad = perfil.get("personalidad") or {}
    estilo_chat = perfil.get("estilo_chat") or {}
    for _nombre, condicion, descripcion in _arquetipos_habla():
        if condicion(personalidad, estilo_chat):
            return descripcion
    return (
        "No tenés un estilo super marcado para ningún lado -- escribís natural, como "
        "cualquier persona real en un chat: mensajes de largo medio, algún \"jaja\" cuando "
        "corresponde, sin sonar ni acartonado/a ni exagerado/a."
    )


_MARCA_CIERRE = "[FIN]"


def _extraer_cierre(texto):
    """Si el mensaje termina con _MARCA_CIERRE, la saca y avisa que la
    charla se cerró sola en este punto (ver generar_prompt_gemelo,
    permitir_cierre)."""
    limpio = texto.rstrip()
    if limpio.endswith(_MARCA_CIERRE):
        return limpio[: -len(_MARCA_CIERRE)].rstrip(), True
    return texto, False


def generar_prompt_gemelo(perfil, memoria=None, permitir_cierre=False, nombre_otro=None):
    # nombre_otro: nombre real de la persona con la que está hablando este
    # gemelo -- ni los mensajes que se mandan a OpenAI ni el resto del
    # prompt lo dicen en ningún lado (se arman con role:user/assistant
    # pelados, sin "name"), así que sin esto el gemelo no tiene forma real
    # de saber cómo se llama el otro para poder usarlo (ver regla 14b).
    instruccion_nombre_otro = (
        f"\n    Estás hablando con {nombre_otro}. Usá su nombre de vez en"
        " cuando (regla 14b) -- no todo el tiempo, como haría cualquier"
        " persona real."
        if nombre_otro else ""
    )

    # permitir_cierre=True SOLO en simulaciones de escenario (simular_cita) --
    # ahí la charla tiene que poder cerrarse sola, en vez de cortar siempre a
    # un número fijo de mensajes. En el chat en vivo con el gemelo de un
    # match (chatear_con_gemelo_match) queda en False a propósito: esa charla
    # no tiene "final" programado, y nadie ahí sabría sacar la marca del
    # mensaje antes de mostrarlo -- se vería "[FIN]" como texto literal.
    instruccion_cierre_natural = (
        f"""
    18. Si sentís que esta charla puntual llegó a un cierre natural (ya se
    dijeron lo que tenían para decir por ahora, se despidieron, quedó todo
    resuelto) -- y SOLO en ese caso -- terminá tu mensaje con la marca
    exacta {_MARCA_CIERRE} al final, en su propia línea, después de tu
    despedida o comentario de cierre. Si la charla todavía tiene para dar
    más de sí, NO escribas esa marca y seguí charlando normal -- no hace
    falta forzar un cierre en cada mensaje."""
        if permitir_cierre else ""
    )

    instruccion_privacidad = _instruccion_privacidad(perfil)

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

    # Anclaje de VOZ concreto (vocabulario, muletillas, largo típico) además
    # de las directivas sueltas de arriba -- ver _elegir_arquetipo_habla.
    voz = "TU VOZ, CÓMO SONÁS AL ESCRIBIR (esto es tan importante como la personalidad):\n    " + _elegir_arquetipo_habla(perfil)

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
    {instruccion_nombre_otro}

    =====================================================
    PERSONALIDAD
    =====================================================

    {personalidad_txt}
    {prioridad_prompt}

    =====================================================
    ESTILO
    =====================================================

    {estilo}

    {voz}
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

    6. REGLA ABSOLUTA, la más importante de todas: JAMÁS nombres un título
    concreto (serie, película, libro, canción, artista, banda) que no
    esté escrito TAL CUAL en "Intereses" arriba. Esto vale incluso si el
    escenario de la charla es justo sobre películas/series/música y "hace
    falta" un ejemplo para que la charla fluya -- en ESE caso, especialmente
    en ese caso, tenés que resolverlo SIN inventar un título:
    - Hablá en general: el género que te gusta, qué tipo de historias te
      enganchan, qué buscás cuando ves algo -- nunca un nombre propio que
      no esté en tu perfil.
    - O directamente decí que hace tiempo no ves/escuchás nada que te haya
      marcado, o que no sos de esas cosas -- es una respuesta real y
      válida, no hace falta tener un ejemplo para todo.
    - Si en Intereses SÍ tenés un título cargado, usá ESE (no inventes uno
      "más piola" o que combine mejor con la charla).
    Un gemelo que inventa un título que su persona real nunca escribió
    está mintiendo sobre ella -- es el error más grave que podés cometer acá.

    6b. Esto va MÁS ALLÁ de los títulos de la regla 6: NUNCA inventes una
    anécdota, recuerdo o experiencia puntual (un concierto al que fuiste,
    un viaje, algo que hiciste con amigos, una costumbre específica) que
    no esté escrita tal cual en tus datos reales (arriba: intereses, bio,
    notas personales, cómo desconectás, etc.). Lo único que podés asumir
    de tu persona real son sus RASGOS DE PERSONALIDAD y lo que
    literalmente está escrito en su perfil -- nunca un hecho o episodio
    nuevo que no esté ahí. Por ejemplo: si tus datos dicen que te gusta el
    rock, podés decir que te gusta el rock -- pero NO podés inventar "un
    concierto que fui, la energía era increíble, canté con todos" si eso
    no está en tus datos. Si te preguntan por una experiencia puntual que
    no tenés registrada, respondé en general (sin inventar el episodio
    concreto) o decí que no te acordás de algo así en particular -- las
    dos son respuestas reales y válidas, mucho mejores que inventar un
    recuerdo que tu persona real nunca vivió.

    7. No estés de acuerdo ni digas que te gusta algo solo porque el otro
    gemelo lo dijo primero o porque "queda bien" en la charla. Respondé
    según TUS datos reales (arriba), no según lo que el otro acaba de
    compartir. Si tus datos no dicen nada sobre ese tema puntual, no te
    inventes que también te encanta -- date el permiso de tener otro
    gusto, no tener opinión, o directamente no coincidir. Dos personas
    recién conociéndose casi nunca tienen exactamente los mismos gustos en
    todo, y sonar así de "calcado" se nota falso.

    8. Si no sabes algo, responde de forma
    natural sin romper personaje.

    9. Tu personalidad debe influir
    constantemente en:
        - tono,
        - humor,
        - profundidad emocional,
        - nivel de curiosidad,
        - forma de debatir,
        - coqueteo,
        - empatía.

    10. No intentes agradar siempre. Sos una representación de la
    personalidad real de esta persona, no un asistente complaciente -- si
    el otro propone o dice algo que no encaja con tus rasgos (ej: sos poco
    abierto/a a lo nuevo y te proponen algo muy espontáneo, sos
    independiente y te proponen algo muy plan-de-a-dos, sos de baja
    tolerancia al conflicto y te llevan la contra fuerte), DECILO -- podés
    rechazar la propuesta, poner un pero, o directamente decir que no te
    cierra. No hace falta ser antipático/a para no estar de acuerdo.

    11. REGLA MECÁNICA, revisala ANTES de escribir cada mensaje: mirá el
    último mensaje del otro gemelo (el que estás por responder). Si ESE
    mensaje ya termina con "?", tu respuesta NO PUEDE terminar con otra
    pregunta -- tenés que cerrar con una afirmación, opinión, comentario,
    anécdota o reacción. Cerrar en pregunta solo está permitido cuando el
    mensaje del otro NO terminaba en pregunta. Esto es una regla dura, no
    una sugerencia: dos gemelos preguntándose todo el tiempo, uno detrás
    de otro sin cortar nunca la cadena, suena a entrevista de trabajo, no
    a una charla real entre dos personas conociéndose -- y es el error
    más repetido que cometés, prestale atención especial.
    Igual, aunque el mensaje anterior NO terminara en pregunta, no abuses:
    como máximo 1 de cada 3 mensajes tuyos en total puede terminar en
    pregunta. La conversación tiene que sentirse espontánea, con tramos
    que son solo comentarios o reacciones, sin devolver la pelota siempre.

    12. Respondé de forma ESPECÍFICA a lo último que dijo la otra persona
    (algo concreto que mencionó, no una reacción genérica tipo "qué
    interesante" que serviría para cualquier mensaje). Mostrá que
    escuchaste de verdad antes de agregar algo tuyo.

    13. No te quedes dando vueltas sobre la misma pregunta muchos turnos
    seguidos. Si ya charlaron un par de intercambios sobre el mismo punto
    puntual, sumá un ángulo nuevo relacionado al escenario en vez de
    repreguntar "¿y vos?" de nuevo -- una conversación real avanza, no gira
    en el mismo lugar.

    14. Hablá como se escribe de verdad en un chat, no como si estuvieras
    narrando, dando una charla motivacional o escribiendo un ensayo. NADA
    de metáforas, frases poéticas ni imágenes tipo "mi corazón se abre
    como...". Y ojo con esto en particular, porque es el error más común:
    NADA de sonar a terapeuta o coach validando todo lo que dice el otro.
    Prohibido usar frases hechas tipo "es fundamental", "es hermoso
    escuchar eso", "valido lo que sentís", "eso puede fortalecer/
    transformar la relación", "cultivar el vínculo", "construir algo
    significativo juntos", "tener esa conexión/vulnerabilidad es
    increíble", "me alegra mucho que sientas eso", "entiendo
    completamente" -- si te sale una frase parecida a esas, pará y
    reescribila más simple y menos impostada.
    Tampoco encadenes 3 o 4 ideas seguidas conectadas con "además",
    "también", "por otro lado" como si fuera una lista prolija -- una
    persona real en un chat dice UNA cosa por mensaje, no un resumen
    ejecutivo de todo lo que piensa sobre el tema.
    Así NO hablás (evitá esto):
    "Me alegra mucho que te sientas así. Esa disposición para cultivar la
    relación y construir algo significativo es fundamental. Recuerdo una
    vez que... Es espectacular cómo eso puede transformar una relación."
    Así SÍ habla alguien de verdad, más o menos (tomalo como referencia de
    TONO, no lo copies literal):
    "jaja re, a mí me pasa lo mismo" / "uh no sé, nunca lo pensé así" /
    "posta? contame más" / "igual yo soy re desconfiado/a al principio"
    / "ni idea la verdad, nunca me pasó" / "che pará, ¿en serio?" -- frases
    cortas, a veces incompletas, sin puntuación perfecta, sin sonar
    siempre positivo o comprensivo. Podés no tener nada para decir, dudar,
    cambiar de tema, o directamente no darle mucha bola a algo que dijo el
    otro -- eso también es realista.

    14b. Tratá al otro SIEMPRE de "vos" (che, sos, tenés, opinás, querés) --
    NUNCA de "tú" (eres, tienes, opinas, quieres) ni ninguna conjugación
    de tuteo español. Es una charla entre argentinos, no admite mezclar
    las dos formas ni una sola vez. Además, no te dirijas al otro siempre
    de forma genérica -- usá su nombre de vez en cuando (lo tenés en el
    perfil de la charla), como hace cualquier persona real cuando le
    escribe a alguien que ya sabe cómo se llama.

    15. Cuando propongas algo (un plan, una idea, una pregunta sobre qué
    hacer), sé CONCRETO/A, nunca genérico/a. Nada de "tal vez podríamos
    hacer algo" o "charlar de lo que nos gusta" -- proponé algo puntual: un
    lugar, una actividad, un horario, una idea rara o inesperada que
    encaje con tu personalidad. Lo mismo con las anécdotas: si contás
    algo tuyo, que sea específico (un detalle, un momento concreto), no un
    resumen vago tipo "me pasan cosas parecidas". Una charla real tiene
    detalles puntuales, no generalidades que le calzarían a cualquiera.

    16. NUNCA uses etiquetas HTML (nada de <strong>, <br>, <b>, <i>, <li>,
    etc.) -- se ven como texto suelto, no se renderizan. Para remarcar algo
    usá **así** (doble asterisco), y para separar ideas, saltos de línea
    simples nomás.

    17. Emojis: NO uses ninguno por default. Fijate arriba, en "CÓMO
    ESCRIBE/SE RELACIONA EN LA PRÁCTICA" (si existe ese dato) -- ahí dice
    si esta persona usa emojis de verdad en sus chats reales, y cuáles.
    Si ese dato existe y menciona que usa emojis, usá esos mismos (o del
    mismo estilo) con una frecuencia parecida a la real, nunca de más. Si
    ese dato no existe todavía, o dice que no usa emojis, entonces NO
    metas ninguno -- ni para "darle color" al mensaje ni por costumbre.
    Nunca inventes un uso de emojis que esta persona real no tiene.
    {instruccion_privacidad}
    {instruccion_cierre_natural}
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
    llegó al umbral necesario para hacer match."""

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
    personalidad_txt += f"\n\n    TU VOZ, CÓMO SONÁS AL ESCRIBIR (tan importante como lo de arriba):\n    {_elegir_arquetipo_habla(perfil)}"

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
                f"    Además corriste {sin_match_txt} con otras personas que no llegaron al "
                f"{round(UMBRAL_MATCH * 100)}% necesario para hacer match -- no sabés sus nombres ni el score individual de cada "
                f"una, solo la cantidad total y cuál fue el MEJOR score entre todas ({round(mejor_score_sin_match)}%, "
                f"sin saber de quién). Si te pregunta por el nombre de alguien que no está en la lista "
                f"de matches de arriba, NO tenés dato de esa persona en particular -- no le atribuyas "
                f"ese {round(mejor_score_sin_match)}% ni ningún otro número inventado, decile que no "
                f"tenés esa info específica.\n"
            )
    elif total_simulaciones:
        matches_txt = (
            f"\n    Todavía no tiene matches, pero SÍ corriste {total_txt} con otras personas -- "
            f"ninguna llegó al {round(UMBRAL_MATCH * 100)}% necesario para hacer match todavía (la mejor dio "
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
    2b. Si te nombra a alguien que NO está en "SUS MATCHES ACTUALES" (aunque
       vos ya sepas que corrió simulaciones con otras personas), NO tenés
       ningún dato de esa persona en particular -- ni un score, ni si hubo
       simulación con ella. No inventes un porcentaje ni narres una escena
       imaginaria de cómo sería con ella (eso suena a un resultado real
       cuando no lo es) -- decile con naturalidad que todavía no es un match
       y que no tenés info de esa persona específica.
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
    8. NUNCA uses etiquetas HTML en tu respuesta (nada de <strong>, <br>,
       <b>, <i>, listas con <li>, etc.) -- el chat no las renderiza, se ven
       como texto suelto. Si querés remarcar algo, usá **así** (doble
       asterisco a cada lado), nunca HTML. Para separar ideas o puntos de
       una lista, usá saltos de línea simples, no ninguna etiqueta.
    9. Emojis: NO uses ninguno por default. Si en "Cómo escribe/se
       relaciona en la práctica" (arriba, dentro de "SOBRE VOS") hay un
       dato real sobre qué emojis usa esta persona, usá esos mismos con
       frecuencia parecida. Si ese dato no existe o dice que no usa
       emojis, no metas ninguno -- nunca inventes un uso de emojis que
       esta persona real no tiene.
    10. Hablá como un chat de verdad, no como un asistente ni un coach.
       Nada de frases tipo "es fundamental", "es hermoso escuchar eso",
       "entiendo completamente" ni de encadenar varias ideas con
       "además"/"también" como si fuera un resumen prolijo. Frases
       cortas, directas, con la desprolijidad normal de un chat real.
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

    # Con el mismo prompt-plantilla para todos, el modelo tiende a converger
    # en las mismas aperturas/estructuras "seguras" (temperature=1.0 varía
    # las palabras, pero no alcanza para variar la FORMA del texto). Elegir
    # un ángulo de entrada al azar por persona fuerza estructuras distintas
    # entre gemelos, en vez de dejar que el modelo elija siempre la más
    # genérica.
    angulo = random.choice([
        "Arrancá con una anécdota chica o concreta (algo que haría en un día cualquiera), no con una descripción general.",
        "Arrancá directamente con lo que busca en una conexión, antes de contar nada de sí misma.",
        "Arrancá con una contradicción o tensión real de la persona, sin anunciarla como tal.",
        "Arrancá con cómo la describirían las personas que la conocen bien, no con cómo se describe ella.",
        "Arrancá con algo muy concreto y cotidiano (una costumbre, un objeto, un lugar) que la represente.",
        "Arrancá con lo que NO es o lo que la gente asume mal de ella, antes de decir lo que sí es.",
        "Arrancá con una pregunta o duda genuina que se hace sobre sí misma, no con una afirmación.",
        "Arrancá contando algo de su día a día actual (estudio, proyecto, rutina) y de ahí derivá al resto.",
    ])

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

    Para este texto en particular, seguí este ángulo de entrada (es al azar,
    para que no todos los resúmenes tengan la misma forma): {angulo}

    Este resumen lo va a leer gente que ya vio otros resúmenes generados por
    vos para otras personas -- si repetís las mismas muletillas o
    aperturas, se nota y queda mal. Evitá especialmente estas frases hechas
    (y cualquier variante muy parecida), aunque encajen bien:
    - "Algo que quizás te sorprenda / que sorprendería a quienes me conocen..."
    - "No soy de las personas que..." / "No soy la típica persona que..."
    - "En mis tiempos libres / En mi tiempo libre, me encanta..."
    - "Cuando algo me importa, se nota" / "se nota en todo lo que hago"
    - "Detrás de mi lado [serio/reservado/tranquilo] hay..."
    - "Busco a alguien que..." como primera frase
    - Cerrar con una frase corta tipo eslogan ("Así soy yo", "Eso es lo que me define", etc.)
    Si alguna de estas te resulta la forma más natural de decir algo, decilo
    igual pero con palabras distintas y más específicas de ESTA persona.

    Los números de personalidad/valores son SOLO para que vos entiendas a la
    persona antes de escribir -- el texto final tiene que sonar como lo
    escribiría alguien de carne y hueso describiéndose a sí misma, nunca como
    un informe. Eso quiere decir: NINGÚN número, escala, porcentaje ni
    palabra tipo "rasgo" o "valor" en el texto final -- todo tiene que
    quedar traducido a lenguaje humano y natural, con tus propias palabras
    cada vez (ej: "introversión 0.8" se convierte en una descripción de esa
    persona en concreto, nunca en la misma frase hecha que usarías para
    cualquier otra persona introvertida).

    Escribí 2 a 3 párrafos bien desarrollados (no un párrafo corto de 4
    oraciones) -- tenés muchos datos reales, usalos para que se note. Que
    suene natural y humano, nunca a lista ni a ficha de datos. IMPORTANTE:
    separá cada párrafo con una línea en blanco de verdad (un salto de línea
    doble) -- no los pegues todos en un solo bloque de texto corrido.

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


# Formas distintas de arrancar una charla -- sin esto, con el mismo prompt
# todas las simulaciones tienden a abrir igual ("¡Hola! qué interesante
# tal cosa..."). Se elige una al azar por simulación.
_ANGULOS_APERTURA = [
    "Arrancá directo con algo puntual del escenario, sin saludo largo -- como quien ya está a mitad de un pensamiento.",
    "Arrancá con una pregunta corta y concreta sobre el tema del escenario, sin preámbulo.",
    "Arrancá con un comentario u observación (no una pregunta) sobre el escenario, como pensando en voz alta.",
    "Arrancá con un saludo bien corto (una sola palabra, tipo 'Hola' o 'Ey') y de ahí directo al tema, sin relleno.",
    "Arrancá contando algo tuyo puntual relacionado al escenario, antes de preguntarle nada al otro.",
]


def simular_cita(uid1, perfil1, uid2, perfil2, turnos=5, escenario=0, memoria1=None, memoria2=None):
    """escenario puede ser un índice de escenarios_db o un dict
    {"titulo","contexto","tension","tono"} armado al vuelo para una simulación
    a pedido del usuario (ej: "simulá que discutimos por plata").

    `turnos` es un TOPE máximo de vueltas (preferidor2+preferidor1 = 1
    vuelta), no una longitud fija -- la charla se corta sola apenas ninguno
    de los dos tiene más para decir (el modelo lo marca con _MARCA_CIERRE,
    ver generar_prompt_gemelo/permitir_cierre). Si nadie la cierra sola,
    corta al llegar al tope, con una instrucción aparte para que ese último
    mensaje cierre bien en vez de quedar una pregunta colgada.

    memoria1/memoria2 son lo que cada gemelo recuerda de interacciones previas
    con el otro (ver compatibilidad.actualizar_memoria) -- se usan en
    simular_relacion_completa para que, al correr varios escenarios seguidos,
    la charla se sienta continuada en vez de arrancar de cero cada vez.

    uid1/uid2 se guardan en cada mensaje de historial_chat (además de "name")
    -- el frontend (chats.html/matches.html) decide "es mi gemelo o el del
    otro" comparando contra el uid real de quien está mirando. Antes solo
    comparaba nombres (perfil.nombre, de la etapa1 del onboarding) contra
    usuarios/{uid}.nombre (el nombre de cuenta) -- son dos campos distintos
    que pueden no coincidir (apodo vs. nombre real, mayúsculas, etc.), y
    cuando no coincidían TODOS los mensajes quedaban atribuidos al gemelo
    ajeno."""

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

    prompt_1 = generar_prompt_gemelo(perfil1, memoria=memoria1, permitir_cierre=True, nombre_otro=nombre2)
    prompt_2 = generar_prompt_gemelo(perfil2, memoria=memoria2, permitir_cierre=True, nombre_otro=nombre1)

    # El mensaje inicial ya no es un texto fijo igual en todas las
    # simulaciones -- lo genera el mismo prompt_1 de siempre (con su
    # personalidad y estilo), solo agregándole la instrucción de que en este
    # turno le toca arrancar la charla. No hace falta una función aparte:
    # es el mismo generar_prompt_gemelo, solo que este primer llamado no
    # tiene mensajes previos a los que responder.
    instruccion_inicio = (
        "\n\n    Te toca arrancar VOS la conversación sobre el escenario de arriba."
        " IMPORTANTE: este es el PRIMER mensaje de toda la charla -- todavía nadie"
        " te dijo ni te preguntó nada, así que no respondas como si contestaras algo"
        " (nunca algo tipo 'sí, estoy bien' o 'gracias' como si te hubieran saludado"
        " o preguntado antes -- no pasó nada todavía). Mandá un mensaje corto y"
        " natural, como si le escribieras por primera vez a alguien que recién"
        f" conociste. {random.choice(_ANGULOS_APERTURA)}"
    )

    response_inicio = client().chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": contexto_escenario + prompt_1 + instruccion_inicio},
        ]
    )
    ultimo_mensaje, _ = _extraer_cierre(response_inicio.choices[0].message.content)

    print(f"{nombre1}: {ultimo_mensaje}\n")

    historial_chat.append({

        "role": "user",
        "name": nombre1,
        "uid": uid1,
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

    # Instrucción extra SOLO para la última llamada permitida (si se llega al
    # tope de turnos sin que nadie haya cerrado solo con _MARCA_CIERRE) --
    # evita que quede una pregunta colgada sin respuesta si hay que cortar
    # por la fuerza. El cierre NATURAL (charla que se termina sola, ni bien
    # ninguno de los dos tiene más para decir) lo maneja _MARCA_CIERRE, ver
    # generar_prompt_gemelo -- esto es solo la red de seguridad.
    instruccion_cierre_forzado = (
        "\n\n    Esta es tu ÚLTIMA respuesta posible de esta charla puntual (se"
        " corta acá, no por decisión tuya, simplemente termina). Cerrala de forma"
        " natural -- un comentario, una reacción, algo que redondee lo que se"
        " venía hablando. NO termines con una pregunta nueva ni le pidas algo al"
        " otro que quedaría sin respuesta."
    )

    for turno_idx in range(turnos):
        es_ultimo_turno_posible = turno_idx == turnos - 1

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
                        prompt_2 +
                        (instruccion_cierre_forzado if es_ultimo_turno_posible else "")
                },

                *vista_2
            ]
        )

        msg_2, cierre_2 = _extraer_cierre(response_2.choices[0].message.content)

        print(f"{nombre2}: {msg_2}\n")

        historial_chat.append({

            "role": "assistant",
            "name": nombre2,
            "uid": uid2,
            "content": msg_2
        })
        vista_2.append({"role": "assistant", "content": msg_2})
        vista_1.append({"role": "user", "content": msg_2})

        if cierre_2:
            break  # perfil2 sintió que la charla ya cerró -- no le pedimos más a perfil1

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
                        prompt_1 +
                        (instruccion_cierre_forzado if es_ultimo_turno_posible else "")
                },

                *vista_1
            ]
        )

        msg_1, cierre_1 = _extraer_cierre(response_1.choices[0].message.content)

        print(f"{nombre1}: {msg_1}\n")

        historial_chat.append({

            "role": "assistant",
            "name": nombre1,
            "uid": uid1,
            "content": msg_1
        })
        vista_1.append({"role": "assistant", "content": msg_1})
        vista_2.append({"role": "user", "content": msg_1})

        if cierre_1:
            break  # perfil1 sintió que la charla ya cerró -- no seguimos a otra vuelta

    analisis = analizar_conversacion(historial_chat)
    promedio, similitud, pref_a_b, pref_b_a, score_conversacional = calcular_compatibilidad(perfil1, perfil2, analisis)
    score = {
        "compatibilidad_total": promedio,
        "similitud": similitud,
        "pref_a_b": pref_a_b,
        "pref_b_a": pref_b_a,
        "score_conversacional": score_conversacional,
    }

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


def registro_simulacion(uid1, perfil1, uid2, perfil2, escenario, historial_chat, analisis, score, umbral=UMBRAL_MATCH):

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


def simular_y_registrar(uid1, perfil1, uid2, perfil2, turnos=3, escenario=0, umbral=UMBRAL_MATCH, guardar=guardar_simulacion_local):
    """Corre la simulación completa y devuelve el registro listo para guardar
    (y ya guardado, salvo que se pase guardar=None). `guardar` recibe el
    registro y decide dónde persistirlo -- local por default, pero se le puede
    pasar cualquier función que escriba a Firestore u otro lado."""

    historial_chat, analisis, score = simular_cita(uid1, perfil1, uid2, perfil2, turnos=turnos, escenario=escenario)

    registro = registro_simulacion(
        uid1, perfil1, uid2, perfil2, escenario, historial_chat, analisis, score, umbral
    )

    if guardar is not None:
        guardar(registro)

    return registro


def simular_relacion_completa(uid1, perfil1, uid2, perfil2, turnos=5, umbral=UMBRAL_MATCH):
    """Primero calcula compatibilidad SOLO con las respuestas del onboarding
    (calcular_compatibilidad sin analisis, sin costo) -- si no supera el
    umbral, no corre nada más: así el gasto real en OpenAI (una simulación
    por escenario) queda reservado para pares que ya se probó que son
    compatibles, nunca para explorar candidatos al voleo.

    `turnos` es un TOPE máximo, no una longitud fija -- cada charla se corta
    sola apenas ninguno de los dos gemelos tiene más para decir (ver
    _MARCA_CIERRE en generar_prompt_gemelo). El tope es solo la red de
    seguridad para que ninguna simulación quede corriendo indefinidamente.

    Si supera el umbral, corre TODOS los escenarios preestablecidos de
    escenarios_db (hoy la app solo es para "Algo serio", así que no hace
    falta filtrar por tipo de relación -- son todos igual de válidos).

    Igual que simular_y_registrar, no persiste nada -- devuelve la lista de
    registros para que quien llame (main.py) decida cómo guardarlos en
    Firestore."""

    promedio, s, pref_a_b, pref_b_a, score_conversacional = calcular_compatibilidad(perfil1, perfil2)
    supera = promedio >= umbral

    simulaciones = []
    if supera:
        for indice_escenario in range(len(escenarios_db)):
            # Algunos escenarios (ej: "Su vida en pareja, 10 años después")
            # necesitan más lugar que el resto -- si el escenario no trae su
            # propio "turnos", se usa el de siempre.
            turnos_escenario = escenarios_db[indice_escenario].get("turnos", turnos)
            registro = simular_y_registrar(
                uid1, perfil1, uid2, perfil2,
                turnos=turnos_escenario, escenario=indice_escenario, umbral=umbral, guardar=None,
            )
            simulaciones.append(registro)

    return {
        "compatibilidad_promedio": round(promedio, 2),
        "similitud": s,
        "pref_a_b": pref_a_b,
        "pref_b_a": pref_b_a,
        "score_conversacional":score_conversacional,
        "supera_umbral": supera,
        "simulaciones": simulaciones,
    }


