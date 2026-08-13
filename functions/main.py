import random
import datetime

import firebase_admin
from firebase_admin import firestore
from firebase_functions import firestore_fn, https_fn, scheduler_fn
from firebase_functions.options import set_global_options, MemoryOption

from gemelo_perfil import construir_perfil_gemelo
import simulador as motor
from geolocalizacion import distancia_entre_perfiles
from compatibilidad import compatible_por_genero, compatible_por_edad, compatible_por_hijos, extraer_aprendizaje_chats

set_global_options(max_instances=10)
firebase_admin.initialize_app()


def _con_creado(par_ref, payload):
    """Agrega 'creado' al payload SOLO si el doc de la conexión todavía no
    existe -- si no, cada simulación nueva sobre la misma pareja resetearía
    el timestamp de creación. matches.html lo usa para la regla de "match
    nuevo sin empezar a hablar en una semana, desaparece de la lista"."""
    if not par_ref.get().exists:
        payload["creado"] = firestore.SERVER_TIMESTAMP
    return payload


def _crear_notificacion(db, uid, tipo, titulo, cuerpo, otro_uid=None, otro_nombre=None, accion=None):
    """Todas las notificaciones reales (nuevo match, interés en común,
    recordatorio de retomar chat, gemelo inactivo) pasan por acá -- ver
    notificaciones.html, que lee usuarios/{uid}/notificaciones tal cual se
    escribe esto."""
    db.collection("usuarios").document(uid).collection("notificaciones").add({
        "tipo": tipo,
        "titulo": titulo,
        "cuerpo": cuerpo,
        "otroUid": otro_uid,
        "otroNombre": otro_nombre,
        "accion": accion,
        "leida": False,
        "creado": firestore.SERVER_TIMESTAMP,
    })


def _obtener_o_generar_perfil(db, uid):
    """Lee usuarios/{uid}/gemelo/perfil -- si todavía no existe pero el
    onboarding ya está completed:true, lo genera ahí mismo en vez de
    devolver None. generar_perfil_gemelo (el trigger de Firestore) hace este
    mismo trabajo pero de forma asincrónica, así que hay una ventana real
    (o, si el trigger falló una sola vez por lo que sea, una ventana
    permanente) en la que el onboarding ya está marcado como completo pero
    el perfil real todavía no existe. En vez de que el chat con el gemelo y
    las simulaciones fallen con "todavía no generaste tu gemelo" en ese
    caso, se genera acá al vuelo -- es la misma función pura
    (construir_perfil_gemelo) que ya usa el trigger, así que el resultado es
    idéntico. Devuelve None solo si de verdad no completó el onboarding."""
    ref = db.collection("usuarios").document(uid).collection("gemelo").document("perfil")
    snap = ref.get()
    if snap.exists:
        return snap.to_dict()

    doc_setup = db.collection("usuarios").document(uid).collection("gemelo_setup").document("data").get()
    if not doc_setup.exists or not doc_setup.get("completed"):
        return None

    perfil = construir_perfil_gemelo(doc_setup.to_dict())
    ref.set(perfil)
    return perfil


def _parse_fecha(valor):
    """'actualizado' en conexiones se guarda como string ISO (ver
    registro_simulacion), no como Timestamp nativo -- hay que parsearlo a
    mano para poder compararlo con datetime.now()."""
    if not valor:
        return None
    try:
        return datetime.datetime.fromisoformat(valor)
    except (TypeError, ValueError):
        return None


@firestore_fn.on_document_written(document="usuarios/{uid}/gemelo_setup/data")
def generar_perfil_gemelo(event: firestore_fn.Event) -> None:
    """Se dispara solo cada vez que se escribe usuarios/{uid}/gemelo_setup/data
    (que es donde gemelo-setup.html va guardando el onboarding). Cuando detecta
    que `completed` pasó a True por primera vez, arma el perfil normalizado y
    lo guarda en usuarios/{uid}/gemelo/perfil."""

    despues = event.data.after
    # despues es None si este evento es un borrado del doc (on_document_written
    # dispara en create/update/delete) -- no hay nada que generar en ese caso.
    if despues is None or not despues.exists or not despues.get("completed"):
        return

    antes = event.data.before
    # antes es None (no un snapshot con exists=False) cuando este es el
    # primer write de todos sobre este doc -- pasa siempre en el onboarding
    # de un usuario nuevo, así que hay que contemplarlo.
    if antes is not None and antes.exists and antes.get("completed"):
        return  # ya se había generado, no lo repetimos en cada merge posterior

    uid = event.params["uid"]
    respuestas_raw = despues.to_dict()
    perfil = construir_perfil_gemelo(respuestas_raw)

    db = firestore.client()
    db.collection("usuarios").document(uid).collection("gemelo").document("perfil").set(perfil)


@https_fn.on_call()
def generar_gemelo_ahora(request: https_fn.CallableRequest):
    """Genera usuarios/{uid}/gemelo/perfil DE FORMA SINCRÓNICA y lo espera
    antes de devolver la respuesta -- generar_perfil_gemelo (arriba) hace lo
    mismo pero como trigger asincrónico de Firestore, que dispara con demora
    variable (cold start, etc.). gemelo-setup.html marcaba completed:true y
    redirigía en el mismo instante, sin esperar a que el trigger terminara:
    quedaba una ventana real en la que usuarios/{uid}.gemelo_completado ya
    era true pero usuarios/{uid}/gemelo/perfil todavía no existía, y tanto el
    chat con el gemelo (chatear_con_gemelo/simular_situacion) como la
    tarjeta "Mi gemelo digital" de perfil.html lo interpretaban como
    "todavía no completaste el onboarding" -- aunque la persona ya lo había
    terminado. Este endpoint se llama y se espera (`await`) justo después de
    marcar completed:true, así el perfil real ya existe antes de redirigir.
    Es idempotente: si el trigger ya escribió el perfil, esto simplemente lo
    recalcula con los mismos datos y pisa el mismo resultado."""

    if request.auth is None:
        raise https_fn.HttpsError(
            https_fn.FunctionsErrorCode.UNAUTHENTICATED,
            "Hay que estar logueado."
        )

    uid = request.auth.uid
    db = firestore.client()

    # Se fuerza la regeneración (no simplemente reusar si ya existe) porque
    # este endpoint se llama justo al terminar el onboarding, cuando
    # gemelo_setup/data tiene la versión más nueva de las respuestas.
    doc_setup = db.collection("usuarios").document(uid).collection("gemelo_setup").document("data").get()
    if not doc_setup.exists or not doc_setup.get("completed"):
        raise https_fn.HttpsError(
            https_fn.FunctionsErrorCode.FAILED_PRECONDITION,
            "Todavía no completaste el onboarding de tu gemelo."
        )

    perfil = construir_perfil_gemelo(doc_setup.to_dict())
    db.collection("usuarios").document(uid).collection("gemelo").document("perfil").set(perfil)

    return {"ok": True}


@https_fn.on_call(secrets=["OPENAI_API_KEY"], timeout_sec=60, memory=MemoryOption.MB_512)
def generar_resumen_gemelo_ia(request: https_fn.CallableRequest):
    """Genera el párrafo de presentación de la última etapa del onboarding
    (gemelo-setup.html, etapa 7) con IA -- reemplaza la plantilla vieja de
    una sola oración armada en el cliente con motor.generar_resumen_gemelo,
    que usa TODAS las respuestas ya dadas (intereses, notas personales,
    personalidad, etc.), igual que ya se hace para el chat con el propio
    gemelo. Se llama ANTES de terminar el onboarding (se llega a esta etapa
    sin haber tocado "Este soy yo" todavía), así que a diferencia de
    generar_gemelo_ahora no exige completed:true -- alcanza con que exista
    el doc de gemelo_setup con lo que se completó hasta ahora."""

    if request.auth is None:
        raise https_fn.HttpsError(
            https_fn.FunctionsErrorCode.UNAUTHENTICATED,
            "Hay que estar logueado."
        )

    uid = request.auth.uid
    db = firestore.client()

    doc_setup = db.collection("usuarios").document(uid).collection("gemelo_setup").document("data").get()
    if not doc_setup.exists:
        raise https_fn.HttpsError(
            https_fn.FunctionsErrorCode.FAILED_PRECONDITION,
            "Todavía no completaste ninguna etapa del onboarding."
        )

    perfil = construir_perfil_gemelo(doc_setup.to_dict())

    try:
        texto = motor.generar_resumen_gemelo(perfil)
    except Exception as e:
        print(f"generar_resumen_gemelo_ia: error llamando a OpenAI: {e}")
        raise https_fn.HttpsError(
            https_fn.FunctionsErrorCode.UNAVAILABLE,
            "No se pudo generar el resumen en este momento. Probá de nuevo en un rato."
        )

    return {"texto": texto}


@https_fn.on_call()
def actualizar_preferencias_matching(request: https_fn.CallableRequest):
    """usuarios/{uid}/gemelo/perfil (lo que usa el matching real) es de
    solo-lectura para el cliente -- se genera una sola vez en el onboarding
    y después queda congelado (ver generar_perfil_gemelo), justamente para
    que nadie pueda inventarse rasgos falsos y matchear mejor. Pero
    perfil.html también deja editar género/orientación/rango de edad desde
    la tarjeta de perfil, así que hace falta un lugar server-side que
    propague ESE cambio puntual al perfil real -- este endpoint es ese
    lugar, y solo toca estos campos puntuales, nada más.

    Datos esperados en request.data:
      - genero (opcional)
      - orientacion (opcional)
      - edadMinBusco (opcional)
      - edadMaxBusco (opcional)
    """

    if request.auth is None:
        raise https_fn.HttpsError(
            https_fn.FunctionsErrorCode.UNAUTHENTICATED,
            "Hay que estar logueado."
        )

    uid = request.auth.uid
    data = request.data or {}

    # Esto es una Cloud Function: nada impide llamarla directo con
    # cualquier string, aunque el <select> de perfil.html solo mande estos
    # valores. Si viene algo fuera de esta lista, se ignora ese campo en vez
    # de guardar basura en el perfil que usa el matching.
    GENEROS_VALIDOS = {"Mujer", "Hombre", "No binario", "Género fluido", "Prefiero no decir", "Otro"}
    ORIENTACIONES_VALIDAS = {
        "Heterosexual", "Bisexual", "Gay / Lesbiana", "Pansexual", "Asexual",
        "Prefiero no decir", "Otro",
    }
    EDAD_MIN_VALIDA, EDAD_MAX_VALIDA = 18, 99

    cambios = {}
    if "genero" in data:
        valor = (data.get("genero") or "").strip()
        if valor in GENEROS_VALIDOS:
            cambios["genero"] = valor
    if "orientacion" in data:
        valor = (data.get("orientacion") or "").strip()
        if valor in ORIENTACIONES_VALIDAS:
            cambios["orientacion"] = valor

    if "edadMinBusco" in data or "edadMaxBusco" in data:
        minimo = data.get("edadMinBusco")
        maximo = data.get("edadMaxBusco")
        minimo = int(minimo) if isinstance(minimo, (int, float)) else None
        maximo = int(maximo) if isinstance(maximo, (int, float)) else None
        if minimo is not None:
            minimo = max(EDAD_MIN_VALIDA, min(EDAD_MAX_VALIDA, minimo))
        if maximo is not None:
            maximo = max(EDAD_MIN_VALIDA, min(EDAD_MAX_VALIDA, maximo))
        cambios["rango_edad_busco"] = {"min": minimo, "max": maximo} if (minimo or maximo) else None

    if not cambios:
        return {"ok": True}

    db = firestore.client()
    ref = db.collection("usuarios").document(uid).collection("gemelo").document("perfil")

    # Si todavía no generó su gemelo, no hay nada que actualizar -- cuando
    # complete el onboarding, generar_perfil_gemelo va a crear el perfil con
    # los valores que haya puesto ahí en ese momento.
    if not ref.get().exists:
        return {"ok": True}

    ref.set(cambios, merge=True)
    return {"ok": True}


@https_fn.on_call(secrets=["OPENAI_API_KEY"], timeout_sec=300, memory=MemoryOption.MB_512)
def simular_situacion(request: https_fn.CallableRequest):
    """Se llama desde el chat con el propio gemelo (gemelo.html): el usuario
    le pide a SU gemelo que simule una situación con el gemelo de otra persona
    (un match). No es un chat en vivo entre los dos gemelos -- la simulación
    corre acá atrás y se guarda; lo que el usuario ve en su chat es el resumen.

    Datos esperados en request.data:
      - otroUid (obligatorio): uid de la otra persona (el match)
      - situacion (opcional): texto libre de la situación pedida por el
        usuario. Si no viene, se elige un escenario al azar de los 9 fijos.
    """

    if request.auth is None:
        raise https_fn.HttpsError(
            https_fn.FunctionsErrorCode.UNAUTHENTICATED,
            "Hay que estar logueado para pedir una simulación."
        )

    uid1 = request.auth.uid
    data = request.data or {}
    uid2 = (data.get("otroUid") or "").strip()
    situacion = (data.get("situacion") or "").strip()

    if not uid2:
        raise https_fn.HttpsError(
            https_fn.FunctionsErrorCode.INVALID_ARGUMENT,
            "Falta indicar con quién simular (otroUid)."
        )
    if uid2 == uid1:
        raise https_fn.HttpsError(
            https_fn.FunctionsErrorCode.INVALID_ARGUMENT,
            "No podés simular una situación con vos mismo/a."
        )
    if len(situacion) > 500:
        raise https_fn.HttpsError(
            https_fn.FunctionsErrorCode.INVALID_ARGUMENT,
            "La situación es demasiado larga (máximo 500 caracteres)."
        )

    db = firestore.client()

    perfil1 = _obtener_o_generar_perfil(db, uid1)
    perfil2 = _obtener_o_generar_perfil(db, uid2)

    if perfil1 is None:
        raise https_fn.HttpsError(
            https_fn.FunctionsErrorCode.FAILED_PRECONDITION,
            "Todavía no generaste tu gemelo (completá el onboarding primero)."
        )
    if perfil2 is None:
        raise https_fn.HttpsError(
            https_fn.FunctionsErrorCode.NOT_FOUND,
            "Esa persona todavía no tiene su gemelo generado."
        )

    # Este endpoint se llama con cualquier otroUid que mande el cliente --
    # normalmente viene del picker de "Consejo para un match" (que solo
    # ofrece matches reales), pero como Cloud Function nada impide llamarlo
    # directo con cualquier uid. Sin este chequeo, alguien podría usarlo para
    # esquivar los mismos filtros de género/orientación/edad que aplica la
    # cola automática (buscar_parejas_pendientes) y forzar una conexión real
    # con alguien que nunca hubiera sido un candidato válido.
    if not compatible_por_genero(perfil1, perfil2):
        raise https_fn.HttpsError(
            https_fn.FunctionsErrorCode.FAILED_PRECONDITION,
            "Esa persona no es un candidato válido según género/orientación."
        )
    if not compatible_por_edad(perfil1, perfil2):
        raise https_fn.HttpsError(
            https_fn.FunctionsErrorCode.FAILED_PRECONDITION,
            "Esa persona no es un candidato válido según el rango de edad."
        )
    if not compatible_por_hijos(perfil1, perfil2):
        raise https_fn.HttpsError(
            https_fn.FunctionsErrorCode.FAILED_PRECONDITION,
            "Esa persona no es un candidato válido según hijos."
        )

    if situacion:
        escenario = motor.armar_escenario_personalizado(situacion)
    else:
        escenario = random.randrange(len(motor.escenarios_db))

    try:
        registro = motor.simular_y_registrar(uid1, perfil1, uid2, perfil2, turnos=2, escenario=escenario)
    except Exception as e:
        # Igual que en chatear_con_gemelo: sin este try/except una falla de
        # OpenAI acá (red, cuota, etc.) llegaba al cliente como "INTERNAL"
        # sin ninguna pista. Se loguea el error real y se devuelve un
        # mensaje honesto en vez de uno genérico.
        print(f"simular_situacion: error corriendo la simulación: {e}")
        raise https_fn.HttpsError(
            https_fn.FunctionsErrorCode.UNAVAILABLE,
            "No se pudo correr la simulación en este momento. Probá de nuevo en un rato."
        )

    par_ref = db.collection("conexiones").document(registro["par_id"])
    payload = {
        "usuario_1": registro["usuario_1"],
        "usuario_2": registro["usuario_2"],
        "participantes": [uid1, uid2],
        "ultimo_score": registro["score"]["compatibilidad_total"],
        "supera_umbral": registro["supera_umbral"],
        "actualizado": registro["fecha"],
    }
    payload = _con_creado(par_ref, payload)
    par_ref.collection("simulaciones").add(registro)
    par_ref.set(payload, merge=True)

    return {
        "resumen": registro["analisis"].get("resumen_interaccion", ""),
        "score": registro["score"],
        "superaUmbral": registro["supera_umbral"],
        "escenario": registro["escenario"]["titulo"],
    }


@https_fn.on_call(secrets=["OPENAI_API_KEY"], timeout_sec=60, memory=MemoryOption.MB_512)
def chatear_con_gemelo(request: https_fn.CallableRequest):
    """Chat DIRECTO entre el usuario y su propio gemelo (gemelo.html) -- a
    diferencia de simular_situacion (que simula una charla con el gemelo de
    OTRA persona), acá el usuario le habla a su propia representación de IA
    y la respuesta es una llamada real a OpenAI, no texto armado a mano.

    Datos esperados en request.data:
      - mensaje (obligatorio): lo que escribió el usuario.
      - historial (opcional): los últimos mensajes de la conversación, en
        formato [{"role": "user"|"assistant", "content": str}, ...], para
        que el gemelo tenga contexto de lo que ya se habló. Se recortan a
        los últimos 8 acá mismo por las dudas.
    """

    if request.auth is None:
        raise https_fn.HttpsError(
            https_fn.FunctionsErrorCode.UNAUTHENTICATED,
            "Hay que estar logueado para hablar con tu gemelo."
        )

    uid = request.auth.uid
    data = request.data or {}
    mensaje = (data.get("mensaje") or "").strip()
    historial = data.get("historial") or []

    if not mensaje:
        raise https_fn.HttpsError(
            https_fn.FunctionsErrorCode.INVALID_ARGUMENT,
            "Falta el mensaje."
        )
    if len(mensaje) > 2000:
        raise https_fn.HttpsError(
            https_fn.FunctionsErrorCode.INVALID_ARGUMENT,
            "El mensaje es demasiado largo (máximo 2000 caracteres)."
        )
    if not isinstance(historial, list):
        historial = []

    db = firestore.client()

    perfil = _obtener_o_generar_perfil(db, uid)
    if perfil is None:
        raise https_fn.HttpsError(
            https_fn.FunctionsErrorCode.FAILED_PRECONDITION,
            "Todavía no generaste tu gemelo (completá el onboarding primero)."
        )

    # Resumen liviano de los matches reales (solo nombre + score) para que
    # el gemelo pueda dar consejos concretos si le preguntan por alguno --
    # no hace falta el perfil completo de cada uno acá.
    matches_resumen = []
    try:
        for doc in db.collection("conexiones").where("participantes", "array_contains", uid).stream():
            cd = doc.to_dict()
            if not cd.get("supera_umbral"):
                continue
            u1 = cd.get("usuario_1", {})
            u2 = cd.get("usuario_2", {})
            otro = u2 if u1.get("uid") == uid else u1
            matches_resumen.append({
                "nombre": otro.get("nombre", "Usuario"),
                "score": round((cd.get("ultimo_score") or 0) * 100),
            })
    except Exception as e:
        print(f"chatear_con_gemelo: error trayendo matches para el resumen: {e}")

    system_prompt = motor.generar_prompt_gemelo_personal(perfil, matches_resumen)

    mensajes = [{"role": "system", "content": system_prompt}]
    for h in historial[-8:]:
        if not isinstance(h, dict):
            continue
        role = h.get("role")
        content = (h.get("content") or "").strip()[:2000]
        if role in ("user", "assistant") and content:
            mensajes.append({"role": role, "content": content})
    mensajes.append({"role": "user", "content": mensaje})

    try:
        response = motor.client().chat.completions.create(
            model="gpt-4o-mini",
            messages=mensajes,
        )
    except Exception as e:
        # Sin este try/except, cualquier falla acá (red, cuota de la API,
        # etc.) se propagaba sin atrapar y el cliente solo veía "INTERNAL"
        # -- un error sin ninguna pista de qué pasó ni qué hacer. Se loguea
        # el error real server-side (visible en los logs de la función) y se
        # le devuelve al usuario un mensaje honesto: el problema fue de la
        # IA en ese momento, no que le falte terminar su gemelo.
        print(f"chatear_con_gemelo: error llamando a OpenAI: {e}")
        raise https_fn.HttpsError(
            https_fn.FunctionsErrorCode.UNAVAILABLE,
            "Tu gemelo no pudo responder en este momento. Probá de nuevo en un rato."
        )

    return {"respuesta": response.choices[0].message.content}


# Firestore no incluye en un orderBy() los docs a los que les falta ese campo
# -- por eso, cuando no hay distancia (a alguno de los dos le falta ubicación),
# guardamos este número gigante en vez de None: así ese par igual entra en la
# cola, pero al ordenar por cercanía en procesar_parejas_pendientes() queda
# último en vez de desaparecer de la consulta.
_SIN_UBICACION = 999999

# Cuántas parejas pendientes se simulan por corrida nocturna -- cada una llama
# a OpenAI varias veces (una por escenario), así que esto es lo que controla
# cuánto tarda y cuánto cuesta cada corrida. Lo que no entra queda para la
# corrida siguiente (no se pierde, sigue en estado PENDIENTE). 10 deja margen
# cómodo contra el límite de 1800s (30 min) de las funciones programadas,
# incluso en el caso más caro (pareja "Algo serio", ~9 escenarios).
LOTE_NOCTURNO = 10


@scheduler_fn.on_schedule(schedule="every 60 minutes", timezone="America/Argentina/Buenos_Aires")
def buscar_parejas_pendientes(event: scheduler_fn.ScheduledEvent) -> None:
    """Fase 1 (rápida, sin llamar a OpenAI): recorre todos los usuarios con
    gemelo generado, arma las parejas que todavía no se evaluaron ni están
    en cola, y las deja en 'parejas_pendientes' con estado PENDIENTE. La
    fase 2 (procesar_parejas_pendientes) es la que corre las simulaciones
    de verdad, de a lotes, para no pasarse del timeout de la función.

    Filtro acá es superficial (mismo "busco") a propósito -- es solo para no
    generar simulaciones inútiles entre gente que busca cosas incompatibles;
    el filtro real de compatibilidad lo hace la simulación en sí."""

    db = firestore.client()

    usuarios = []
    for doc in db.collection_group("gemelo").stream():
        if doc.id != "perfil":
            continue
        uid = doc.reference.parent.parent.id
        usuarios.append((uid, doc.to_dict()))

    nuevas = 0

    for i in range(len(usuarios)):
        uid1, perfil1 = usuarios[i]
        for j in range(i + 1, len(usuarios)):
            uid2, perfil2 = usuarios[j]

            if (perfil1.get("busco") or "") != (perfil2.get("busco") or ""):
                continue

            if not compatible_por_genero(perfil1, perfil2):
                continue

            if not compatible_por_edad(perfil1, perfil2):
                continue

            if not compatible_por_hijos(perfil1, perfil2):
                continue

            par_id = motor._par_id(uid1, uid2)

            if db.collection("parejas_pendientes").document(par_id).get().exists:
                continue
            if db.collection("conexiones").document(par_id).get().exists:
                continue

            distancia = distancia_entre_perfiles(perfil1, perfil2)

            db.collection("parejas_pendientes").document(par_id).set({
                "par_id": par_id,
                "usuario_1": {"uid": uid1, "nombre": perfil1.get("nombre", "")},
                "usuario_2": {"uid": uid2, "nombre": perfil2.get("nombre", "")},
                "distancia_km": round(distancia, 1) if distancia is not None else _SIN_UBICACION,
                "estado": "PENDIENTE",
                "creado": firestore.SERVER_TIMESTAMP,
            })
            nuevas += 1

    print(f"buscar_parejas_pendientes: {nuevas} parejas nuevas encoladas.")


@scheduler_fn.on_schedule(
    schedule="0 3 * * *",
    timezone="America/Argentina/Buenos_Aires",
    secrets=["OPENAI_API_KEY"],
    timeout_sec=1800,  # 30 min -- el máximo permitido para funciones programadas
    memory=MemoryOption.MB_512,
)
def procesar_parejas_pendientes(event: scheduler_fn.ScheduledEvent) -> None:
    """Fase 2: toma un lote de 'parejas_pendientes' (las más cercanas
    geográficamente primero) y corre la simulación real para cada una --
    esto es lo que realmente llama a OpenAI, por eso corre de noche y en
    lotes chicos en vez de todas juntas.

    LOTE_NOCTURNO pares por corrida -- si queda cola, la siguiente corrida
    (mañana) sigue con las que falten. Cada par se procesa en su propio
    try/except para que un error puntual (ej: un timeout de OpenAI) no tire
    abajo el resto del lote."""

    db = firestore.client()

    pendientes = (
        db.collection("parejas_pendientes")
        .where("estado", "==", "PENDIENTE")
        .order_by("distancia_km")
        .limit(LOTE_NOCTURNO)
        .stream()
    )

    procesadas, con_error = 0, 0

    for doc in pendientes:
        data = doc.to_dict()
        uid1 = data["usuario_1"]["uid"]
        uid2 = data["usuario_2"]["uid"]

        try:
            doc1 = db.collection("usuarios").document(uid1).collection("gemelo").document("perfil").get()
            doc2 = db.collection("usuarios").document(uid2).collection("gemelo").document("perfil").get()
            if not doc1.exists or not doc2.exists:
                raise ValueError("A alguno de los dos ya no le existe el perfil de gemelo.")

            resultado = motor.simular_relacion_completa(uid1, doc1.to_dict(), uid2, doc2.to_dict())

            par_ref = db.collection("conexiones").document(data["par_id"])
            payload = {
                "usuario_1": data["usuario_1"],
                "usuario_2": data["usuario_2"],
                "participantes": [uid1, uid2],
                "ultimo_score": resultado["compatibilidad_promedio"],
                "supera_umbral": resultado["supera_umbral"],
                "distancia_km": data.get("distancia_km"),
                "actualizado": resultado["simulaciones"][-1]["fecha"],
            }
            payload = _con_creado(par_ref, payload)

            for registro in resultado["simulaciones"]:
                par_ref.collection("simulaciones").add(registro)
            par_ref.set(payload, merge=True)

            # Como cada pareja llega acá una sola vez (buscar_parejas_pendientes
            # ya descarta pares que ya tienen conexión), supera_umbral==True acá
            # siempre significa "match nuevo" -- no hace falta comparar contra
            # un score anterior. El umbral (0.75) lo define
            # simular_relacion_completa/registro_simulacion, no algo hardcodeado
            # acá: supera_umbral ya viene calculado con ese piso.
            if resultado["supera_umbral"]:
                nombre1 = data["usuario_1"]["nombre"] or "Usuario"
                nombre2 = data["usuario_2"]["nombre"] or "Usuario"
                pct = round(resultado["compatibilidad_promedio"] * 100)

                _crear_notificacion(
                    db, uid1, "match", f"¡Nuevo match con {nombre2}!",
                    f"Tu gemelo alcanzó {pct}% de afinidad con {nombre2}. Ya podés ver la conversación.",
                    otro_uid=uid2, otro_nombre=nombre2, accion="matches",
                )
                _crear_notificacion(
                    db, uid2, "match", f"¡Nuevo match con {nombre1}!",
                    f"Tu gemelo alcanzó {pct}% de afinidad con {nombre1}. Ya podés ver la conversación.",
                    otro_uid=uid1, otro_nombre=nombre1, accion="matches",
                )

                # Interés real en común (no un evento inventado) -- solo si
                # ambos perfiles comparten al menos uno de verdad.
                comunes = set(doc1.to_dict().get("intereses") or []) & set(doc2.to_dict().get("intereses") or [])
                if comunes:
                    interes = sorted(comunes)[0]
                    _crear_notificacion(
                        db, uid1, "interes", f"Vos y {nombre2} tienen algo en común",
                        f"A los dos les gusta {interes}. Podría ser una buena forma de arrancar la conversación.",
                        otro_uid=uid2, otro_nombre=nombre2, accion="chats",
                    )
                    _crear_notificacion(
                        db, uid2, "interes", f"Vos y {nombre1} tienen algo en común",
                        f"A los dos les gusta {interes}. Podría ser una buena forma de arrancar la conversación.",
                        otro_uid=uid1, otro_nombre=nombre1, accion="chats",
                    )

            doc.reference.update({"estado": "COMPLETADO"})
            procesadas += 1

        except Exception as e:
            doc.reference.update({"estado": "ERROR", "error": str(e)})
            con_error += 1

    print(f"procesar_parejas_pendientes: {procesadas} procesadas, {con_error} con error.")


# Mismo umbral que usa matches.html para hacer desaparecer un match nuevo
# sin empezar a hablar -- acá es "recordame retomar" en vez de "ocultalo",
# pero es la misma ventana de tiempo conceptualmente.
DIAS_RETOMAR_CHAT = 7

# Cuántos días sin que le corran una simulación nueva antes de avisarle que
# su gemelo está inactivo.
DIAS_INACTIVIDAD_GEMELO = 3

# Mínimo de mensajes propios (chat con el gemelo + chats reales con
# matches, combinados) para que valga la pena una llamada a OpenAI -- con
# menos que esto no hay suficiente texto para sacar nada real.
MIN_MENSAJES_APRENDIZAJE = 10

# Ventana de mensajes propios más recientes que se analiza en cada corrida.
# Los logs de chat se guardan como array completo pisado en cada guardado
# (no son append-only), así que no hay forma barata de trackear "solo lo
# nuevo desde la última vez" -- en cambio, se recalcula sobre esta ventana
# reciente todos los días, que ya alcanza para mantener el estilo al día.
VENTANA_MENSAJES_APRENDIZAJE = 40


@scheduler_fn.on_schedule(schedule="0 10 * * *", timezone="America/Argentina/Buenos_Aires")
def generar_recordatorios_diarios(event: scheduler_fn.ScheduledEvent) -> None:
    """Corre una vez por día (separado del batch pesado de las 3am) y genera
    los dos tipos de aviso que no dependen de que corra una simulación
    nueva:

    - "¿Retomás con X?": un chat real que ya arrancó pero no tiene mensajes
      nuevos hace DIAS_RETOMAR_CHAT días.
    - "Tu gemelo lleva N días sin interacciones": a este usuario no se le
      corrió ninguna simulación nueva en DIAS_INACTIVIDAD_GEMELO días.

    Cada aviso se throttlea con un timestamp guardado -- sin eso, correr
    todos los días generaría una notificación nueva todos los días mientras
    la situación no cambie."""

    db = firestore.client()
    ahora = datetime.datetime.now(datetime.timezone.utc)

    ultima_actividad_por_usuario = {}
    avisos_retomar = 0

    for doc in db.collection("conexiones").where("supera_umbral", "==", True).stream():
        data = doc.to_dict()
        participantes = data.get("participantes") or []
        if len(participantes) != 2:
            continue
        uid1, uid2 = participantes
        nombre1 = data.get("usuario_1", {}).get("nombre", "Usuario")
        nombre2 = data.get("usuario_2", {}).get("nombre", "Usuario")

        fecha_sim = _parse_fecha(data.get("actualizado"))
        if fecha_sim:
            for u in (uid1, uid2):
                actual = ultima_actividad_por_usuario.get(u)
                if actual is None or fecha_sim > actual:
                    ultima_actividad_por_usuario[u] = fecha_sim

        real = data.get("real") or {}
        msgs = real.get("msgs") or []
        ultima_msg = real.get("ultimaActividad")  # Timestamp real -- ver chats.html
        if msgs and ultima_msg:
            dias_inactivo = (ahora - ultima_msg).days
            recordado_en = real.get("recordatorioRetomarEn")
            ya_avisado = recordado_en and (ahora - recordado_en).days < DIAS_RETOMAR_CHAT
            if dias_inactivo >= DIAS_RETOMAR_CHAT and not ya_avisado:
                _crear_notificacion(
                    db, uid1, "retomar", f"¿Retomás con {nombre2}?",
                    f"La conversación quedó abierta hace {dias_inactivo} días.",
                    otro_uid=uid2, otro_nombre=nombre2, accion="chats",
                )
                _crear_notificacion(
                    db, uid2, "retomar", f"¿Retomás con {nombre1}?",
                    f"La conversación quedó abierta hace {dias_inactivo} días.",
                    otro_uid=uid1, otro_nombre=nombre1, accion="chats",
                )
                doc.reference.update({"real.recordatorioRetomarEn": firestore.SERVER_TIMESTAMP})
                avisos_retomar += 2

    avisos_inactivo = 0
    for uid, fecha_sim in ultima_actividad_por_usuario.items():
        dias_inactivo = (ahora - fecha_sim).days
        if dias_inactivo < DIAS_INACTIVIDAD_GEMELO:
            continue

        ref_usuario = db.collection("usuarios").document(uid)
        doc_usuario = ref_usuario.get()
        recordado_en = doc_usuario.to_dict().get("recordatorioInactivoEn") if doc_usuario.exists else None
        if recordado_en and (ahora - recordado_en).days < DIAS_INACTIVIDAD_GEMELO:
            continue

        _crear_notificacion(
            db, uid, "inactivo", f"Tu gemelo lleva {dias_inactivo} días sin interacciones",
            "Ajustar su personalidad o tus preferencias puede mejorar los resultados.",
            accion="gemelo",
        )
        ref_usuario.set({"recordatorioInactivoEn": firestore.SERVER_TIMESTAMP}, merge=True)
        avisos_inactivo += 1

    print(
        f"generar_recordatorios_diarios: {avisos_retomar} avisos de retomar chat, "
        f"{avisos_inactivo} avisos de gemelo inactivo (sobre {len(ultima_actividad_por_usuario)} usuarios con conexiones)."
    )


def _mensajes_propios_recientes(db, uid, limite=VENTANA_MENSAJES_APRENDIZAJE):
    """Junta los mensajes que ESTA persona escribió de verdad -- del chat
    con su propio gemelo (usuarios/{uid}/chats/gemelo_propio.log,
    tipo:"user") y de sus chats reales con matches (conexiones/{parId}.real.msgs,
    from:"me") -- y devuelve los últimos `limite`. No se mezclan mensajes
    de la otra persona ni respuestas del propio gemelo: son solo palabras
    de la persona dueña del perfil."""

    mensajes = []

    try:
        snap = db.collection("usuarios").document(uid).collection("chats").document("gemelo_propio").get()
        if snap.exists:
            log = snap.to_dict().get("log") or []
            for entrada in log:
                if isinstance(entrada, dict) and entrada.get("tipo") == "user" and entrada.get("text"):
                    mensajes.append(entrada["text"])
    except Exception as e:
        print(f"_mensajes_propios_recientes: error leyendo chat con el gemelo de {uid}: {e}")

    try:
        for doc in db.collection("conexiones").where("participantes", "array_contains", uid).stream():
            real_msgs = (doc.to_dict().get("real") or {}).get("msgs") or []
            for m in real_msgs:
                if isinstance(m, dict) and m.get("from") == "me" and m.get("text"):
                    mensajes.append(m["text"])
    except Exception as e:
        print(f"_mensajes_propios_recientes: error leyendo conexiones de {uid}: {e}")

    return mensajes[-limite:]


@scheduler_fn.on_schedule(
    schedule="0 4 * * *",
    timezone="America/Argentina/Buenos_Aires",
    secrets=["OPENAI_API_KEY"],
    timeout_sec=1800,
    memory=MemoryOption.MB_512,
)
def actualizar_aprendizaje_gemelo(event: scheduler_fn.ScheduledEvent) -> None:
    """Corre una vez por día: para cada usuario que dio consentimiento
    explícito (usuarios/{uid}.consentimientoAprendizajeChats == true), junta
    sus mensajes propios recientes (chat con su gemelo + chats reales con
    matches) y le pide a la IA que describa su estilo de escritura/forma de
    relacionarse e identifique intereses nuevos mencionados de verdad.

    A propósito NO toca personalidad ni valores -- esos números son los que
    se comparan matemáticamente entre dos perfiles para calcular
    compatibilidad real (compatibilidad.calcular_compatibilidad), y siguen
    viniendo solo de lo que la persona contestó a conciencia en el
    onboarding. Lo que se actualiza acá (estilo_aprendido + intereses
    nuevos) solo afecta CÓMO habla el gemelo, no CON QUIÉN matchea. Ver
    simulador.generar_prompt_gemelo/generar_prompt_gemelo_personal, que ya
    usan estilo_aprendido si está presente."""

    db = firestore.client()

    actualizados, sin_perfil_generado, sin_mensajes_suficientes, con_error = 0, 0, 0, 0

    for doc_usuario in db.collection("usuarios").where("consentimientoAprendizajeChats", "==", True).stream():
        uid = doc_usuario.id

        perfil_ref = db.collection("usuarios").document(uid).collection("gemelo").document("perfil")
        perfil_snap = perfil_ref.get()
        if not perfil_snap.exists:
            sin_perfil_generado += 1
            continue

        mensajes = _mensajes_propios_recientes(db, uid)
        if len(mensajes) < MIN_MENSAJES_APRENDIZAJE:
            sin_mensajes_suficientes += 1
            continue

        try:
            perfil = perfil_snap.to_dict()
            resultado = extraer_aprendizaje_chats(mensajes, intereses_actuales=perfil.get("intereses") or [])

            intereses_actuales = perfil.get("intereses") or []
            vistos = {i.casefold() for i in intereses_actuales}
            intereses_nuevos = [i for i in resultado["intereses_nuevos"] if i.casefold() not in vistos]

            cambios = {}
            if resultado["estilo"]:
                cambios["estilo_aprendido"] = resultado["estilo"]
            if intereses_nuevos:
                cambios["intereses"] = intereses_actuales + intereses_nuevos

            if cambios:
                perfil_ref.set(cambios, merge=True)
                actualizados += 1

        except Exception as e:
            print(f"actualizar_aprendizaje_gemelo: error procesando {uid}: {e}")
            con_error += 1

    print(
        f"actualizar_aprendizaje_gemelo: {actualizados} actualizados, "
        f"{sin_perfil_generado} sin perfil generado todavía, "
        f"{sin_mensajes_suficientes} sin mensajes suficientes, {con_error} con error."
    )
