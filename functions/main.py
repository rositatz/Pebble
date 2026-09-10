import random
import datetime
import hashlib
import json
import traceback
import os
import smtplib
from email.message import EmailMessage
from dotenv import load_dotenv

import firebase_admin
from firebase_admin import firestore, auth
from firebase_functions import firestore_fn, https_fn, scheduler_fn
from firebase_functions.options import set_global_options, MemoryOption

from gemelo_perfil import construir_perfil_gemelo
import simulador as motor
from geolocalizacion import distancia_entre_perfiles
from compatibilidad import compatible_por_genero, compatible_por_edad, compatible_por_hijos, extraer_aprendizaje_chats, extraer_correcciones_gemelo, instruccion_nivel_compatibilidad

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


def _score_promedio_simulaciones(par_ref, score_nuevo=None):
    """Promedia el score de TODAS las simulaciones guardadas para este par
    (la del match original al hacerse match + cualquiera pedida después
    desde el chat con el gemelo) -- así el % que se muestra en
    conexiones/{parId}.ultimo_score representa la compatibilidad GENERAL
    entre los dos, no solo la última situación puntual que se simuló.

    El score de una charla individual puede variar bastante según el
    escenario (una charla de "discutimos por plata" da un número más bajo
    que una charla liviana de conocerse, por ejemplo) sin que eso
    signifique que en general sean más o menos compatibles -- es
    justamente lo esperable que suba, baje o se mantenga según la
    situación puntual. Promediar contra el resto de simulaciones ya
    corridas amortigua esa variación normal en vez de que el número que ve
    el usuario salte de una simulación a la otra.

    score_nuevo: si se pasa, se suma al promedio aunque el doc de esa
    simulación todavía no se haya guardado en Firestore (evita depender del
    orden de escritura -- no importa si esto se llama antes o después de
    agregar el nuevo doc a la subcolección)."""
    scores = [
        doc.to_dict().get("score", {}).get("compatibilidad_total")
        for doc in par_ref.collection("simulaciones").stream()
    ]
    scores = [s for s in scores if isinstance(s, (int, float))]
    if score_nuevo is not None:
        scores.append(score_nuevo)
    if not scores:
        return score_nuevo
    return sum(scores) / len(scores)


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

def generar_enlace_app(accion, otro_uid=None):
    # IMPORTANTE: Cambia esto por tu dominio real en producción
    # Si estás probando en tu compu, podría ser "http://localhost:5500"
    base_url = "https://pebble.ar" 
    
    if accion == "matches":
        if otro_uid:
            return f"{base_url}/matches.html?persona={otro_uid}"
        else:
            return f"{base_url}/matches.html"
            
    elif accion == "chats":
        if otro_uid:
            return f"{base_url}/chats.html?persona={otro_uid}"
        else:
            return f"{base_url}/chats.html"
            
    elif accion == "gemelo":
        return f"{base_url}/gemelo.html"
        
    else:
        # Por defecto, los mandamos a notificaciones
        return f"{base_url}/notificacion.html"
def _mandar_correo(correo, titulo, texto, enlace_url):

    remitente = "pebble@pebble.ar"
    password = os.getenv("CONTRASEÑA_PEBBLE")

    # 2. Configurar el mensaje
    msg = EmailMessage()
    msg["Subject"] = titulo
    msg["From"] = remitente
    msg["To"] = correo

    # 3. Construir el cuerpo del correo
    # Primero el texto plano (fallback por si el cliente de correo no lee HTML)
    cuerpo_plano = f"{texto}\n\nEnlace: {enlace_url}"
    msg.set_content(cuerpo_plano)

    # Luego agregamos la versión HTML con la etiqueta <a> para que el link sea clickeable
    cuerpo_html = f"""
    <html>
        <body>
            <p>{texto}</p>
            <p>
                <a href="{enlace_url}" style="padding: 10px 15px; background-color: #007bff; color: white; text-decoration: none; border-radius: 5px;">
                    Haz clic aquí
                </a>
            </p>
            <br>
            <p><small>Si el botón no funciona, copia y pega este enlace en tu navegador: {enlace_url}</small></p>
        </body>
    </html>
    """
    msg.add_alternative(cuerpo_html, subtype='html')

    # 4. Enviar usando el puerto 587 y starttls() que ya comprobaste que funciona
    try:
        # Usamos 'with' para que la conexión se cierre automáticamente al terminar
        with smtplib.SMTP("smtp.gmail.com", 587) as servidor:
            servidor.starttls()
            servidor.login(remitente, password)
            servidor.send_message(msg)
        print("Correo enviado con éxito")
    except Exception as e:
        print(f"Error al enviar: {e}")

def _quiere_notif(db, uid, campo):
    """Preferencias de notificaciones (perfil.html, sheet 'Notificaciones')
    -- usuarios/{uid}.notificaciones.{campo}, campo en "matches"/"mensajes"/
    "gemelo"/"novedades". El evento real (match, mensaje, etc.) se crea
    siempre; esto solo decide si se le avisa a esta persona en particular.
    Ante cualquier duda (error de lectura, nunca guardó preferencias) se
    avisa igual -- los toggles nacen todos tildados en el sheet."""
    try:
        data = db.collection("usuarios").document(uid).get().to_dict() or {}
        valor = (data.get("notificaciones") or {}).get(campo)
        return valor is not False
    except Exception as e:
        print(f"_quiere_notif: error leyendo preferencia de {uid}: {e}")
        return True


def _con_privacidad(db, uid, perfil):
    """Agrega las preferencias de 'Privacidad' (perfil.html -- qué campos
    del perfil real, no del gemelo, dejó visibles) al perfil que arma el
    prompt del gemelo, como perfil["_privacidad"]. Es lo único que le
    permite a generar_prompt_gemelo saber qué NO tiene que revelar en una
    conversación aunque se lo pregunten directamente (género, orientación).
    No se persiste -- se recalcula cada vez que se arma un prompt."""
    if perfil is None:
        return perfil
    try:
        datos = db.collection("usuarios").document(uid).get().to_dict() or {}
        perfil["_privacidad"] = datos.get("privacidad") or {}
    except Exception as e:
        print(f"_con_privacidad: error leyendo privacidad de {uid}: {e}")
        perfil["_privacidad"] = {}
    return perfil


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
        return _con_privacidad(db, uid, snap.to_dict())

    doc_setup = db.collection("usuarios").document(uid).collection("gemelo_setup").document("data").get()
    if not doc_setup.exists or not doc_setup.to_dict().get("completed"):
        return None

    perfil = construir_perfil_gemelo(doc_setup.to_dict())
    ref.set(perfil)
    return _con_privacidad(db, uid, perfil)


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
    # OJO: snapshot.get("completed") (a diferencia de dict.get) tira KeyError
    # si el campo todavía no existe -- y no existe en ningún autoguardado
    # antes de terminar el onboarding, así que este trigger explotaba en cada
    # merge intermedio. Por eso se usa to_dict().get(), que sí devuelve None.
    if despues is None or not despues.exists or not despues.to_dict().get("completed"):
        return

    antes = event.data.before
    # antes es None (no un snapshot con exists=False) cuando este es el
    # primer write de todos sobre este doc -- pasa siempre en el onboarding
    # de un usuario nuevo, así que hay que contemplarlo.
    if antes is not None and antes.exists and antes.to_dict().get("completed"):
        return  # ya se había generado, no lo repetimos en cada merge posterior

    uid = event.params["uid"]
    respuestas_raw = despues.to_dict()
    perfil = construir_perfil_gemelo(respuestas_raw)

    db = firestore.client()
    db.collection("usuarios").document(uid).collection("gemelo").document("perfil").set(perfil)


@firestore_fn.on_document_written(document="conexiones/{parId}")
def notificar_mensaje_nuevo(event: firestore_fn.Event) -> None:
    """Se dispara en cada escritura de conexiones/{parId} (el doc de chat
    compartido por las dos cuentas -- ver chats.html _db_agregarMensajeReal).
    Solo actúa cuando real.msgs creció, para no generar notificaciones por
    escrituras no relacionadas a un mensaje real (marcarLeido, el chat con
    el gemelo, o el registro de una simulación tocan el mismo doc)."""
    despues = event.data.after
    if despues is None or not despues.exists:
        return
    despues_dict = despues.to_dict()
    msgs_despues = (despues_dict.get("real") or {}).get("msgs") or []

    antes = event.data.before
    msgs_antes = []
    if antes is not None and antes.exists:
        msgs_antes = (antes.to_dict().get("real") or {}).get("msgs") or []

    if len(msgs_despues) <= len(msgs_antes):
        return  # no se agregó ningún mensaje real nuevo

    uid1 = (despues_dict.get("usuario_1") or {}).get("uid")
    uid2 = (despues_dict.get("usuario_2") or {}).get("uid")
    nombre1 = (despues_dict.get("usuario_1") or {}).get("nombre") or "Usuario"
    nombre2 = (despues_dict.get("usuario_2") or {}).get("nombre") or "Usuario"
 
    if not uid1 or not uid2:
        return

    db = firestore.client()
    for msg in msgs_despues[len(msgs_antes):]:
        remitente = msg.get("from") if isinstance(msg, dict) else None
        if remitente not in (uid1, uid2):
            continue  # mensaje mal formado, no debería pasar
        destinatario = uid2 if remitente == uid1 else uid1
        nombre_remitente = nombre1 if remitente == uid1 else nombre2
        # 1. Obtener los documentos
        doc1_snap = db.collection("usuarios").document(uid1).get()
        doc2_snap = db.collection("usuarios").document(uid2).get()

        # 2. Extraer el diccionario de forma segura
        dict1 = doc1_snap.to_dict() if doc1_snap.exists else {}
        dict2 = doc2_snap.to_dict() if doc2_snap.exists else {}

        # 3. Obtener el string del correo (probando 'email' o 'correo' por si acaso)
        correo1 = dict1.get("email") or dict1.get("correo")
        correo2 = dict2.get("email") or dict2.get("correo")
        correo_destinatario = correo2 if remitente == uid1 else correo1
        if not _quiere_notif(db, destinatario, "mensajes"):
            continue
        texto = (msg.get("text") or "").strip()
        preview = texto if len(texto) <= 80 else texto[:77] + "..."
        _crear_notificacion(
            db, destinatario, "mensaje", f"Nuevo mensaje de {nombre_remitente}",
            preview or "Te escribió en Pebble.",
            otro_uid=remitente, otro_nombre=nombre_remitente, accion="chats",
        )
        if correo_destinatario:
            # Generamos el enlace para que el botón lo lleve directo al chat con esta persona
            enlace_chat = generar_enlace_app(accion="chats", otro_uid=remitente)
            
            titulo_mail = f"Tienes un nuevo mensaje de {nombre_remitente}"
            cuerpo_mail = f"{nombre_remitente} te escribió:\n\n\"{preview}\"\n\nEntra a Pebble para responderle."
            
            _mandar_correo(
                correo=correo_destinatario, 
                titulo=titulo_mail, 
                texto=cuerpo_mail, 
                enlace_url=enlace_chat
            )


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
    if not doc_setup.exists or not doc_setup.to_dict().get("completed"):
        raise https_fn.HttpsError(
            https_fn.FunctionsErrorCode.FAILED_PRECONDITION,
            "Todavía no completaste el onboarding de tu gemelo."
        )

    perfil_ref = db.collection("usuarios").document(uid).collection("gemelo").document("perfil")

    # construir_perfil_gemelo recalcula TODO desde gemelo_setup/data -- para
    # personalidad/valores eso es lo correcto (si cambiaste una respuesta,
    # tu gemelo tiene que reflejarlo). Pero "intereses"/"intereses_onboarding"
    # también se venían pisando por completo con la lista angosta que se
    # arma sola a partir de 5-6 campos puntuales (artista, género musical,
    # serie, deporte, equipo, estética) -- así que cualquier interés que se
    # hubiera agregado después (eligiéndolo a mano en perfil.html, o
    # aprendido de chats reales vía actualizar_aprendizaje_gemelo) se
    # perdía apenas se volvía a tocar CUALQUIER respuesta del onboarding,
    # aunque no tuviera nada que ver con intereses. Se combina la lista
    # nueva (recalculada, capta un cambio real como "cambié mi serie
    # favorita") con la ya guardada (preserva lo aprendido/elegido a mano)
    # en vez de que una pise a la otra.
    # Merge en vez de pisar: "intereses_slots" guarda SOLO lo que sale de
    # las 6 respuestas puntuales (artista/género musical/serie/deporte/
    # equipo/estética) la vez anterior que se generó el perfil. Restando
    # eso del "intereses" completo de esa vez, queda el resto -- lo
    # agregado a mano en perfil.html o aprendido de chats reales -- que
    # SIEMPRE se preserva. Los slots nuevos (recalculados ahora) reemplazan
    # a los viejos automáticamente: si cambiaste tu serie favorita, la
    # vieja no queda dando vueltas para siempre, la nueva ocupa su lugar.
    datos_anteriores = perfil_ref.get().to_dict() or {}
    intereses_previos = datos_anteriores.get("intereses") or []
    slots_previos = {str(s).strip().casefold() for s in (datos_anteriores.get("intereses_slots") or [])}
    extras = [i for i in intereses_previos if str(i).strip().casefold() not in slots_previos]

    perfil = construir_perfil_gemelo(doc_setup.to_dict())

    vistos, combinados = set(), []
    for i in (perfil.get("intereses_slots") or []) + extras:
        i = str(i).strip()
        if i and i.casefold() not in vistos:
            vistos.add(i.casefold())
            combinados.append(i)
    combinados = combinados[:20]
    perfil["intereses"] = combinados
    perfil["intereses_onboarding"] = combinados
    # "intereses_slots" queda tal cual lo devolvió construir_perfil_gemelo
    # (los slots NUEVOS) -- es la referencia para la PRÓXIMA regeneración.

    perfil_ref.set(perfil)

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

    # generar_resumen_gemelo usa temperature=1.0 a propósito (para que el
    # resumen de dos personas distintas no suene siempre igual de
    # "plantilla") -- pero eso mismo hacía que, si volvías a "Editar gemelo"
    # SIN cambiar ninguna respuesta, salía un texto distinto cada vez, lo
    # cual se siente como un bug aunque no lo sea. En vez de bajar la
    # temperatura (eso sí volvería a todos los resúmenes más parecidos entre
    # sí), se guarda un hash de los datos que realmente alimentan el prompt
    # -- si no cambiaron desde la última vez, se reusa el mismo texto ya
    # generado en vez de volver a llamar a OpenAI (ahorra la llamada Y
    # garantiza el mismo resultado).
    datos_para_hash = {k: v for k, v in perfil.items() if k != "bio"}
    hash_actual = hashlib.sha256(
        json.dumps(datos_para_hash, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    ).hexdigest()

    datos_setup = doc_setup.to_dict()
    if datos_setup.get("resumen_ia_hash") == hash_actual and datos_setup.get("resumen_ia_texto"):
        return {"texto": datos_setup["resumen_ia_texto"]}

    try:
        texto = motor.generar_resumen_gemelo(perfil)
    except Exception as e:
        print(f"generar_resumen_gemelo_ia: error llamando a OpenAI: {e}")
        raise https_fn.HttpsError(
            https_fn.FunctionsErrorCode.UNAVAILABLE,
            "No se pudo generar el resumen en este momento. Probá de nuevo en un rato."
        )

    doc_setup.reference.set(
        {"resumen_ia_hash": hash_actual, "resumen_ia_texto": texto}, merge=True
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
      - ciudad (opcional)
      - intereses (opcional)
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
    GENEROS_VALIDOS = {"Mujer", "Hombre", "No binario", "Otro"}
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

    if "ciudad" in data:
        valor = (data.get("ciudad") or "").strip()[:60]
        if valor:
            cambios["ciudad"] = valor

    # El picker de intereses de perfil.html (usuarios/{uid}.intereses) vivía
    # totalmente desconectado del "intereses_onboarding" congelado que
    # calcular_compatibilidad y las simulaciones usan de verdad -- ese
    # campo se armaba solo, a partir de 5-6 respuestas puntuales del
    # onboarding (artista, género musical, serie, deporte, equipo,
    # estética), así que elegir un interés nuevo acá (ej: Pilates, Stand
    # up) nunca llegaba a afectar el % de compatibilidad ni las charlas
    # simuladas. Se actualizan los dos ("intereses" e "intereses_onboarding")
    # a lo mismo que la persona eligió a mano en su perfil -- a diferencia
    # de personalidad/valores (que si se dejaran editar libremente
    # permitirían "inflar" el match), elegir tus propios intereses reales
    # no tiene ese riesgo: es la persona reportando de sí misma, no su
    # gemelo aprendiendo algo de un chat.
    if "intereses" in data:
        crudos = data.get("intereses")
        if isinstance(crudos, list):
            vistos, limpio = set(), []
            for i in crudos:
                i = str(i).strip()[:40]
                if i and i.casefold() not in vistos:
                    vistos.add(i.casefold())
                    limpio.append(i)
                if len(limpio) >= 15:
                    break
            cambios["intereses"] = limpio
            cambios["intereses_onboarding"] = limpio

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


@https_fn.on_call(secrets=["OPENAI_API_KEY"], timeout_sec=540, memory=MemoryOption.MB_512)
def simular_situacion(request: https_fn.CallableRequest):
    """Se llama desde el chat con el propio gemelo (gemelo.html): el usuario
    le pide a SU gemelo que simule una situación con el gemelo de otra persona
    (un match). No es un chat en vivo entre los dos gemelos -- la simulación
    corre acá atrás y se guarda; lo que el usuario ve en su chat es el resumen.

    Datos esperados en request.data:
      - otroUid (obligatorio): uid de la otra persona (el match)
      - situacion (opcional): texto libre de la situación pedida por el
        usuario. Si no viene, corre la charla libre de motor.escenarios_db
        (hoy un solo escenario genérico -- "Conociéndose" -- sin tema
        impuesto, para que la compatibilidad real se note sola en cómo
        fluye la charla, en vez de dividir todo en escenarios de tema fijo).
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
    # directo con cualquier uid. Por eso se exige un match confirmado
    # (conexiones/{par_id} con supera_umbral=true) en vez de solo repetir
    # los filtros de género/edad/hijos: ese documento no existe salvo que
    # buscar_parejas_pendientes ya haya filtrado por esos criterios Y
    # procesar_parejas_pendientes ya haya calculado compatibilidad por encima del umbral
    # con las respuestas del onboarding -- sin esto, cualquiera podría
    # gastar en OpenAI simulando con alguien con quien ni siquiera hay match.
    par_doc = db.collection("conexiones").document(motor._par_id(uid1, uid2)).get()
    if not par_doc.exists or not par_doc.to_dict().get("supera_umbral"):
        raise https_fn.HttpsError(
            https_fn.FunctionsErrorCode.FAILED_PRECONDITION,
            "Todavía no sos match con esa persona."
        )

    if situacion:
        escenario = motor.armar_escenario_personalizado(situacion)
        turnos_escenario = 5
    else:
        escenario = random.randrange(len(motor.escenarios_db))
        # Ver "turnos" opcional en motor.escenarios_db -- la charla libre
        # de hoy necesita bastante más lugar que un escenario de tema único.
        turnos_escenario = motor.escenarios_db[escenario].get("turnos", 5)

    try:
        registro = motor.simular_y_registrar(uid1, perfil1, uid2, perfil2, turnos=turnos_escenario, escenario=escenario)
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

    # El score de ESTA simulación puntual (registro["score"]) no se muestra
    # solo -- se promedia con el resto de simulaciones ya corridas para este
    # par (la del match original incluida), para que ultimo_score refleje
    # la compatibilidad general y no salte de una situación puntual a la
    # otra. Ver _score_promedio_simulaciones.
    score_promedio = _score_promedio_simulaciones(
        par_ref, score_nuevo=registro["score"]["compatibilidad_total"]
    )

    payload = {
        "usuario_1": registro["usuario_1"],
        "usuario_2": registro["usuario_2"],
        "participantes": [uid1, uid2],
        "ultimo_score": score_promedio,
        "supera_umbral": score_promedio >= motor.UMBRAL_MATCH,
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
def dar_consejo_match(request: https_fn.CallableRequest):
    """"Dame un consejo para hablar con X" (picker de gemelo.html) -- antes
    disparaba simular_situacion entera (una conversación completa simulada,
    varios minutos) solo para devolver un resumen. Esto es lo que
    específicamente se pidió: consejo directo y concreto, UN solo llamado a
    OpenAI, sin actuar ninguna charla. simular_situacion sigue existiendo
    tal cual para cuando alguien pide de verdad "simulá tal situación"."""

    if request.auth is None:
        raise https_fn.HttpsError(
            https_fn.FunctionsErrorCode.UNAUTHENTICATED,
            "Hay que estar logueado para pedir un consejo."
        )

    uid1 = request.auth.uid
    data = request.data or {}
    uid2 = (data.get("otroUid") or "").strip()

    if not uid2:
        raise https_fn.HttpsError(
            https_fn.FunctionsErrorCode.INVALID_ARGUMENT,
            "Falta indicar sobre quién (otroUid)."
        )
    if uid2 == uid1:
        raise https_fn.HttpsError(
            https_fn.FunctionsErrorCode.INVALID_ARGUMENT,
            "No podés pedir consejo sobre vos mismo/a."
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

    # Mismo chequeo que simular_situacion -- exigir un match confirmado en
    # vez de solo repetir los filtros de género/edad/hijos, ver el comentario
    # de ahí para el motivo completo.
    par_id = motor._par_id(uid1, uid2)
    par_doc = db.collection("conexiones").document(par_id).get()
    if not par_doc.exists or not par_doc.to_dict().get("supera_umbral"):
        raise https_fn.HttpsError(
            https_fn.FunctionsErrorCode.FAILED_PRECONDITION,
            "Todavía no sos match con esa persona."
        )

    # Las diferencias reales de personalidad ya se calcularon y guardaron
    # cuando se procesó este match (procesar_parejas_pendientes) -- se
    # reusan acá en vez de recalcularlas, es el mismo dato que ya se
    # muestra en matches.html.
    diferencias = ((par_doc.to_dict().get("diferencias_personalidad") or {}).get(uid1)) or []

    perfil2_priv = _con_privacidad(db, uid2, perfil2)
    nombre2 = perfil2.get("nombre") or "esa persona"

    try:
        consejo = motor.generar_consejo_match(perfil1, perfil2_priv, nombre2, diferencias)
    except Exception as e:
        print(f"dar_consejo_match: error generando el consejo: {e}")
        raise https_fn.HttpsError(
            https_fn.FunctionsErrorCode.UNAVAILABLE,
            "No se pudo generar el consejo en este momento. Probá de nuevo en un rato."
        )

    return {"consejo": consejo, "nombre": nombre2}


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
        los últimos 20 acá mismo por las dudas (antes eran 8: una corrección
        del tipo "dejá de decir X" se salía de ese límite después de un par
        de idas y vueltas más, y el gemelo "se olvidaba" de respetarla
        dentro de la MISMA conversación, no por no aprender sino porque
        directamente ya no la tenía en el contexto que se le mandaba).
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
    # no hace falta el perfil completo de cada uno acá. También se cuentan
    # las simulaciones que corrieron pero no llegaron al umbral de match
    # (mismo dato que ya usa el cartel "Tu gemelo está activo" de home.html)
    # -- si no se le pasa esto, el gemelo respondía "no corriste ninguna
    # simulación" aunque sí hubieran corrido, solo que ninguna dio match.
    matches_resumen = []
    total_simulaciones = 0
    mejor_score_sin_match = 0
    try:
        for doc in db.collection("conexiones").where("participantes", "array_contains", uid).stream():
            cd = doc.to_dict()
            total_simulaciones += 1
            if not cd.get("supera_umbral"):
                mejor_score_sin_match = max(mejor_score_sin_match, cd.get("ultimo_score") or 0)
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

    system_prompt = motor.generar_prompt_gemelo_personal(
        perfil, matches_resumen, total_simulaciones, round(mejor_score_sin_match * 100)
    )

    mensajes = [{"role": "system", "content": system_prompt}]
    for h in historial[-20:]:
        if not isinstance(h, dict):
            continue
        role = h.get("role")
        content = (h.get("content") or "").strip()[:2000]
        if role in ("user", "assistant") and content:
            mensajes.append({"role": role, "content": content})
    mensajes.append({"role": "user", "content": mensaje})

    try:
        response = motor._completar_chat_gemelo(mensajes)
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


@https_fn.on_call(secrets=["OPENAI_API_KEY"], timeout_sec=60, memory=MemoryOption.MB_512)
def chatear_con_gemelo_match(request: https_fn.CallableRequest):
    """Chat en vivo con el gemelo de UN MATCH real (chats.html, pestaña
    "gemelo" del panel de conversación) -- a diferencia de
    chatear_con_gemelo (que habla con TU PROPIO gemelo), acá el que responde
    es el gemelo de LA OTRA PERSONA, con su personalidad real, como si
    estuvieran charlando en vivo. Reemplaza el autoReply() enlatado que
    había antes (respuestas fijas con nombres de demo hardcodeados) por una
    respuesta real de OpenAI, usando el mismo generar_prompt_gemelo que ya
    arma las simulaciones automáticas entre dos gemelos.

    Datos esperados en request.data:
      - otroUid (obligatorio): uid del match cuyo gemelo va a responder.
      - mensaje (obligatorio): lo que escribió el usuario.
      - historial (opcional): últimos mensajes, en formato
        [{"role":"user"|"assistant","content":str}, ...].
    """

    if request.auth is None:
        raise https_fn.HttpsError(
            https_fn.FunctionsErrorCode.UNAUTHENTICATED,
            "Hay que estar logueado."
        )

    uid = request.auth.uid
    data = request.data or {}
    otro_uid = (data.get("otroUid") or "").strip()
    mensaje = (data.get("mensaje") or "").strip()
    historial = data.get("historial") or []

    if not otro_uid:
        raise https_fn.HttpsError(
            https_fn.FunctionsErrorCode.INVALID_ARGUMENT,
            "Falta indicar de quién es el gemelo (otroUid)."
        )
    if otro_uid == uid:
        raise https_fn.HttpsError(
            https_fn.FunctionsErrorCode.INVALID_ARGUMENT,
            "Para hablar con tu propio gemelo usá el chat de gemelo.html, no este."
        )
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

    # Solo se puede chatear con el gemelo de alguien con quien ya sos match
    # real (supera_umbral) -- sin este chequeo, cualquiera podría usar este
    # endpoint para sondear el gemelo de cualquier otro usuario adivinando
    # su uid, sin haber pasado nunca por el matching real.
    par_doc = db.collection("conexiones").document(motor._par_id(uid, otro_uid)).get()
    if not par_doc.exists or not par_doc.to_dict().get("supera_umbral"):
        raise https_fn.HttpsError(
            https_fn.FunctionsErrorCode.FAILED_PRECONDITION,
            "Todavía no sos match con esa persona."
        )

    perfil_otro = _obtener_o_generar_perfil(db, otro_uid)
    if perfil_otro is None:
        raise https_fn.HttpsError(
            https_fn.FunctionsErrorCode.NOT_FOUND,
            "Esa persona todavía no tiene su gemelo generado."
        )

    # Nombre real de quien está chateando -- sin esto, el gemelo de otro_uid
    # no tiene forma de saber cómo se llama la persona real que le está
    # escribiendo (ver nombre_otro en generar_prompt_gemelo).
    perfil_propio = _obtener_o_generar_perfil(db, uid)
    nombre_propio = (perfil_propio or {}).get("apodo") or (perfil_propio or {}).get("nombre")

    system_prompt = motor.generar_prompt_gemelo(
        perfil_otro, nombre_otro=nombre_propio,
        genero_otro=motor._genero_visible(perfil_propio) if perfil_propio else None,
    )
    if perfil_propio is not None:
        # Mismo criterio que las simulaciones automáticas: que la charla en
        # vivo también refleje qué tan compatibles son de verdad, no solo
        # que ya pasaron el umbral para ser match -- un 51% no debería
        # sentirse como un 95%.
        system_prompt += instruccion_nivel_compatibilidad(
            perfil_propio, perfil_otro, motor.UMBRAL_MATCH,
            nombre1=nombre_propio, nombre2=perfil_otro.get("nombre", "la otra persona"),
        )

    mensajes = [{"role": "system", "content": system_prompt}]
    for h in historial[-20:]:
        if not isinstance(h, dict):
            continue
        role = h.get("role")
        content = (h.get("content") or "").strip()[:2000]
        if role in ("user", "assistant") and content:
            mensajes.append({"role": role, "content": content})
    mensajes.append({"role": "user", "content": mensaje})

    try:
        response = motor._completar_chat_gemelo(mensajes)
    except Exception as e:
        print(f"chatear_con_gemelo_match: error llamando a OpenAI: {e}")
        raise https_fn.HttpsError(
            https_fn.FunctionsErrorCode.UNAVAILABLE,
            "El gemelo no pudo responder en este momento. Probá de nuevo en un rato."
        )

    # generar_prompt_gemelo (motor.py) le permite al modelo partir su turno
    # en varios mensajitos cortos separados con motor._MARCA_MULTIMENSAJE --
    # antes acá se reemplazaba esa marca por un salto de línea doble y se
    # devolvía un solo string, así que en vez de aparecer como burbujas de
    # chat separadas (como sí pasa en simular_cita), se veía como un salto
    # de línea raro en el medio de una sola burbuja. Ahora se parte de
    # verdad con _dividir_mensajes y se devuelve la lista -- el frontend
    # (chats.html) tiene que agregar cada parte como un mensaje separado.
    partes = motor._dividir_mensajes(response.choices[0].message.content)
    return {"partes": partes}


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

# Pool de candidatas de donde se arma cada lote nocturno -- más grande que
# LOTE_NOCTURNO a propósito, para poder ELEGIR entre varias en vez de
# quedarse con las 10 primeras por cercanía sin más criterio. Es una lectura
# barata (Firestore, no OpenAI), así que no pesa en el costo real de la
# corrida -- lo caro sigue limitado por LOTE_NOCTURNO.
POOL_CANDIDATAS_NOCTURNO = 300


@scheduler_fn.on_schedule(schedule="every 60 minutes", timezone="America/Argentina/Buenos_Aires")
def buscar_parejas_pendientes(event: scheduler_fn.ScheduledEvent) -> None:
    """Fase 1 (rápida, sin llamar a OpenAI): recorre todos los usuarios con
    gemelo generado, arma las parejas que todavía no se evaluaron ni están
    en cola, y las deja en 'parejas_pendientes' con estado PENDIENTE. La
    fase 2 (procesar_parejas_pendientes) es la que corre las simulaciones
    de verdad, de a lotes, para no pasarse del timeout de la función.

    Filtro acá es superficial (mismo "busco") a propósito -- es solo para no
    generar simulaciones inútiles entre gente que busca cosas incompatibles;
    el filtro real de compatibilidad lo hace la simulación en sí.

    "busco" ya no se pregunta en el onboarding (ver gemelo-setup.html), así
    que la gran mayoría de los perfiles tienen ese campo vacío -- solo queda
    seteado si alguien lo editó a mano desde perfil.html. Comparar "" contra
    cualquier valor real (o dos valores reales distintos) descartaba casi
    todos los pares por un campo que ni siquiera se le pregunta a nadie hoy.
    Mismo criterio que compatible_por_genero/edad/hijos: sin dato de alguno
    de los dos lados, no se puede evaluar esa mitad -- se deja pasar."""

    db = firestore.client()

    # Cuentas pausadas (Privacidad avanzada > Pausar mi cuenta) no entran a
    # buscar pareja nueva -- ni como origen ni como candidato para nadie más.
    pausados = {
        doc.id
        for doc in db.collection("usuarios").where("privacidadAvanzada.pausada", "==", True).stream()
    }

    usuarios = []
    for doc in db.collection_group("gemelo").stream():
        if doc.id != "perfil":
            continue
        uid = doc.reference.parent.parent.id
        if uid in pausados:
            continue
        usuarios.append((uid, doc.to_dict()))

    nuevas = 0
    # Diagnóstico: por qué un par NO se encola, sin loguear ningún dato
    # personal (solo conteos) -- para poder ver de un vistazo en los logs si
    # "0 parejas nuevas" es porque hay un solo gemelo generado, o porque hay
    # varios pero ninguno pasa alguno de los filtros.
    descartes = {
        "busco_distinto": 0,
        "genero_incompatible": 0,
        "edad_incompatible": 0,
        "hijos_incompatible": 0,
        "ya_en_cola_o_conectados": 0,
    }

    for i in range(len(usuarios)):
        uid1, perfil1 = usuarios[i]
        for j in range(i + 1, len(usuarios)):
            uid2, perfil2 = usuarios[j]

            busco1 = (perfil1.get("busco") or "").strip()
            busco2 = (perfil2.get("busco") or "").strip()
            if busco1 and busco2 and busco1 != busco2:
                descartes["busco_distinto"] += 1
                continue

            if not compatible_por_genero(perfil1, perfil2):
                descartes["genero_incompatible"] += 1
                continue

            if not compatible_por_edad(perfil1, perfil2):
                descartes["edad_incompatible"] += 1
                continue

            if not compatible_por_hijos(perfil1, perfil2):
                descartes["hijos_incompatible"] += 1
                continue

            par_id = motor._par_id(uid1, uid2)

            if db.collection("parejas_pendientes").document(par_id).get().exists:
                descartes["ya_en_cola_o_conectados"] += 1
                continue
            if db.collection("conexiones").document(par_id).get().exists:
                descartes["ya_en_cola_o_conectados"] += 1
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

    print(
        f"buscar_parejas_pendientes: {nuevas} parejas nuevas encoladas "
        f"(de {len(usuarios)} gemelos generados en total). Descartes: {descartes}"
    )


def _elegir_lote_diverso(pool, tamano_lote):
    """De una lista de docs de 'parejas_pendientes' (ya ordenada por
    cercanía), arma un lote de hasta tamano_lote pares maximizando cuántas
    cuentas DISTINTAS toca -- en vez de tomar directo las primeras
    tamano_lote por cercanía, que podían ser todas de la misma cuenta con
    muchos pares pendientes cerca suyo.

    3 pasadas sobre el pool (greedy, respetando el orden por cercanía
    dentro de cada pasada):
    1. Pares donde NINGUNO de los dos ya entró en el lote.
    2. Pares donde como máximo UNO de los dos ya entró (repite una cuenta,
       no dos).
    3. Cualquiera que quede, sin restricción -- para SIEMPRE llenar el
       lote completo si hay pares disponibles, aunque eso implique repetir
       cuentas."""
    seleccionados = []
    usados = set()
    ids_elegidos = set()

    for max_repetidos in (0, 1, None):
        if len(seleccionados) >= tamano_lote:
            break
        for doc in pool:
            if len(seleccionados) >= tamano_lote:
                break
            if doc.id in ids_elegidos:
                continue
            data = doc.to_dict()
            uid1 = data["usuario_1"]["uid"]
            uid2 = data["usuario_2"]["uid"]
            repetidos = (uid1 in usados) + (uid2 in usados)
            if max_repetidos is not None and repetidos > max_repetidos:
                continue
            seleccionados.append(doc)
            ids_elegidos.add(doc.id)
            usados.add(uid1)
            usados.add(uid2)

    return seleccionados


@scheduler_fn.on_schedule(
    schedule="0 3 * * *",
    timezone="America/Argentina/Buenos_Aires",
    secrets=["OPENAI_API_KEY"],
    timeout_sec=1800,  # 30 min -- el máximo permitido para funciones programadas
    memory=MemoryOption.MB_512,
)
def procesar_parejas_pendientes(event: scheduler_fn.ScheduledEvent) -> None:
    _procesar_parejas_pendientes_logica()


def _procesar_parejas_pendientes_logica() -> None:
    """Fase 2 (arranque): toma un lote de 'parejas_pendientes' (las más
    cercanas geográficamente primero) y para cada una calcula compatibilidad
    SOLO con matemática del onboarding (gratis, sin OpenAI). Los pares que NO
    llegan al umbral se resuelven ACÁ MISMO, no hace falta gastar nada más.

    Los que SÍ llegan al umbral necesitan la simulación de charla real -- en
    vez de correrla en el momento (llamadas en vivo a OpenAI, una por turno),
    se arma el estado inicial de cada conversación y se manda como Batch API
    de OpenAI (~50% más barata que la API en vivo, ver motor.armar_estado_par_batch/
    armar_solicitud_batch). Por eso esta función YA NO deja el resultado final
    escrito para esos pares -- solo arma y dispara el primer batch ("ola 0") y
    termina; continuar_lote_batch_nocturno (corre cada 15 min) es quien va
    completando cada conversación ola por ola y guarda el resultado cuando
    cierra.

    La elección de CUÁLES pares entran en el lote de esta noche prioriza
    diversidad de cuentas (ver _elegir_lote_diverso): si hay más de
    LOTE_NOCTURNO cuentas con pares pendientes, el lote intenta no repetir
    ninguna cuenta dos veces -- así a más gente le llega alguna novedad por
    noche, en vez de que una cuenta con muchos pares pendientes se coma el
    lote entero. Cuando ya no alcanzan pares "frescos" para completar el
    lote, ahí sí se permite repetir cuentas, pero siempre se llena el lote
    completo (nunca se deja un lugar vacío pudiendo llenarlo)."""

    db = firestore.client()

    # Si ya hay un lote de batch en curso de una corrida anterior, no arranca
    # uno nuevo encima -- se espera a que continuar_lote_batch_nocturno lo
    # termine. Evita mandar dos Batch jobs pisándose (y perder el seguimiento
    # de uno de los dos).
    en_curso = list(
        db.collection("lotes_batch").where("estado", "in", ["armando", "esperando_batch"]).limit(1).stream()
    )
    if en_curso:
        print(f"procesar_parejas_pendientes: ya hay un lote de batch en curso ({en_curso[0].id}), no arranco uno nuevo -- espero a que termine.")
        return

    pool = list(
        db.collection("parejas_pendientes")
        .where("estado", "==", "PENDIENTE")
        .order_by("distancia_km")
        .limit(POOL_CANDIDATAS_NOCTURNO)
        .stream()
    )
    pendientes = _elegir_lote_diverso(pool, LOTE_NOCTURNO)

    resueltos_sin_match, con_error, descartados, encolados = 0, 0, 0, 0
    lote_id = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=-3))).strftime("%Y%m%d_%H%M%S")
    lote_ref = db.collection("lotes_batch").document(lote_id)
    solicitudes = []
    estados_por_par = {}

    for doc in pendientes:
        data = doc.to_dict()
        uid1 = data["usuario_1"]["uid"]
        uid2 = data["usuario_2"]["uid"]

        try:
            doc1 = db.collection("usuarios").document(uid1).collection("gemelo").document("perfil").get()
            doc2 = db.collection("usuarios").document(uid2).collection("gemelo").document("perfil").get()
            if not doc1.exists or not doc2.exists:
                raise ValueError("A alguno de los dos ya no le existe el perfil de gemelo.")

            # buscar_parejas_pendientes ya filtró por género/orientación,
            # edad e hijos al encolar el par -- pero eso fue en ese momento
            # puntual. Si alguno de los dos editó su onboarding (cambió
            # orientación, rango de edad que busca, o postura sobre hijos)
            # mientras el par seguía PENDIENTE, sin este re-chequeo se
            # procesaba igual con los filtros ya vencidos, y podía terminar
            # en un match que ya no correspondía según los datos actuales.
            perfil1_raw, perfil2_raw = doc1.to_dict(), doc2.to_dict()
            if not compatible_por_genero(perfil1_raw, perfil2_raw):
                doc.reference.update({"estado": "DESCARTADO", "motivo_descarte": "genero_incompatible"})
                descartados += 1
                continue
            if not compatible_por_edad(perfil1_raw, perfil2_raw):
                doc.reference.update({"estado": "DESCARTADO", "motivo_descarte": "edad_incompatible"})
                descartados += 1
                continue
            if not compatible_por_hijos(perfil1_raw, perfil2_raw):
                doc.reference.update({"estado": "DESCARTADO", "motivo_descarte": "hijos_incompatible"})
                descartados += 1
                continue

            perfil1_data = _con_privacidad(db, uid1, doc1.to_dict())
            perfil2_data = _con_privacidad(db, uid2, doc2.to_dict())

            # Compatibilidad matemática del onboarding, gratis (sin OpenAI) --
            # mismo cálculo que antes hacía simular_relacion_completa antes de
            # decidir si corría o no la simulación.
            promedio, s, pref_a_b, pref_b_a, score_conversacional, desglose = motor.calcular_compatibilidad(perfil1_data, perfil2_data)
            supera = promedio >= motor.UMBRAL_MATCH

            diferencias = {
                uid1: motor._diferencias_personalidad(
                    perfil2_data, perfil1_data, data["usuario_1"]["nombre"] or "Usuario", top_n=3, minimo=3
                ),
                uid2: motor._diferencias_personalidad(
                    perfil1_data, perfil2_data, data["usuario_2"]["nombre"] or "Usuario", top_n=3, minimo=3
                ),
            }

            if not supera:
                # No hace falta simulación -- se resuelve gratis, ahora mismo.
                par_ref = db.collection("conexiones").document(data["par_id"])
                payload = {
                    "usuario_1": data["usuario_1"],
                    "usuario_2": data["usuario_2"],
                    "participantes": [uid1, uid2],
                    "ultimo_score": round(promedio, 2),
                    "ultimo_sim": s,
                    "ultimo_pref_a_b": pref_a_b,
                    "ultimo_pref_b_a": pref_b_a,
                    "ultimo_conv": score_conversacional,
                    "desglose": {
                        "psicologico": desglose["psicologico"],
                        "valores": desglose["valores"],
                        "intereses": desglose["intereses"],
                        "creencias": desglose["creencias"],
                        "comunicacion": desglose["comunicacion"],
                    },
                    "diferencias_personalidad": diferencias,
                    "supera_umbral": False,
                    "distancia_km": data.get("distancia_km"),
                    "actualizado": firestore.SERVER_TIMESTAMP,
                }
                payload = _con_creado(par_ref, payload)
                par_ref.set(payload, merge=True)
                doc.reference.update({"estado": "COMPLETADO"})
                resueltos_sin_match += 1
                continue

            # Supera el umbral: hace falta la simulación real de charla --
            # se arma el estado inicial y se encola para la Batch API en vez
            # de correrla ahora mismo.
            estado_par = motor.armar_estado_par_batch(
                uid1, perfil1_data, uid2, perfil2_data,
                data["usuario_1"], data["usuario_2"], data.get("distancia_km"),
            )
            par_id = data["par_id"]
            estados_por_par[par_id] = estado_par
            solicitud = motor.armar_solicitud_batch(par_id, estado_par)
            if solicitud:
                solicitudes.append(solicitud)
            encolados += 1

        except Exception as e:
            # traceback completo, no solo str(e) -- un mensaje como
            # "unsupported operand type(s) for *: 'dict' and 'float'" no
            # dice en qué línea/función pasó, y sin eso hay que adivinar.
            doc.reference.update({"estado": "ERROR", "error": traceback.format_exc()})
            con_error += 1

    print(
        f"procesar_parejas_pendientes: {resueltos_sin_match} resueltos sin match (gratis), "
        f"{encolados} encolados para simulación por batch, {con_error} con error, "
        f"{descartados} descartados por cambio de datos."
    )

    if not solicitudes:
        return

    # Guarda el estado de cada pareja ANTES de mandar el batch -- así, si algo
    # falla mandando el batch, el trabajo de armar los prompts no se pierde.
    escritura = db.batch()
    for par_id, estado_par in estados_por_par.items():
        escritura.set(lote_ref.collection("pares").document(par_id), estado_par)
    escritura.commit()

    jsonl = "\n".join(json.dumps(s, ensure_ascii=False) for s in solicitudes).encode("utf-8")
    archivo = motor.client().files.create(file=("lote.jsonl", jsonl), purpose="batch")
    batch_job = motor.client().batches.create(
        input_file_id=archivo.id,
        endpoint="/v1/chat/completions",
        completion_window="24h",
        metadata={"lote_id": lote_id},
    )

    lote_ref.set({
        "estado": "esperando_batch",
        "ola": 0,
        "openai_batch_id": batch_job.id,
        "creado": firestore.SERVER_TIMESTAMP,
    })
    print(f"procesar_parejas_pendientes: lote {lote_id} mandado a Batch API ({batch_job.id}), {len(solicitudes)} pares en la ola 0.")


def _finalizar_par_de_batch(db, estado_par):
    """Cuando la charla de una pareja terminó (ver continuar_lote_batch_nocturno):
    recalcula el score final con la conversación completa y lo guarda en
    conexiones -- mismo resultado que antes dejaba la vía síncrona."""
    uid1, uid2 = estado_par["uid1"], estado_par["uid2"]
    doc1 = db.collection("usuarios").document(uid1).collection("gemelo").document("perfil").get()
    doc2 = db.collection("usuarios").document(uid2).collection("gemelo").document("perfil").get()
    if not doc1.exists or not doc2.exists:
        print(f"_finalizar_par_de_batch: ya no existe el perfil de {uid1} o {uid2}, se descarta el resultado.")
        return
    perfil1_data = _con_privacidad(db, uid1, doc1.to_dict())
    perfil2_data = _con_privacidad(db, uid2, doc2.to_dict())

    registro = motor.finalizar_par_batch(perfil1_data, perfil2_data, estado_par)

    par_id = motor._par_id(uid1, uid2)
    par_ref = db.collection("conexiones").document(par_id)
    payload = {
        "usuario_1": estado_par["usuario_1"],
        "usuario_2": estado_par["usuario_2"],
        "participantes": [uid1, uid2],
        "ultimo_score": registro["score"]["compatibilidad_total"],
        "ultimo_sim": registro["score"]["similitud"],
        "ultimo_pref_a_b": registro["score"]["pref_a_b"],
        "ultimo_pref_b_a": registro["score"]["pref_b_a"],
        "ultimo_conv": registro["score"]["score_conversacional"],
        "desglose": {
            "psicologico": registro["score"]["score_psicologico"],
            "valores": registro["score"]["score_valores"],
            "intereses": registro["score"]["score_intereses"],
            "creencias": registro["score"]["score_creencias"],
            "comunicacion": registro["score"]["score_comunicacion"],
        },
        "diferencias_personalidad": {
            uid1: motor._diferencias_personalidad(
                perfil2_data, perfil1_data, estado_par["usuario_1"]["nombre"] or "Usuario", top_n=3, minimo=3
            ),
            uid2: motor._diferencias_personalidad(
                perfil1_data, perfil2_data, estado_par["usuario_2"]["nombre"] or "Usuario", top_n=3, minimo=3
            ),
        },
        "supera_umbral": registro["supera_umbral"],
        "distancia_km": estado_par.get("distancia_km"),
        "actualizado": firestore.SERVER_TIMESTAMP,
    }
    payload = _con_creado(par_ref, payload)
    par_ref.set(payload, merge=True)
    par_ref.collection("simulaciones").add(registro)

    nombre1 = estado_par["usuario_1"]["nombre"] or "Usuario"
    nombre2 = estado_par["usuario_2"]["nombre"] or "Usuario"
    doc1_snap = db.collection("usuarios").document(uid1).get()
    doc2_snap = db.collection("usuarios").document(uid2).get()

    # 2. Extraer el diccionario de forma segura
    dict1 = doc1_snap.to_dict() if doc1_snap.exists else {}
    dict2 = doc2_snap.to_dict() if doc2_snap.exists else {}

    # 3. Obtener el string del correo (probando 'email' o 'correo' por si acaso)
    correo1 = dict1.get("email") 
    correo2 = dict2.get("email") 

    if registro["supera_umbral"]:
        pct = round(registro["score"]["compatibilidad_total"] * 100)
        
        # --- MATCH PARA USUARIO 1 ---
        if _quiere_notif(db, uid1, "matches"):
            # 1. Notificación In-App
            _crear_notificacion(
                db, uid1, "match", f"¡Nuevo match con {nombre2}!",
                f"Tu gemelo alcanzó {pct}% de afinidad con {nombre2}. Ya podés ver la conversación.",
                otro_uid=uid2, otro_nombre=nombre2, accion="matches",
            )
            # 2. Correo electrónico
            if correo1:
                enlace1 = generar_enlace_app(accion="matches", otro_uid=uid2)
                _mandar_correo(
                    correo=correo1,
                    titulo=f"¡Nuevo match con {nombre2}!",
                    texto=f"¡Buenas noticias! Tu gemelo virtual alcanzó un {pct}% de afinidad con {nombre2}. Ya podés ingresar a Pebble para ver la conversación.",
                    enlace_url=enlace1
                )

        # --- MATCH PARA USUARIO 2 ---
        if _quiere_notif(db, uid2, "matches"):
            # 1. Notificación In-App
            _crear_notificacion(
                db, uid2, "match", f"¡Nuevo match con {nombre1}!",
                f"Tu gemelo alcanzó {pct}% de afinidad con {nombre1}. Ya podés ver la conversación.",
                otro_uid=uid1, otro_nombre=nombre1, accion="matches",
            )
            # 2. Correo electrónico
            if correo2:
                enlace2 = generar_enlace_app(accion="matches", otro_uid=uid1)
                _mandar_correo(
                    correo=correo2,
                    titulo=f"¡Nuevo match con {nombre1}!",
                    texto=f"¡Buenas noticias! Tu gemelo virtual alcanzó un {pct}% de afinidad con {nombre1}. Ya podés ingresar a Pebble para ver la conversación.",
                    enlace_url=enlace2
                )

        # Intereses en común (solo genera notificación in-app para sugerir conversación)
        comunes = set((perfil1_data.get("intereses") or [])) & set((perfil2_data.get("intereses") or []))
        if comunes:
            interes = sorted(comunes)[0]
            if _quiere_notif(db, uid1, "matches"):
                _crear_notificacion(
                    db, uid1, "interes", f"Vos y {nombre2} tienen algo en común",
                    f"A los dos les gusta {interes}. Podría ser una buena forma de arrancar la conversación.",
                    otro_uid=uid2, otro_nombre=nombre2, accion="chats",
                )
                if correo1:
                    enlace1 = generar_enlace_app(accion="matches", otro_uid=uid2)
                    _mandar_correo(
                        correo=correo1,
                        titulo=f"Vos y {nombre2} tienen algo en común",
                        texto=f"A los dos les gusta {interes}. Podría ser una buena forma de arrancar la conversación.",
                        enlace_url=enlace1
                    )
            if _quiere_notif(db, uid2, "matches"):
                _crear_notificacion(
                    db, uid2, "interes", f"Vos y {nombre1} tienen algo en común",
                    f"A los dos les gusta {interes}. Podría ser una buena forma de arrancar la conversación.",
                    otro_uid=uid1, otro_nombre=nombre1, accion="chats",
                )
                if correo2:
                    enlace2 = generar_enlace_app(accion="matches", otro_uid=uid1)
                    _mandar_correo(
                        correo=correo2,
                        titulo=f"Vos y {nombre1} tienen algo en común",
                        texto=f"A los dos les gusta {interes}. Podría ser una buena forma de arrancar la conversación.",
                        enlace_url=enlace2
                    )
    db.collection("parejas_pendientes").document(par_id).update({"estado": "COMPLETADO"})


@scheduler_fn.on_schedule(
    schedule="every 2 minutes",
    timezone="America/Argentina/Buenos_Aires",
    secrets=["OPENAI_API_KEY"],
    timeout_sec=540,
    memory=MemoryOption.MB_512,
)
def continuar_lote_batch_nocturno(event: scheduler_fn.ScheduledEvent) -> None:
    _continuar_lote_batch_nocturno_logica()


def _continuar_lote_batch_nocturno_logica() -> None:
    """Fase 2 (continuación): revisa si el lote de Batch API en curso (ver
    procesar_parejas_pendientes) ya terminó. Si terminó, aplica la respuesta
    de cada pareja (una ola = un turno de charla), guarda a las que ya
    cerraron (_finalizar_par_de_batch), y si quedan pares activos manda la
    siguiente ola como un nuevo batch. Corre cada 15 min porque una
    conversación puede necesitar varias olas -- cuanto más rápido se detecta
    que un batch terminó, más rápido avanza la charla completa."""
    db = firestore.client()

    lotes = list(db.collection("lotes_batch").where("estado", "==", "esperando_batch").stream())
    if not lotes:
        return

    for lote_doc in lotes:
        lote_id = lote_doc.id

        # Traba de concurrencia: esta función corre cada 15 min, pero una
        # corrida puede tardar (esperar OpenAI, mandar el siguiente batch) --
        # si la siguiente corrida programada arranca antes de que la anterior
        # termine (o si se dispara una prueba manual mientras el scheduler
        # también corre), las dos procesarían el mismo lote a la vez y se
        # pisan (una pareja podía procesarse dos veces, o perderse una
        # escritura). @firestore.transactional hace el chequeo-y-marcado
        # atómico: solo UNA corrida puede "tomar" el lote. Si una corrida
        # anterior se cortó a mitad de camino (crash, timeout) y dejó la
        # traba puesta, se considera vencida después de 10 minutos y se
        # puede volver a tomar.
        @firestore.transactional
        def _tomar_lote(transaccion, ref=lote_doc.reference):
            snap = ref.get(transaction=transaccion)
            if not snap.exists:
                return None
            data = snap.to_dict()
            if data.get("estado") != "esperando_batch":
                return None
            procesando_desde = data.get("procesando_desde")
            if data.get("procesando") and procesando_desde:
                vencida = (
                    datetime.datetime.now(datetime.timezone.utc) - procesando_desde
                ) > datetime.timedelta(minutes=10)
                if not vencida:
                    return None
            transaccion.update(ref, {"procesando": True, "procesando_desde": firestore.SERVER_TIMESTAMP})
            return data

        lote = _tomar_lote(db.transaction())
        if lote is None:
            print(f"continuar_lote_batch_nocturno: lote {lote_id} ya lo está procesando otra corrida, se salta.")
            continue

        batch_id = lote.get("openai_batch_id")
        if not batch_id:
            lote_doc.reference.update({"procesando": False})
            continue

        try:
            batch_job = motor.client().batches.retrieve(batch_id)
        except Exception as e:
            print(f"continuar_lote_batch_nocturno: error consultando batch {batch_id} del lote {lote_id}: {e}")
            lote_doc.reference.update({"procesando": False})
            continue

        if batch_job.status in ("validating", "in_progress", "finalizing"):
            print(f"continuar_lote_batch_nocturno: lote {lote_id} todavía en curso ({batch_job.status}).")
            lote_doc.reference.update({"procesando": False})
            continue

        if batch_job.status in ("failed", "expired", "cancelled", "cancelling"):
            print(f"continuar_lote_batch_nocturno: lote {lote_id} terminó en estado {batch_job.status} -- se abandona, las parejas vuelven a PENDIENTE para la próxima corrida.")
            for par_doc in lote_doc.reference.collection("pares").stream():
                db.collection("parejas_pendientes").document(par_doc.id).update({"estado": "PENDIENTE"})
                par_doc.reference.delete()
            lote_doc.reference.update({"estado": "error", "procesando": False})
            continue

        # status == "completed"
        if not batch_job.output_file_id:
            lote_doc.reference.update({"estado": "error", "procesando": False})
            continue

        try:
            contenido = motor.client().files.content(batch_job.output_file_id).text
            respuestas_por_par = {}
            for linea in contenido.splitlines():
                if not linea.strip():
                    continue
                item = json.loads(linea)
                par_id = item.get("custom_id")
                body = (item.get("response") or {}).get("body") or {}
                choices = body.get("choices") or []
                respuestas_por_par[par_id] = choices[0]["message"]["content"] if choices else ""
        except Exception as e:
            # Si esto falla no hay forma de saber qué le tocaba a cada
            # pareja en esta ola -- se libera la traba y se reintenta en el
            # próximo tick (el batch_id ya está guardado, no se pierde nada).
            print(f"continuar_lote_batch_nocturno: error bajando/parseando el resultado del batch {batch_id} del lote {lote_id}: {e}")
            lote_doc.reference.update({"procesando": False})
            continue

        pares_ref = lote_doc.reference.collection("pares")
        siguientes_solicitudes = []

        for par_doc in pares_ref.stream():
            par_id = par_doc.id
            try:
                estado_par = par_doc.to_dict()
                contenido_msg = respuestas_por_par.get(par_id)

                if contenido_msg is None:
                    # No vino respuesta para este par en este batch (no
                    # debería pasar) -- se reintenta la misma fase en la
                    # próxima ola.
                    solicitud = motor.armar_solicitud_batch(par_id, estado_par)
                    if solicitud:
                        siguientes_solicitudes.append(solicitud)
                    continue

                if motor._parece_razonamiento_filtrado(contenido_msg):
                    # Reintento SÍNCRONO puntual (una sola llamada normal) en
                    # vez de gastar otra ola entera de batch solo por esta
                    # pareja.
                    print(f"continuar_lote_batch_nocturno: respuesta con pinta de razonamiento filtrado en {par_id}, reintento síncrono.")
                    solicitud = motor.armar_solicitud_batch(par_id, estado_par)
                    try:
                        resp = motor.client().chat.completions.create(**solicitud["body"])
                        contenido_msg = resp.choices[0].message.content
                    except Exception as e:
                        print(f"continuar_lote_batch_nocturno: reintento síncrono también falló para {par_id}: {e}")
                        contenido_msg = ""

                if not contenido_msg:
                    # Sin respuesta usable ni con el reintento -- se deja la
                    # pareja en la misma fase, se reintenta en la próxima ola
                    # en vez de perderla o guardar un mensaje vacío.
                    solicitud = motor.armar_solicitud_batch(par_id, estado_par)
                    if solicitud:
                        siguientes_solicitudes.append(solicitud)
                    continue

                estado_par = motor.aplicar_respuesta_batch(estado_par, contenido_msg)

                if estado_par["estado"] == "cerrado":
                    _finalizar_par_de_batch(db, estado_par)
                    par_doc.reference.delete()
                else:
                    par_doc.reference.set(estado_par)
                    solicitud = motor.armar_solicitud_batch(par_id, estado_par)
                    if solicitud:
                        siguientes_solicitudes.append(solicitud)

            except Exception as e:
                # Una pareja puntual no puede tirar abajo el resto de la ola
                # (ni dejar la traba de concurrencia pisada para siempre) --
                # se marca su parejas_pendientes como ERROR (mismo criterio
                # que ya usaba la vía síncrona) y se la saca del lote; el
                # resto de las parejas sigue procesándose normal.
                print(f"continuar_lote_batch_nocturno: error procesando {par_id} en el lote {lote_id}: {traceback.format_exc()}")
                db.collection("parejas_pendientes").document(par_id).update({
                    "estado": "ERROR", "error": traceback.format_exc(),
                })
                par_doc.reference.delete()

        if not siguientes_solicitudes:
            lote_doc.reference.update({"estado": "completo", "procesando": False})
            print(f"continuar_lote_batch_nocturno: lote {lote_id} completo, todas las parejas cerradas.")
            continue

        try:
            jsonl = "\n".join(json.dumps(s, ensure_ascii=False) for s in siguientes_solicitudes).encode("utf-8")
            archivo = motor.client().files.create(file=("ola.jsonl", jsonl), purpose="batch")
            nuevo_batch = motor.client().batches.create(
                input_file_id=archivo.id,
                endpoint="/v1/chat/completions",
                completion_window="24h",
                metadata={"lote_id": lote_id, "ola": str(lote.get("ola", 0) + 1)},
            )
        except Exception as e:
            # El estado de cada pareja activa ya quedó guardado arriba (antes
            # de este punto) -- si esto falla no se pierde nada, solo no se
            # manda la siguiente ola todavía. Se libera la traba para
            # reintentar en el próximo tick.
            print(f"continuar_lote_batch_nocturno: error mandando la siguiente ola del lote {lote_id}: {e}")
            lote_doc.reference.update({"procesando": False})
            continue

        nueva_ola = lote.get("ola", 0) + 1
        lote_doc.reference.update({"ola": nueva_ola, "openai_batch_id": nuevo_batch.id, "procesando": False})
        print(f"continuar_lote_batch_nocturno: lote {lote_id} pasa a la ola {nueva_ola} con {len(siguientes_solicitudes)} pares activos.")


@scheduler_fn.on_schedule(schedule="0 1 1 * *", timezone="America/Argentina/Buenos_Aires")
def resetear_no_compatibles_mensual(event: scheduler_fn.ScheduledEvent) -> None:
    """Corre una sola vez, el día 1 de cada mes calendario (no 30 días desde
    que se simuló cada par -- todos se revisan juntos el mismo día). Hoy,
    una vez que dos personas se simulan, buscar_parejas_pendientes nunca las
    vuelve a tocar (ve que ya existe conexiones/{par_id} y las descarta para
    siempre) -- bien para ahorrar en OpenAI, pero significa que alguien
    marcado "no compatible" se queda así para siempre aunque después edite
    su gemelo. Esto le da una segunda oportunidad mensual sin volver a
    simular todas las noches: borra la conexión (y su subcolección de
    simulaciones, para no dejar basura huérfana) y la entrada en
    parejas_pendientes de cada par SIN match, así vuelven a verse como
    "nunca evaluados" -- buscar_parejas_pendientes los va a re-encolar en su
    próxima corrida (cada hora) y procesar_parejas_pendientes los simula de
    nuevo esta misma noche (corre a la 1am, antes de las 3am). Los pares que
    SÍ hicieron match (supera_umbral == true) no se tocan -- ya desbloquearon
    una conexión real, no hace falta re-evaluarlos."""
    db = firestore.client()
    reseteados = 0
    for doc in db.collection("conexiones").where("supera_umbral", "==", False).stream():
        par_id = doc.id
        for sim_doc in doc.reference.collection("simulaciones").stream():
            sim_doc.reference.delete()
        doc.reference.delete()
        db.collection("parejas_pendientes").document(par_id).delete()
        reseteados += 1

    print(f"resetear_no_compatibles_mensual: {reseteados} pares no-compatibles reseteados para reevaluar este mes.")


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
        doc_user1=db.collection("usuarios").document(uid1).get()
        data_user1=doc_user1.to_dict()
        doc_user2=db.collection("usuarios").document(uid2).get()
        data_user2=doc_user2.to_dict()
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
                # "¿Retomás con X?" es un recordatorio sobre la conversación --
                # respeta la preferencia de Notificaciones > Mensajes nuevos.
                if _quiere_notif(db, uid1, "mensajes"):
                    _crear_notificacion(
                        db, uid1, "retomar", f"¿Retomás con {nombre2}?",
                        f"La conversación quedó abierta hace {dias_inactivo} días.",
                        otro_uid=uid2, otro_nombre=nombre2, accion="chats",
                    )
                    correo1 = data_user1.get("email")
                    if not correo1: # Fallback: buscar en el documento del usuario si no está en la conexión
                        doc1_snap = db.collection("usuarios").document(uid1).get()
                        dict1 = doc1_snap.to_dict() if doc1_snap.exists else {}
                        correo1 = dict1.get("email") or dict1.get("correo")
                        
                    if correo1:
                        enlace1 = generar_enlace_app(accion="chats", otro_uid=uid2)
                        _mandar_correo(
                            correo=correo1,
                            titulo=f"¿Retomás tu charla con {nombre2}?",
                            texto=f"Hola, tu conversación con {nombre2} quedó en pausa hace {dias_inactivo} días. ¡Entrá a Pebble y fíjate en qué andan!",
                            enlace_url=enlace1
                        )
                if _quiere_notif(db, uid2, "mensajes"):
                    _crear_notificacion(
                        db, uid2, "retomar", f"¿Retomás con {nombre1}?",
                        f"La conversación quedó abierta hace {dias_inactivo} días.",
                        otro_uid=uid1, otro_nombre=nombre1, accion="chats",
                    )
                    correo2 = data_user2.get("email")
                    if not correo2:
                        doc2_snap = db.collection("usuarios").document(uid2).get()
                        dict2 = doc2_snap.to_dict() if doc2_snap.exists else {}
                        correo2 = dict2.get("email") or dict2.get("correo")
                        
                    if correo2:
                        enlace2 = generar_enlace_app(accion="chats", otro_uid=uid1)
                        _mandar_correo(
                            correo=correo2,
                            titulo=f"¿Retomás tu charla con {nombre1}?",
                            texto=f"Hola, tu conversación con {nombre1} quedó en pausa hace {dias_inactivo} días. ¡Entrá a Pebble y fíjate en qué andan!",
                            enlace_url=enlace2
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
        datos_usuario = doc_usuario.to_dict() if doc_usuario.exists else {}
        recordado_en = doc_usuario.to_dict().get("recordatorioInactivoEn") if doc_usuario.exists else None
        if recordado_en and (ahora - recordado_en).days < DIAS_INACTIVIDAD_GEMELO:
            continue

        if _quiere_notif(db, uid, "gemelo"):
            _crear_notificacion(
                db, uid, "inactivo", f"Tu gemelo lleva {dias_inactivo} días sin interacciones",
                "Ajustar su personalidad o tus preferencias puede mejorar los resultados.",
                accion="gemelo",
            )
            correo_inactivo = datos_usuario.get("email") or datos_usuario.get("correo")
            if correo_inactivo:
                enlace_gemelo = generar_enlace_app(accion="gemelo")
                _mandar_correo(
                    correo=correo_inactivo,
                    titulo="Tu gemelo virtual necesita ajustes",
                    texto=f"Tu gemelo virtual lleva {dias_inactivo} días sin interacciones en Pebble. Ajustar su personalidad o actualizar tus preferencias puede ayudarte a mejorar los resultados y obtener nuevos matches.",
                    enlace_url=enlace_gemelo
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
                # En modo "real" el campo "from" tiene el uid real de quien
                # escribió (no el string "me" -- eso es solo la convención
                # del modo "gemelo") -- comparar contra "me" acá nunca
                # matcheaba nada, así que esto nunca aportaba mensajes reales.
                if isinstance(m, dict) and m.get("from") == uid and m.get("text"):
                    mensajes.append(m["text"])
    except Exception as e:
        print(f"_mensajes_propios_recientes: error leyendo conexiones de {uid}: {e}")

    return mensajes[-limite:]


def _mensajes_al_propio_gemelo(db, uid, limite=VENTANA_MENSAJES_APRENDIZAJE):
    """Igual que la primera parte de _mensajes_propios_recientes, pero SOLO
    el chat con el propio gemelo (gemelo.html) -- a propósito no mezcla los
    mensajes reales con matches acá, porque una corrección de comportamiento
    ("dejá de decir X") solo tiene sentido si se la dijo AL GEMELO, no a otra
    persona real en un chat de match."""

    mensajes = []
    try:
        snap = db.collection("usuarios").document(uid).collection("chats").document("gemelo_propio").get()
        if snap.exists:
            log = snap.to_dict().get("log") or []
            for entrada in log:
                if isinstance(entrada, dict) and entrada.get("tipo") == "user" and entrada.get("text"):
                    mensajes.append(entrada["text"])
    except Exception as e:
        print(f"_mensajes_al_propio_gemelo: error leyendo chat con el gemelo de {uid}: {e}")

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
            # Mensajes reales, copiados tal cual (nunca generados) -- sirven de
            # ancla concreta para que el gemelo no suene más ingenioso/rápido
            # de lo que esta persona es en la práctica (ver simulador.
            # generar_prompt_gemelo/generar_prompt_gemelo_personal). Un texto
            # descriptivo ("respuestas cortas y simples") es mucho más débil
            # como techo que mostrarle al modelo ejemplos reales concretos.
            if resultado["ejemplos_textuales"]:
                cambios["estilo_ejemplos"] = resultado["ejemplos_textuales"]
            if intereses_nuevos:
                cambios["intereses"] = intereses_actuales + intereses_nuevos

            # Correcciones que la persona le dio a SU PROPIO gemelo sobre
            # cómo comportarse (ver extraer_correcciones_gemelo) -- se
            # guardan aparte de estilo_aprendido/intereses porque son
            # instrucciones directas, no descripciones. Se acumulan (dedupe
            # sin importar mayúsculas) y se recortan a las últimas 15 para
            # que la lista no crezca sin límite.
            correcciones_actuales = perfil.get("correcciones_gemelo") or []
            mensajes_gemelo = _mensajes_al_propio_gemelo(db, uid)
            if mensajes_gemelo:
                correcciones_nuevas = extraer_correcciones_gemelo(mensajes_gemelo)
                vistas_corr = {c.casefold() for c in correcciones_actuales}
                a_agregar = [c for c in correcciones_nuevas if c.casefold() not in vistas_corr]
                if a_agregar:
                    cambios["correcciones_gemelo"] = (correcciones_actuales + a_agregar)[-15:]

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


def _borrar_coleccion(ref):
    for doc in ref.stream():
        doc.reference.delete()


@https_fn.on_call(timeout_sec=120, memory=MemoryOption.MB_512)
def eliminar_cuenta(request: https_fn.CallableRequest):
    """Borra la cuenta y TODOS los datos de Pebble asociados -- perfil,
    respuestas del onboarding, chats, notificaciones, conexiones/matches
    (con sus simulaciones) y la cuenta de Firebase Auth. Irreversible: no
    hay forma de recuperar nada de esto después de llamado. Antes 'Eliminar
    mi cuenta' en perfil.html solo mostraba un toast pidiendo escribir a
    soporte -- no borraba nada de verdad."""

    if request.auth is None:
        raise https_fn.HttpsError(
            https_fn.FunctionsErrorCode.UNAUTHENTICATED,
            "Hay que estar logueado."
        )

    uid = request.auth.uid
    db = firestore.client()

    ref_usuario = db.collection("usuarios").document(uid)
    _borrar_coleccion(ref_usuario.collection("gemelo"))
    _borrar_coleccion(ref_usuario.collection("gemelo_setup"))
    _borrar_coleccion(ref_usuario.collection("chats"))
    _borrar_coleccion(ref_usuario.collection("notificaciones"))
    ref_usuario.delete()

    for doc in db.collection("conexiones").where("participantes", "array_contains", uid).stream():
        _borrar_coleccion(doc.reference.collection("simulaciones"))
        doc.reference.delete()

    # parejas_pendientes no tiene un campo "participantes" (array) como
    # conexiones -- son pocos docs y de corta vida (se consumen en el batch
    # nocturno), así que un escaneo completo acá es aceptable.
    for doc in db.collection("parejas_pendientes").stream():
        data = doc.to_dict()
        u1 = (data.get("usuario_1") or {}).get("uid")
        u2 = (data.get("usuario_2") or {}).get("uid")
        if uid in (u1, u2):
            doc.reference.delete()

    try:
        auth.delete_user(uid)
    except Exception as e:
        print(f"eliminar_cuenta: error borrando la cuenta de Auth {uid}: {e}")


# ─────────────────────────────────────────────────────────────────────────
# FUNCIÓN TEMPORAL DE UN SOLO USO -- borrar después de correrla una vez.
#
# Se reemplazó la lista de green/red flags del juego (FLAGS en
# gemelo-setup.html / FLAGS_JUEGO en gemelo_perfil.py) por una nueva -- los
# votos viejos guardados en gemelo_setup/data.etapa5.flags quedaron
# apuntando a índices que ahora significan un comportamiento distinto (o ni
# siquiera existen si la lista nueva es más corta), así que la preferencia
# de personalidad que se calculaba a partir de esos votos (ver
# gemelo_perfil._construir_preferencias_pareja_personalidad) queda mal
# interpretada en cualquiera que ya haya completado el juego con la lista
# vieja. Esto borra SOLO ese campo puntual (etapa5.flags) para todos los
# que ya lo tengan, dejando el resto del onboarding intacto, y regenera
# gemelo/perfil de cada uno para que el cambio se refleje al toque -- así
# el juego vuelve a aparecer sin contestar y lo pueden rejugar con la
# lista nueva.
#
# Restringida a "estar logueado" nomás -- el chequeo por email específico
# rebotó porque la cuenta de prueba usada para dispararla no coincidía, y
# no vale la pena perseguir el email exacto para algo de un solo uso, bajo
# riesgo (solo borra un campo puntual y regenera perfiles, nunca borra
# cuentas ni expone datos de nadie) y que se borra apenas se corre.
# ─────────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────
@https_fn.on_call(timeout_sec=300, memory=MemoryOption.MB_512)
def limpiar_flags_viejas(request: https_fn.CallableRequest):
    if request.auth is None:
        raise https_fn.HttpsError(
            https_fn.FunctionsErrorCode.PERMISSION_DENIED,
            "No autorizado."
        )

    db = firestore.client()
    limpiados = []

    for doc in db.collection_group("gemelo_setup").stream():
        if doc.id != "data":
            continue
        data = doc.to_dict()
        if not (data.get("etapa5") or {}).get("flags"):
            continue

        doc.reference.update({"etapa5.flags": firestore.DELETE_FIELD})

        uid = doc.reference.parent.parent.id
        try:
            nuevo_setup = doc.reference.get().to_dict()
            perfil = construir_perfil_gemelo(nuevo_setup)
            db.collection("usuarios").document(uid).collection("gemelo").document("perfil").set(perfil)
        except Exception as e:
            print(f"limpiar_flags_viejas: error regenerando perfil de {uid}: {e}")

        limpiados.append(uid)

    return {"limpiados": limpiados, "total": len(limpiados)}


# ─────────────────────────────────────────────────────────────────────────
# FUNCIÓN TEMPORAL DE DIAGNÓSTICO -- borrar cuando ya no haga falta.
#
# "Forzar la corrida de matches" (buscar_parejas_pendientes +
# procesar_parejas_pendientes) devolvió "no se corrió ninguna simulación" --
# esto lee el estado real de Firestore para saber por qué: si es porque no
# hay parejas pendientes, porque todas dieron un score por debajo del
# umbral (comportamiento esperado: si no superan el umbral, no se gasta en
# una simulación real de OpenAI), o porque algo tiró una excepción real.
# ─────────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────
@https_fn.on_call(timeout_sec=120, memory=MemoryOption.MB_512)
def diagnostico_matches(request: https_fn.CallableRequest):
    if request.auth is None:
        raise https_fn.HttpsError(
            https_fn.FunctionsErrorCode.PERMISSION_DENIED,
            "No autorizado."
        )

    db = firestore.client()

    # {"resetear_errores": true} vuelve a poner en PENDIENTE cualquier
    # pareja que haya quedado en ERROR, así procesar_parejas_pendientes la
    # vuelve a tomar en la próxima corrida forzada (por default solo mira
    # estado == PENDIENTE, nunca reintenta un ERROR solo).
    if (request.data or {}).get("resetear_errores"):
        reseteadas = 0
        for doc in db.collection("parejas_pendientes").where("estado", "==", "ERROR").stream():
            doc.reference.update({"estado": "PENDIENTE", "error": None})
            reseteadas += 1
        return {"reseteadas": reseteadas}

    # {"eliminar_par_id": "<uid1>_<uid2>"} borra ese match por completo --
    # conexiones/{par_id} (y su subcolección simulaciones) + parejas_pendientes
    # /{par_id}, para un caso puntual que no debería haberse creado (ej: el
    # filtro de género/orientación corrió con código viejo antes de un fix).
    eliminar_par_id = (request.data or {}).get("eliminar_par_id")
    if eliminar_par_id:
        con_ref = db.collection("conexiones").document(eliminar_par_id)
        for sub in con_ref.collection("simulaciones").stream():
            sub.reference.delete()
        con_existia = con_ref.get().exists
        con_ref.delete()
        pend_ref = db.collection("parejas_pendientes").document(eliminar_par_id)
        pend_existia = pend_ref.get().exists
        pend_ref.delete()
        return {"conexion_borrada": con_existia, "pareja_pendiente_borrada": pend_existia}

    pendientes = []
    for doc in db.collection("parejas_pendientes").stream():
        d = doc.to_dict()
        pendientes.append({
            "par_id": d.get("par_id"),
            "estado": d.get("estado"),
            "usuario_1": (d.get("usuario_1") or {}).get("nombre"),
            "usuario_2": (d.get("usuario_2") or {}).get("nombre"),
            "error": d.get("error"),
        })

    conexiones_recientes = []
    for doc in db.collection("conexiones").order_by("creado", direction=firestore.Query.DESCENDING).limit(50).stream():
        d = doc.to_dict()
        conexiones_recientes.append({
            "par_id": doc.id,
            "usuario_1": (d.get("usuario_1") or {}).get("nombre"),
            "usuario_1_uid": (d.get("usuario_1") or {}).get("uid"),
            "usuario_2": (d.get("usuario_2") or {}).get("nombre"),
            "usuario_2_uid": (d.get("usuario_2") or {}).get("uid"),
            "ultimo_score": d.get("ultimo_score"),
            "supera_umbral": d.get("supera_umbral"),
        })

    return {
        "umbral_actual": motor.UMBRAL_MATCH,
        "parejas_pendientes_count": len(pendientes),
        "parejas_pendientes": pendientes,
        "conexiones_recientes": conexiones_recientes,
    }
