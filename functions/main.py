import random

import firebase_admin
from firebase_admin import firestore
from firebase_functions import firestore_fn, https_fn
from firebase_functions.options import set_global_options, MemoryOption

from gemelo_perfil import construir_perfil_gemelo
import simulador as motor

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
