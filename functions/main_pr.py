import random
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel
import json
import os
import firebase_admin
from firebase_admin import credentials, firestore
from compatibilidad import analizar_conversacion, calcular_compatibilidad
from gemelo_perfil import construir_perfil_gemelo
import simulador as motor
from datetime import datetime, timezone
# ==========================================
# 1. INICIALIZACIÓN DE FIREBASE Y FASTAPI
# ==========================================
if not firebase_admin._apps:
    # Si estás en desarrollo local usa la Service Account;
    # en Vercel/Google Cloud se detectan las credenciales por entorno.
    if os.path.exists("serviceAccountKey.json"):
        cred = credentials.Certificate("serviceAccountKey.json")
        firebase_admin.initialize_app(cred)
    else:
        firebase_admin.initialize_app()

db = firestore.client()
app = FastAPI(
    title="Gemelos Digitales - Engine",
    description="Backend de Filtrado y Compatibilidad",
)

def obtener_pair_id(id1: str, id2: str) -> str:
    """Retorna un ID canónico único para la pareja en orden alfabético."""
    return f"{id1}_{id2}" if id1 < id2 else f"{id2}_{id1}"

class SolicitudSimulacion(BaseModel):
    otroUid: str
    situacion: str | None = None
class SolicitudAnalisis(BaseModel):
    user_a_id: str
    user_b_id: str
    historial_chat: str
# En tu main.py (FastAPI)
@app.post("/api/generar-parejas-pendientes")
def generar_parejas_pendientes():
    """1. Lee la colección usuarios en Firestore.
    2. Filtra por edad, ubicación y preferencias básicas. 
    3. Guarda en 'evaluacion_parejas' con estado 'PENDIENTE'.
    """
    usuarios_ref = db.collection("usuarios").stream()
    usuarios = [
        {"id": doc.id, **doc.to_dict()} for doc in usuarios_ref
    ]

    parejas_creadas = 0

    # Iterar combinaciones de usuarios
    for i in range(len(usuarios)):
        for j in range(i + 1, len(usuarios)):
            usr1 = usuarios[i]
            usr2 = usuarios[j]

            # --- FILTROS BÁSICOS ---
            # Ejemplo: Validar busco / género o ubicación básica
            if usr1.get("busco") != usr2.get("busco"):
                continue
#=======================HAY QUE AGREGAR ALGO MAS PARA FILTRAR=========================
            # Generar un ID único para la pareja (ordenado alfabéticamente)
            pair_id = obtener_pair_id(usr1['id'], usr2['id'])

            # Verificar si ya existe en evaluacion_parejas
            doc_existente = (
                db.collection("evaluacion_parejas").document(pair_id).get()
            )
            if doc_existente.exists:
                continue

            escenarios_ref = db.collection("escenarios").stream()
            escenarios_ids = [doc.id for doc in escenarios_ref]

            if not escenarios_ids:
                raise HTTPException(
                    status_code=404,
                    detail="No se encontraron escenarios en la base de datos.",
                )

            # Crear el registro PENDIENTE
            db.collection("evaluacion_parejas").document(pair_id).set({
                "user_a_id": usr1["id"],
                "user_b_id": usr2["id"],
                "estado": "PENDIENTE",
                "compatibilidad_acumulada": 0,
                "escenarios_pendientes": escenarios_ids,
                "escenarios_completados": [],
            })
            parejas_creadas += 1

    return {
        "status": "exitoso",
        "parejas_nuevas_en_cola": parejas_creadas,
    }
@app.post("/api/gemelo/generar-perfil/{uid}")
def generar_perfil_endpoint(uid: str):
   
    setup_doc = (
        db.collection("usuarios")
        .document(uid)
        .collection("gemelo_setup")
        .document("data")
        .get()
    )

    if not setup_doc.exists or not setup_doc.get("completed"):
        raise HTTPException(
            status_code=400, detail="Onboarding incompleto."
        )

    perfil = construir_perfil_gemelo(setup_doc.to_dict())
    db.collection("usuarios").document(uid).collection("gemelo").document(
        "perfil"
    ).set(perfil)

    return {"status": "ok", "perfil": perfil}
@app.post("/api/simular-situacion")
def simular_situacion_endpoint(
    datos: SolicitudSimulacion, authorization: str = Header(None)
):
    """Ejecuta una simulación tomando un escenario de 'escenarios_pendientes'

    de la pareja y actualiza su estado.
    """
    # 1. Autenticación
    if not authorization:
        raise HTTPException(status_code=401, detail="Usuario no autenticado.")

    # uid1 = verificar_token_firebase(authorization)
    uid1 = "ID_DEL_USUARIO_AUTENTICADO"
    uid2 = datos.otroUid.strip()
    situacion_custom = (datos.situacion or "").strip()

    if not uid2:
        raise HTTPException(status_code=400, detail="Falta indicar otroUid.")
    if uid2 == uid1:
        raise HTTPException(
            status_code=400, detail="No podés simular con vos mismo."
        )

    db = firestore.client()

    # 2. Verificar que ambos usuarios tengan sus gemelos listos
    doc1 = (
        db.collection("usuarios")
        .document(uid1)
        .collection("gemelo_setup")
        .document("data")
        .get()
    )
    doc2 = (
        db.collection("usuarios")
        .document(uid2)
        .collection("gemelo_setup")
        .document("data")
        .get()
    )

    if not doc1.exists:
        raise HTTPException(
            status_code=400, detail="Completá el onboarding primero."
        )
    if not doc2.exists:
        raise HTTPException(
            status_code=404, detail="Esa persona no tiene gemelo generado."
        )

    perfil1 = doc1.to_dict()
    perfil2 = doc2.to_dict()

    # 3. Consultar o inicializar el documento en 'evaluacion_parejas'
    pair_id = obtener_pair_id(uid1, uid2)
    par_ref = db.collection("evaluacion_parejas").document(pair_id)
    par_doc = par_ref.get()

    if not par_doc.exists:
        # Si la pareja no existe, la creamos trayendo todos los escenarios
        escenarios_all = [
            d.id for d in db.collection("escenarios").stream()
        ]
        par_data = {
            "user_a_id": uid1,
            "user_b_id": uid2,
            "estado": "PENDIENTE",
            "compatibilidad_acumulada": 0,
            "escenarios_pendientes": escenarios_all,
            "escenarios_completados": [],
        }
        par_ref.set(par_data)
    else:
        par_data = par_doc.to_dict()

    escenarios_pendientes = par_data.get("escenarios_pendientes", [])
    escenarios_completados = par_data.get("escenarios_completados", [])
    compatibilidad_acumulada = par_data.get("compatibilidad_acumulada", 0)

    # 4. Determinar qué escenario simular
    escenario = None
    escenario_id_usado = None

    if situacion_custom:
        # Si vino una situación personalizada ingresada por el usuario
        escenario = motor.armar_escenario_personalizado(situacion_custom)
    else:
        # Si no hay situaciones pendientes para evaluar
        if not escenarios_pendientes:
            raise HTTPException(
                status_code=400,
                detail="Esta pareja ya completó todos los escenarios pendientes.",
            )

        # Tomamos el primer escenario pendiente (o uno al azar de la lista de pendientes)
        escenario_id_usado = escenarios_pendientes[0]

        # Traemos los datos de ese escenario específico desde la colección 'escenarios'
        esc_doc = (
            db.collection("escenarios").document(escenario_id_usado).get()
        )
        if not esc_doc.exists:
            raise HTTPException(
                status_code=404,
                detail=f"El escenario '{escenario_id_usado}' no existe en la base de datos.",
            )

        escenario = esc_doc.to_dict()
        escenario["id"] = esc_doc.id

    # 5. Ejecutar simulación con el motor
    registro = motor.simular_y_registrar(
        uid1, perfil1, uid2, perfil2, turnos=2, escenario=escenario
    )

    # 6. Actualizar las listas y puntajes de 'evaluacion_parejas'
    score_obtenido = registro["score"]["compatibilidad_total"]
    nueva_compatibilidad = compatibilidad_acumulada + score_obtenido

    if escenario_id_usado:
        escenarios_pendientes.remove(escenario_id_usado)
        escenarios_completados.append(escenario_id_usado)

    nuevo_estado = (
        "COMPLETADO" if len(escenarios_pendientes) == 0 else "PENDIENTE"
    )

    # Guardar la simulación en la subcolección
    par_ref.collection("simulaciones").add(registro)

    # Actualizar el documento principal del par
    par_ref.set(
        {
            "user_a_id": uid1,
            "user_b_id": uid2,
            "estado": nuevo_estado,
            "ultimo_score": score_obtenido,
            "compatibilidad_acumulada": nueva_compatibilidad,
            "escenarios_pendientes": escenarios_pendientes,
            "escenarios_completados": escenarios_completados,
            "supera_umbral": registro["supera_umbral"],
            "actualizado": datetime.now(timezone.utc),
        },
        merge=True,
    )

    # 7. Respuesta
    return {
        "resumen": registro["analisis"].get("resumen_interaccion", ""),
        "score": registro["score"],
        "superaUmbral": registro["supera_umbral"],
        "escenario": escenario.get("titulo", "Escenario Personalizado"),
        "escenarios_restantes": len(escenarios_pendientes),
        "estado_pareja": nuevo_estado,
    }
@app.post("/api/evaluar-simulacion")
def evaluar_simulacion_endpoint(datos: SolicitudAnalisis):
    """Recibe la conversación generada entre gemelos, ejecuta la evaluación de

    OpenAI, calcula el score y actualiza Firestore.
    """
    # 1. Obtener datos de Firestore de ambos usuarios
    usr_a_doc = (
        db.collection("usuarios").document(datos.user_a_id).get().to_dict()
    )
    usr_b_doc = (
        db.collection("usuarios").document(datos.user_b_id).get().to_dict()
    )

    if not usr_a_doc or not usr_b_doc:
        raise HTTPException(
            status_code=404, detail="Uno o ambos usuarios no existen."
        )

    perfil_a = construir_perfil_gemelo(usr_a_doc)
    perfil_b = construir_perfil_gemelo(usr_b_doc)

    # 2. Ejecutar tu análisis de OpenAI
    analisis = analizar_conversacion(datos.historial_chat)

    # 3. Calcular compatibilidad final
    score_final = calcular_compatibilidad(perfil_a, perfil_b, analisis)

    # 4. Actualizar Firestore en la colección evaluacion_parejas
    pair_id = obtener_pair_id(datos.user_a_id, datos.user_b_id)

    db.collection("evaluacion_parejas").document(pair_id).update({
        "compatibilidad_acumulada": score_final,
        "estado": (
            "DISPONIBLE_PARA_MATCH" if score_final >= 80.0 else "DESCARTADO"
        ),
        "ultimo_analisis": analisis,
    })

    return {
        "status": "completado",
        "pair_id": pair_id,
        "compatibilidad": score_final,
        "analisis": analisis,
    }

class SolicitudConectar(BaseModel):
    otro_uid: str


@app.post("/api/Conectar/dar-Conectar")
def dar_Conectar_endpoint(
    datos: SolicitudConectar, authorization: str = Header(None)
):
    """Registra un 'Conectar'. Si la otra persona ya le dio Conectar previa o

    recíprocamente, crea la entrada en 'conexiones'.
    """
    if not authorization:
        raise HTTPException(status_code=401, detail="Usuario no autenticado.")

    # 1. Obtener el ID del usuario actual (quien da el Conectar)
    # uid_emisor = verificar_token_firebase(authorization)
    uid_emisor = "ID_DEL_USUARIO_AUTENTICADO"
    uid_receptor = datos.otro_uid.strip()

    if not uid_receptor:
        raise HTTPException(status_code=400, detail="Falta indicar el otro_uid.")

    if uid_emisor == uid_receptor:
        raise HTTPException(
            status_code=400, detail="No podés darte Conectar a vos mismo."
        )

    db = firestore.client()

    # 2. Guardar mi Conectar en la colección 'Conectars'
    # Usamos un ID compuesto para evitar duplicados: "emisor_receptor"
    Conectar_id_propio = f"{uid_emisor}_{uid_receptor}"
    db.collection("por_conectar").document(Conectar_id_propio).set(
        {
            "from_uid": uid_emisor,
            "to_uid": uid_receptor,
            "timestamp": datetime.now(timezone.utc),
        }
    )

    # 3. Verificar si la otra persona YA me había dado Conectar antes
    Conectar_id_inverso = f"{uid_receptor}_{uid_emisor}"
    Conectar_inverso_doc = (
        db.collection("por_conectar").document(Conectar_id_inverso).get()
    )

    # Si la otra persona también me dio Conectar -> ¡HAY MATCH!
    if Conectar_inverso_doc.exists:
        conexion_id = obtener_pair_id(uid_emisor, uid_receptor)
        conexion_ref = db.collection("conexiones").document(conexion_id)

        # Crear el documento en la colección 'conexiones'
        conexion_ref.set(
            {
                "usuarios": [uid_emisor, uid_receptor],
                "usuario_1": (
                    uid_emisor if uid_emisor < uid_receptor else uid_receptor
                ),
                "usuario_2": (
                    uid_receptor if uid_emisor < uid_receptor else uid_emisor
                ),
                "creado_en": datetime.now(timezone.utc),
                "ultimo_mensaje": None,
                "ultimo_mensaje_fecha": None,
            },
            merge=True,
        )

        return {
            "status": "ok",
            "es_match": True,
            "conexion_id": conexion_id,
            "mensaje": "¡Hay Match! La conexión fue creada.",
        }

    # Si todavía no hay reciprocidad
    return {
        "status": "ok",
        "es_match": False,
        "conexion_id": None,
        "mensaje": "Conectar registrado exitosamente.",
    }