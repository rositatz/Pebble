import random

import firebase_admin
from firebase_admin import firestore
from firebase_functions import firestore_fn, https_fn, scheduler_fn
from firebase_functions.options import set_global_options, MemoryOption

from gemelo_perfil import construir_perfil_gemelo
import simulador as motor
from geolocalizacion import distancia_entre_perfiles

set_global_options(max_instances=10)
firebase_admin.initialize_app()


@firestore_fn.on_document_written(document="usuarios/{uid}/gemelo_setup/data")
def generar_perfil_gemelo(event: firestore_fn.Event) -> None:
    """Se dispara solo cada vez que se escribe usuarios/{uid}/gemelo_setup/data
    (que es donde gemelo-setup.html va guardando el onboarding). Cuando detecta
    que `completed` pasó a True por primera vez, arma el perfil normalizado y
    lo guarda en usuarios/{uid}/gemelo/perfil."""

    despues = event.data.after
    if not despues.exists or not despues.get("completed"):
        return

    antes = event.data.before
    if antes.exists and antes.get("completed"):
        return  # ya se había generado, no lo repetimos en cada merge posterior

    uid = event.params["uid"]
    respuestas_raw = despues.to_dict()
    perfil = construir_perfil_gemelo(respuestas_raw)

    db = firestore.client()
    db.collection("usuarios").document(uid).collection("gemelo").document("perfil").set(perfil)


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

    par_ref = db.collection("matches").document(registro["par_id"])
    par_ref.collection("simulaciones").add(registro)
    par_ref.set({
        "usuario_1": registro["usuario_1"],
        "usuario_2": registro["usuario_2"],
        "ultimo_score": registro["score"]["compatibilidad_total"],
        "supera_umbral": registro["supera_umbral"],
        "actualizado": registro["fecha"],
    }, merge=True)

    return {
        "resumen": registro["analisis"].get("resumen_interaccion", ""),
        "score": registro["score"],
        "superaUmbral": registro["supera_umbral"],
        "escenario": registro["escenario"]["titulo"],
    }


@https_fn.on_call(secrets=["OPENAI_API_KEY"], timeout_sec=540, memory=MemoryOption.MB_512)
def buscar_matches_cercanos(request: https_fn.CallableRequest):
    """Corre simulaciones contra otros usuarios que ya generaron su gemelo,
    priorizando por cercanía geográfica (ver geolocalizacion.py y
    simulador.simular_matches_por_cercania): primero se evalúan los
    escenarios con la gente más cerca. Es una corrida cara (llama a OpenAI
    varias veces por candidato), así que por default se limita a los 5
    candidatos más cercanos -- se puede subir con `limite` en request.data.

    Datos esperados en request.data:
      - tipoRelacion (opcional): fuerza el tipo de relación a simular en vez
        de usar el "busco" del propio perfil.
      - limite (opcional, default 5): cantidad máxima de candidatos a evaluar,
        ya ordenados de más cerca a más lejos.
    """

    if request.auth is None:
        raise https_fn.HttpsError(
            https_fn.FunctionsErrorCode.UNAUTHENTICATED,
            "Hay que estar logueado para buscar matches."
        )

    uid = request.auth.uid
    data = request.data or {}
    tipo_relacion = (data.get("tipoRelacion") or "").strip() or None
    limite = data.get("limite")
    limite = int(limite) if limite else 5

    db = firestore.client()

    doc_propio = db.collection("usuarios").document(uid).collection("gemelo").document("perfil").get()
    if not doc_propio.exists:
        raise https_fn.HttpsError(
            https_fn.FunctionsErrorCode.FAILED_PRECONDITION,
            "Todavía no generaste tu gemelo (completá el onboarding primero)."
        )
    perfil_propio = doc_propio.to_dict()

    candidatos = []
    for doc in db.collection_group("gemelo").stream():
        if doc.id != "perfil":
            continue
        uid_candidato = doc.reference.parent.parent.id
        if uid_candidato == uid:
            continue
        candidatos.append((uid_candidato, doc.to_dict()))

    candidatos_por_uid = dict(candidatos)

    resultados = motor.simular_matches_por_cercania(
        uid, perfil_propio, candidatos,
        tipo_relacion=tipo_relacion, turnos=2, limite_candidatos=limite,
    )

    resumen = []
    for resultado in resultados:
        uid_candidato = resultado["uid_candidato"]
        par_ref = db.collection("matches").document(motor._par_id(uid, uid_candidato))

        for registro in resultado["simulaciones"]:
            par_ref.collection("simulaciones").add(registro)

        par_ref.set({
            "usuario_1": {"uid": uid, "nombre": perfil_propio.get("nombre", "")},
            "usuario_2": {"uid": uid_candidato, "nombre": candidatos_por_uid.get(uid_candidato, {}).get("nombre", "")},
            "ultimo_score": resultado["compatibilidad_promedio"],
            "supera_umbral": resultado["supera_umbral"],
            "distancia_km": resultado["distancia_km"],
            "actualizado": resultado["simulaciones"][-1]["fecha"],
        }, merge=True)

        resumen.append({
            "uid": uid_candidato,
            "distanciaKm": resultado["distancia_km"],
            "compatibilidadPromedio": resultado["compatibilidad_promedio"],
            "superaUmbral": resultado["supera_umbral"],
            "escenariosCorridos": resultado["escenarios_corridos"],
        })

    return {"matches": resumen}


# Firestore no incluye en un orderBy() los docs a los que les falta ese campo
# -- por eso, cuando no hay distancia (a alguno de los dos le falta ubicación),
# guardamos este número gigante en vez de None: así ese par igual entra en la
# cola, pero al ordenar por cercanía en procesar_parejas_pendientes() queda
# último en vez de desaparecer de la consulta.
_SIN_UBICACION = 999999

# Cuántas parejas pendientes se simulan por corrida nocturna -- cada una llama
# a OpenAI varias veces (una por escenario), así que esto es lo que controla
# cuánto tarda y cuánto cuesta cada corrida. Lo que no entra queda para la
# corrida siguiente (no se pierde, sigue en estado PENDIENTE).
LOTE_NOCTURNO = 20


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

            par_id = motor._par_id(uid1, uid2)

            if db.collection("parejas_pendientes").document(par_id).get().exists:
                continue
            if db.collection("matches").document(par_id).get().exists:
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
    timeout_sec=3600,
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

            par_ref = db.collection("matches").document(data["par_id"])
            for registro in resultado["simulaciones"]:
                par_ref.collection("simulaciones").add(registro)
            par_ref.set({
                "usuario_1": data["usuario_1"],
                "usuario_2": data["usuario_2"],
                "ultimo_score": resultado["compatibilidad_promedio"],
                "supera_umbral": resultado["supera_umbral"],
                "distancia_km": data.get("distancia_km"),
                "actualizado": resultado["simulaciones"][-1]["fecha"],
            }, merge=True)

            doc.reference.update({"estado": "COMPLETADO"})
            procesadas += 1

        except Exception as e:
            doc.reference.update({"estado": "ERROR", "error": str(e)})
            con_error += 1

    print(f"procesar_parejas_pendientes: {procesadas} procesadas, {con_error} con error.")
