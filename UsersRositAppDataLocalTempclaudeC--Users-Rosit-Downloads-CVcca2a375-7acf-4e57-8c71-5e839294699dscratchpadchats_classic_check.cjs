
      // Se llena con datos reales de Firestore -- ver cargarChatsReales()
      // más abajo. openChat()/refreshListItem()/etc. leen de acá igual que antes.
      // "var" (no "let") a propósito: un top-level "let" en un <script>
      // clásico NO queda expuesto en window, así que el otro <script
      // type="module"> de más abajo (que es el que arma "people" con datos
      // reales de Firestore) no podría verlo -- "var" sí queda en window.
      var people = {};

      // Persona actualmente abierta en el panel de chat (ej: 'sofia', 'mateo')
      let curPerson = null;
      // Modo activo en el panel: 'gemelo' (chat con IA) o 'real' (chat directo con la persona)
      let curMode = null;

      /* ── Open chat panel ── */
      // Abre el panel lateral de chat para la persona con el id dado
      // Si el click fue en un botón de modo (gemelo/real), lo ignora para no interferir
      function openChat(id, e) {
        if (e && e.target.closest(".conv-mode-btn")) return;
        const p = people[id];
        curPerson = id;
        curMode = p.currentMode;

        document.getElementById("panelAv").style.cssText = p.photo
          ? `background-image:url('${p.photo}');background-size:cover;background-position:center;cursor:pointer`
          : `background:linear-gradient(135deg,#888,#555);cursor:pointer`;
        document.getElementById("panelAv").textContent = p.photo
          ? ""
          : (p.name[0] || "?").toUpperCase();
        document.getElementById("panelName").textContent = p.name;
        document.getElementById("panelMeta").textContent = [
          p.age ? `${p.age} años` : "",
          p.city,
          `${p.afinidad}% afinidad`,
        ]
          .filter(Boolean)
          .join(" · ");

        const realBtn = document.getElementById("pmBtnReal");
        realBtn.classList.toggle("locked", !p.realUnlocked);

        syncPanelModeBtns();
        updateModeBar();
        renderMessages();

        document.getElementById("chatPanel").classList.add("open");
        setTimeout(scrollBottom, 60);

        // Marcar como leído (en memoria y en Firestore)
        p.gemelo.unread = 0;
        if (p.real) p.real.unread = 0;
        refreshListItem(id);
        if (typeof window._db_marcarLeido === "function") {
          window._db_marcarLeido(id);
        }
      }

      // Cierra el panel de chat y resetea la persona y modo activos
      function closeChat() {
        document.getElementById("chatPanel").classList.remove("open");
        curPerson = null;
        curMode = null;
      }

      /* ── Panel mode switch ── */
      // Cambia entre modo gemelo (IA) y modo real (persona)
      // Si el chat real no está desbloqueado aún, muestra un toast de aviso y cancela
      function switchPanelMode(mode) {
        const p = people[curPerson];
        if (mode === "real" && !p.realUnlocked) {
          showToast();
          return;
        }
        curMode = mode;
        p.currentMode = mode;
        syncPanelModeBtns();
        updateModeBar();
        renderMessages();
        setTimeout(scrollBottom, 40);
        refreshListItem(curPerson);
      }

      // Actualiza visualmente cuál botón de modo (Gemelo / Real) está activo en el panel
      function syncPanelModeBtns() {
        document
          .getElementById("pmBtnGemelo")
          .classList.toggle("active", curMode === "gemelo");
        document
          .getElementById("pmBtnReal")
          .classList.toggle("active", curMode === "real");
        // Mandar fotos es solo para la persona real, nunca para el gemelo.
        document.getElementById("panelPhotoBtn").style.display =
          curMode === "real" ? "flex" : "none";
      }

      // Actualiza la barra de contexto del panel según el modo activo
      // En modo gemelo muestra "Hablás con el gemelo de X · Modo práctica"
      // En modo real muestra "Chat real con X · En línea"
      function updateModeBar() {
        const p = people[curPerson];
        const bar = document.getElementById("panelModeBar");
        const inp = document.getElementById("panelInput");
        document
          .getElementById("chatPanel")
          .classList.toggle("gemelo-mode", curMode === "gemelo");
        if (curMode === "gemelo") {
          bar.className = "panel-mode-bar gemelo-bar";
          bar.innerHTML = `
      <svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><path d="M12 8v4l3 3"/></svg>
      <span style="flex:1">Hablás con el <strong style="color:#fff">gemelo de ${esc(p.name)}</strong> · Modo práctica</span>
      ${p.simulacion && p.simulacion.length ? `<button onclick="openSimulation()" style="background:rgba(255,117,31,0.15);border:1px solid rgba(255,117,31,0.3);border-radius:10px;padding:3px 10px;font-size:0.62rem;font-weight:700;color:var(--orange);cursor:pointer;letter-spacing:0.03em;white-space:nowrap;touch-action:manipulation;flex-shrink:0">Ver simulación ↗</button>` : ""}
      <span class="mode-bar-badge" style="background:var(--orange);color:#fff">IA</span>`;
          inp.placeholder = `Preguntale algo al gemelo de ${p.name}...`;
        } else {
          bar.className = "panel-mode-bar real-bar";
          bar.innerHTML = `
      <span style="width:8px;height:8px;border-radius:50%;background:#22c55e;flex-shrink:0;display:inline-block"></span>
      <span style="flex:1">Chat real con <strong>${esc(p.name)}</strong></span>
      <span class="mode-bar-badge" style="background:rgba(34,197,94,0.15);color:#16a34a">En línea</span>`;
          inp.placeholder = `Escribile a ${p.name}...`;
        }
      }

      /* ── Render messages ── */
      // Limpia y redibuja todos los mensajes del chat abierto según la persona y modo activos
      // Agrega el separador "Hoy" y, en modo gemelo, la tarjeta de simulación al tope
      function renderMessages() {
        const p = people[curPerson];
        const md = p[curMode];
        const con = document.getElementById("panelMsgsInner");
        const isG = curMode === "gemelo";
        con.innerHTML = "";

        const sep = document.createElement("div");
        sep.className = "day-sep";
        sep.innerHTML =
          '<div class="day-sep-line"></div><span class="day-sep-text">Hoy</span><div class="day-sep-line"></div>';
        con.appendChild(sep);

        // Tarjeta de simulación al tope del chat gemelo
        if (isG && p.simulacion && p.simulacion.length) {
          const card = document.createElement("div");
          card.className = "sim-teaser-card";
          card.onclick = openSimulation;
          card.innerHTML = `
      <div class="sim-teaser-icon">
        <svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><path d="M8 12h8"/><path d="M12 8v8"/></svg>
      </div>
      <div class="sim-teaser-text">
        <div class="sim-teaser-title">Tu gemelo y el de ${esc(p.name)} ya se conocieron</div>
        <div class="sim-teaser-sub">Ver la conversación que tuvieron antes de que ustedes se conectaran</div>
      </div>
      <div class="sim-teaser-arrow"><svg viewBox="0 0 24 24"><path d="M9 18l6-6-6-6"/></svg></div>`;
          con.appendChild(card);
        }

        (md.msgs || []).forEach((msg) => addMsgEl(con, msg, p, isG));
      }

      // Contenido de una burbuja: si el mensaje trae foto (solo pasa en modo
      // "real", nunca con el gemelo) se muestra la imagen en vez del texto,
      // tocable para agrandarla (mismo lightbox que el perfil).
      function _bubbleContent(msg) {
        if (msg.photo) {
          return `<img class="pbubble-photo" src="${msg.photo}" onclick="openLightbox('${msg.photo}')" alt="Foto" />`;
        }
        return esc(msg.text);
      }

      // Crea y agrega un elemento de mensaje al contenedor del chat
      // El estilo varía según si es mensaje propio (me), del gemelo IA (isG) o de la persona real (them)
      function addMsgEl(container, msg, p, isG) {
        // "gemelo" sigue con "me"/"them" relativo (sin cambios); "real" usa
        // el uid real de quien escribió cada mensaje, porque el mismo doc
        // lo leen las dos cuentas y "me" no tiene sentido ahí.
        const isMe = isG ? msg.from === "me" : msg.from === window._uid;
        const div = document.createElement("div");
        div.className = `pmsg ${isMe ? "me" : "them"}${!isMe && isG ? " is-gemelo" : ""}${msg.photo ? " has-photo" : ""}`;

        if (isMe) {
          div.innerHTML = `<span class="pmsg-time">${msg.time}</span><div class="pbubble">${_bubbleContent(msg)}</div>`;
        } else if (isG) {
          div.innerHTML = `
      <div class="pmsg-av pmsg-av-ai" style="background:${p.color}">
        <svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><path d="M12 8v4l3 3"/></svg>
      </div>
      <div class="pbubble"><span class="gemelo-tag">Gemelo de ${esc(p.name)}</span>${_bubbleContent(msg)}</div>
      <span class="pmsg-time">${msg.time}</span>`;
        } else {
          div.innerHTML = `
      <div class="pmsg-av" style="${p.photo ? `background-image:url('${p.photo}');background-size:cover;background-position:center` : "background:linear-gradient(135deg,#888,#555)"}">${p.photo ? "" : esc((p.name[0] || "?").toUpperCase())}</div>
      <div class="pbubble">${_bubbleContent(msg)}</div>
      <span class="pmsg-time">${msg.time}</span>`;
        }
        container.appendChild(div);
      }

      /* ── Send message ── */
      // Envía el mensaje del usuario, lo guarda en memoria y en Firestore
      // Si es el primer mensaje con esa persona, inyecta el ítem en la lista de conversaciones
      // Después de 300ms muestra typing y genera una respuesta automática
      // Mientras se espera la respuesta del gemelo de un match (modo
      // "gemelo"), se bloquea mandar otro mensaje -- mismo problema que en
      // gemelo.html: mandar dos mensajes seguidos rápido hacía que el
      // gemelo "pensara" para los dos y el orden de las respuestas quedara
      // mezclado. El modo "real" (chat humano-humano, sin IA de por medio)
      // no necesita este bloqueo.
      let esperandoRespuestaGemeloMatch = false;
      function _bloquearEnvioPanel(bloquear) {
        esperandoRespuestaGemeloMatch = bloquear;
        const btn = document.getElementById("panelSendBtn");
        if (btn) btn.disabled = bloquear;
      }

      function sendPanelMsg() {
        if (esperandoRespuestaGemeloMatch) return;
        const input = document.getElementById("panelInput");
        const text = input.value.trim();
        if (!text || !curPerson) return;
        const p = people[curPerson];
        const md = p[curMode];
        const persona = curPerson;
        const mode = curMode;
        const t = nowTime();
        // "real" guarda el uid real de quien escribe (no "me"/"them"
        // relativo) -- el mismo documento lo leen las dos cuentas, así que
        // "me" no significa nada ahí. "gemelo" sigue con "me"/"them" como
        // siempre, no se tocó ese modo.
        const msg = {
          id: `${Date.now()}_${Math.random().toString(36).slice(2)}`,
          from: mode === "real" ? window._uid : "me",
          text,
          time: t,
        };
        md.msgs.push(msg);
        md.lastTime = t;
        // Primer mensaje con esta persona → inyectar en la lista de conversaciones
        if (md.msgs.length === 1) {
          injectConvItem(persona);
        }
        renderMessages();
        refreshListItem(persona);
        input.value = "";
        panelResize(input);
        setTimeout(scrollBottom, 40);

        if (mode === "real") {
          // Chat real entre las dos cuentas: se guarda con arrayUnion (no
          // pisa lo que la otra persona haya escrito un instante antes) y
          // nada se inventa acá -- la respuesta real de la otra persona
          // llega sola por el listener en vivo (onSnapshot, ver
          // cargarChatsReales) cuando ella la escriba de verdad.
          if (typeof window._db_agregarMensajeReal === "function") {
            window._db_agregarMensajeReal(persona, msg);
          }
          return;
        }

        // Modo "gemelo": chat en vivo con el gemelo real del match.
        if (typeof window._db_saveChat === "function") {
          window._db_saveChat(persona, mode, [...md.msgs]);
        }

        _bloquearEnvioPanel(true);
        setTimeout(() => {
          addTyping();
          (async () => {
            // Llama de verdad al gemelo del match (chatear_con_gemelo_match)
            // -- reemplaza el autoReply() enlatado con nombres de demo que
            // había acá antes. El historial excluye el mensaje que se acaba
            // de mandar (ya va aparte como "mensaje" al backend).
            let partes;
            try {
              const historial = md.msgs
                .slice(0, -1)
                .slice(-20)
                .map((m) => ({
                  role: m.from === "me" ? "user" : "assistant",
                  content: m.text,
                }));
              partes = await window._llamarChatGemeloMatch(
                persona,
                text,
                historial,
              );
            } catch (err) {
              console.error("Error en chatear_con_gemelo_match:", err);
              partes = ["No pude responder ahora mismo. Probá de nuevo en un rato."];
            }
            removeTyping();
            // El gemelo puede partir su turno en varios mensajitos cortos
            // (ver motor._dividir_mensajes en el backend) -- cada parte va
            // como una burbuja separada, no todas pegadas con saltos de
            // línea dentro de un solo mensaje.
            (partes || []).forEach((parte) => {
              md.msgs.push({ from: "them", text: parte, time: nowTime() });
            });
            md.lastTime = nowTime();
            // Si seguís mirando esta misma conversación cuando llega la
            // respuesta, se da por leída al toque (en vez de sumarla a los
            // no leídos); si no, sí cuenta como no leído -- el contador
            // tiene que poder subir, no solo bajar.
            const sigueAbierto = curPerson === persona && curMode === mode;
            if (sigueAbierto) {
              if (typeof window._db_marcarLeido === "function") {
                window._db_marcarLeido(persona);
              }
            } else {
              md.unread = (md.unread || 0) + 1;
            }
            renderMessages();
            refreshListItem(persona);
            setTimeout(scrollBottom, 40);
            // Guardar respuesta real en Firestore
            if (typeof window._db_saveChat === "function") {
              window._db_saveChat(persona, mode, [...md.msgs]);
            }
            _bloquearEnvioPanel(false);
          })();
        }, 300);
      }

      /* ── Send photo (solo chat real, nunca al gemelo) ── */

      // HEIC/HEIF (formato típico de fotos de iPhone/Mac) no lo puede
      // decodificar un <img> -- mismo problema y mismo arreglo que ya se
      // hizo en perfil.html para subir fotos de perfil.
      function _pareceHeicChat(file) {
        const tipo = (file.type || "").toLowerCase();
        if (tipo.includes("heic") || tipo.includes("heif")) return true;
        const nombre = (file.name || "").toLowerCase();
        return nombre.endsWith(".heic") || nombre.endsWith(".heif");
      }

      let _heic2anyCargandoChat = null;
      function _cargarHeic2anyChat() {
        if (window.heic2any) return Promise.resolve();
        if (_heic2anyCargandoChat) return _heic2anyCargandoChat;
        _heic2anyCargandoChat = new Promise((resolve, reject) => {
          const script = document.createElement("script");
          script.src =
            "https://cdn.jsdelivr.net/npm/heic2any@0.0.4/dist/heic2any.min.js";
          script.onload = () => resolve();
          script.onerror = () =>
            reject(new Error("No se pudo cargar el conversor de HEIC"));
          document.head.appendChild(script);
        });
        return _heic2anyCargandoChat;
      }

      // El chat entero (todos los mensajes de la pareja) vive en un solo
      // documento de Firestore con un techo de 1MB -- cada foto tiene que
      // pesar lo menos posible sin quedar ilegible. Arranca en calidad alta
      // y solo la baja de a pasos si hace falta (mismo criterio que
      // canvasToCompressedDataUrl en perfil.html).
      function _comprimirFotoChat(
        img,
        { maxLado = 1000, targetBytes = 150000, minQuality = 0.5 } = {},
      ) {
        const escala = Math.min(1, maxLado / Math.max(img.width, img.height));
        const canvas = document.createElement("canvas");
        canvas.width = Math.round(img.width * escala);
        canvas.height = Math.round(img.height * escala);
        canvas.getContext("2d").drawImage(img, 0, 0, canvas.width, canvas.height);
        let quality = 0.85;
        let dataUrl = canvas.toDataURL("image/jpeg", quality);
        while (dataUrl.length > targetBytes && quality > minQuality) {
          quality = Math.round((quality - 0.1) * 10) / 10;
          dataUrl = canvas.toDataURL("image/jpeg", quality);
        }
        return dataUrl;
      }

      // Handler del <input type="file"> del botón de adjuntar foto.
      async function handlePanelPhotoSelected(event) {
        const file = event.target.files && event.target.files[0];
        event.target.value = ""; // permite elegir la misma foto de nuevo después
        if (!file || !curPerson || curMode !== "real") return;

        let archivo = file;
        if (_pareceHeicChat(file)) {
          try {
            await _cargarHeic2anyChat();
            const resultado = await window.heic2any({
              blob: file,
              toType: "image/jpeg",
              quality: 0.9,
            });
            archivo = Array.isArray(resultado) ? resultado[0] : resultado;
          } catch (e) {
            console.error("Error convirtiendo HEIC:", e);
            alert(
              "Esa foto está en formato HEIC (típico de iPhone/Mac) y no se pudo convertir automáticamente. Exportala como JPG o PNG desde Fotos y probá de nuevo.",
            );
            return;
          }
        }

        const reader = new FileReader();
        reader.onerror = () => alert("No se pudo leer la imagen");
        reader.onload = () => {
          const img = new Image();
          img.onerror = () =>
            alert("No se pudo procesar la imagen -- probá con otra (JPG o PNG)");
          img.onload = () => sendPanelPhoto(_comprimirFotoChat(img));
          img.src = reader.result;
        };
        reader.readAsDataURL(archivo);
      }

      // Agrega el mensaje-foto al chat real y lo persiste -- mismo flujo que
      // la rama "real" de sendPanelMsg, sin respuesta automática (eso solo
      // pasa en modo gemelo).
      function sendPanelPhoto(dataUrl) {
        if (!curPerson || curMode !== "real") return;
        const p = people[curPerson];
        const md = p.real;
        const persona = curPerson;
        const t = nowTime();
        const msg = {
          id: `${Date.now()}_${Math.random().toString(36).slice(2)}`,
          from: window._uid,
          text: "",
          photo: dataUrl,
          time: t,
        };
        md.msgs.push(msg);
        md.lastTime = t;
        if (md.msgs.length === 1) {
          injectConvItem(persona);
        }
        renderMessages();
        refreshListItem(persona);
        setTimeout(scrollBottom, 40);
        if (typeof window._db_agregarMensajeReal === "function") {
          window._db_agregarMensajeReal(persona, msg);
        }
      }

      // Muestra el indicador de "escribiendo..." con el avatar correcto según el modo (gemelo o real)
      function addTyping() {
        const p = people[curPerson];
        const isG = curMode === "gemelo";
        const con = document.getElementById("panelMsgsInner");
        const div = document.createElement("div");
        div.id = "ptyping";
        div.className = `pmsg them${isG ? " is-gemelo" : ""}`;
        const av = isG
          ? `<div class="pmsg-av pmsg-av-ai" style="background:${p.color}"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><path d="M12 8v4l3 3"/></svg></div>`
          : `<div class="pmsg-av" style="${p.photo ? `background-image:url('${p.photo}');background-size:cover;background-position:center` : "background:linear-gradient(135deg,#888,#555)"}">${p.photo ? "" : esc((p.name[0] || "?").toUpperCase())}</div>`;
        div.innerHTML = `${av}<div class="typing-bubble"><div class="typing-dot"></div><div class="typing-dot"></div><div class="typing-dot"></div></div>`;
        con.appendChild(div);
        scrollBottom();
      }
      // Elimina el indicador de "escribiendo..." del chat
      function removeTyping() {
        const el = document.getElementById("ptyping");
        if (el) el.remove();
      }

      /* ── Auto replies ── */
      // Genera una respuesta automática según el modo (gemelo o real) y el contenido del mensaje
      // En modo gemelo: responde preguntas sobre gustos, consejos, familia, etc. con info específica de cada persona
      // En modo real: elige al azar una respuesta del banco de frases de esa persona para simular conversación real
      /* ── List mode switch ── */
      // Cambia el modo activo (gemelo/real) desde los botones de la lista de conversaciones
      // Detiene la propagación para que no abra el chat al cambiar de modo
      function listSwitch(e, id, mode) {
        e.stopPropagation();
        const p = people[id];
        if (mode === "real" && !p.realUnlocked) {
          showToast();
          return;
        }
        p.currentMode = mode;
        refreshListItem(id);
      }

      // Maneja el tap en el botón de chat real cuando está bloqueado — muestra el toast sin abrir nada
      function lockTap(e, id) {
        e.stopPropagation();
        showToast();
      }

      // Actualiza el ítem de la lista de conversaciones para una persona:
      // preview del último mensaje, hora, badge de no leídos y botones de modo activo
      function refreshListItem(id) {
        const p = people[id];
        const md = p[p.currentMode];

        const previewEl = document.getElementById(`${id}-preview`);
        const timeEl = document.getElementById(`${id}-time`);
        const unreadEl = document.getElementById(`${id}-unread`);

        if (previewEl) {
          const msgs = md.msgs || [];
          const last = msgs.length ? msgs[msgs.length - 1] : null;
          previewEl.textContent = !last
            ? "Sin mensajes"
            : last.photo
              ? "📷 Foto"
              : last.text.length > 55
                ? last.text.slice(0, 55) + "…"
                : last.text;
          previewEl.className = "conv-preview" + (md.unread > 0 ? " bold" : "");
        }
        if (timeEl) timeEl.textContent = md.lastTime || "";
        if (unreadEl) {
          unreadEl.textContent = md.unread;
          unreadEl.style.display = md.unread > 0 ? "" : "none";
        }

        // mode buttons highlight
        const gBtn = document.getElementById(`${id}-btn-gemelo`);
        const rBtn = document.getElementById(`${id}-btn-real`);
        if (gBtn)
          gBtn.classList.toggle("mode-active", p.currentMode === "gemelo");
        if (rBtn && !rBtn.classList.contains("mode-locked"))
          rBtn.classList.toggle("mode-active", p.currentMode === "real");
      }

      /* ── Inject new conv-list item (for people without a pre-existing chat) ── */
      // Agrega dinámicamente un ítem a la lista de conversaciones para personas que no tenían chat previo
      // Solo se ejecuta la primera vez que se envía un mensaje a esa persona
      // Si el ítem ya existe (cargado desde Firestore), no hace nada
      function injectConvItem(id) {
        if (document.getElementById(`conv-${id}`)) return; // ya existe
        const p = people[id];
        const el = document.createElement("div");
        el.className = "conv-item";
        el.id = `conv-${id}`;
        el.innerHTML = `
    <div class="conv-av" style="${p.photo ? `background-image:url('${p.photo}');background-size:cover;background-position:center` : "background:linear-gradient(135deg,#888,#555)"}">${p.photo ? "" : esc((p.name[0] || "?").toUpperCase())}</div>
    <div class="conv-content">
      <div class="conv-top">
        <span class="conv-name">${esc(p.name)}</span>
        <span class="conv-afinidad">${p.afinidad}%</span>
        <span class="conv-time" id="${id}-time"></span>
      </div>
      <div class="conv-preview-row">
        <span class="conv-preview" id="${id}-preview">Sin mensajes</span>
        <span class="conv-unread" id="${id}-unread" style="display:none">0</span>
      </div>
      <div class="conv-modes">
        <button class="conv-mode-btn mode-active" id="${id}-btn-gemelo" onclick="listSwitch(event,'${id}','gemelo')">
          <svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><path d="M12 8v4l3 3"/></svg>
          Gemelo
        </button>
        <button class="conv-mode-btn${p.realUnlocked ? "" : " mode-locked"}" id="${id}-btn-real" onclick="listSwitch(event,'${id}','real')">
          <svg viewBox="0 0 24 24"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
          Real
        </button>
      </div>
    </div>`;
        el.onclick = function (e) {
          openChat(id, e);
        };
        const list = document.getElementById("convList");
        list.prepend(el);
        // Actualizar contador
        const countEl = document.querySelector(".conv-count");
        if (countEl) {
          const n = list.querySelectorAll(".conv-item").length;
          countEl.textContent = `${n} conversación${n !== 1 ? "es" : ""} activa${n !== 1 ? "s" : ""}`;
        }
        refreshListItem(id);
      }

      /* ── Search ── */
      // Filtra las conversaciones de la lista en tiempo real según el texto del buscador
      // Oculta los ítems cuyo nombre no coincide con la búsqueda
      function filterConvs(q) {
        const ql = q.toLowerCase();
        document.querySelectorAll(".conv-item").forEach((el) => {
          const name = el.querySelector(".conv-name").textContent.toLowerCase();
          el.style.display = !ql || name.includes(ql) ? "" : "none";
        });
      }

      /* ── Person profile overlay ── */
      // Abre el overlay con el perfil completo de la persona del chat abierto
      // Muestra foto, nombre, edad, ciudad, afinidad, bio, intereses (marcando los compartidos) y fotos
      function openPersonProfile() {
        if (!curPerson) return;
        const p = people[curPerson];
        document.getElementById("poTitle").textContent = p.name;

        const sharedSet = new Set(p.sharedInterests || []);
        const interestChips = (p.interests || [])
          .map(
            (i) =>
              `<span class="po-chip${sharedSet.has(i) ? " shared" : ""}">${esc(i)}</span>`,
          )
          .join("");

        const photosHtml = (p.photos || [])
          .map(
            (url) =>
              `<div class="po-photo" onclick="openLightbox('${url}')" style="background:url('${url}') center/cover no-repeat"></div>`,
          )
          .join("");

        document.getElementById("poInner").innerHTML = `
    <div class="po-hero">
      <div class="po-hero-av" ${p.photo ? `onclick="openLightbox('${p.photo}')"` : ""} style="${p.photo ? `background-image:url('${p.photo}');background-size:cover;background-position:center` : "background:linear-gradient(135deg,#888,#555)"}">${p.photo ? "" : esc((p.name[0] || "?").toUpperCase())}</div>
      <div class="po-hero-info">
        <div class="po-hero-name">${esc(p.name)}${p.age ? ", " + p.age : ""}</div>
        <div class="po-hero-meta">${esc([p.city, p.identidad].filter(Boolean).join(" · "))}</div>
      </div>
      <div class="po-hero-score">${p.afinidad}%<span>Afinidad</span></div>
    </div>
    ${p.bio ? `<div class="po-section"><div class="po-section-label">Sobre ${esc(p.name)}</div><p class="po-bio">${esc(p.bio)}</p></div>` : ""}
    ${interestChips ? `<div class="po-section"><div class="po-section-label">Intereses <span style="color:var(--orange);text-transform:none;letter-spacing:0">— naranja = compartidos</span></div><div class="po-chips">${interestChips}</div></div>` : ""}
    ${photosHtml ? `<div class="po-section"><div class="po-section-label">Fotos</div><div class="po-photos-grid">${photosHtml}</div></div>` : ""}
  `;

        document.getElementById("profileOverlay").classList.add("open");
      }

      // Cierra el overlay del perfil de la persona
      function closePersonProfile() {
        document.getElementById("profileOverlay").classList.remove("open");
      }

      // Agranda una foto (la de perfil o cualquiera de la grilla) a pantalla
      // completa -- `url` es la foto tal cual (data URL o http), no el
      // string de background CSS.
      window.openLightbox = function (url) {
        if (!url) return;
        document.getElementById("lightboxImg").src = url;
        document.getElementById("lightboxOverlay").classList.add("open");
      };
      window.closeLightbox = function () {
        document.getElementById("lightboxOverlay").classList.remove("open");
      };
      document.addEventListener("keydown", (e) => {
        if (e.key === "Escape") closeLightbox();
      });

      /* ── Lock toast ── */
      // Muestra un mensaje temporal ("Chat bloqueado") cuando el usuario intenta acceder al chat real sin haberlo desbloqueado
      // Se oculta automáticamente después de 3 segundos
      let toastTimer = null;
      function showToast() {
        const el = document.getElementById("lockToast");
        el.classList.add("show");
        clearTimeout(toastTimer);
        toastTimer = setTimeout(() => el.classList.remove("show"), 3000);
      }

      /* ── Simulation overlay ── */
      // Abre el overlay que muestra la conversación previa entre los gemelos digitales
      // Construye el HTML de cada mensaje diferenciando "tu gemelo" del "gemelo de la otra persona"
      function openSimulation() {
        if (!curPerson) return;
        const p = people[curPerson];
        // p.simulacion es un array por ESCENARIO (no un solo chat) -- antes
        // solo se guardaba/mostraba el último escenario simulado con esta
        // persona; ahora se muestran todos, uno atrás del otro.
        const escenarios = p.simulacion || [];

        document.getElementById("simNavTitle").textContent =
          `Tu gemelo × ${p.name}`;

        const inner = document.getElementById("simInner");

        let html = `<div class="sim-intro">
    <div class="sim-intro-label">¿Qué es esto?</div>
    <div class="sim-intro-text">
      Antes de conectarte con ${esc(p.name)}, los gemelos digitales de ambos exploraron su compatibilidad de forma autónoma en varios escenarios distintos. Estas son esas conversaciones — privadas, tuyas, generadas solo para vos.
    </div>
  </div>`;

        escenarios.forEach((sim, i) => {
          const titulo = sim.escenario || `Escenario ${i + 1}`;
          html += `<div class="sim-scenario-sep">
      <div class="sim-scenario-sep-line"></div>
      <span class="sim-scenario-sep-badge">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M8 12h8"/><path d="M12 8v8"/></svg>
        ${esc(titulo)}
      </span>
      <div class="sim-scenario-sep-line"></div>
    </div>`;

          sim.mensajes.forEach((msg) => {
            const isMe = msg.from === "mi-gemelo";
            if (isMe) {
              html += `<div class="smsg me">
        <span class="smsg-time">${msg.time}</span>
        <div class="sbubble"><span class="smsg-label">Tu gemelo</span>${esc(msg.text)}</div>
        <div class="smsg-av" style="background:#2a2a2a;outline:2px solid rgba(255,160,60,0.45);outline-offset:1px">G</div>
      </div>`;
            } else {
              html += `<div class="smsg them">
        <div class="smsg-av" style="background:${p.color};outline:2px solid var(--orange);outline-offset:1px">G</div>
        <div class="sbubble"><span class="smsg-label">Gemelo de ${esc(p.name)}</span>${esc(msg.text)}</div>
        <span class="smsg-time">${msg.time}</span>
      </div>`;
            }
          });
        });

        html += escenarios.length
          ? `<div class="sim-sep"><div class="sim-sep-line"></div><span class="sim-sep-text">Fin de las simulaciones</span><div class="sim-sep-line"></div></div>`
          : `<div class="sim-sep"><div class="sim-sep-line"></div><span class="sim-sep-text">Todavía no hay escenarios simulados</span><div class="sim-sep-line"></div></div>`;

        inner.innerHTML = html;
        document.getElementById("simOverlay").classList.add("open");
        // Scroll al inicio
        document
          .getElementById("simOverlay")
          .querySelector(".sim-body").scrollTop = 0;
      }

      // Cierra el overlay de simulación
      function closeSimulation() {
        document.getElementById("simOverlay").classList.remove("open");
      }

      /* ── Helpers ── */
      // Hace scroll al fondo del panel de mensajes
      function scrollBottom() {
        const el = document.getElementById("panelMessages");
        if (el) el.scrollTop = el.scrollHeight;
      }
      // Devuelve la hora actual en formato HH:MM (horario Argentina)
      function nowTime() {
        return new Date().toLocaleTimeString("es-AR", {
          hour: "2-digit",
          minute: "2-digit",
        });
      }
      // Escapa caracteres especiales de HTML para evitar inyección de código en los mensajes
      function esc(t) {
        return String(t)
          .replace(/&/g, "&amp;")
          .replace(/</g, "&lt;")
          .replace(/>/g, "&gt;")
          .replace(/"/g, "&quot;")
          .replace(/'/g, "&#39;");
      }
      // Detecta Enter en el input del panel para enviar el mensaje (Shift+Enter hace salto de línea)
      function handlePanelKey(e) {
        if (e.key === "Enter" && !e.shiftKey) {
          e.preventDefault();
          sendPanelMsg();
        }
      }
      // Ajusta la altura del textarea del panel automáticamente según el contenido, hasta 100px de alto
      function panelResize(el) {
        el.style.height = "auto";
        el.style.height = Math.min(el.scrollHeight, 100) + "px";
      }

      // Si la página fue abierta con ?persona=ID (desde home o matches), abre ese
      // chat directamente -- se ejecuta desde cargarChatsReales() (script de más
      // abajo) una vez que "people" ya tiene datos reales, no acá, porque a esta
      // altura todavía no cargó nada de Firestore.
      // ?modo=real fuerza el chat con la persona real (ej: botón "Escribirle a
      // X" de matches.html) -- sin esto, openChat() abría el modo que haya
      // quedado guardado en currentMode, que en un match sin mensajes reales
      // todavía por defecto es "gemelo", así que "Escribirle" mandaba al chat
      // con el gemelo en vez de con la persona.
      function abrirChatDesdeQueryParam() {
        const params = new URLSearchParams(location.search);
        const param = params.get("persona");
        const modo = params.get("modo");
        if (param && people[param]) {
          openChat(param);
          if (modo === "real" || modo === "gemelo") {
            switchPanelMode(modo);
          }
          // Sacamos el ?persona=/?modo= de la URL para que un refresh no
          // vuelva a abrir el chat si el usuario ya lo cerró.
          history.replaceState(null, "", location.pathname + location.hash);
        }
      }
    