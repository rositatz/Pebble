import random

import firebase_admin
from firebase_admin import firestore
from firebase_functions import firestore_fn, https_fn, scheduler_fn
from firebase_functions.options import set_global_options, MemoryOption

from gemelo_perfil import construir_perfil_gemelo
import simulador as motor
from geolocalizacion import distancia_entre_perfiles
from compatibilidad import compatible_por_genero, compatible_por_edad

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

    cambios = {}
    if "genero" in data:
        cambios["genero"] = (data.get("genero") or "").strip()
    if "orientacion" in data:
        cambios["orientacion"] = (data.get("orientacion") or "").strip()

    if "edadMinBusco" in data or "edadMaxBusco" in data:
        minimo = data.get("edadMinBusco")
        maximo = data.get("edadMaxBusco")
        minimo = int(minimo) if isinstance(minimo, (int, float)) else None
        maximo = int(maximo) if isinstance(maximo, (int, float)) else None
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

    db = firestore.client()

    doc1 = db.collection("usuarios").document(uid1).collection("gemelo").document("perfil").get()
    doc2 = db.collection("usuarios").document(uid2).collection("gemelo").document("perfil").get()

    if not doc1.exists:
        raise https_fn.HttpsError(
            https_fn.FunctionsErrorCode.FAILED_PRECONDITION,
            "Todavía no generaste tu gemelo (completá el onboarding primero)."
        )
    if not doc2.exists:
        raise https_fn.HttpsError(
            https_fn.FunctionsErrorCode.NOT_FOUND,
            "Esa persona todavía no tiene su gemelo generado."
        )

    perfil1 = doc1.to_dict()
    perfil2 = doc2.to_dict()

    if situacion:
        escenario = motor.armar_escenario_personalizado(situacion)
    else:
        escenario = random.randrange(len(motor.escenarios_db))

    registro = motor.simular_y_registrar(uid1, perfil1, uid2, perfil2, turnos=2, escenario=escenario)

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

    db = firestore.client()

    doc_perfil = db.collection("usuarios").document(uid).collection("gemelo").document("perfil").get()
    if not doc_perfil.exists:
        raise https_fn.HttpsError(
            https_fn.FunctionsErrorCode.FAILED_PRECONDITION,
            "Todavía no generaste tu gemelo (completá el onboarding primero)."
        )
    perfil = doc_perfil.to_dict()

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
        role = h.get("role")
        content = (h.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            mensajes.append({"role": role, "content": content})
    mensajes.append({"role": "user", "content": mensaje})

    response = motor.client().chat.completions.create(
        model="gpt-4o-mini",
        messages=mensajes,
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

            doc.reference.update({"estado": "COMPLETADO"})
            procesadas += 1

        except Exception as e:
            doc.reference.update({"estado": "ERROR", "error": str(e)})
            con_error += 1

    print(f"procesar_parejas_pendientes: {procesadas} procesadas, {con_error} con error.")
