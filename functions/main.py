import firebase_admin
from firebase_admin import firestore
from firebase_functions import firestore_fn
from firebase_functions.options import set_global_options

from gemelo_perfil import construir_perfil_gemelo

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
